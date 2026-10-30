"""Export each fictional source in its own shape."""

from dataclasses import dataclass, replace
from pathlib import Path

import pandas as pd

from .manifest import Manifest
from .model import MONTHS, Line


@dataclass(frozen=True)
class Billing:
    suffix: str
    date: str
    quantity: int
    cents: int


def last_billing_date(line: Line) -> pd.Timestamp:
    return min(
        pd.Timestamp(line.order_date) + pd.Timedelta(days=75),
        MONTHS[-1].end_time.normalize(),
    )


def multi_invoice_counts(lines: list[Line]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for month in MONTHS:
        for status, divisor in (("partially_invoiced", 2), ("over_invoiced", 3)):
            candidates = [
                line for line in lines
                if line.period == str(month) and line.status == status
            ]
            eligible = [
                line for line in candidates
                if pd.Timestamp(line.order_date) < last_billing_date(line)
                and line.billing_quantity >= 2
            ]
            for index, line in enumerate(eligible[:len(candidates) // divisor]):
                days = (last_billing_date(line) - pd.Timestamp(line.order_date)).days + 1
                counts[line.order_id, line.product_code] = min(
                    2 + index % 2, days, line.billing_quantity,
                )
    return counts


def split_billing(line: Line, parts: int) -> list[Billing]:
    if parts == 1:
        return [Billing("", line.billing_date, line.billing_quantity, line.billing_cents)]
    first_possible_end = pd.Timestamp(line.order_date) + pd.Timedelta(days=parts - 1)
    end = min(max(pd.Timestamp(line.billing_date), first_possible_end), last_billing_date(line))
    first_date = end - pd.Timedelta(days=parts - 1)
    units, remainder = divmod(line.billing_quantity, parts)
    unit_cents = line.order_cents // line.quantity
    return [
        Billing(
            f"-{index + 1:02d}",
            (first_date + pd.Timedelta(days=index)).strftime("%Y-%m-%d"),
            units + (1 if index < remainder else 0),
            (units + (1 if index < remainder else 0)) * unit_cents,
        )
        for index in range(parts)
    ]


def billing_span_score(dates: list[int], months: list[int]) -> int:
    first, last = min(dates), max(dates)
    # A month crossing outweighs any span change for two lines.
    return last - first + 151 * (months[first] != months[last])


def best_date_swap(
    left: list[int], right: list[int],
    left_bounds: tuple[int, int], right_bounds: tuple[int, int],
    months: list[int],
) -> tuple[int, int] | None:
    best_score = billing_span_score(left, months) + billing_span_score(right, months)
    best: tuple[int, int] | None = None
    for left_index, left_date in enumerate(left):
        if not right_bounds[0] <= left_date <= right_bounds[1] or left_date in right:
            continue
        for right_index, right_date in enumerate(right):
            if not left_bounds[0] <= right_date <= left_bounds[1] or right_date in left:
                continue
            new_left, new_right = left.copy(), right.copy()
            new_left[left_index], new_right[right_index] = right_date, left_date
            score = billing_span_score(new_left, months) + billing_span_score(new_right, months)
            if score > best_score:
                best_score = score
                best = (left_index, right_index)
    return best


def spread_billing_dates(
    lines: list[Line], billings: dict[tuple[str, str], list[Billing]]
) -> None:
    selected = [
        line for line in lines
        if len(billings.get((line.order_id, line.product_code), [])) > 1
    ]
    base = MONTHS[0].start_time.toordinal()
    months = [date.month for date in pd.date_range(MONTHS[0].start_time, MONTHS[-1].end_time)]
    keys = [(line.order_id, line.product_code) for line in selected]
    dates = [[pd.Timestamp(bill.date).toordinal() - base for bill in billings[key]] for key in keys]
    bounds = [
        (pd.Timestamp(line.order_date).toordinal() - base, last_billing_date(line).toordinal() - base)
        for line in selected
    ]
    # Swaps preserve the existing number of billing rows in every month.
    for _ in range(6):
        changed = False
        for left in range(len(keys)):
            for right in range(left + 1, len(keys)):
                swap = best_date_swap(dates[left], dates[right], bounds[left], bounds[right], months)
                if swap is not None:
                    first, second = swap
                    dates[left][first], dates[right][second] = dates[right][second], dates[left][first]
                    changed = True
        if not changed:
            break
    for key, assigned in zip(keys, dates):
        billings[key] = [
            replace(bill, date=pd.Timestamp.fromordinal(base + day).strftime("%Y-%m-%d"))
            for bill, day in zip(billings[key], sorted(assigned))
        ]


def build_billings(
    lines: list[Line], manifest: Manifest
) -> dict[tuple[str, str], list[Billing]]:
    counts = multi_invoice_counts(lines)
    billings: dict[tuple[str, str], list[Billing]] = {}
    for line in lines:
        if not line.billing_quantity:
            continue
        key = (line.order_id, line.product_code)
        parts = counts.get(key, 1)
        billings[key] = split_billing(line, parts)
        if parts > 1:
            manifest.add(line.source, line.period, "multi_invoice_lines")
    spread_billing_dates(lines, billings)
    for line in lines:
        rows = billings.get((line.order_id, line.product_code), [])
        if len({bill.date[:7] for bill in rows}) > 1:
            manifest.add(line.source, line.period, "multi_month_billing_lines")
    return billings


def save_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def record_rows(
    manifest: Manifest, source: str, rows: list[dict[str, object]],
    date_column: str, case: str,
) -> None:
    for row in rows:
        # Future exceptions belong to the file's final covered period.
        period = min(str(row[date_column])[:7], str(MONTHS[-1]))
        manifest.add(source, period, case)


def a_order(line: Line) -> dict[str, object]:
    return {
        "doc_no": line.order_id, "item_code": line.product_code,
        "customer_id": line.customer_id, "order_date": line.order_date,
        "quantity": line.quantity, "order_value_gbp": line.order_cents / 100,
    }


def a_invoice(line: Line, billing: Billing) -> dict[str, object]:
    return {
        "invoice_no": f"INV-{line.order_id}-{line.product_code}{billing.suffix}",
        "doc_no": line.order_id, "item_code": line.product_code,
        "invoice_date": billing.date,
        "invoiced_quantity": billing.quantity,
        "invoice_value_gbp": billing.cents / 100,
    }


def write_a(raw: Path, lines: list[Line], manifest: Manifest) -> None:
    orders = [a_order(line) for line in lines]
    billings = build_billings(lines, manifest)
    invoices = [
        a_invoice(line, billing) for line in lines
        for billing in billings.get((line.order_id, line.product_code), [])
    ]
    for month_index in range(0, len(MONTHS), 3):
        period = str(MONTHS[month_index])
        original = next(row for row in orders if str(row["order_date"]).startswith(period))
        orders.append(original.copy())
        manifest.add("A", period, "duplicate_keys")
        manifest.add("A", period, "duplicate_extra_rows")
    for month in MONTHS:
        period = str(month)
        for kind, rows, date_column in (
            ("orders", orders, "order_date"), ("invoices", invoices, "invoice_date"),
        ):
            monthly = [row for row in rows if str(row[date_column]).startswith(period)]
            save_csv(raw / "source_a" / f"{kind}_{period}.csv", pd.DataFrame(monthly))
    record_rows(manifest, "A", orders, "order_date", "raw_order_rows")
    record_rows(manifest, "A", invoices, "invoice_date", "raw_billing_rows")


def b_order(line: Line) -> dict[str, object]:
    return {
        "order_ref": line.order_id, "product_ref": line.product_code,
        "account_ref": line.customer_id, "ordered_on": line.order_date,
        "ordered_units": line.quantity, "order_amount_usd": line.order_cents / 100,
    }


def b_sale(line: Line, billing: Billing) -> dict[str, object]:
    return {
        "sale_ref": f"SALE-{line.order_id}-{line.product_code}{billing.suffix}",
        "order_ref": line.order_id, "product_ref": line.product_code,
        "account_ref": line.customer_id, "sold_on": billing.date,
        "sold_units": billing.quantity, "sales_amount_usd": billing.cents / 100,
    }


def add_b_exceptions(
    orders: list[dict[str, object]], sales: list[dict[str, object]], manifest: Manifest
) -> None:
    for month_index in range(0, len(MONTHS), 3):
        period = str(MONTHS[month_index])
        for index in range(1, 3):
            sales.append({
                "sale_ref": f"SALE-ORPHAN-{period}-{index}",
                "order_ref": f"B-ORPHAN-{period}-{index}",
                "product_ref": f"P{200 + index:04d}", "account_ref": f"CU{index:03d}",
                "sold_on": f"{period}-15", "sold_units": 2,
                "sales_amount_usd": 100.0 * index,
            })
            manifest.add("B", period, "unmatched_sales_rows")
    for index in range(1, 4):
        order_ref = f"B-FUTURE-{index:03d}"
        orders.append({
            "order_ref": order_ref, "product_ref": f"P{index:04d}",
            "account_ref": f"CU{index:03d}", "ordered_on": f"2026-07-{index:02d}",
            "ordered_units": 10, "order_amount_usd": 1000.0,
        })
        sales.append({
            "sale_ref": f"SALE-{order_ref}", "order_ref": order_ref,
            "product_ref": f"P{index:04d}", "account_ref": f"CU{index:03d}",
            "sold_on": f"2026-07-{index + 3:02d}", "sold_units": 5,
            "sales_amount_usd": 500.0,
        })
    manifest.add("B", str(MONTHS[-1]), "future_dated_rows", 6)


def write_b(raw: Path, lines: list[Line], manifest: Manifest) -> None:
    orders = [b_order(line) for line in lines]
    billings = build_billings(lines, manifest)
    sales = [
        b_sale(line, billing) for line in lines
        for billing in billings.get((line.order_id, line.product_code), [])
    ]
    add_b_exceptions(orders, sales, manifest)
    coverage = "2025-01_to_2026-06"
    save_csv(raw / "source_b" / f"orders_{coverage}.csv", pd.DataFrame(orders))
    save_csv(raw / "source_b" / f"sales_{coverage}.csv", pd.DataFrame(sales))
    record_rows(manifest, "B", orders, "ordered_on", "raw_order_rows")
    record_rows(manifest, "B", sales, "sold_on", "raw_billing_rows")


def c_event(
    line: Line, event_type: str, event_date: str, quantity: int, cents: int,
    suffix: str = "",
) -> dict[str, object]:
    return {
        "event_id": f"EV-{line.order_id}-{line.product_code}-{event_type}{suffix}",
        "event_date": event_date, "event_type": event_type,
        "order_id": line.order_id, "product_code": line.product_code,
        "customer_id": line.customer_id, "quantity_delta": quantity,
        "amount_aud": cents / 100,
    }


def write_c(raw: Path, lines: list[Line], manifest: Manifest) -> None:
    events: list[dict[str, object]] = []
    billings = build_billings(lines, manifest)
    for line in lines:
        events.append(c_event(line, "ORDER", line.order_date, line.quantity, line.order_cents))
        if line.adjustment_cents:
            events.append(c_event(
                line, "ORDER_ADJUSTMENT", line.order_date,
                -line.adjustment_quantity, -line.adjustment_cents,
            ))
            manifest.add("C", line.period, "negative_adjustment_rows")
        for billing in billings.get((line.order_id, line.product_code), []):
            events.append(c_event(
                line, "BILLING", billing.date,
                -billing.quantity, -billing.cents, billing.suffix,
            ))
    frame = pd.DataFrame(events).sort_values(["event_date", "event_id"], kind="stable")
    save_csv(raw / "source_c" / "ledger_2025-01_to_2026-06.csv", frame)
    record_rows(manifest, "C", events, "event_date", "raw_event_rows")
