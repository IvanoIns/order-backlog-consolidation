"""Signed AUD ledger, aggregated after the cutoff filter."""

from pathlib import Path

from ..common import AdapterResult, InputTotals, at_cutoff, cents, frame, make_line, quantities, read_csv

KEYS = ["order_id", "product_code"]
EVENT_TYPES = {"ORDER", "ORDER_ADJUSTMENT", "BILLING"}


def load(raw: Path, cutoff: str) -> AdapterResult:
    all_events = read_csv(raw / "source_c" / "ledger_2025-01_to_2026-06.csv", KEYS + [
        "event_id", "event_date", "event_type", "customer_id", "quantity_delta", "amount_aud",
    ])
    events = at_cutoff(all_events, "event_date", cutoff)
    if not set(events["event_type"]) <= EVENT_TYPES:
        raise ValueError("C: unrecognized ledger event type")
    if not events["event_id"].is_unique:
        raise ValueError("C: duplicate event identifiers")
    events["units"] = quantities(events["quantity_delta"])
    events["cents"] = events["amount_aud"].map(cents)
    orders = events[events["event_type"] != "BILLING"]
    billing = events[events["event_type"] == "BILLING"]
    totals = InputTotals(
        len(events), int(orders["cents"].sum()), -int(billing["cents"].sum()),
        event_rows=len(events),
    )
    rows = []
    for (order, code), group in events.groupby(KEYS, sort=False):
        if group["customer_id"].nunique() != 1:
            raise ValueError(f"C: conflicting customers for {order}|{code}")
        original = group[group["event_type"] == "ORDER"]
        ordered = group[group["event_type"] != "BILLING"]
        billed = group[group["event_type"] == "BILLING"]
        rows.append(make_line(
            "C", cutoff, "AUD", order, code, str(group["customer_id"].iloc[0]),
            str(original["event_date"].min()) if len(original) else "",
            int(ordered["units"].sum()), -int(billed["units"].sum()),
            int(ordered["cents"].sum()), -int(billed["cents"].sum()),
            status="review" if original.empty else "",
            reason="ledger event without order" if original.empty else "",
        ))
    return AdapterResult(frame(rows), totals, notes={
        "after_cutoff_rows": len(all_events) - len(events),
        "order_adjustment_rows": int((events["event_type"] == "ORDER_ADJUSTMENT").sum()),
    })
