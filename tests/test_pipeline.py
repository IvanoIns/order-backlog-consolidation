"""Accounting, duplicate routing, and monthly-history invariants."""

from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import shutil

import pandas as pd

from pipeline.__main__ import run
from pipeline.adapters import source_a, source_b, source_c
from pipeline.history import load_month, open_database
from pipeline.products import Products


def read_view(project: Path, month: str, view: str) -> pd.DataFrame:
    return pd.read_csv(project / "output" / month / f"{view}.csv", dtype=str, keep_default_na=False)


def test_reconciliation_differences_are_zero(march_project: Path) -> None:
    report = read_view(march_project, "2026-03", "reconciliation")
    assert set(report["source_system"]) == {"A", "B", "C"}
    assert report["source_status"].eq("success").all()
    assert report["rows_difference"].astype(int).eq(0).all()
    for column in ("ordered_difference_lc", "billed_difference_lc"):
        assert report[column].map(Decimal).eq(0).all()


def test_bundle_quantities_and_values_are_conserved(generated_project: Path) -> None:
    raw = generated_project / "data" / "raw"
    products = Products(raw)
    mapping = pd.read_csv(raw / "bundle_mapping.csv")
    checked = 0
    for source, adapter in (("A", source_a), ("B", source_b), ("C", source_c)):
        parents = adapter.load(raw, "2026-03-31").lines
        resolved = products.resolve(parents, source)
        for parent in parents.to_dict("records"):
            components = mapping[(mapping["source_system"] == source) & (mapping["bundle_code"] == parent["source_product_code"])]
            if components.empty:
                continue
            rows = resolved[resolved["line_key"].str.startswith(str(parent["line_key"]) + "::")]
            assert set(rows["product_code"]) == set(components["component_product_code"])
            multipliers = components.set_index("component_product_code")["quantity_multiplier"].to_dict()
            for column in ("qty_ordered", "qty_billed", "qty_open"):
                assert Fraction(sum(rows[column]), sum(multipliers.values())) == int(parent[column])
                for row in rows.to_dict("records"):
                    assert row[column] == parent[column] * multipliers[row["product_code"]]
            for column in ("amount_ordered_lc", "amount_billed_lc", "amount_open_lc"):
                assert sum(rows[column].map(Decimal), Decimal(0)) == Decimal(parent[column])
            checked += 1
    assert checked == 181


def test_loading_a_month_twice_is_identical(march_project: Path, tmp_path: Path) -> None:
    connection = open_database(tmp_path / "history.duckdb")
    try:
        snapshot = march_project / "output" / "2026-03" / "open_book.csv"
        load_month(connection, "2026-03", snapshot)
        before = connection.execute("SELECT * FROM open_book_history ORDER BY source_system, line_key").fetchall()
        totals = connection.execute("SELECT COUNT(*), SUM(amount_open_usd) FROM open_book_history").fetchone()
        load_month(connection, "2026-03", snapshot)
        assert connection.execute("SELECT COUNT(*), SUM(amount_open_usd) FROM open_book_history").fetchone() == totals
        assert connection.execute("SELECT * FROM open_book_history ORDER BY source_system, line_key").fetchall() == before
    finally:
        connection.close()


def test_missing_fx_fails_only_its_source(generated_project: Path, tmp_path: Path) -> None:
    raw = tmp_path / "data" / "raw"
    shutil.copytree(generated_project / "data" / "raw", raw)
    rates = pd.read_csv(raw / "fx_rates.csv")
    rates = rates[~((rates["period"] == "2026-03") & (rates["currency"] == "GBP"))]
    rates.to_csv(raw / "fx_rates.csv", index=False)
    assert run(tmp_path, "2026-03", "2026-03-31") == 1
    summary = json.loads((tmp_path / "output" / "2026-03" / "run_summary.json").read_text())
    assert summary["exit_code"] == 1
    assert summary["sources"]["A"]["status"] == "failed"
    assert "FX 2026-03 GBP" in summary["sources"]["A"]["errors"][0]
    assert summary["sources"]["B"]["status"] == summary["sources"]["C"]["status"] == "success"
    assert set(read_view(tmp_path, "2026-03", "open_book")["source_system"]) == {"B", "C"}


def test_duplicate_order_copies_only_appear_in_review(march_project: Path) -> None:
    pattern = r"-dup\d+(?:::|$)"
    for view in ("open_book", "closed"):
        assert not read_view(march_project, "2026-03", view)["line_key"].str.contains(pattern).any()
    review = read_view(march_project, "2026-03", "review")
    copies = review[review["line_key"].str.contains(pattern)]
    assert len(copies) == 7
    assert copies["line_status"].eq("review").all()
    assert copies["status_reason"].eq("duplicate order row").all()
    summary = json.loads((march_project / "output" / "2026-03" / "run_summary.json").read_text())
    assert set(copies["line_key"].str.split("::").str[0]) == set(summary["sources"]["A"]["duplicate_order_lines"])


def test_movements_sum_to_the_change_in_open_amount(march_project: Path, tmp_path: Path) -> None:
    assert run(march_project, "2026-02", "2026-02-28") == 0
    connection = open_database(tmp_path / "history.duckdb")
    try:
        for month in ("2026-02", "2026-03"):
            load_month(connection, month, march_project / "output" / month / "open_book.csv")
        change = connection.execute("""
            SELECT SUM(operational_usd + fx_effect_usd) FROM monthly_movements
            WHERE month_before = '2026-02' AND month_after = '2026-03'
        """).fetchone()[0]
        totals = [sum(read_view(march_project, month, "open_book")["amount_open_usd"].map(Decimal), Decimal(0)) for month in ("2026-02", "2026-03")]
        assert change == totals[1] - totals[0]
        assert connection.execute("""
            SELECT COUNT(*) FROM monthly_movements
            WHERE amount_open_usd_difference <> operational_usd + fx_effect_usd
        """).fetchone()[0] == 0
        assert connection.execute("""
            SELECT COUNT(*) FROM monthly_movements
            WHERE currency_code = 'USD' AND fx_effect_usd <> 0
        """).fetchone()[0] == 0
        assert connection.execute("""
            SELECT COUNT(*) FROM monthly_movements
            WHERE (movement_type = 'changed' AND amount_open_lc_before = amount_open_lc_after)
               OR (movement_type = 'unchanged' AND amount_open_lc_before <> amount_open_lc_after)
        """).fetchone()[0] == 0
        counts = dict(connection.execute("SELECT movement_type, COUNT(*) FROM monthly_movements GROUP BY movement_type").fetchall())
        assert all(counts.get(kind, 0) > 0 for kind in ("added", "removed", "changed"))
    finally:
        connection.close()
