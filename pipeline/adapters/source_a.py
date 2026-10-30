"""Monthly GBP orders and invoices with a full outer join."""

from pathlib import Path

from ..common import AdapterResult, InputTotals, at_cutoff, cents, frame, make_line, quantities, read_files

KEYS = ["doc_no", "item_code"]


def load(raw: Path, cutoff: str) -> AdapterResult:
    folder = raw / "source_a"
    all_orders = read_files(folder, "orders_*.csv", KEYS + [
        "customer_id", "order_date", "quantity", "order_value_gbp",
    ])
    all_invoices = read_files(folder, "invoices_*.csv", KEYS + [
        "invoice_no", "invoice_date", "invoiced_quantity", "invoice_value_gbp",
    ])
    orders = at_cutoff(all_orders, "order_date", cutoff)
    invoices = at_cutoff(all_invoices, "invoice_date", cutoff)
    if orders.drop_duplicates().duplicated(KEYS).any():
        raise ValueError("A: conflicting order rows share a document and product key")
    orders["qty_ordered"] = quantities(orders["quantity"])
    orders["ordered_cents"] = orders["order_value_gbp"].map(cents)
    invoices["qty_billed"] = quantities(invoices["invoiced_quantity"])
    invoices["billed_cents"] = invoices["invoice_value_gbp"].map(cents)
    orders["copy_number"] = orders.groupby(KEYS, sort=False).cumcount()
    billing = invoices.groupby(KEYS, as_index=False)[["qty_billed", "billed_cents"]].sum()
    joined = orders.merge(billing, on=KEYS, how="outer", indicator=True, validate="many_to_one")
    rows, duplicates = [], []
    for record in joined.to_dict("records"):
        row, duplicate = joined_line(record, cutoff)
        rows.append(row)
        if duplicate:
            duplicates.append(str(row["line_key"]))
    totals = InputTotals(
        len(orders) + len(invoices), int(orders["ordered_cents"].sum()),
        int(invoices["billed_cents"].sum()), len(orders), len(invoices),
    )
    return AdapterResult(frame(rows), totals, notes={
        "after_cutoff_rows": len(all_orders) + len(all_invoices) - totals.rows,
        "duplicate_order_lines": duplicates,
        "duplicate_billing_rule": "Billing is assigned once to the original; duplicate copies keep their amounts in review.",
    })


def joined_line(record: dict[str, object], cutoff: str) -> tuple[dict[str, object], bool]:
    has_order = record["_merge"] != "right_only"
    has_billing = record["_merge"] != "left_only"
    copy = int(record["copy_number"]) if has_order else 0
    key = f"A:{record['doc_no']}|{record['item_code']}"
    if copy:
        key += f"-dup{copy}"
    # Repeating the invoice total on each copy would create extra billing.
    billed = has_billing and copy == 0
    row = make_line(
        "A", cutoff, "GBP", str(record["doc_no"]), str(record["item_code"]),
        str(record["customer_id"]) if has_order else "",
        str(record["order_date"]) if has_order else "",
        int(record["qty_ordered"]) if has_order else 0,
        int(record["qty_billed"]) if billed else 0,
        int(record["ordered_cents"]) if has_order else 0,
        int(record["billed_cents"]) if billed else 0, key=key,
        status="review" if copy or not has_order else "",
        reason="duplicate order row" if copy else ("invoice without order" if not has_order else ""),
    )
    return row, copy > 0
