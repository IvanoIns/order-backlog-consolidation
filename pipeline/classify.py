"""Assign exactly one status and explain each non-open line."""

import pandas as pd

from .common import add_reason, cents, frame


def classify(table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for row in table.to_dict("records"):
        if row["line_status"] == "excluded":
            if not row["status_reason"]:
                raise ValueError(f"Excluded line needs a reason: {row['line_key']}")
            rows.append(row)
            continue
        reasons = str(row["status_reason"])
        if "duplicate order row" in reasons.split("; "):
            row["line_status"], row["status_reason"] = "review", "duplicate order row"
            rows.append(row)
            continue
        if not row["product_code"] and "unmapped product code" not in reasons:
            reasons = add_reason(reasons, "unmapped product code")
        qty, amount = int(row["qty_open"]), cents(row["amount_open_lc"])
        if qty < 0 or amount < 0:
            reasons = add_reason(reasons, "over-billed")
        if reasons:
            row["line_status"], row["status_reason"] = "review", reasons
        elif qty > 0 and amount > 0:
            row["line_status"], row["status_reason"] = "open", ""
        elif qty == 0 and amount == 0:
            row["line_status"], row["status_reason"] = "closed", "fully billed"
        else:
            row["line_status"], row["status_reason"] = "review", "quantity and value do not agree"
        rows.append(row)
    return frame(rows)
