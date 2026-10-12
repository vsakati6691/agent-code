"""Strategy B: focused daily desk for TQQQ, SQQQ, IBIT (Bitcoin ETF) and NVDA.

Each instrument has its own pre-registered rules (written before testing):

TQQQ / SQQQ (3x daily leveraged / inverse Nasdaq-100). Signals come from QQQ,
the underlying, never from the leveraged ETF itself:
  BUY TQQQ  QQQ close > SMA50 > SMA200, close > SMA20, 20-day vol <= max_vol_long
  BUY SQQQ  QQQ close < SMA50 < SMA200, close < SMA20, 20-day vol <= max_vol_inverse
  EXIT      QQQ crosses SMA20 against the position, the stop, or max holding days
  BLOCK     no entries within event_blackout_days of a high-impact US release or
            a Nasdaq-leader earnings date; an unavailable calendar also blocks
  Never both at once (RiskEngine exclusive group); tighter per-trade risk.
NVDA: trend (close > SMA20 > SMA50, 63-day momentum > 0, RSI < 75), relative
  strength vs SMH >= 0, no entry within earnings_blackout_days (unknown date
  blocks). Exit on a close below SMA50 or the stop.
IBIT: the same trend rules on IBIT itself. It tracks spot bitcoin but trades
  only in US stock hours, so weekend bitcoin moves arrive as Monday gaps.

Confidence labels are rule-agreement counts, NOT calibrated probabilities.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from ..config import Settings
from ..indicators import atr, rate_of_change, rsi, sma

ACTIONS = ("BUY", "SELL/REDUCE", "HOLD", "WAIT", "NO TRADE")


@dataclass
class Position:
    quantity: float
    entry_price: float
    stop: float
    entry_date: date


@dataclass
class DeskDecision:
    symbol: str
    action: str
    confidence: str
    price: float | None
    price_date: date | None
    trend: str
    reasons: list[str]
    entry_conditions: str
    stop: float | None
    holding_period: str
    what_changes: str
    catalysts: list[str] = field(default_factory=list)
    position: Position | None = None


def _snapshot(df: pd.DataFrame) -> dict:
    c = df["close"]
    return {
        "close": float(c.iloc[-1]),
        "date": df.index[-1].date(),
        "sma20": float(sma(c, 20).iloc[-1]),
        "sma50": float(sma(c, 50).iloc[-1]),
        "sma200": float(sma(c, 200).iloc[-1]) if len(c) >= 200 else math.nan,
        "vol20": float(c.pct_change().iloc[-20:].std() * math.sqrt(252)),
        "atr": float(atr(df, 14).iloc[-1]),
        "rsi": float(rsi(c, 14).iloc[-1]),
        "mom63": float(rate_of_change(c, 63).iloc[-1]) if len(c) > 63 else math.nan,
        "ret_1d": float(c.iloc[-1] / c.iloc[-2] - 1),
    }


def qqq_regime(qqq: pd.DataFrame) -> dict:
    s = _snapshot(qqq)
    if s["close"] > s["sma50"] > s["sma200"]:
        trend = "up"
    elif s["close"] < s["sma50"] < s["sma200"]:
        trend = "down"
    else:
        trend = "mixed"
    s["trend"] = trend
    s["above_sma20"] = s["close"] > s["sma20"]
    return s


def _days_held(p: Position, as_of: date) -> int:
    return int(np.busday_count(p.entry_date, as_of))


def leveraged_blockers(events: pd.DataFrame | None, leader_earnings: dict[str, date | None],
                       as_of: date, window: int) -> list[str]:
    """Reasons to block leveraged entries. A missing calendar is itself a blocker."""
    out = []
    if events is None:
        out.append("economic calendar unavailable or stale (fail-safe block)")
    elif not events.empty:
        names = sorted({f"{r.name} ({r.date})" for r in events.itertuples()})
        out.append("high-impact US releases within the blackout: " + "; ".join(names[:4])
                   + ("" if len(names) <= 4 else f" (+{len(names) - 4} more)"))
    for sym, d in leader_earnings.items():
        if d is not None and 0 <= (d - as_of).days <= window:
            out.append(f"{sym} earnings on {d}")
    return out


def _leveraged(sym: str, direction: str, own: pd.DataFrame | None, reg: dict, settings: Settings,
               blockers: list[str], position: Position | None, other_held: bool, as_of: date) -> DeskDecision:
    d = settings.desk
    max_days = settings.risk.max_holding_days.get(sym, 5)
    k = settings.risk.atr_stop_multiple
    if own is None:
        return DeskDecision(sym, "NO TRADE", "n/a", None, None, reg["trend"], ["no valid price data"], "-", None,
                            "-", "valid data", position=position)
    s = _snapshot(own)
    stop = s["close"] - k * s["atr"]
    want = "up" if direction == "long" else "down"
    aligned_short = reg["above_sma20"] if direction == "long" else not reg["above_sma20"]
    max_vol = d.max_vol_long if direction == "long" else d.max_vol_inverse
    holding = f"1-{max_days} trading days (hard limit; leveraged ETFs decay)"
    changes = (f"QQQ closing {'below' if direction == 'long' else 'above'} its 20-day SMA "
               f"({reg['sma20']:.2f}), QQQ volatility above {max_vol:.0%}, or a blackout event")
    regime_txt = f"QQQ {reg['trend']} trend, {'above' if reg['above_sma20'] else 'below'} SMA20, 20d vol {reg['vol20']:.0%}"

    if position is not None:
        held = _days_held(position, as_of)
        if held >= max_days:
            return DeskDecision(sym, "SELL/REDUCE", "high", s["close"], s["date"], regime_txt,
                                [f"held {held} days >= {max_days}-day limit"], "-", position.stop, holding, "-",
                                position=position)
        if s["close"] <= position.stop:
            return DeskDecision(sym, "SELL/REDUCE", "high", s["close"], s["date"], regime_txt,
                                ["closed at or below the stop"], "-", position.stop, holding, "-", position=position)
        if not aligned_short:
            return DeskDecision(sym, "SELL/REDUCE", "medium", s["close"], s["date"], regime_txt,
                                ["QQQ short-term trend turned against the position"], "-", position.stop, holding,
                                "-", position=position)
        return DeskDecision(sym, "HOLD", "medium", s["close"], s["date"], regime_txt,
                            [f"QQQ still {'above' if direction == 'long' else 'below'} SMA20; day {held} of {max_days}"],
                            "-", position.stop, holding, changes, position=position)

    reasons = [regime_txt]
    if other_held:
        return DeskDecision(sym, "NO TRADE", "high", s["close"], s["date"], regime_txt,
                            reasons + ["the opposite leveraged ETF is held"], "-", None, holding, changes)
    if reg["trend"] != want:
        return DeskDecision(sym, "NO TRADE", "high", s["close"], s["date"], regime_txt,
                            reasons + [f"QQQ trend is {reg['trend']}, rule needs {want}"], "-", None, holding,
                            f"QQQ trend turning {want}")
    if reg["vol20"] > max_vol:
        return DeskDecision(sym, "NO TRADE", "medium", s["close"], s["date"], regime_txt,
                            reasons + [f"QQQ 20d volatility {reg['vol20']:.0%} > {max_vol:.0%} (volatility drag)"],
                            "-", None, holding, f"QQQ volatility falling below {max_vol:.0%}")
    if not aligned_short or blockers:
        why = blockers if blockers else [f"QQQ not yet {'above' if direction == 'long' else 'below'} its 20-day SMA"]
        return DeskDecision(sym, "WAIT", "low", s["close"], s["date"], regime_txt, reasons + why,
                            f"QQQ {'above' if direction == 'long' else 'below'} SMA20 with no blackout event",
                            stop, holding, changes, catalysts=blockers)
    conf = "high" if reg["vol20"] < 0.8 * max_vol else "medium"
    return DeskDecision(sym, "BUY", conf, s["close"], s["date"], regime_txt, reasons + ["all entry rules met"],
                        f"next open; skip if it gaps more than 0.5 ATR ({0.5 * s['atr']:.2f}) above {s['close']:.2f}",
                        stop, holding, changes)


def _trend_asset(sym: str, df: pd.DataFrame | None, bench: pd.DataFrame | None, settings: Settings,
                 position: Position | None, earnings: date | None, earnings_known: bool, as_of: date,
                 notes: list[str]) -> DeskDecision:
    k = settings.risk.atr_stop_multiple
    if df is None:
        return DeskDecision(sym, "NO TRADE", "n/a", None, None, "unknown", ["no valid price data"], "-", None,
                            "-", "valid data", position=position)
    s = _snapshot(df)
    up = s["close"] > s["sma20"] > s["sma50"]
    trend = f"{'up' if up else 'not up'}: close {s['close']:.2f}, SMA20 {s['sma20']:.2f}, SMA50 {s['sma50']:.2f}; " \
            f"RSI {s['rsi']:.0f}; 63d {s['mom63']:+.1%}"
    rs = math.nan
    if bench is not None and len(bench) > 63 and len(df) > 63:
        b = bench["close"].loc[:df.index[-1]]
        rs = s["mom63"] - float(b.iloc[-1] / b.iloc[-64] - 1)
    stop = s["close"] - k * s["atr"]
    holding = "2-8 weeks; exit on a close below the 50-day SMA or the stop"
    catalysts = list(notes)
    if earnings is not None:
        catalysts.append(f"earnings on {earnings}")
    if position is not None:
        if s["close"] <= position.stop:
            return DeskDecision(sym, "SELL/REDUCE", "high", s["close"], s["date"], trend, ["closed at or below the stop"],
                                "-", position.stop, holding, "-", catalysts, position)
        if s["close"] < s["sma50"]:
            return DeskDecision(sym, "SELL/REDUCE", "medium", s["close"], s["date"], trend,
                                ["closed below the 50-day SMA (exit rule)"], "-", position.stop, holding, "-",
                                catalysts, position)
        return DeskDecision(sym, "HOLD", "medium", s["close"], s["date"], trend, ["trend intact"], "-",
                            position.stop, holding, f"a close below the 50-day SMA ({s['sma50']:.2f})", catalysts,
                            position)
    rules = {
        "uptrend (close > SMA20 > SMA50)": up,
        "63-day momentum > 0": s["mom63"] > 0,
        "RSI < 75": s["rsi"] < 75,
    }
    if bench is not None:
        rules["relative strength vs benchmark >= 0"] = bool(pd.notna(rs) and rs >= 0)
    failed = [r for r, ok in rules.items() if not ok]
    blackout = settings.desk.earnings_blackout_days
    blocked = []
    if not earnings_known:
        blocked.append("earnings date unverified")
    elif earnings is not None and 0 <= (earnings - as_of).days <= blackout:
        blocked.append(f"earnings on {earnings} inside the {blackout}-day blackout")
    if not up:
        return DeskDecision(sym, "NO TRADE", "high", s["close"], s["date"], trend, ["not in an uptrend"] + failed,
                            "-", None, holding, f"a close above SMA20 ({s['sma20']:.2f}) with SMA20 > SMA50", catalysts)
    if failed or blocked:
        return DeskDecision(sym, "WAIT", "low", s["close"], s["date"], trend, failed + blocked,
                            "all trend rules true and no earnings inside the blackout", stop, holding,
                            "; ".join(failed + blocked), catalysts)
    conf = "high" if s["mom63"] > 0.1 else "medium"
    return DeskDecision(sym, "BUY", conf, s["close"], s["date"], trend, ["all entry rules met"],
                        f"next open; skip if it gaps more than 0.5 ATR ({0.5 * s['atr']:.2f}) above {s['close']:.2f}",
                        stop, holding, f"a close below the 50-day SMA ({s['sma50']:.2f})", catalysts)


def run_desk(
    bars: dict[str, pd.DataFrame],
    settings: Settings,
    as_of: date,
    positions: dict[str, Position],
    events: pd.DataFrame | None,
    earnings_lookup,
) -> tuple[dict, list[DeskDecision]]:
    """`earnings_lookup(symbol) -> (date | None, known: bool)`."""
    d = settings.desk
    qqq = bars.get(d.underlying)
    decisions = []
    regime = qqq_regime(qqq) if qqq is not None and len(qqq) >= 200 else None
    if regime is None:
        for sym in (d.leveraged_long, d.leveraged_inverse):
            decisions.append(DeskDecision(sym, "NO TRADE", "n/a", None, None, "unknown",
                                          [f"{d.underlying} data missing or too short for the regime rules"],
                                          "-", None, "-", "valid QQQ data", position=positions.get(sym)))
    else:
        leaders = {s: earnings_lookup(s)[0] for s in d.nasdaq_leaders}
        blockers = leveraged_blockers(events, leaders, as_of, d.event_blackout_days)
        for sym, direction, other in [(d.leveraged_long, "long", d.leveraged_inverse),
                                      (d.leveraged_inverse, "inverse", d.leveraged_long)]:
            decisions.append(_leveraged(sym, direction, bars.get(sym), regime, settings, blockers,
                                        positions.get(sym), other in positions, as_of))
    nv_date, nv_known = earnings_lookup("NVDA")
    decisions.append(_trend_asset("NVDA", bars.get("NVDA"), bars.get(d.nvda_benchmark), settings,
                                  positions.get("NVDA"), nv_date, nv_known, as_of,
                                  ["review AI/data-center demand, export rules and customer news before acting"]))
    decisions.append(_trend_asset(d.bitcoin_instrument, bars.get(d.bitcoin_instrument), None, settings,
                                  positions.get(d.bitcoin_instrument), None, True, as_of,
                                  ["tracks spot bitcoin; trades only in US hours, so weekend moves gap at Monday's open"]))
    return (regime or {}), decisions
