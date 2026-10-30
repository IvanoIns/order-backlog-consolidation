"""Counts recorded when synthetic cases are planted."""

from collections import Counter

import pandas as pd

from .model import CODE_KINDS, MONTHS, SOURCES, STATUSES, Line

CASE_UNITS = {
    **{status: "order_lines" for status in STATUSES},
    **{kind: "order_lines" for kind in CODE_KINDS},
    "unique_order_lines": "order_lines",
    "multi_invoice_lines": "order_lines",
    "multi_month_billing_lines": "order_lines",
    "duplicate_keys": "keys",
    "duplicate_extra_rows": "rows",
    "unmatched_sales_rows": "rows",
    "future_dated_rows": "rows",
    "negative_adjustment_rows": "rows",
    "raw_order_rows": "rows",
    "raw_billing_rows": "rows",
    "raw_event_rows": "rows",
}


class Manifest:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.counts: Counter[tuple[str, str, str]] = Counter()

    def add(self, source: str, period: str, case: str, count: int = 1) -> None:
        self.counts[source, period, case] += count

    def add_lines(self, lines: list[Line]) -> None:
        for line in lines:
            for case in (line.status, line.code_kind, "unique_order_lines"):
                self.add(line.source, line.period, case)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([
            {
                "seed": self.seed, "source": source, "period": str(month),
                "case_name": case, "count": self.counts[source, str(month), case],
                "unit": unit,
            }
            for source in SOURCES
            for month in MONTHS
            for case, unit in CASE_UNITS.items()
        ])
