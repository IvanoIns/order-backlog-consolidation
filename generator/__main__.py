"""Run with python -m generator --seed 42."""

import argparse
from pathlib import Path

import numpy as np

from .manifest import Manifest
from .model import MONTHS, SOURCES, build_month
from .references import build_references, code_pools
from .sources import save_csv, write_a, write_b, write_c


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate invented order source data.")
    parser.add_argument("--seed", type=int, default=42, help="Non-negative random seed (default: 42).")
    args = parser.parse_args()
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    return args


def generate(seed: int, raw: Path) -> None:
    streams = np.random.SeedSequence(seed).spawn(4)
    references = build_references(np.random.default_rng(streams[0]))
    for name, frame in references.items():
        save_csv(raw / name, frame)
    manifest = Manifest(seed)
    writers = {"A": write_a, "B": write_b, "C": write_c}
    for source, stream in zip(SOURCES, streams[1:]):
        rng = np.random.default_rng(stream)
        pools = code_pools(source, references)
        lines = [
            line
            for month_index, month in enumerate(MONTHS)
            for line in build_month(source, month, month_index, pools, rng)
        ]
        manifest.add_lines(lines)
        writers[source](raw, lines, manifest)
    save_csv(raw / "generation_manifest.csv", manifest.frame())


def main() -> None:
    args = parse_args()
    raw = Path(__file__).resolve().parents[1] / "data" / "raw"
    generate(args.seed, raw)
    print(f"Generated 18 periods, 150 customers, 250 products, seed={args.seed}.")
    print(f"Wrote 45 CSV files to {raw}")


if __name__ == "__main__":
    main()
