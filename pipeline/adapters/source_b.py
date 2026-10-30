"""USD order-led book, separate orphan sales, and declared coverage."""

from pathlib import Path

import pandas as pd

from ..common import AdapterResult, InputTotals, at_cutoff, cents, frame, make_line, quantities, read_csv

KEYS = ["order_ref", "product_ref"]
COVERAGE_END = "2026-06-30"


def load(raw: Path, cutoff: str) -> AdapterResult:
    folder = raw / "source_b"
    all_orders = read_csv(folder / "orders_2025-01_to_2026-06.csv", KEYS + [
        "account_ref", "ordered_on", "ordered_units", "order_amount_usd",
    ])
    all_sales = read_csv(folder / "sales_2025-01_to_2026-06.csv", KEYS + [
        "sale_ref", "account_ref", "sold_on", "sold_units", "sales_amount_usd",
    ])
    orders = at_cutoff(all_orders, "ordered_on", cutoff)
    sales = at_cutoff(all_sales, "sold_on", cutoff)
    orders["qty_ordered"] = quantities(orders["ordered_units"])
    orders["ordered_cents"] = orders["order_amount_usd"].map(cents)
    sales["qty_billed"] = quantities(sales["sold_units"])
    sales["billed_cents"] = sales["sales_amount_usd"].map(cents)
    totals = InputTotals(
        len(orders) + len(sales), int(orders["ordered_cents"].sum()),
        int(sales["billed_cents"].sum()), len(orders), len(sales),
    )
    excluded = coverage_rows(orders, sales, cutoff)
    orders = orders[orders["ordered_on"] <= COVERAGE_END].copy()
    sales = sales[sales["sold_on"] <= COVERAGE_END].copy()
    if orders.duplicated(KEYS).any():
        raise ValueError("B: duplicate order keys are not supported")
    billing = sales.groupby(KEYS, as_index=False)[["qty_billed", "billed_cents"]].sum()
    joined = orders.merge(billing, on=KEYS, how="left", validate="one_to_one")
    rows = [order_line(record, cutoff) for record in joined.to_dict("records")]
    orphan = sales.merge(orders[KEYS], on=KEYS, how="left", indicator=True)
    orphan = orphan[orphan["_merge"] == "left_only"]
    orphan = orphan.groupby(KEYS, as_index=False).agg(
        account_ref=("account_ref", "first"), qty_billed=("qty_billed", "sum"),
        billed_cents=("billed_cents", "sum"),
    )
    orphan_rows = [make_line(
        "B", cutoff, "USD", record.order_ref, record.product_ref, record.account_ref,
        "", 0, int(record.qty_billed), 0, int(record.billed_cents),
        key=f"B:sales_without_order:{record.order_ref}|{record.product_ref}",
        status="review", reason="sale without matching order",
    ) for record in orphan.itertuples(index=False)]
    outside_after_cutoff = int(
        ((all_orders["ordered_on"] > COVERAGE_END) & (all_orders["ordered_on"] > cutoff)).sum()
        + ((all_sales["sold_on"] > COVERAGE_END) & (all_sales["sold_on"] > cutoff)).sum()
    )
    return AdapterResult(frame(rows), totals, frame(orphan_rows), frame(excluded), {
        "after_cutoff_rows": len(all_orders) + len(all_sales) - totals.rows,
        "outside_coverage_after_cutoff_rows": outside_after_cutoff,
        "outside_coverage_after_cutoff_reason": "outside coverage: dated after 2026-06-30; also after cutoff",
    })


def order_line(record: dict[str, object], cutoff: str) -> dict[str, object]:
    billed = pd.notna(record["qty_billed"])
    return make_line(
        "B", cutoff, "USD", str(record["order_ref"]), str(record["product_ref"]),
        str(record["account_ref"]), str(record["ordered_on"]),
        int(record["qty_ordered"]), int(record["qty_billed"]) if billed else 0,
        int(record["ordered_cents"]), int(record["billed_cents"]) if billed else 0,
    )


def coverage_rows(orders: pd.DataFrame, sales: pd.DataFrame, cutoff: str) -> list[dict[str, object]]:
    rows = []
    for index, record in enumerate(orders[orders["ordered_on"] > COVERAGE_END].itertuples(index=False)):
        rows.append(make_line(
            "B", cutoff, "USD", record.order_ref, record.product_ref, record.account_ref,
            record.ordered_on, int(record.qty_ordered), 0, int(record.ordered_cents), 0,
            key=f"B:excluded-order:{record.order_ref}|{record.product_ref}:{index}",
            status="excluded", reason=f"outside coverage: order dated {record.ordered_on} after {COVERAGE_END}",
        ))
    for record in sales[sales["sold_on"] > COVERAGE_END].itertuples(index=False):
        rows.append(make_line(
            "B", cutoff, "USD", record.order_ref, record.product_ref, record.account_ref,
            "", 0, int(record.qty_billed), 0, int(record.billed_cents),
            key=f"B:excluded-sale:{record.sale_ref}", status="excluded",
            reason=f"outside coverage: sale dated {record.sold_on} after {COVERAGE_END}",
        ))
    return rows
