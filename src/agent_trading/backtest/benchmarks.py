"""Simple baselines every strategy must be compared against.

All baselines use the same cost model (fills worse by `cost` per side) and are
price-return only (dividends excluded, as in the strategy backtest).
"""
from __future__ import annotations

import pandas as pd

from ..indicators import sma
from .metrics import compute_metrics


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


def trend_timing(df: pd.DataFrame, start, end, initial: float, cost: float, ma: int = 200,
                 cash_rate: pd.Series | None = None) -> pd.Series:
    """Hold the benchmark only while its close is above its `ma`-day SMA.

    Signal at day t's close, trade at day t+1's open (same timing as the strategy).
    Cash earns `cash_rate` (per-day) when provided, as in the strategy backtest.
    """
    full = df.copy()
    full["sma"] = sma(full["close"], ma)
    w = _window(full, start, end)
    if w.empty:
        return pd.Series(dtype=float)
    signal = (full["close"] > full["sma"]).shift(1).reindex(w.index).fillna(False)
    cash, units, curve = initial, 0.0, {}
    rates = cash_rate.to_dict() if cash_rate is not None else {}
    for day, row in w.iterrows():
        cash += cash * float(rates.get(day, 0.0))
        want = bool(signal.loc[day])
        if want and units == 0:
            units = cash / (row["open"] * (1 + cost))
            cash = 0.0
        elif not want and units > 0:
            cash = units * row["open"] * (1 - cost)
            units = 0.0
        curve[day] = cash + units * row["close"]
    return pd.Series(curve, dtype=float).rename("equity")


def benchmark_table(
    bars: dict[str, pd.DataFrame], bench_symbol: str, start, end, initial: float, cost: float,
    cash_rate: pd.Series | None = None,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if bench_symbol in bars:
        b = bars[bench_symbol]
        out[f"{bench_symbol} buy & hold"] = compute_metrics(buy_and_hold(b, start, end, initial, cost), [], initial, 1.0)
        out[f"{bench_symbol} 200-day trend timing"] = compute_metrics(
            trend_timing(b, start, end, initial, cost, cash_rate=cash_rate), [], initial)
    out["Equal-weight universe buy & hold"] = compute_metrics(equal_weight(bars, start, end, initial, cost), [], initial, 1.0)
    return out
