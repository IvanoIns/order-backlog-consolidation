# Synthetic source data contract

## Coverage and layout

Coverage is January 2025 through June 2026, inclusive. Each source has 60 distinct order lines per month, or 1,080 lines in coverage. Each order contains three distinct product codes sharing one order date. Billing dates remain per line. The catalogs contain 150 invented customers and 250 invented products. Source order identifiers are independent and are not cross-source matches.

All CSV files use UTF-8, a header row, ISO dates, and decimal monetary amounts in the named currency. Quantities, including billing and adjustment quantities, are whole units. Billed quantities are rounded to the nearest whole unit first, with ties to even; values are then units times the unit price in integer cents before export. No real names, transactions, or exchange rates are used. Customer names and product names begin with `Invented`.

| Location | Files | Meaning |
| --- | --- | --- |
| `source_a/orders_YYYY-MM.csv` | 18 | Orders placed in each month, GBP |
| `source_a/invoices_YYYY-MM.csv` | 18 | Invoice movements dated in each month, GBP |
| `source_b/orders_2025-01_to_2026-06.csv` | 1 | Multi-year orders, already USD |
| `source_b/sales_2025-01_to_2026-06.csv` | 1 | Multi-year sales movements, already USD |
| `source_c/ledger_2025-01_to_2026-06.csv` | 1 | Signed order, adjustment, and billing events, AUD |
| `customers.csv` | 1 | `customer_id`, `customer_name` |
| `product_catalog.csv` | 1 | `product_code`, `product_name`, `category` |
| `code_mapping.csv` | 1 | `source_system`, `local_code`, `product_code` |
| `bundle_mapping.csv` | 1 | `source_system`, `bundle_code`, `component_product_code`, `quantity_multiplier` |
| `fx_rates.csv` | 1 | `period`, `currency`, `rate_to_usd` |
| `generation_manifest.csv` | 1 | Creation counts by source, month, and case |

## Source conventions

A uses `doc_no + item_code`. Order values and invoice values are positive GBP amounts. Invoices can appear up to 75 days after the order, capped at June 30, 2026. Monthly files contain movements, not repeated month-end snapshots. Billed lines normally have one invoice row. About half of partially invoiced lines and one third of over-invoiced lines per order month have two or three invoices on distinct dates. Splitting preserves each line's total billed units and value. Invoice identifiers are unique. Six exact extra order rows deliberately repeat six keys, one in each of January, April, July, and October 2025 and January and April 2026. Other order keys are unique across coverage.

B uses `order_ref + product_ref`. Order and sales values are positive USD amounts. Billing can lag orders and use multiple rows under the same rules as A. Sale identifiers are unique. Twelve sales rows have no matching order. Three additional order rows and three matching sales rows are dated in July 2026 even though the filenames declare coverage ending in June. These future rows are separate from the 1,080 in-coverage lines. There are no duplicate order keys in B.

C uses `order_id + product_code` as the line identity and `event_id` as the unique ledger row identity. `ORDER` amounts and quantities are positive. `BILLING` amounts and quantities are negative. Six `ORDER_ADJUSTMENT` events reduce order value and quantity by 10 percent; these are distinct from ordinary negative billing events. Adjustment dates equal their order dates. A negative adjustment modifies the order before the whole billed quantity is calculated. Multiple `BILLING` events follow the same split rules as A, with unique event identifiers. The ledger contains no backlog or balance column. No aggregation or currency conversion is performed in step 1.

Catalog codes are `P0001` through `P0250`. There are 30 old/local aliases per source, each mapping to one distinct catalog code. All 90 mapping targets are distinct. Each source has four bundle codes with three components each and quantity multipliers 1, 2, and 3. Bundle components reference catalog codes directly. Bundle multipliers define component quantities; no monetary allocation rule is supplied in step 1. Codes containing `UNKNOWN` deliberately have no mapping.

FX rates are invented USD per one unit of GBP, AUD, or USD. There is exactly one rate for each currency and covered month, including USD = 1. No July FX rate is supplied for the deliberate out-of-coverage records.

## Manifest interpretation

Columns are `seed`, `source`, `period`, `case_name`, `count`, and `unit`. Counts are recorded when cases are created. Zero counts are explicit. There are no total rows; summing a case across the 18 periods gives its source total.

The four invoice-status cases classify distinct, in-coverage order lines at June 30, 2026, before duplicate copies and excluding orphan sales and future rows. C's status uses order value after its order adjustment. Per source and order month there are 24 fully open lines, 18 partially invoiced lines, 12 fully invoiced lines, and 6 over-invoiced lines. Fully open lines have no billing; partial billing targets 25, 50, or 75 percent of units; full billing uses 100 percent; over-billing targets 120 percent. Whole-unit rounding happens before values are calculated. Split lines need at least two available dates before the coverage cutoff; otherwise they keep one billing row.

Each source and order month has 42 `catalog_code`, 12 `mapped_code`, 4 `bundle_code`, and 2 `unmapped_code` lines. These counts and status counts describe different dimensions of the same 60 lines, so they must not be added together.

| Case | Count basis |
| --- | --- |
| `fully_open`, `partially_invoiced`, `fully_invoiced`, `over_invoiced` | Distinct in-coverage lines, attributed to order month |
| `catalog_code`, `mapped_code`, `bundle_code`, `unmapped_code` | Distinct in-coverage lines, attributed to order month |
| `unique_order_lines` | All 60 distinct in-coverage lines per order month |
| `multi_invoice_lines` | Distinct in-coverage lines with more than one billing row, attributed to order month |
| `duplicate_keys` | Distinct A order keys with an extra raw copy |
| `duplicate_extra_rows` | Additional A order rows beyond the original row |
| `unmatched_sales_rows` | B sales rows with no matching order, attributed to sales month |
| `future_dated_rows` | All six B rows after coverage, attributed to June 2026 |
| `negative_adjustment_rows` | C `ORDER_ADJUSTMENT` rows, attributed to event month |
| `raw_order_rows` | Exported A/B order rows, including copies and future rows |
| `raw_billing_rows` | Exported A invoice or B sales rows, including exceptions |
| `raw_event_rows` | All exported C ledger events |

Raw row counts use their own record dates. Dates after coverage are attributed to the final covered month so that raw totals reconcile to file lengths. Raw billing counts do not use order month. C raw order and billing row counters are zero because C exports only a ledger.

## Reproducibility and scope

The CLI accepts a non-negative integer seed and defaults to 42. A NumPy seed sequence creates separate deterministic streams for reference FX and each source. Same-seed byte reproduction assumes the same Python, pandas, and numpy versions. No wall-clock timestamps, network calls, or external data enter generation.

The generator writes only its known CSV paths under this project's `data/raw/`; it does not delete unrelated files. Generation performs no consolidation, joins between sources, component expansion, backlog calculation, or FX application. The pipeline is described in `pipeline_contract.md`; monthly history and tests are described in `history_contract.md`.
