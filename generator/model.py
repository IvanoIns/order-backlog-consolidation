"""Shared definitions for synthetic source records."""

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

MONTHS = tuple(pd.period_range("2025-01", "2026-06", freq="M"))
SOURCES = ("A", "B", "C")
STATUSES = (
    "fully_open",
    "partially_invoiced",
    "fully_invoiced",
    "over_invoiced",
)
CODE_KINDS = ("catalog_code", "mapped_code", "bundle_code", "unmapped_code")


@dataclass(frozen=True)
class Line:
    source: str
    period: str
    order_id: str
    product_code: str
    customer_id: str
    order_date: str
    billing_date: str
    quantity: int
    order_cents: int
    billing_quantity: int
    billing_cents: int
    adjustment_quantity: int
    adjustment_cents: int
    status: str
    code_kind: str


def random_date(month: pd.Period, rng: np.random.Generator) -> str:
    day = int(rng.integers(1, month.days_in_month + 1))
    return f"{month}-{day:02d}"


def billing_date(order_date: str, rng: np.random.Generator) -> str:
    start = pd.Timestamp(order_date)
    stop = min(start + pd.Timedelta(days=75), MONTHS[-1].end_time.normalize())
    offset = int(rng.integers(0, (stop - start).days + 1))
    return (start + pd.Timedelta(days=offset)).strftime("%Y-%m-%d")


def make_line(
    source: str,
    month: pd.Period,
    index: int,
    code: str,
    customer: str,
    status: str,
    code_kind: str,
    adjusted: bool,
    rng: np.random.Generator,
) -> Line:
    quantity = int(rng.integers(1, 11)) * 20
    unit_cents = int(rng.integers(500, 30001))
    adjustment_quantity = quantity // 10 if adjusted else 0
    adjustment_cents = adjustment_quantity * unit_cents
    order_cents = quantity * unit_cents
    net_quantity = quantity - adjustment_quantity
    ratios = {"fully_open": 0.0, "fully_invoiced": 1.0, "over_invoiced": 1.2}
    ratio = (
        float(rng.choice([0.25, 0.5, 0.75]))
        if status == "partially_invoiced"
        else ratios[status]
    )
    placed = random_date(month, rng)
    billed_quantity = int(round(net_quantity * ratio))
    return Line(
        source=source,
        period=str(month),
        order_id=f"{source}{month.strftime('%y%m')}-{index // 3 + 1:04d}",
        product_code=code,
        customer_id=customer,
        order_date=placed,
        billing_date=billing_date(placed, rng),
        quantity=quantity,
        order_cents=order_cents,
        billing_quantity=billed_quantity,
        billing_cents=billed_quantity * unit_cents,
        adjustment_quantity=adjustment_quantity,
        adjustment_cents=adjustment_cents,
        status=status,
        code_kind=code_kind,
    )


def with_order_date(line: Line, order_date: str) -> Line:
    latest = min(
        pd.Timestamp(order_date) + pd.Timedelta(days=75),
        MONTHS[-1].end_time.normalize(),
    ).strftime("%Y-%m-%d")
    billed_on = max(order_date, min(line.billing_date, latest))
    return replace(line, order_date=order_date, billing_date=billed_on)


def choose_code(
    pool: list[str], used: set[str], rng: np.random.Generator
) -> str:
    available = [code for code in pool if code not in used]
    code = str(rng.choice(available))
    used.add(code)
    return code


def build_month(
    source: str,
    month: pd.Period,
    month_index: int,
    pools: dict[str, list[str]],
    rng: np.random.Generator,
) -> list[Line]:
    statuses = rng.permutation(
        [STATUSES[0]] * 24 + [STATUSES[1]] * 18
        + [STATUSES[2]] * 12 + [STATUSES[3]] * 6
    )
    kinds = rng.permutation(
        [CODE_KINDS[0]] * 42 + [CODE_KINDS[1]] * 12
        + [CODE_KINDS[2]] * 4 + [CODE_KINDS[3]] * 2
    )
    lines: list[Line] = []
    used: set[str] = set()
    customer = ""
    order_date = ""
    has_adjustment = False
    for index, (status, kind) in enumerate(zip(statuses, kinds)):
        if index % 3 == 0:
            used = set()
            customer = f"CU{int(rng.integers(1, 151)):03d}"
        adjusted = (
            source == "C" and month_index % 3 == 1
            and status == "partially_invoiced" and not has_adjustment
        )
        # Keep line-level draws so other seeded fields stay unchanged.
        line = make_line(
            source, month, index, choose_code(pools[str(kind)], used, rng),
            customer, str(status), str(kind), adjusted, rng,
        )
        if index % 3 == 0:
            order_date = line.order_date
        lines.append(with_order_date(line, order_date))
        has_adjustment = has_adjustment or adjusted
    return lines
