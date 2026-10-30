# order-backlog-consolidation

## What this is

This pipeline combines open orders from three fictional source systems into one open order book in USD. It includes monthly history and separates operational movements from FX effects. All data is synthetic.

## The problem

Appending the files would mix different line identities and accounting rules. The sources use different keys, joins, coverage periods and currencies. One source supplies only signed events, so its open balance has to be calculated. Product codes also need attention. Some are local aliases, some represent bundles, and some have no valid mapping.

## The three sources

| Source | Key | Join rule | Currency | Special cases |
| --- | --- | --- | --- | --- |
| A | `doc_no + item_code` | Full outer join of orders and aggregated invoices | GBP | Separate monthly files. Invoice-only lines and duplicate order copies go to review. |
| B | `order_ref + product_ref` | Order-led left join to aggregated sales | USD | Sales without an order have a separate view. Records after declared file coverage are excluded. |
| C | `order_id + product_code` | Aggregate order, adjustment and billing events per key | AUD | No backlog file. Signed order adjustments reduce ordered quantity and value before billing is compared. |

## How to run

Use Python 3.11 or later. Run these commands from the project root.

Install the project and development dependencies:

```text
python -m pip install -e ".[dev]"
```

Generate the synthetic source files:

```text
python -m generator --seed 42
```

Run one cutoff:

```text
python -m pipeline --cutoff 2026-03
```

The cutoff is the last day of the month. Orders and billing are filtered independently by their own dates before joins or aggregation.

Build monthly history for the inclusive range:

```text
python -m pipeline --history 2025-01 2026-06
```

Each successful month replaces its existing snapshot in one transaction. Repeating a load gives the same rows and totals. A month with a failed source is not loaded into history.

Run the tests:

```text
python -m pytest -q
```

Tests generate their own seed-42 data in temporary folders. They do not need files from a previous generator or pipeline run.

## Project structure

```text
|-- generator/  Synthetic source data generation
|-- pipeline/   Consolidation and history, with source rules in adapters/
|-- tests/      Automated checks
`-- docs/       Data, pipeline and history contracts
```

## Design decisions

- **One adapter per source.** I keep each source's joins, coverage and accounting rules together so all the rules for one source live in one place.
- **Nothing is dropped silently.** Exceptions have review or excluded views. Unmatched B sales have their own view. Records after the cutoff are counted in the run summary. This makes omissions and differences visible.
- **Bundle values follow component quantities.** Component quantities use the mapping multipliers. Ordered and billed values are split in proportion to those quantities. Conservation checks verify quantities against the multipliers and values to the cent. A failed check stops that source's run before its rows reach the outputs.
- **FX comes from the cutoff month, with no default rate.** A needed rate must appear exactly once and be positive. Invalid rates fail that source, so missing reference data cannot silently alter the valuation.
- **Duplicate order copies go to review.** I keep their `-dupN` keys and report them, including bundle components. Their values remain available for reconciliation without inflating open demand.
- **Operational movement and FX effect are separate.** Movement types use the local open amount to the cent. USD changes are split into operational and FX columns so a rate change does not look like an operational change. Any remaining snapshot rounding cent is assigned to FX so the components sum to the stored USD difference.

## Generated data

Generated files are under `data/raw/`:

| File | Contents |
| --- | --- |
| `source_a/orders_YYYY-MM.csv` | Monthly order lines in GBP. |
| `source_a/invoices_YYYY-MM.csv` | Monthly invoice movements in GBP. |
| `source_b/orders_2025-01_to_2026-06.csv` | Orders across the declared coverage period, in USD. |
| `source_b/sales_2025-01_to_2026-06.csv` | Sales movements in USD, including planted exceptions. |
| `source_c/ledger_2025-01_to_2026-06.csv` | Signed order, adjustment and billing events in AUD. |
| `customers.csv` | Invented customer identifiers and names. |
| `product_catalog.csv` | Catalog product codes, invented names and categories. |
| `code_mapping.csv` | Source-specific aliases mapped one-to-one to catalog codes. |
| `bundle_mapping.csv` | Bundle components and their quantity multipliers. |
| `fx_rates.csv` | Invented monthly rates to USD. |
| `generation_manifest.csv` | Counts of planted cases by source and period. |

## Pipeline outputs

Each cutoff writes these files under `output/<cutoff>/`:

| File | Contents |
| --- | --- |
| `open_book.csv` | Open lines with resolved products, local amounts and USD open amounts. |
| `review.csv` | Lines needing review, with reasons. Includes duplicate copies, over-billing, unmapped products and missing orders. |
| `closed.csv` | Fully billed lines that pass the product and exception checks. |
| `excluded.csv` | Records within the cutoff but outside declared source coverage, with reasons. |
| `sales_without_order.csv` | B sales with no matching order. They do not enter the open book. |
| `reconciliation.csv` | Input and output local-currency totals, explicit differences, a row-count bridge and duplicate listings. |
| `run_summary.json` | Source status, row counts by view, open USD amounts, duplicate keys, cutoff omissions and errors. |

Records after the cutoff do not enter these views or reconciliation totals. Their counts appear in the summary. The row-count bridge explains how billing aggregation and bundle expansion change the number of rows.

History writes these files:

| File | Contents |
| --- | --- |
| `output/backlog_history.duckdb` | `open_book_history` stores monthly open snapshots. `monthly_movements` compares consecutive loaded months. The internal `history_months` table records successful loads, including empty snapshots. |
| `output/history_summary.json` | Load status, row counts and open USD totals by month, plus the overall exit code. |
| `output/tableau/open_book_history.csv` | CSV export of the open-order history for Tableau. |
| `output/tableau/monthly_movements.csv` | Line movements with local amounts, currency, USD amounts before and after, `operational_usd` and `fx_effect_usd`. |

## What the tests check

- Reconciliation differences are zero for every source at the March 2026 cutoff.
- Bundle component quantities follow their multipliers, and allocated values conserve each original line to the cent.
- Loading the same month twice gives identical rows, row counts and USD totals.
- A missing FX rate fails only the affected source while the others succeed, with exit code 1.
- Duplicate order copies, including bundle components, appear only in review.
- Operational and FX movements sum to the change in total open USD amount, movement types follow local amounts, and USD lines have zero FX effect.

## Limitations

- All inputs are invented. Results describe the behavior of this synthetic dataset.
- There are no cancellations or cancellation rules.
- Open orders never age out. An old order stays open while it meets the open-line rules.
- Technical reconciliation is not financial approval. A zero difference confirms that the selected inputs are accounted for under the implemented rules.

## Context

This project is an independent rebuild, with invented data, of the type of pipeline I build at work. No employer code, data or business rules are used. The Tableau demo on my portfolio site uses a separate synthetic dataset.

[Backlog Intelligence demo](https://ivanoinserra.com/backlog-intelligence/)
