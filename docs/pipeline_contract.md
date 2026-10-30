# One-cutoff pipeline

Run `python -m pipeline --cutoff 2026-03` from the project folder. The cutoff is March 31, 2026. Orders and billing are filtered independently by their own dates before any join or ledger aggregation. Later records do not enter the views or reconciliation totals.

## Source accounting

A uses a full outer join between order rows and billing totals by document and product. Exact duplicate order rows remain separate and receive `-dup1`, `-dup2`, and later suffixes. Billing is assigned once to the original row. Each copy keeps its full ordered quantity and value with zero billing, but goes to review with the exact reason `duplicate order row`. Bundle components of a copy follow the same rule. Copies never enter the open or closed views. This preserves raw order and invoice totals without treating copies as extra demand. Duplicate line keys appear in both reports. Conflicting order rows with the same key stop A. Invoice-only keys go to review.

B uses an order-led left join. Sales without an order are aggregated into `sales_without_order.csv` with review status and never enter the open book. Eligible records after declared coverage end, June 30, 2026, go to `excluded.csv` with an outside-coverage reason. Records also after the cutoff are omitted from all views; their counts and coverage reason appear in the summary. At the March cutoff the six July records are in this latter group, so `excluded.csv` is empty.

C first filters events by date, then sums `ORDER` and `ORDER_ADJUSTMENT` into the ordered quantity and value. The sign of `BILLING` is reversed for the positive billed columns. Open quantities and amounts equal ordered minus billed. A ledger key without an `ORDER` event goes to review.

## Products, values, and rates

Resolution checks the catalog, then that source's one-to-one aliases, then bundles. Unmatched codes retain `source_product_code`, leave `product_code` empty, and go to review with `unmapped product code`.

Bundle component quantities equal the parent quantity times each multiplier. A bundle with multipliers 1, 2, and 3 therefore has six component units per parent unit. Quantity conservation means each component follows its multiplier and the total divided by the sum of multipliers equals the parent quantity. Summing component quantities directly would mix bundle units and component units.

Ordered and billed values are allocated separately in proportion to component quantities. Integer-cent allocation assigns remaining cents by fractional remainder, with product code as the tie order. Open component value equals ordered component value minus billed component value. All three monetary sums must equal the parent to the cent. A failed quantity, value, or row conservation check stops that source before its outputs are committed.

Each source uses its cutoff-month USD rate, including the USD reference rate. A needed rate must occur exactly once and be finite and positive. There is no fallback. USD values are rounded to cents per output line, with half cents rounded away from zero.

## Classification and reconciliation

An eligible mapped line is open when both open quantity and open local value are positive. It is closed when both are zero. Over-billing, unmatched products, missing orders, and disagreements between quantity and value go to review. Outside-coverage lines are excluded. Every non-open line has a reason.

The five views are disjoint. Reconciliation sums local ordered and billed values across all five, including review, closed, excluded, and sales without orders. All money differences must be zero.

Raw records, joined lines, and expanded component lines have different counts. The row bridge is `input_rows + adapter_row_adjustment + bundle_added_rows = expected_output_rows`. `output_rows` is counted independently from the five views; `rows_difference` compares it with the expected count. Bundle additions come from the mapping, rather than from the final row count.

Sources run in A, B, C order. A source failure leaves its views empty and records its error; later sources still run. A failed reconciliation row has blank totals rather than a false zero. Exit codes are 0 for all sources successful, 1 for any source failure, and 2 for bad arguments, shared configuration, or output configuration. A cutoff rerun replaces its seven files. The history command and focused tests are described in `history_contract.md`.
