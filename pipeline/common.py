"""Shared source contract and exact monetary values."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

COLUMNS = [
    "cutoff_month", "source_system", "line_key", "source_order_id",
    "source_product_code", "product_code", "customer_id", "order_date",
    "qty_ordered", "qty_billed", "qty_open", "amount_ordered_lc",
    "amount_billed_lc", "amount_open_lc", "currency_code", "fx_rate_to_usd",
    "amount_open_usd", "line_status", "status_reason",
]
VIEWS = ("open_book", "review", "closed", "excluded", "sales_without_order")


@dataclass
class InputTotals:
    rows: int
    ordered_cents: int
    billed_cents: int
    order_rows: int = 0
    billing_rows: int = 0
    event_rows: int = 0


@dataclass
class AdapterResult:
    lines: pd.DataFrame
    totals: InputTotals
    sales_without_order: pd.DataFrame = field(default_factory=lambda: frame([]))
    excluded: pd.DataFrame = field(default_factory=lambda: frame([]))
    notes: dict[str, object] = field(default_factory=dict)


def cents(value: object) -> int:
    try:
        scaled = Decimal(str(value)) * 100
        if not scaled.is_finite() or scaled != scaled.to_integral_value():
            raise ValueError(f"Amount must have whole cents: {value}")
        return int(scaled)
    except InvalidOperation as error:
        raise ValueError(f"Invalid monetary amount: {value}") from error


def money(value: int) -> str:
    return f"{Decimal(int(value)) / 100:.2f}"


def total_cents(values: pd.Series) -> int:
    return sum(cents(value) for value in values)


def read_csv(path: Path, required: list[str]) -> pd.DataFrame:
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = set(required) - set(table.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    return table


def read_files(folder: Path, pattern: str, required: list[str]) -> pd.DataFrame:
    paths = sorted(folder.glob(pattern))
    if not paths:
        raise ValueError(f"No input files: {folder.name}/{pattern}")
    return pd.concat([read_csv(path, required) for path in paths], ignore_index=True)


def at_cutoff(table: pd.DataFrame, date_column: str, cutoff: str) -> pd.DataFrame:
    dates = table[date_column]
    if not dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise ValueError(f"Invalid ISO date in {date_column}")
    pd.to_datetime(dates, format="%Y-%m-%d", errors="raise")
    return table.loc[dates <= cutoff].copy()


def quantities(values: pd.Series) -> pd.Series:
    numbers = pd.to_numeric(values, errors="raise")
    if numbers.isna().any() or (numbers % 1 != 0).any():
        raise ValueError("Quantities must be finite whole units")
    return numbers.astype("int64")


def frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=COLUMNS)


def make_line(
    source: str, cutoff: str, currency: str, order: str, code: str,
    customer: str, order_date: str, qty_ordered: int, qty_billed: int,
    ordered_cents: int, billed_cents: int, key: str = "",
    status: str = "", reason: str = "",
) -> dict[str, object]:
    return dict(zip(COLUMNS, [
        cutoff[:7], source, key or f"{source}:{order}|{code}", order, code, "",
        customer, order_date, int(qty_ordered), int(qty_billed),
        int(qty_ordered - qty_billed), money(ordered_cents), money(billed_cents),
        money(ordered_cents - billed_cents), currency, "", "", status, reason,
    ]))


def add_reason(existing: str, reason: str) -> str:
    return f"{existing}; {reason}" if existing else reason
