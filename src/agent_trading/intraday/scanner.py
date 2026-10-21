"""Causal scanner: five capped factor groups, with independent safety vetoes."""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..indicators import atr, rsi, true_range
from .calendar import NY, aware, session
from .config import Settings
from .models import Bar, Scan, Signal, Snapshot


def frame(bars: list[Bar], now: datetime) -> pd.DataFrame:
    rows = []
    seen = set()
    for b in bars:
        if b.end > now:
            continue  # unfinished/future bars cannot affect a signal
        if b.end in seen:
            raise ValueError("duplicate bar timestamps")
        seen.add(b.end)
        s = session(b.end.astimezone(NY).date())
        if s and s.open < b.end <= s.close:
            rows.append(b.model_dump())
    if not rows:
        raise ValueError("no completed regular-session bars")
    return pd.DataFrame(rows).set_index("end").sort_index()


def current(df: pd.DataFrame, now: datetime, cfg: Settings) -> pd.DataFrame:
    s = session(aware(now).date())
    if not s or not s.open < now < s.close:
        raise ValueError("market closed")
    today = df.loc[(df.index > s.open) & (df.index <= now)]
    expected = int((now.replace(second=0, microsecond=0) - s.open).total_seconds() // 60)
    if len(today) != expected or expected < 15:
        raise ValueError("incomplete intraday minute coverage")
    if (now - today.index[-1]).total_seconds() > cfg.max_bar_age_seconds:
        raise ValueError("stale stock bars")
    return today


def vwap(df: pd.DataFrame) -> float:
    volume = float(df.volume.sum())
    if volume <= 0:
        raise ValueError("zero cumulative volume")
    return float((df.vwap * df.volume).sum() / volume)


def event_clear(snap: Snapshot, symbol: str, now: datetime) -> bool:
    e = snap.events.get(symbol)
    return bool(
        e
        and e.status == "clear"
        and e.observed_at <= now <= e.valid_until
        and e.observed_at.astimezone(NY).date() == aware(now).date()
    )


def evaluate(
    symbol: str,
    df: pd.DataFrame,
    today: pd.DataFrame,
    spy: pd.DataFrame,
    sector: pd.DataFrame,
    breadth: float,
    snap: Snapshot,
    now: datetime,
    cfg: Settings,
) -> Signal:
    close = float(today.close.iloc[-1])
    vw = vwap(today)
    right = "CALL" if close >= vw else "PUT"
    direction = 1 if right == "CALL" else -1
    orb = today.iloc[:15]
    breakout = len(today) > 15 and (close > orb.high.max() if direction == 1 else close < orb.low.min())
    previous = df.loc[df.index < today.index[0]]
    baselines = []
    minute = today.index[-1].astimezone(NY).hour * 60 + today.index[-1].astimezone(NY).minute
    for _, group in previous.groupby(previous.index.tz_convert(NY).date):
        comparable = group.loc[(group.index.tz_convert(NY).hour * 60 + group.index.tz_convert(NY).minute) <= minute]
        if len(comparable) == len(today):
            baselines.append(float(comparable.volume.sum()))
    if len(baselines) < cfg.rvol_sessions:
        raise ValueError("insufficient time-of-day RVOL history")
    baseline = float(np.mean(baselines[-cfg.rvol_sessions :]))
    if baseline <= 0:
        raise ValueError("zero historical volume")
    rvol = float(today.volume.sum() / baseline)
    ret = close / float(today.open.iloc[0]) - 1
    market_ret = float(spy.close.iloc[-1] / spy.open.iloc[0] - 1)
    sector_ret = float(sector.close.iloc[-1] / sector.open.iloc[0] - 1)
    relative = (ret - market_ret) * direction
    sector_relative = (sector_ret - market_ret) * direction
    market_ok = market_ret * direction > 0 and (float(spy.close.iloc[-1]) - vwap(spy)) * direction > 0
    sector_ok = sector_ret * direction > 0 and (float(sector.close.iloc[-1]) - vwap(sector)) * direction > 0
    recent = today.iloc[-5:]
    structure = bool(
        ((recent.high.diff().dropna() * direction) > 0).all() and ((recent.low.diff().dropna() * direction) > 0).all()
    )
    accel_base = float(today.volume.iloc[-10:-5].mean())
    accel = float(recent.volume.mean() / accel_base) if accel_base > 0 else 0
    tail = df.tail(200)
    av = float(atr(tail).iloc[-1])
    rv = float(rsi(tail.close).iloc[-1])
    up, down = tail.high.diff(), -tail.low.diff()
    tr = true_range(tail).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    plus = 100 * up.where((up > down) & (up > 0), 0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / tr
    minus = 100 * down.where((down > up) & (down > 0), 0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / tr
    dx = 100 * (plus - minus).abs() / (plus + minus).replace(0, np.nan)
    adx = float(dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean().iloc[-1])
    if not all(np.isfinite(x) for x in [av, rv, adx]):
        raise ValueError("indicator warm-up incomplete")
    prior = previous.loc[previous.index.tz_convert(NY).date == previous.index[-1].astimezone(NY).date()]
    support, resistance = float(prior.low.min()), float(prior.high.max())
    clearance = (resistance - close) if direction == 1 else (close - support)
    space = clearance <= 0 or clearance >= av
    momentum = float(close / today.close.iloc[-6] - 1) * direction
    breadth_ok = breadth >= 0.55 if direction == 1 else breadth <= 0.45
    # Correlated trend indicators share ONE 30-point budget; RSI/ADX share 15.
    group = {
        "trend": sum([(close - vw) * direction > 0, breakout, structure]) / 3,
        "participation": (min(rvol / 2, 1) + min(accel / 1.5, 1)) / 2,
        "relative_strength": (max(0, min(relative / 0.005, 1)) + float(sector_ok) + float(sector_relative > 0)) / 3,
        "momentum": (float(momentum > 0) + float(rv > 50 if direction == 1 else rv < 50) + min(adx / 25, 1)) / 3,
        "context": (float(breadth_ok) + float(space)) / 2,
    }
    score = round(sum(group[k] * cfg.weights.model_dump()[k] for k in group), 2)
    checks = {
        "VWAP": (close - vw) * direction > 0,
        "opening range": breakout,
        "RVOL": rvol >= cfg.minimum_rvol,
        "market trend": market_ok,
        "sector trend": sector_ok,
        "relative strength": relative > 0,
        "breadth": breadth_ok,
        "volatility": 0 < av / close <= cfg.max_atr_fraction,
        "event coverage": event_clear(snap, symbol, now) and event_clear(snap, "MARKET", now),
        "technical score": score >= cfg.minimum_score,
    }
    failed = [f"rejected: {k}" for k, ok in checks.items() if not ok]
    factors = {
        **group,
        "vwap": vw,
        "vwap_relationship": "above" if close > vw else "below",
        "rvol": rvol,
        "breakout": bool(breakout),
        "market_confirmation": bool(market_ok),
        "sector_confirmation": bool(sector_ok),
        "atr": av,
        "rsi": rv,
        "adx": adx,
        "momentum_return": momentum,
        "volume_acceleration": accel,
        "support": support,
        "resistance": resistance,
        "breadth": breadth,
        "relative_return": relative,
        "sector_relative_return": sector_relative,
        "structure": structure,
    }
    return Signal(
        symbol=symbol,
        right=right,
        timestamp=now,
        score=score,
        qualified=not failed,
        reasons=failed or ["confirmed directional breakout, participation and market/sector alignment"],
        factors=factors,
    )


def scan(snap: Snapshot, now: datetime, cfg: Settings) -> Scan:
    aware(now)
    problems = list(snap.problems)
    if not 0 <= (now - snap.observed_at).total_seconds() <= cfg.max_bar_age_seconds:
        problems.append("stale or future snapshot")
    if not 0 <= (now - snap.membership_at).total_seconds() <= timedelta(days=1).total_seconds():
        problems.append("membership not known at decision time or older than one day")
    if snap.feed == "delayed":
        problems.append("delayed feed cannot authorize entries")
    if snap.feed != "fixture" and not 480 <= len(snap.universe) <= 520:
        problems.append("incomplete S&P 500 membership")
    frames, current_frames, rejected = {}, {}, {}
    for symbol in sorted(set(snap.universe) | set(snap.universe.values()) | {"SPY"}):
        try:
            frames[symbol] = frame(snap.bars.get(symbol, []), now)
            current_frames[symbol] = current(frames[symbol], now, cfg)
        except ValueError as exc:
            rejected[symbol] = str(exc)
    good = [s for s in snap.universe if s in current_frames]
    coverage = len(good) / len(snap.universe) if snap.universe else 0
    if coverage < cfg.minimum_coverage:
        problems.append("insufficient universe bar coverage")
    breadth = (
        sum(current_frames[s].close.iloc[-1] > current_frames[s].open.iloc[0] for s in good) / len(good)
        if good
        else 0.5
    )
    signals = []
    for symbol in sorted(snap.universe):
        try:
            signal = evaluate(
                symbol,
                frames[symbol],
                current_frames[symbol],
                current_frames["SPY"],
                current_frames[snap.universe[symbol]],
                breadth,
                snap,
                now,
                cfg,
            )
            signals.append(signal)
            if not signal.qualified:
                rejected[symbol] = "; ".join(signal.reasons)
        except (ValueError, KeyError, IndexError) as exc:
            rejected.setdefault(
                symbol, str(exc) if isinstance(exc, ValueError) else "missing benchmark, sector or history"
            )
    return Scan(
        timestamp=now,
        source=snap.source,
        feed=snap.feed,
        expected=len(snap.universe),
        scanned=len(good),
        coverage=coverage,
        signals=signals,
        rejected=rejected,
        problems=problems,
    )
