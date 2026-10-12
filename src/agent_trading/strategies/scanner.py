"""Strategy A: rank every S&P 500 constituent with a transparent factor model.

Scoring (percentile ranks across the scanned universe, 0..1, higher = better).
Each idea is counted once, to avoid double counting correlated indicators:

  price_strength  mean of: 12-1 month momentum, 63-day return relative to SPY,
                  distance above the 200-day SMA (trend, momentum and relative
                  strength are highly correlated, so they share ONE weight)
  volume          20-day up-volume / down-volume ratio (accumulation)
  quality         mean of: operating margin, return on equity (fundamentals)
  valuation       forward earnings yield (1 / forward P/E), ranked within sector
  risk            lower 63-day realised volatility ranks higher

composite = weighted mean of the factors that are available; missing factors are
reported, and their weight is redistributed (never silently treated as zero).

A high rank is a research candidate, not a trade. "Actionable" additionally
requires: a bullish setup, liquidity, fresh data, no earnings inside the
blackout window (an unknown earnings date also blocks), RSI below 75, and a
spread below the limit when a live quote is available. Position sizing then
goes through the RiskEngine. No shorting: bearish setups are "avoid / exit".
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from ..config import Settings
from ..indicators import atr, macd, rsi, sma

FACTORS = ["price_strength", "volume", "quality", "valuation", "risk"]


def features(df: pd.DataFrame, bench: pd.DataFrame | None) -> dict | None:
    """Point-in-time features from daily bars ending at the last bar."""
    if len(df) < 60:
        return None
    c, v = df["close"], df["volume"]
    last = float(c.iloc[-1])

    def ret(n):
        return float(c.iloc[-1] / c.iloc[-1 - n] - 1) if len(c) > n else math.nan

    s50, s200 = sma(c, 50).iloc[-1], sma(c, 200).iloc[-1]
    a = float(atr(df, 14).iloc[-1])
    daily = c.pct_change()
    up_vol = v.where(daily > 0, 0.0).iloc[-20:].sum()
    down_vol = v.where(daily < 0, 0.0).iloc[-20:].sum()
    bench_63 = math.nan
    if bench is not None and len(bench) > 63:
        b = bench["close"].loc[:df.index[-1]]
        bench_63 = float(b.iloc[-1] / b.iloc[-64] - 1) if len(b) > 63 else math.nan
    window = c.iloc[-63:]
    return {
        "date": df.index[-1].date(),
        "close": last,
        "ret_1d": ret(1), "ret_5d": ret(5), "ret_21d": ret(21), "ret_63d": ret(63), "ret_126d": ret(126),
        "mom_12_1": float(c.iloc[-22] / c.iloc[-253] - 1) if len(c) > 253 else math.nan,
        "rs_63": ret(63) - bench_63,
        "sma50": float(s50), "sma200": float(s200),
        "dist_200": last / float(s200) - 1 if pd.notna(s200) else math.nan,
        "uptrend": bool(pd.notna(s200) and last > s50 > s200),
        "downtrend": bool(pd.notna(s200) and last < s50 < s200),
        "rsi": float(rsi(c, 14).iloc[-1]),
        "macd_hist": float(macd(c)["macd_hist"].iloc[-1]),
        "atr": a, "atr_pct": a / last,
        "vol_63": float(daily.iloc[-63:].std() * math.sqrt(252)),
        "max_dd_63": float((window / window.cummax() - 1).min()),
        "avg_dollar_volume": float((c * v).iloc[-20:].mean()),
        "vol_ratio": float(v.iloc[-1] / v.iloc[-21:-1].mean()) if v.iloc[-21:-1].mean() > 0 else math.nan,
        "updown_volume": float(up_vol / down_vol) if down_vol > 0 else math.nan,
        "breakout_55": bool(last >= df["high"].iloc[-56:-1].max()) if len(df) > 56 else False,
        "support_20": float(df["low"].iloc[-20:].min()),
        "resistance_55": float(df["high"].iloc[-55:].max()),
    }


def _rank(s: pd.Series, ascending: bool = True) -> pd.Series:
    return s.rank(pct=True, ascending=ascending)


def score(table: pd.DataFrame, fundamentals: pd.DataFrame | None, weights: dict[str, float]) -> pd.DataFrame:
    t = table.copy()
    if fundamentals is not None and not fundamentals.empty:
        t = t.join(fundamentals.set_index("ticker"), how="left")
    for col in ["operating_margin", "roe", "forward_pe", "sector_code", "earnings_date"]:
        if col not in t:
            t[col] = np.nan
    t["price_strength"] = pd.concat([_rank(t["mom_12_1"]), _rank(t["rs_63"]), _rank(t["dist_200"])], axis=1).mean(axis=1)
    t["volume"] = _rank(t["updown_volume"])
    t["quality"] = pd.concat([_rank(t["operating_margin"]), _rank(t["roe"])], axis=1).mean(axis=1)
    ey = (1 / t["forward_pe"]).where(t["forward_pe"] > 0)
    t["valuation"] = ey.groupby(t["sector_code"].fillna("?")).rank(pct=True)
    t["risk"] = _rank(t["vol_63"], ascending=False)
    w = pd.Series(weights)
    avail = t[FACTORS].notna()
    t["composite"] = (t[FACTORS].fillna(0) * w).sum(axis=1) / (avail * w).sum(axis=1).replace(0, np.nan)
    t["missing_factors"] = avail.apply(lambda r: ", ".join(f for f in FACTORS if not r[f]), axis=1)
    t["setup"] = np.where(t["uptrend"] & (t["mom_12_1"] > 0) & (t["rs_63"] > 0), "bullish",
                          np.where(t["downtrend"] & (t["mom_12_1"] < 0), "bearish", "neutral"))
    return t.sort_values("composite", ascending=False)


@dataclass
class Setup:
    ticker: str
    rank: int
    composite: float
    setup: str
    entry_ref: float
    max_entry: float
    stop: float
    target: float
    reward_risk: float
    holding_period: str
    evidence: list[str]
    risks: list[str]
    earnings_date: str | None


@dataclass
class ScanResult:
    as_of: date
    table: pd.DataFrame
    research: list[Setup]
    actionable: list[Setup]
    rejected: dict[str, list[str]] = field(default_factory=dict)
    bearish: list[str] = field(default_factory=list)


def _earnings(t: str, row, earnings_table: pd.DataFrame | None, as_of: date) -> date | None:
    dates = []
    if isinstance(row.get("earnings_date"), str):
        d = date.fromisoformat(row["earnings_date"])
        if d >= as_of:
            dates.append(d)
    if earnings_table is not None and not earnings_table.empty:
        hits = earnings_table[(earnings_table["symbol"] == t) & (earnings_table["reportDate"] >= as_of)]
        dates += list(hits["reportDate"])
    return min(dates) if dates else None


def _setup(t: str, i: int, row, settings: Settings, nxt: date | None) -> Setup:
    k = settings.risk.atr_stop_multiple
    stop = row["close"] - k * row["atr"]
    r_mult = settings.scanner.target_r_multiple
    evidence = [
        f"12-1 month momentum {row['mom_12_1']:+.1%}" if pd.notna(row["mom_12_1"]) else "12-1 momentum n/a (short history)",
        f"63-day return vs SPY {row['rs_63']:+.1%}",
        f"{row['dist_200']:+.1%} vs 200-day SMA; trend {'up' if row['uptrend'] else 'down' if row['downtrend'] else 'mixed'}",
        f"up/down volume (20d) {row['updown_volume']:.2f}" if pd.notna(row["updown_volume"]) else "volume ratio n/a",
    ]
    if pd.notna(row.get("operating_margin")):
        evidence.append(f"operating margin {row['operating_margin']:.0%}, ROE {row['roe']:.0%}" if pd.notna(row.get("roe"))
                        else f"operating margin {row['operating_margin']:.0%}")
    if pd.notna(row.get("forward_pe")):
        evidence.append(f"forward P/E {row['forward_pe']:.1f}")
    if row["breakout_55"]:
        evidence.append("closed at a 55-day high (breakout)")
    risks = [f"63-day volatility {row['vol_63']:.0%}, ATR {row['atr_pct']:.1%} of price",
             f"worst 63-day drawdown {row['max_dd_63']:.0%}"]
    if row["rsi"] >= 70:
        risks.append(f"RSI {row['rsi']:.0f}: extended")
    if row["missing_factors"]:
        risks.append(f"missing data: {row['missing_factors']}")
    risks.append(f"next earnings {nxt}" if nxt else "earnings date unverified")
    return Setup(t, i, float(row["composite"]), row["setup"], float(row["close"]),
                 float(row["close"] + 0.5 * row["atr"]), float(stop),
                 float(row["close"] + r_mult * (row["close"] - stop)), r_mult,
                 "2-8 weeks; exit on a close below the 50-day SMA, the stop, or the target",
                 evidence, risks, nxt.isoformat() if nxt else None)


def run_scan(
    bars: dict[str, pd.DataFrame],
    settings: Settings,
    as_of: date,
    fundamentals: pd.DataFrame | None = None,
    quotes: pd.DataFrame | None = None,
    earnings_table: pd.DataFrame | None = None,
    bench: pd.DataFrame | None = None,
) -> ScanResult:
    """`bars`: constituents only. `bench`: benchmark bars for relative strength."""
    sc = settings.scanner
    rows = {}
    for t, df in bars.items():
        f = features(df, bench)
        if f is not None:
            rows[t] = f
    table = pd.DataFrame.from_dict(rows, orient="index")
    if table.empty:
        return ScanResult(as_of, table, [], [])
    table = score(table, fundamentals, sc.weights)
    spreads = quotes.set_index("ticker")["spread_pct"] if quotes is not None and not quotes.empty else pd.Series(dtype=float)

    research, actionable, rejected, bearish = [], [], {}, []
    for i, (t, row) in enumerate(table.iterrows(), start=1):
        nxt = _earnings(t, row, earnings_table, as_of)
        if row["setup"] == "bearish" and len(bearish) < sc.top_research:
            bearish.append(t)
        if i <= sc.top_research:
            research.append(_setup(t, i, row, settings, nxt))
        if len(actionable) >= sc.top_actionable or row["setup"] != "bullish":
            continue
        reasons = []
        if row["close"] < sc.min_price:
            reasons.append(f"price ${row['close']:.2f} < ${sc.min_price:.0f}")
        if row["avg_dollar_volume"] < sc.min_avg_dollar_volume:
            reasons.append(f"avg dollar volume ${row['avg_dollar_volume'] / 1e6:.0f}M < ${sc.min_avg_dollar_volume / 1e6:.0f}M")
        if nxt is None:
            reasons.append("earnings date unverified")
        elif (nxt - as_of).days <= sc.earnings_blackout_days:
            reasons.append(f"earnings on {nxt} (inside {sc.earnings_blackout_days}-day blackout)")
        if row["rsi"] >= 75:
            reasons.append(f"RSI {row['rsi']:.0f} >= 75 (extended; wait for a pullback)")
        spread = spreads.get(t)
        if spread is not None and pd.notna(spread) and spread > sc.max_spread_pct:
            reasons.append(f"spread {spread:.2%} > {sc.max_spread_pct:.2%}")
        if row["missing_factors"].count(",") >= 1:
            reasons.append(f"too much missing data ({row['missing_factors']})")
        if reasons:
            if i <= sc.top_research * 3:
                rejected[t] = reasons
            continue
        actionable.append(_setup(t, i, row, settings, nxt))
    return ScanResult(as_of, table, research, actionable, rejected, bearish)
