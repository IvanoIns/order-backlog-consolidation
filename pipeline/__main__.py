"""Run one cutoff or a monthly history range."""

import argparse
from pathlib import Path
import re
import sys

import pandas as pd

from .adapters import source_a, source_b, source_c
from .classify import classify
from .common import AdapterResult, VIEWS, total_cents, money
from .fx import FxRates
from .products import Products
from . import reconcile
from .writer import write


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Consolidate month-end order books.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--cutoff", help="Cutoff month in YYYY-MM format.")
    mode.add_argument("--history", nargs=2, metavar=("START", "END"), help="Inclusive YYYY-MM range.")
    args = parser.parse_args()
    for month in args.history or [args.cutoff]:
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            parser.error("Months must use YYYY-MM")
        try:
            pd.Period(month, freq="M").end_time
        except (ValueError, OverflowError) as error:
            parser.error(f"Invalid month: {error}")
    if args.history and args.history[0] > args.history[1]:
        parser.error("History start must not be after history end")
    return args


def source_views(
    adapted: AdapterResult, source: str, products: Products, fx: FxRates
) -> tuple[dict[str, pd.DataFrame], int]:
    resolved = products.resolve(adapted.lines, source)
    bundle_added = int(resolved.attrs["bundle_added_rows"])
    main = classify(fx.convert(resolved))
    views = {
        view: main[main["line_status"] == status].copy()
        for view, status in (("open_book", "open"), ("review", "review"), ("closed", "closed"))
    }
    for name, table in (("excluded", adapted.excluded), ("sales_without_order", adapted.sales_without_order)):
        resolved = products.resolve(table, source)
        bundle_added += int(resolved.attrs["bundle_added_rows"])
        views[name] = classify(fx.convert(resolved))
    combined = pd.concat(list(views.values()), ignore_index=True)
    if combined["line_key"].duplicated().any():
        raise ValueError(f"{source}: output line keys are not unique")
    if len(main) != sum(len(views[view]) for view in ("open_book", "review", "closed")):
        raise ValueError(f"{source}: a book line has no output view")
    return views, bundle_added


def run(project: Path, month: str, cutoff: str) -> int:
    raw = project / "data" / "raw"
    try:
        products, fx = Products(raw), FxRates(raw, month)
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    summary: dict[str, object] = {
        "cutoff_month": month, "cutoff_date": cutoff,
        "cutoff_policy": "Rows after cutoff do not enter output views or reconciliation totals.",
        "sources": {},
    }
    collected: dict[str, list[pd.DataFrame]] = {view: [] for view in VIEWS}
    reports = []
    exit_code = 0
    for source, adapter in (("A", source_a), ("B", source_b), ("C", source_c)):
        try:
            adapted = adapter.load(raw, cutoff)
            views, bundle_added = source_views(adapted, source, products, fx)
            row = reconcile.report(source, adapted, views, bundle_added)
            reconcile.check(row)
            for view, table in views.items():
                collected[view].append(table)
            summary["sources"][source] = {
                "status": "success", "row_counts": {view: len(table) for view, table in views.items()},
                "open_amount_usd": money(total_cents(views["open_book"]["amount_open_usd"])),
                "input_rows": adapted.totals.rows, **adapted.notes, "errors": [],
            }
            reports.append(row)
        except Exception as error:
            exit_code = 1
            message = f"{type(error).__name__}: {error}"
            summary["sources"][source] = {
                "status": "failed", "row_counts": dict.fromkeys(VIEWS, 0),
                "open_amount_usd": "0.00", "errors": [message],
            }
            reports.append(reconcile.failed(source, message))
            print(f"Source {source} failed: {message}", file=sys.stderr)
    summary["exit_code"] = exit_code
    try:
        write(project / "output" / month, collected, reports, summary)
    except (OSError, ValueError) as error:
        print(f"Output configuration error: {error}", file=sys.stderr)
        return 2
    print(f"Cutoff {month}: exit_code={exit_code}; output/{month}/")
    return exit_code


def main() -> int:
    args = arguments()
    project = Path(__file__).resolve().parents[1]
    if args.history:
        try:
            from .history import run_history
        except ImportError as error:
            print(f"History dependency error: {error}", file=sys.stderr)
            return 2
        return run_history(project, args.history[0], args.history[1], run)
    cutoff = pd.Period(args.cutoff, freq="M").end_time.strftime("%Y-%m-%d")
    return run(project, args.cutoff, cutoff)


if __name__ == "__main__":
    raise SystemExit(main())
