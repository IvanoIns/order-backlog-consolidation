# Monthly history

Run `python -m pipeline --history 2025-01 2026-06` for the inclusive range. Each month runs the same cutoff pipeline as `--cutoff`. The generator and project raw files are not modified.

## Loading

`output/backlog_history.duckdb` contains `open_book_history` with the 19 common columns. Amounts use fixed decimal types, quantities use integers, and order dates use the date type. The primary key is cutoff month, source, and line key.

For each successful month, one explicit transaction deletes its old snapshot, inserts the new snapshot, records the loaded month, and rebuilds movements. A failure rolls the transaction back. Repeating a month replaces it and gives the same logical rows and totals. The small internal `history_months` table also records successful empty snapshots, so an empty month is distinct from an unloaded month.

A month with any failed source is not loaded. Existing history for that month remains untouched. Later months can still run. `output/history_summary.json` records each attempted month and the final exit code. Shared configuration errors stop the range with code 2; a month or load failure gives code 1.

## Movements

`monthly_movements` compares every pair of loaded calendar months exactly one month apart. It uses the union of their source and line keys. It does not compare across gaps and does not create movements before the first loaded month.

| Type | Rule |
| --- | --- |
| `added` | Open only in the later month |
| `removed` | Open only in the earlier month |
| `changed` | Open in both, with a different local open amount to the cent |
| `unchanged` | Open in both, with the same local open amount to the cent |

The columns `amount_open_lc_before`, `amount_open_lc_after`, and `currency_code` retain the local amounts and currency. The USD before, after, and difference columns remain exact decimals. An absent line has zero on that side. Difference is after minus before. FX-only changes leave the movement type unchanged.

`operational_usd` is the local amount change times the later rate, rounded to cents. `fx_effect_usd` starts from the earlier local amount times the rate change. Added lines are entirely operational at the later rate; removed lines are entirely operational at the earlier rate. USD lines always have zero FX effect.

Snapshot USD amounts were already rounded separately. Any remaining cent from that rounding is assigned to FX, preserving `amount_open_usd_difference = operational_usd + fx_effect_usd` on every row. The sum of both components equals the change in total open USD amount. Existing databases gain the five movement columns when movements are rebuilt; snapshots stay unchanged.

Replacing a snapshot refreshes both adjacent month pairs in the same transaction. Both tables are exported in stable key order to `output/tableau/open_book_history.csv` and `output/tableau/monthly_movements.csv`.

## Tests

Install development dependencies with `python -m pip install -e ".[dev]"`, then run `python -m pytest -q`. Six focused tests cover cutoff reconciliation, bundle quantities and cent allocation, repeated month loading, source-local FX failure, duplicate routing including bundles, and movement totals. All test inputs are generated with seed 42 in temporary folders during the session. The missing-rate case changes only its private temporary copy.

DuckDB transaction behavior is described in the [official transaction documentation](https://duckdb.org/docs/stable/sql/statements/transactions). History uses explicit begin, commit, and rollback statements.
