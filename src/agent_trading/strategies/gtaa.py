"""Strategy C: GTAA multi-asset trend (Faber, "A Quantitative Approach to
Tactical Asset Allocation", 2007).

Rule (pre-registered, published 2007, so 2008+ is out-of-sample for it):
at each month-end, hold each of the assets with weight 1/N if its month-end
close is above the average of its last `sma_months` month-end closes;
otherwise that slice stays in cash. Trades at the next open.

Under the account's per-position limits (option a) each holding is also sized
by the RiskEngine with an ATR stop, so actual weights are usually far below
1/N and most of the sleeve sits in cash.
"""

from __future__ import annotations

from datetime import date

import pandas as pd


def monthly_closes(df: pd.DataFrame, up_to: pd.Timestamp) -> pd.Series:
    c = df["close"].loc[:up_to]
    return c.groupby([c.index.year, c.index.month]).last()


def signals(history: dict[str, pd.DataFrame], day: pd.Timestamp, assets: list[str], sma_months: int) -> dict[str, dict]:
    """Per asset: month-end close, its SMA, and whether it is above (None if not enough history)."""
    out = {}
    for a in assets:
        df = history.get(a)
        if df is None or df.empty:
            out[a] = {"close": None, "sma": None, "above": None, "reason": "no data"}
            continue
        m = monthly_closes(df, day)
        if len(m) < sma_months:
            out[a] = {
                "close": float(m.iloc[-1]) if len(m) else None,
                "sma": None,
                "above": None,
                "reason": f"only {len(m)} months of history",
            }
            continue
        sma = float(m.iloc[-sma_months:].mean())
        close = float(m.iloc[-1])
        out[a] = {"close": close, "sma": sma, "above": close > sma, "reason": ""}
    return out


def weights(
    history: dict[str, pd.DataFrame], day: pd.Timestamp, assets: list[str], sma_months: int
) -> dict[str, float]:
    sig = signals(history, day, assets, sma_months)
    return {a: 1.0 / len(assets) for a, s in sig.items() if s["above"]}


def vol_managed_weights(
    history: dict[str, pd.DataFrame],
    day: pd.Timestamp,
    assets: list[str],
    sma_months: int,
    target_vol: float = 0.10,
    lookback: int = 63,
    max_exposure: float = 1.0,
) -> dict[str, float]:
    """C2 hypothesis (declared before testing): the GTAA weights scaled so the
    trailing `lookback`-day volatility of the selected basket is at most
    `target_vol`, never above `max_exposure` (no leverage). Uses only data up to `day`."""
    base = weights(history, day, assets, sma_months)
    if not base:
        return {}
    rets = pd.DataFrame({a: history[a]["close"].loc[:day].pct_change() for a in base}).iloc[-lookback:]
    port = (rets * pd.Series(base)).sum(axis=1)
    vol = float(port.std() * (252**0.5)) if len(port.dropna()) > 20 else float("nan")
    scale = min(max_exposure, target_vol / vol) if vol and vol == vol and vol > 0 else 1.0
    return {a: w * scale for a, w in base.items()}


def is_rebalance_day(trading_days: list[pd.Timestamp], day: date) -> bool:
    """Last trading day of the month: from the known trading days (backtests), or
    from the NYSE holiday calendar when `day` is the latest bar."""
    from ..market_calendar import next_trading_day

    ts = pd.Timestamp(day)
    later = [d for d in trading_days if d > ts]
    nxt = later[0] if later else pd.Timestamp(next_trading_day(ts.date()))
    return nxt.month != ts.month
