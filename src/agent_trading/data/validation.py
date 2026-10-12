"""Reject stale, incomplete, or implausible price data before it is used."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")
# A one-day move beyond these ratios in a liquid large-cap almost always means
# an unadjusted split or a bad print rather than a real move.
SPLIT_SUSPECT_LOW = 0.55
SPLIT_SUSPECT_HIGH = 1.8


class DataQualityError(ValueError):
    """Raised when a price series must not be used."""


def validate_bars(
    df: pd.DataFrame | None,
    symbol: str,
    as_of: date,
    max_staleness_days: int,
    min_bars: int,
) -> pd.DataFrame:
    if df is None or df.empty:
        raise DataQualityError(f"{symbol}: no data")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataQualityError(f"{symbol}: missing columns {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise DataQualityError(f"{symbol}: index is not dates")
    if df.index.has_duplicates:
        raise DataQualityError(f"{symbol}: duplicate dates")
    if not df.index.is_monotonic_increasing:
        raise DataQualityError(f"{symbol}: dates not sorted")

    values = df[list(REQUIRED_COLUMNS)]
    if values.isna().any().any():
        raise DataQualityError(f"{symbol}: missing values")
    prices = df[["open", "high", "low", "close"]]
    if (prices <= 0).any().any():
        raise DataQualityError(f"{symbol}: non-positive prices")
    if (df["volume"] < 0).any():
        raise DataQualityError(f"{symbol}: negative volume")
    tol = 1e-6
    if (df["high"] < df["low"] - tol).any():
        raise DataQualityError(f"{symbol}: high below low")
    for col in ("open", "close"):
        if ((df[col] > df["high"] + tol) | (df[col] < df["low"] - tol)).any():
            raise DataQualityError(f"{symbol}: {col} outside high/low range")

    ratio = (df["open"] / df["close"].shift(1)).dropna()
    if ((ratio < SPLIT_SUSPECT_LOW) | (ratio > SPLIT_SUSPECT_HIGH)).any():
        bad = ratio[(ratio < SPLIT_SUSPECT_LOW) | (ratio > SPLIT_SUSPECT_HIGH)].index[0]
        raise DataQualityError(
            f"{symbol}: overnight gap on {bad.date()} looks like an unadjusted split or bad print"
        )

    if len(df) < min_bars:
        raise DataQualityError(f"{symbol}: only {len(df)} bars, need {min_bars}")

    last = df.index[-1].date()
    if last > as_of:
        raise DataQualityError(f"{symbol}: last bar {last} is after as-of date {as_of}")
    lag = int(np.busday_count(last, as_of))
    if lag > max_staleness_days:
        raise DataQualityError(
            f"{symbol}: stale, last bar {last} is {lag} business days old (max {max_staleness_days})"
        )
    return df
