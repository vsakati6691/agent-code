"""Historical test of the Strategy B (desk) rules, using the same engine,
costs, and RiskEngine as everything else.

The rules are exactly those in strategies/desk.py, evaluated on every day:
signals at day t's close, fills at day t+1's open. Not modelled historically
(no point-in-time data): the economic-event blackout and NVDA's earnings
blackout. Results therefore overstate how often the live desk would trade
and include event-day risk the live rules avoid.
"""
from __future__ import annotations

import math
from dataclasses import replace

import pandas as pd

from ..config import Settings
from ..indicators import atr, rate_of_change, rsi, sma
from .engine import BacktestResult, run_backtest


def _frame(df: pd.DataFrame, entry: pd.Series, exit_: pd.Series) -> pd.DataFrame:
    out = df[["open", "high", "low", "close"]].copy()
    out["atr"] = atr(df, 14)
    out["entry"] = entry.reindex(df.index).fillna(False).astype(bool)
    out["exit"] = exit_.reindex(df.index).fillna(False).astype(bool)
    out["momentum"] = 0.0
    return out


def _trend_rules(df: pd.DataFrame, bench: pd.DataFrame | None) -> tuple[pd.Series, pd.Series]:
    c = df["close"]
    s20, s50 = sma(c, 20), sma(c, 50)
    mom = rate_of_change(c, 63)
    entry = (c > s20) & (s20 > s50) & (mom > 0) & (rsi(c, 14) < 75)
    if bench is not None:
        b = bench["close"].reindex(df.index).ffill()
        entry &= (mom - rate_of_change(b, 63)) >= 0
    return entry, c < s50


def desk_rows(bars: dict[str, pd.DataFrame], settings: Settings, symbols: list[str] | None = None) -> dict[str, dict]:
    d = settings.desk
    symbols = symbols or list(d.symbols)
    rows: dict[str, dict] = {}
    qqq = bars.get(d.underlying)
    if qqq is not None:
        c = qqq["close"]
        s20, s50, s200 = sma(c, 20), sma(c, 50), sma(c, 200)
        vol = c.pct_change().rolling(20).std() * math.sqrt(252)
        up = (c > s50) & (s50 > s200)
        down = (c < s50) & (s50 < s200)
        above = c > s20
        rules = {
            d.leveraged_long: (up & above & (vol <= d.max_vol_long), ~above),
            d.leveraged_inverse: (down & ~above & (vol <= d.max_vol_inverse), above),
        }
        for sym, (entry, exit_) in rules.items():
            if sym in symbols and sym in bars:
                rows[sym] = _frame(bars[sym], entry, exit_).to_dict("index")
    if "NVDA" in symbols and "NVDA" in bars:
        e, x = _trend_rules(bars["NVDA"], bars.get(d.nvda_benchmark))
        rows["NVDA"] = _frame(bars["NVDA"], e, x).to_dict("index")
    if d.bitcoin_instrument in symbols and d.bitcoin_instrument in bars:
        e, x = _trend_rules(bars[d.bitcoin_instrument], None)
        rows[d.bitcoin_instrument] = _frame(bars[d.bitcoin_instrument], e, x).to_dict("index")
    return rows


def run_desk_backtest(bars: dict[str, pd.DataFrame], settings: Settings, symbols: list[str] | None = None,
                      start=None, end=None, cash_rate: pd.Series | None = None) -> BacktestResult:
    rows = desk_rows(bars, settings, symbols)
    traded = {s: bars[s] for s in rows}
    return run_backtest(traded, settings, start, end, prepared=rows, cash_rate=cash_rate)


def run_unlevered_baseline(bars: dict[str, pd.DataFrame], settings: Settings, start=None, end=None) -> BacktestResult:
    """The TQQQ rule traded on QQQ itself, with TQQQ's per-trade risk and holding
    limit: isolates what the 3x leverage adds (or costs) versus the same signal."""
    d = settings.desk
    qqq = bars[d.underlying]
    c = qqq["close"]
    s20, s50, s200 = sma(c, 20), sma(c, 50), sma(c, 200)
    vol = c.pct_change().rolling(20).std() * math.sqrt(252)
    above = c > s20
    entry = (c > s50) & (s50 > s200) & above & (vol <= d.max_vol_long)
    rows = {d.underlying: _frame(qqq, entry, ~above).to_dict("index")}
    r = settings.risk
    same_limits = replace(settings, risk=replace(
        r,
        symbol_risk_pct={**r.symbol_risk_pct, d.underlying: r.symbol_risk_pct.get(d.leveraged_long, r.risk_per_trade_pct)},
        max_holding_days={**r.max_holding_days, d.underlying: r.max_holding_days.get(d.leveraged_long, 5)},
    ))
    return run_backtest({d.underlying: qqq}, same_limits, start, end, prepared=rows)


def with_cost_multiplier(settings: Settings, k: float) -> Settings:
    """Same settings with slippage and spread scaled by k (cost stress test)."""
    c = settings.costs
    return replace(settings, costs=replace(c, slippage_bps=c.slippage_bps * k, spread_bps=c.spread_bps * k))
