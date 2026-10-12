"""Baseline long-only trend/momentum rules.

This is a research hypothesis to be tested out-of-sample, not a proven edge.
Signals are computed at the close of day t and may only be acted on at the
open of day t+1.
"""
from __future__ import annotations

import pandas as pd

from .config import StrategyConfig


def generate_signals(ind: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    close = ind["close"]
    uptrend = (close > ind["sma_fast"]) & (ind["sma_fast"] > ind["sma_slow"])
    entry = uptrend & (ind["momentum"] > 0) & (ind["rsi"] < cfg.rsi_max_entry) & ind["atr"].notna()
    exit_ = close < ind["sma_slow"]
    return pd.DataFrame({"uptrend": uptrend, "entry": entry, "exit": exit_}, index=ind.index)
