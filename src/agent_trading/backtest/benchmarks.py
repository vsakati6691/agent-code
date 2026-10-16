"""Simple baselines every strategy must be compared against.

All baselines use the same cost model (fills worse by `cost` per side). They
return whatever the input bars hold: pass total-return bars (data/dividends.py)
for a total-return comparison.
"""

from __future__ import annotations

import pandas as pd


def _window(df: pd.DataFrame, start, end) -> pd.DataFrame:
    return df.loc[start:end]


def buy_and_hold(df: pd.DataFrame, start, end, initial: float, cost: float) -> pd.Series:
    """Buy at the first open of the window, mark to each close."""
    w = _window(df, start, end)
    if w.empty:
        return pd.Series(dtype=float)
    units = initial / (w["open"].iloc[0] * (1 + cost))
    return (units * w["close"]).rename("equity")


def equal_weight(bars: dict[str, pd.DataFrame], start, end, initial: float, cost: float) -> pd.Series:
    """Equal dollars in every symbol that trades on the window's first day; no rebalancing."""
    curves = []
    first_day = None
    for df in bars.values():
        w = _window(df, start, end)
        if w.empty:
            continue
        first_day = w.index[0] if first_day is None else min(first_day, w.index[0])
        curves.append(w)
    members = [w for w in curves if w.index[0] == first_day]
    if not members:
        return pd.Series(dtype=float)
    per = initial / len(members)
    values = pd.concat([(per / (w["open"].iloc[0] * (1 + cost))) * w["close"] for w in members], axis=1)
    return values.sort_index().ffill().sum(axis=1).rename("equity")
