"""Invented customers, products, mappings, and exchange rates."""

import numpy as np
import pandas as pd

from .model import MONTHS, SOURCES

WORDS = ("Zorvelli", "Quenlora", "Vexunel", "Plimora", "Nuvetti")
CATEGORIES = ("Actuators", "Sensors", "Connectors", "Modules", "Fixtures")


def customer_catalog() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "customer_id": f"CU{index:03d}",
            "customer_name": f"Invented {WORDS[(index - 1) % 5]} Works {index:03d}",
        }
        for index in range(1, 151)
    ])


def product_catalog() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "product_code": f"P{index:04d}",
            "product_name": f"Invented {WORDS[(index - 1) % 5]} Part {index:03d}",
            "category": CATEGORIES[(index - 1) % 5],
        }
        for index in range(1, 251)
    ])


def code_mapping() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "source_system": source,
            "local_code": f"{source}-OLD-{index:03d}",
            "product_code": f"P{source_index * 30 + index:04d}",
        }
        for source_index, source in enumerate(SOURCES)
        for index in range(1, 31)
    ])


def bundle_mapping() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "source_system": source,
            "bundle_code": f"{source}-KIT-{bundle:02d}",
            "component_product_code": f"P{100 + source_index * 12 + (bundle - 1) * 3 + component:04d}",
            "quantity_multiplier": component,
        }
        for source_index, source in enumerate(SOURCES)
        for bundle in range(1, 5)
        for component in range(1, 4)
    ])


def fx_rates(rng: np.random.Generator) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    gbp, aud = 1.25, 0.65
    for month in MONTHS:
        gbp = float(np.clip(gbp + rng.normal(0, 0.008), 1.1, 1.5))
        aud = float(np.clip(aud + rng.normal(0, 0.005), 0.5, 0.8))
        for currency, rate in (("GBP", gbp), ("AUD", aud), ("USD", 1.0)):
            rows.append({
                "period": str(month), "currency": currency,
                "rate_to_usd": round(rate, 6),
            })
    return pd.DataFrame(rows)


def build_references(rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    return {
        "customers.csv": customer_catalog(),
        "product_catalog.csv": product_catalog(),
        "code_mapping.csv": code_mapping(),
        "bundle_mapping.csv": bundle_mapping(),
        "fx_rates.csv": fx_rates(rng),
    }


def code_pools(
    source: str, references: dict[str, pd.DataFrame]
) -> dict[str, list[str]]:
    mapping = references["code_mapping.csv"]
    bundles = references["bundle_mapping.csv"]
    return {
        "catalog_code": references["product_catalog.csv"]["product_code"].tolist(),
        "mapped_code": mapping.loc[mapping["source_system"] == source, "local_code"].tolist(),
        "bundle_code": bundles.loc[bundles["source_system"] == source, "bundle_code"].drop_duplicates().tolist(),
        "unmapped_code": [f"{source}-UNKNOWN-{index:02d}" for index in range(1, 6)],
    }
