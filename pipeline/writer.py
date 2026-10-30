"""Write one cutoff's views and run reports."""

import json
from pathlib import Path

import pandas as pd

from .common import COLUMNS, VIEWS, frame
from .reconcile import FIELDS


def write(
    destination: Path, collected: dict[str, list[pd.DataFrame]],
    reconciliation: list[dict[str, object]], summary: dict[str, object],
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for view in VIEWS:
        table = pd.concat(collected[view], ignore_index=True) if collected[view] else frame([])
        table = table.sort_values(["source_system", "line_key"], kind="stable")
        table.to_csv(destination / f"{view}.csv", index=False, columns=COLUMNS, lineterminator="\n")
    pd.DataFrame(reconciliation, columns=FIELDS).to_csv(
        destination / "reconciliation.csv", index=False, lineterminator="\n",
    )
    (destination / "run_summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8",
    )
