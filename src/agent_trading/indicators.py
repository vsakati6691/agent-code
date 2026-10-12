"""Trend, momentum, moving-average, volatility and volume indicators.

All indicators are causal: the value on day t uses only data up to day t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n, min_periods=n).mean()


def ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    out = 100 - 100 / (1 + rs)
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return out.where(avg_gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1, skipna=True)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def rate_of_change(close: pd.Series, n: int) -> pd.Series:
    return close / close.shift(n) - 1


def volume_ratio(volume: pd.Series, n: int = 20) -> pd.Series:
    """Today's volume relative to the average of the previous n days."""
    prior_avg = volume.shift(1).rolling(n, min_periods=n).mean()
    return volume / prior_avg.replace(0, np.nan)


def add_indicators(df: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    out = df.copy()
    close = out["close"]
    out["sma_fast"] = sma(close, cfg.fast_ma)
    out["sma_slow"] = sma(close, cfg.slow_ma)
    out["momentum"] = rate_of_change(close, cfg.momentum_lookback)
    out["rsi"] = rsi(close, cfg.rsi_period)
    out["atr"] = atr(out, cfg.atr_period)
    out["vol_ratio"] = volume_ratio(out["volume"], cfg.volume_lookback)
    out["avg_dollar_volume"] = (close * out["volume"]).rolling(cfg.volume_lookback, min_periods=cfg.volume_lookback).mean()
    out = out.join(macd(close))
    return out
