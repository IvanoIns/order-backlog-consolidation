"""Bridge raw records to output lines and compare local-currency totals."""

import json

import pandas as pd

from .common import AdapterResult, total_cents, money

FIELDS = [
    "source_system", "source_status", "currency_code", "input_rows",
    "adapter_row_adjustment", "bundle_added_rows", "expected_output_rows",
    "output_rows", "rows_difference", "input_ordered_lc", "output_ordered_lc",
    "ordered_difference_lc", "input_billed_lc", "output_billed_lc",
    "billed_difference_lc", "duplicate_order_rows", "duplicate_line_keys", "error",
]


def report(
    source: str, adapted: AdapterResult, views: dict[str, pd.DataFrame], bundle_added: int
) -> dict[str, object]:
    original_lines = len(adapted.lines) + len(adapted.sales_without_order) + len(adapted.excluded)
    output_rows = sum(len(table) for table in views.values())
    ordered = sum(total_cents(table["amount_ordered_lc"]) for table in views.values())
    billed = sum(total_cents(table["amount_billed_lc"]) for table in views.values())
    duplicates = adapted.notes.get("duplicate_order_lines", [])
    return {
        "source_system": source, "source_status": "success",
        "currency_code": {"A": "GBP", "B": "USD", "C": "AUD"}[source],
        "input_rows": adapted.totals.rows,
        "adapter_row_adjustment": original_lines - adapted.totals.rows,
        "bundle_added_rows": bundle_added,
        "expected_output_rows": original_lines + bundle_added,
        "output_rows": output_rows,
        "rows_difference": original_lines + bundle_added - output_rows,
        "input_ordered_lc": money(adapted.totals.ordered_cents),
        "output_ordered_lc": money(ordered),
        "ordered_difference_lc": money(adapted.totals.ordered_cents - ordered),
        "input_billed_lc": money(adapted.totals.billed_cents),
        "output_billed_lc": money(billed),
        "billed_difference_lc": money(adapted.totals.billed_cents - billed),
        "duplicate_order_rows": len(duplicates), "duplicate_line_keys": json.dumps(duplicates),
        "error": "",
    }


def check(row: dict[str, object]) -> None:
    if row["rows_difference"] or row["ordered_difference_lc"] != "0.00" or row["billed_difference_lc"] != "0.00":
        raise ValueError(f"{row['source_system']}: reconciliation failed: {row}")


def failed(source: str, error: str) -> dict[str, object]:
    row = dict.fromkeys(FIELDS, "")
    row.update(source_system=source, source_status="failed", error=error)
    return row
