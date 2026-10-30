"""Replace monthly snapshots atomically and derive adjacent-month movements."""

from collections.abc import Callable
import json
from pathlib import Path
import sys

import duckdb
import pandas as pd

from .common import COLUMNS, read_csv

TYPES = {
    "cutoff_month": "VARCHAR", "source_system": "VARCHAR", "line_key": "VARCHAR",
    "source_order_id": "VARCHAR", "source_product_code": "VARCHAR", "product_code": "VARCHAR",
    "customer_id": "VARCHAR", "order_date": "DATE", "qty_ordered": "BIGINT",
    "qty_billed": "BIGINT", "qty_open": "BIGINT", "amount_ordered_lc": "DECIMAL(20,2)",
    "amount_billed_lc": "DECIMAL(20,2)", "amount_open_lc": "DECIMAL(20,2)",
    "currency_code": "VARCHAR", "fx_rate_to_usd": "DECIMAL(20,10)",
    "amount_open_usd": "DECIMAL(20,2)", "line_status": "VARCHAR", "status_reason": "VARCHAR",
}

MOVEMENT_ADDITIONS = {
    "amount_open_lc_before": "DECIMAL(20,2)",
    "amount_open_lc_after": "DECIMAL(20,2)",
    "currency_code": "VARCHAR",
    "operational_usd": "DECIMAL(20,2)",
    "fx_effect_usd": "DECIMAL(20,2)",
}

MOVEMENTS_SQL = """
INSERT INTO monthly_movements (
    month_before, month_after, source_system, line_key, source_order_id,
    source_product_code, product_code, customer_id, movement_type,
    amount_open_usd_before, amount_open_usd_after, amount_open_usd_difference,
    amount_open_lc_before, amount_open_lc_after, currency_code,
    operational_usd, fx_effect_usd
)
WITH pairs AS (
    SELECT b.cutoff_month AS month_before, a.cutoff_month AS month_after
    FROM history_months b JOIN history_months a
      ON CAST(a.cutoff_month || '-01' AS DATE) =
         CAST(b.cutoff_month || '-01' AS DATE) + INTERVAL '1 month'
), before_rows AS (
    SELECT p.month_before, p.month_after, h.*
    FROM pairs p JOIN open_book_history h ON h.cutoff_month = p.month_before
), after_rows AS (
    SELECT p.month_before, p.month_after, h.*
    FROM pairs p JOIN open_book_history h ON h.cutoff_month = p.month_after
), snapshots AS (
    SELECT
        COALESCE(b.month_before, a.month_before) AS month_before,
        COALESCE(b.month_after, a.month_after) AS month_after,
        COALESCE(a.source_system, b.source_system) AS source_system,
        COALESCE(a.line_key, b.line_key) AS line_key,
        COALESCE(a.source_order_id, b.source_order_id) AS source_order_id,
        COALESCE(a.source_product_code, b.source_product_code) AS source_product_code,
        COALESCE(a.product_code, b.product_code) AS product_code,
        COALESCE(a.customer_id, b.customer_id) AS customer_id,
        CASE WHEN b.line_key IS NULL THEN 'added'
             WHEN a.line_key IS NULL THEN 'removed'
             WHEN b.amount_open_lc <> a.amount_open_lc THEN 'changed'
             ELSE 'unchanged' END AS movement_type,
        COALESCE(b.amount_open_usd, 0.00) AS amount_open_usd_before,
        COALESCE(a.amount_open_usd, 0.00) AS amount_open_usd_after,
        COALESCE(a.amount_open_usd, 0.00) - COALESCE(b.amount_open_usd, 0.00)
            AS amount_open_usd_difference,
        COALESCE(b.amount_open_lc, 0.00) AS amount_open_lc_before,
        COALESCE(a.amount_open_lc, 0.00) AS amount_open_lc_after,
        COALESCE(a.currency_code, b.currency_code) AS currency_code,
        a.fx_rate_to_usd AS rate_after, b.fx_rate_to_usd AS rate_before
    FROM before_rows b FULL OUTER JOIN after_rows a
      ON b.month_before = a.month_before AND b.month_after = a.month_after
     AND b.source_system = a.source_system AND b.line_key = a.line_key
), effects AS (
    SELECT *,
        CASE WHEN movement_type IN ('added', 'removed') OR currency_code = 'USD'
             THEN amount_open_usd_difference
             ELSE CAST(ROUND((amount_open_lc_after - amount_open_lc_before)
                             * rate_after, 2) AS DECIMAL(20,2))
             END AS operational_usd,
        CASE WHEN movement_type IN ('added', 'removed') OR currency_code = 'USD'
             THEN CAST(0 AS DECIMAL(20,2))
             ELSE CAST(ROUND(amount_open_lc_before * (rate_after - rate_before), 2)
                       AS DECIMAL(20,2))
             END AS fx_formula_usd
    FROM snapshots
), rounded AS (
    SELECT *, amount_open_usd_difference - operational_usd - fx_formula_usd
              AS rounding_remainder_usd
    FROM effects
)
SELECT month_before, month_after, source_system, line_key, source_order_id,
       source_product_code, product_code, customer_id, movement_type,
       amount_open_usd_before, amount_open_usd_after, amount_open_usd_difference,
       amount_open_lc_before, amount_open_lc_after, currency_code, operational_usd,
       fx_formula_usd + rounding_remainder_usd
FROM rounded
"""


def open_database(path: Path) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(path))
    try:
        columns = ", ".join(f"{name} {kind}" for name, kind in TYPES.items())
        connection.execute(f"""
            CREATE TABLE IF NOT EXISTS open_book_history (
                {columns}, PRIMARY KEY (cutoff_month, source_system, line_key),
                CHECK (line_status = 'open'), CHECK (qty_open > 0),
                CHECK (amount_open_lc > 0), CHECK (amount_open_usd >= 0)
            )
        """)
        connection.execute("CREATE TABLE IF NOT EXISTS history_months (cutoff_month VARCHAR PRIMARY KEY)")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS monthly_movements (
                month_before VARCHAR, month_after VARCHAR, source_system VARCHAR,
                line_key VARCHAR, source_order_id VARCHAR, source_product_code VARCHAR,
                product_code VARCHAR, customer_id VARCHAR, movement_type VARCHAR,
                amount_open_usd_before DECIMAL(20,2), amount_open_usd_after DECIMAL(20,2),
                amount_open_usd_difference DECIMAL(20,2),
                amount_open_lc_before DECIMAL(20,2), amount_open_lc_after DECIMAL(20,2),
                currency_code VARCHAR, operational_usd DECIMAL(20,2), fx_effect_usd DECIMAL(20,2),
                PRIMARY KEY (month_before, month_after, source_system, line_key),
                CHECK (movement_type IN ('added', 'removed', 'changed', 'unchanged'))
            )
        """)
        return connection
    except Exception:
        connection.close()
        raise


def load_month(connection: duckdb.DuckDBPyConnection, month: str, path: Path) -> None:
    table = read_csv(path, COLUMNS)
    if not table["cutoff_month"].eq(month).all() or not table["line_status"].eq("open").all():
        raise ValueError(f"History snapshot does not match open cutoff {month}")
    if table.duplicated(["source_system", "line_key"]).any():
        raise ValueError(f"History snapshot has duplicate line keys: {month}")
    connection.register("incoming_snapshot", table[COLUMNS])
    expressions = ", ".join(f"CAST({name} AS {TYPES[name]})" for name in COLUMNS)
    connection.execute("BEGIN TRANSACTION")
    try:
        connection.execute("DELETE FROM open_book_history WHERE cutoff_month = ?", [month])
        connection.execute(f"INSERT INTO open_book_history SELECT {expressions} FROM incoming_snapshot")
        connection.execute("INSERT INTO history_months VALUES (?) ON CONFLICT DO NOTHING", [month])
        # Replacing a month can change both neighboring pairs.
        rebuild_movements(connection)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise
    finally:
        connection.unregister("incoming_snapshot")


def rebuild_movements(connection: duckdb.DuckDBPyConnection) -> None:
    existing = {row[0] for row in connection.execute("DESCRIBE monthly_movements").fetchall()}
    for name, kind in MOVEMENT_ADDITIONS.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE monthly_movements ADD COLUMN {name} {kind}")
    connection.execute("DELETE FROM monthly_movements")
    connection.execute(MOVEMENTS_SQL)
    invalid = connection.execute("""
        SELECT COUNT(*) FROM monthly_movements
        WHERE amount_open_usd_difference <> operational_usd + fx_effect_usd
           OR (currency_code = 'USD' AND fx_effect_usd <> 0)
    """).fetchone()[0]
    if invalid:
        raise ValueError(f"Movement USD decomposition failed for {invalid} rows")


def refresh_movements(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("BEGIN TRANSACTION")
    try:
        # Keep rounded snapshot cents; FX absorbs any rounding remainder.
        rebuild_movements(connection)
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise


def export_tables(connection: duckdb.DuckDBPyConnection, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for table, order in (
        ("open_book_history", "cutoff_month, source_system, line_key"),
        ("monthly_movements", "month_before, month_after, source_system, line_key"),
    ):
        path = str(folder / f"{table}.csv").replace("'", "''")
        connection.execute(f"COPY (SELECT * FROM {table} ORDER BY {order}) TO '{path}' (HEADER, FORMAT CSV)")


def process_month(
    project: Path, month: str, connection: duckdb.DuckDBPyConnection,
    runner: Callable[[Path, str, str], int],
) -> tuple[int, dict[str, object]]:
    cutoff = pd.Period(month, freq="M").end_time.strftime("%Y-%m-%d")
    code = runner(project, month, cutoff)
    if code:
        return code, {"status": "not loaded", "run_exit_code": code}
    load_month(connection, month, project / "output" / month / "open_book.csv")
    rows, total = connection.execute("""
        SELECT COUNT(*), COALESCE(SUM(amount_open_usd), 0.00)
        FROM open_book_history WHERE cutoff_month = ?
    """, [month]).fetchone()
    return 0, {"status": "loaded", "rows": rows, "open_amount_usd": str(total)}


def run_history(
    project: Path, start: str, end: str, runner: Callable[[Path, str, str], int]
) -> int:
    output = project / "output"
    try:
        connection = open_database(output / "backlog_history.duckdb")
    except (OSError, duckdb.Error) as error:
        print(f"History configuration error: {error}", file=sys.stderr)
        return 2
    summary: dict[str, object] = {"start_month": start, "end_month": end, "months": {}}
    exit_code = 0
    try:
        for period in pd.period_range(start, end, freq="M"):
            month = str(period)
            try:
                code, details = process_month(project, month, connection, runner)
            except (OSError, ValueError, duckdb.Error) as error:
                code, details = 1, {"status": "not loaded", "error": str(error)}
                print(f"History {month} failed: {error}", file=sys.stderr)
            summary["months"][month] = details
            exit_code = max(exit_code, code)
            if code == 2:
                break
        export_tables(connection, output / "tableau")
    except (OSError, duckdb.Error) as error:
        print(f"History export error: {error}", file=sys.stderr)
        exit_code = 2
    finally:
        connection.close()
    summary["exit_code"] = exit_code
    try:
        (output / "history_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"History summary error: {error}", file=sys.stderr)
        return 2
    print(f"History {start} to {end}: exit_code={exit_code}")
    return exit_code
