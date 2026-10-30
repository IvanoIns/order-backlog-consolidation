"""Use the cutoff-month rate without a fallback."""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

from .common import read_csv


class FxRates:
    def __init__(self, raw: Path, cutoff_month: str) -> None:
        rates = read_csv(raw / "fx_rates.csv", ["period", "currency", "rate_to_usd"])
        self.rates = rates[rates["period"] == cutoff_month]
        self.month = cutoff_month

    def rate(self, currency: str) -> Decimal:
        values = self.rates.loc[self.rates["currency"] == currency, "rate_to_usd"]
        if len(values) != 1:
            raise ValueError(f"FX {self.month} {currency}: expected one rate, found {len(values)}")
        try:
            rate = Decimal(str(values.iloc[0]))
        except InvalidOperation as error:
            raise ValueError(f"FX {self.month} {currency}: invalid rate") from error
        if not rate.is_finite() or rate <= 0:
            raise ValueError(f"FX {self.month} {currency}: rate must be positive and finite")
        return rate

    def convert(self, table: pd.DataFrame) -> pd.DataFrame:
        converted = table.copy()
        rates = {currency: self.rate(currency) for currency in table["currency_code"].unique()}
        converted["fx_rate_to_usd"] = [str(rates[currency]) for currency in table["currency_code"]]
        converted["amount_open_usd"] = [
            f"{(Decimal(str(amount)) * rates[currency]).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
            for amount, currency in zip(table["amount_open_lc"], table["currency_code"])
        ]
        return converted
