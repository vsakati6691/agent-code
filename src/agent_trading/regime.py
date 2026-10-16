"""Market regime classification from a benchmark (SPY by default).

Trend:      bull     close > slow MA and fast MA > slow MA
            bear     close < slow MA and fast MA < slow MA
            sideways otherwise (mixed signals)
Volatility: high when annualised realised volatility over `vol_lookback` days
            exceeds `high_vol_threshold`, else normal.
Labels on day t use data up to and including day t's close.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import RegimeConfig
from .indicators import sma

TRADING_DAYS = 252


def classify(bench: pd.DataFrame, cfg: RegimeConfig) -> pd.DataFrame:
    close = bench["close"]
    fast, slow = sma(close, cfg.fast_ma), sma(close, cfg.slow_ma)
    vol = close.pct_change().rolling(cfg.vol_lookback, min_periods=cfg.vol_lookback).std() * math.sqrt(TRADING_DAYS)
    trend = pd.Series("sideways", index=close.index, dtype=object)
    trend[(close > slow) & (fast > slow)] = "bull"
    trend[(close < slow) & (fast < slow)] = "bear"
    trend[slow.isna()] = None
    volatility = pd.Series(np.where(vol > cfg.high_vol_threshold, "high", "normal"), index=close.index, dtype=object)
    volatility[vol.isna()] = None
    return pd.DataFrame(
        {
            "trend": trend,
            "volatility": volatility,
            "realized_vol": vol,
            "close": close,
            "fast_ma": fast,
            "slow_ma": slow,
        }
    )


def current(bench: pd.DataFrame, cfg: RegimeConfig) -> dict:
    r = classify(bench, cfg).iloc[-1]
    return {
        "date": bench.index[-1].date(),
        "trend": r["trend"],
        "volatility": r["volatility"],
        "realized_vol": float(r["realized_vol"]) if pd.notna(r["realized_vol"]) else None,
        "close_vs_slow_ma": float(r["close"] / r["slow_ma"] - 1) if pd.notna(r["slow_ma"]) else None,
    }
