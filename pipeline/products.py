"""Resolve catalog codes and conserve bundle values to the cent."""

from pathlib import Path

import pandas as pd

from .common import add_reason, cents, frame, money, read_csv

QUANTITIES = ("qty_ordered", "qty_billed", "qty_open")
AMOUNTS = ("amount_ordered_lc", "amount_billed_lc", "amount_open_lc")


class Products:
    def __init__(self, raw: Path) -> None:
        catalog = read_csv(raw / "product_catalog.csv", ["product_code"])
        if not catalog["product_code"].is_unique or (catalog["product_code"] == "").any():
            raise ValueError("Catalog product codes must be unique and nonempty")
        self.catalog = set(catalog["product_code"])
        self.mapping = read_csv(raw / "code_mapping.csv", ["source_system", "local_code", "product_code"])
        self.bundles = read_csv(raw / "bundle_mapping.csv", [
            "source_system", "bundle_code", "component_product_code", "quantity_multiplier",
        ])

    def resolve(self, table: pd.DataFrame, source: str) -> pd.DataFrame:
        mapping = self.mapping[self.mapping["source_system"] == source]
        if mapping["local_code"].duplicated().any() or mapping["product_code"].duplicated().any():
            raise ValueError(f"{source}: code mapping must be one-to-one")
        if not set(mapping["product_code"]) <= self.catalog:
            raise ValueError(f"{source}: mapped product is absent from the catalog")
        aliases = dict(zip(mapping["local_code"], mapping["product_code"]))
        bundles = self.bundles[self.bundles["source_system"] == source]
        rows = []
        bundle_added_rows = 0
        for original in table.to_dict("records"):
            code = str(original["source_product_code"])
            if code in self.catalog or code in aliases:
                original["product_code"] = code if code in self.catalog else aliases[code]
                rows.append(original)
            elif (bundles["bundle_code"] == code).any():
                components = bundles[bundles["bundle_code"] == code]
                bundle_added_rows += len(components) - 1
                rows.extend(self.expand(original, components))
            else:
                original["status_reason"] = add_reason(str(original["status_reason"]), "unmapped product code")
                rows.append(original)
        resolved = frame(rows)
        if resolved["line_key"].duplicated().any():
            raise ValueError(f"{source}: duplicate resolved line keys")
        if len(resolved) != len(table) + bundle_added_rows:
            raise ValueError(f"{source}: product expansion row conservation failed")
        resolved.attrs["bundle_added_rows"] = bundle_added_rows
        return resolved

    def expand(self, original: dict[str, object], components: pd.DataFrame) -> list[dict[str, object]]:
        components = components.sort_values("component_product_code")
        codes = components["component_product_code"].tolist()
        if len(codes) < 2 or len(set(codes)) != len(codes) or not set(codes) <= self.catalog:
            raise ValueError(f"Invalid bundle components for {original['line_key']}")
        weights = []
        for text in components["quantity_multiplier"]:
            number = pd.to_numeric(text, errors="raise")
            if not pd.notna(number) or number <= 0 or number % 1:
                raise ValueError(f"Invalid bundle multiplier for {original['line_key']}")
            weights.append(int(number))
        ordered = allocate(cents(original["amount_ordered_lc"]), weights)
        billed = allocate(cents(original["amount_billed_lc"]), weights)
        rows = []
        for index, (code, multiplier) in enumerate(zip(codes, weights)):
            row = original.copy()
            row["line_key"] = f"{original['line_key']}::{code}"
            row["product_code"] = code
            for column in QUANTITIES:
                row[column] = int(original[column]) * multiplier
            row["amount_ordered_lc"] = money(ordered[index])
            row["amount_billed_lc"] = money(billed[index])
            row["amount_open_lc"] = money(ordered[index] - billed[index])
            rows.append(row)
        check_conservation(original, rows, weights)
        return rows


def allocate(total: int, weights: list[int]) -> list[int]:
    denominator = sum(weights)
    magnitude = abs(total)
    portions = [magnitude * weight // denominator for weight in weights]
    fractions = [magnitude * weight % denominator for weight in weights]
    residual = magnitude - sum(portions)
    for index in sorted(range(len(weights)), key=lambda item: (-fractions[item], item))[:residual]:
        portions[index] += 1
    return [value if total >= 0 else -value for value in portions]


def check_conservation(
    original: dict[str, object], rows: list[dict[str, object]], weights: list[int]
) -> None:
    for column in QUANTITIES:
        expected = int(original[column]) * sum(weights)
        components_match = all(
            int(row[column]) == int(original[column]) * multiplier
            for row, multiplier in zip(rows, weights)
        )
        if len(rows) != len(weights) or not components_match or sum(int(row[column]) for row in rows) != expected:
            raise ValueError(f"Bundle quantity conservation failed: {original['line_key']} {column}")
    for column in AMOUNTS:
        if sum(cents(row[column]) for row in rows) != cents(original[column]):
            raise ValueError(f"Bundle value conservation failed: {original['line_key']} {column}")
