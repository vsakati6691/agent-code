"""Reject stale, incomplete, or implausible price data before it is used."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")
# An overnight gap beyond these ratios is checked against common split ratios.
SPLIT_SUSPECT_LOW = 0.55
SPLIT_SUSPECT_HIGH = 1.8
# Gaps within this tolerance of a split ratio are treated as unadjusted splits
# (e.g. SQQQ's 2019 reverse split). Large gaps that match no split ratio are
# genuine moves (e.g. ECHO +70% on 2025-08-26) and are kept.
SPLIT_RATIOS = [2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30, 40, 50]
SPLIT_TOLERANCE = 0.06


FROZEN_RUN = 3  # consecutive flat bars that mark a frozen feed
RECENT_BARS = 63  # a frozen run this recent means the current feed is broken


class DataQualityError(ValueError):
    """Raised when a price series must not be used."""


def frozen_runs(df: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """(start, end) of every run of FROZEN_RUN+ consecutive flat bars (high == low).

    A liquid stock or ETF does not print identical high and low for days in a
    row; such runs come from dead feeds, pre-merger SPAC shells, or thin
    pre-listing trading. Volume-only dropouts with normal price ranges are a
    known vendor glitch and are deliberately NOT treated as frozen.
    """
    flat = ((df["high"] - df["low"]).abs() <= 1e-9).to_numpy()
    runs, start = [], None
    for i, is_flat in enumerate(list(flat) + [False]):
        if is_flat and start is None:
            start = i
        elif not is_flat and start is not None:
            if i - start >= FROZEN_RUN:
                runs.append((df.index[start], df.index[i - 1]))
            start = None
    return runs


def frozen_feed_start(df: pd.DataFrame) -> pd.Timestamp | None:
    runs = frozen_runs(df)
    return runs[0][0] if runs else None


def split_suspects(df: pd.DataFrame) -> list[pd.Timestamp]:
    """Dates whose overnight gap looks like an unadjusted split (ratio near a split ratio)."""
    ratio = (df["open"] / df["close"].shift(1)).dropna()
    big = ratio[(ratio < SPLIT_SUSPECT_LOW) | (ratio > SPLIT_SUSPECT_HIGH)]
    out = []
    for day, r in big.items():
        mult = r if r >= 1 else 1 / r
        if any(abs(mult / s - 1) <= SPLIT_TOLERANCE for s in SPLIT_RATIOS):
            out.append(day)
    return out


def trim_bad_history(df: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, str | None]:
    """Drop history up to the last data anomaly (frozen run or unadjusted split).

    An anomaly years ago should not block today's analysis; one inside the last
    RECENT_BARS bars means the current feed is unreliable, so that raises.
    """
    marks = [(end, f"frozen bars {start.date()} to {end.date()}") for start, end in frozen_runs(df)]
    marks += [(d, f"unadjusted split on {d.date()}") for d in split_suspects(df)]
    if not marks:
        return df, None
    last, why = max(marks, key=lambda m: m[0])
    if df.index.get_loc(last) >= len(df) - RECENT_BARS:
        raise DataQualityError(f"{symbol}: recent data anomaly ({why}); feed unreliable")
    trimmed = df.loc[df.index > last]
    return trimmed, f"{symbol}: history before {trimmed.index[0].date()} dropped ({why})"


def trim_frozen_history(df: pd.DataFrame, symbol: str) -> tuple[pd.DataFrame, str | None]:
    """Backward-compatible name for trim_bad_history."""
    try:
        return trim_bad_history(df, symbol)
    except DataQualityError as exc:
        raise DataQualityError(str(exc).replace("recent data anomaly", "feed frozen recently")) from None


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
    try:
        finite = np.isfinite(values.to_numpy(dtype=float)).all()
        numeric = all(
            pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype) for dtype in values.dtypes
        )
    except (TypeError, ValueError, OverflowError):
        finite, numeric = False, False
    if not finite or not numeric:
        raise DataQualityError(f"{symbol}: OHLCV must contain finite numeric values")
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

    suspects = split_suspects(df)
    if suspects:
        raise DataQualityError(
            f"{symbol}: overnight gap on {suspects[0].date()} looks like an unadjusted split or bad print"
        )

    frozen = frozen_feed_start(df)
    if frozen is not None:
        raise DataQualityError(
            f"{symbol}: feed looks frozen or broken from {frozen.date()} ({FROZEN_RUN}+ consecutive flat bars)"
        )

    if len(df) < min_bars:
        raise DataQualityError(f"{symbol}: only {len(df)} bars, need {min_bars}")

    last = df.index[-1].date()
    if last > as_of:
        raise DataQualityError(f"{symbol}: last bar {last} is after as-of date {as_of}")
    # Intentionally conservative weekday budget. Discounting exchange holidays
    # would admit older data; the exact-session live/dashboard checks stay stricter.
    lag = int(np.busday_count(last, as_of))
    if lag > max_staleness_days:
        raise DataQualityError(
            f"{symbol}: stale, last bar {last} is {lag} business days old (max {max_staleness_days})"
        )
    return df
