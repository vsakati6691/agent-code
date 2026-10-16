"""Apply the registered company gates, scores and tradability checks."""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

from . import scoring, spec
from .fundamentals import Fundamentals
from .pipeline_collect import _facts, latest_bars
from .pipeline_context import Context, log
from .tradability import Tradability


def dollar_volume(df: pd.DataFrame) -> float:
    tail = df.iloc[-20:]
    return float((tail["close"] * tail["volume"]).median())


def market_cap(f: Fundamentals, close: float) -> tuple[float | None, list[str]]:
    if f.cover_shares:
        return close * f.cover_shares, []
    dil = next((s for s in f.diluted_shares if s), None)
    if dil:
        return close * dil, ["shares from weighted-average fallback"]
    return None, []


def fundamentals_flags(f: Fundamentals, as_of: date, bars: int) -> tuple[list[str], str | None]:
    """(flags, exclusion reason)."""
    flags = []
    if not f.last_filed:
        return flags, "no 10-K/10-Q revenue or income facts filed by the as-of date"
    age = (as_of - date.fromisoformat(f.last_filed)).days
    if age > spec.MAX_FILING_AGE_DAYS:
        return flags, f"fundamentals stale: latest 10-K/10-Q filed {f.last_filed} ({age} days before the as-of date)"
    if age > 120:
        flags.append("latest filing older than 120 days")
    if f.n_quarters < spec.LIMITED_HISTORY_QUARTERS:
        flags.append(f"limited operating history ({f.n_quarters} reported quarters)")
    if bars < spec.LIMITED_HISTORY_DAYS:
        flags.append(f"limited trading history ({bars} daily bars)")
    if f.any_derived():
        flags.append("some quarters derived from cumulative or annual filings")
    return flags, None


GATE_LABELS = {
    "revenue_growth_ttm": "TTM revenue growth",
    "revenue_cagr_3y": "3-year revenue growth",
    "gross_margin": "gross margin",
    "reported_quarters": "reported quarters",
    "dilution": "dilution",
    "survival": "survival (positive FCF or 2+ years of cash runway)",
}


def failed_gate(band: spec.Band, m: dict) -> str | None:
    """The first eligibility gate the stock fails (missing input = fail), or None."""
    for metric, op, limit in band.gates:
        v = m.get(metric)
        label = GATE_LABELS.get(metric, metric)
        if v is None or not math.isfinite(v):
            return f"gate input unavailable: {label}"
        if (op == ">=" and v < limit) or (op == "<=" and v > limit):
            shown = f"{v:.0%}" if abs(limit) < 5 and metric not in ("reported_quarters", "survival") else f"{v:g}"
            want = (
                f"{limit:.0%}" if abs(limit) < 5 and metric not in ("reported_quarters", "survival") else f"{limit:g}"
            )
            return f"gate failed: {label} {shown} (needs {op} {want})"
    return None


def evaluate(ctx: Context, band: spec.Band, tickers: list[tuple[str, int, str, str]], bench: pd.Series) -> list[dict]:
    """Score each (ticker, cik, name, sector) for `band`; exclusions are recorded on ctx."""
    out = []
    for i, (t, cik, name, sector) in enumerate(tickers, 1):
        if i % 100 == 0:
            log.info("%s: evaluated %d of %d", band.key, i, len(tickers))
        df, why, pflags = latest_bars(ctx, t)
        if df is None:
            ctx.exclude(band.key, t, why)
            continue
        close = float(df["close"].iloc[-1])
        if close < band.min_price:
            ctx.exclude(band.key, t, f"price {close:.2f} below {band.min_price:g}")
            continue
        dv = dollar_volume(df)
        if dv < band.min_dollar_volume:
            ctx.exclude(
                band.key,
                t,
                f"illiquid: 20-day median dollar volume ${dv / 1e6:.1f}M < ${band.min_dollar_volume / 1e6:g}M",
            )
            continue
        f, why = _facts(ctx, cik)
        if f is None:
            ctx.exclude(band.key, t, why)
            continue
        flags, why = fundamentals_flags(f, ctx.as_of, len(df))
        if why:
            ctx.exclude(band.key, t, why)
            continue
        cap, cap_flags = market_cap(f, close)
        if cap is None:
            ctx.exclude(band.key, t, "market cap unavailable (no share count)")
            continue
        if band.min_cap is not None and cap < band.min_cap or band.max_cap is not None and cap >= band.max_cap:
            ctx.exclude(band.key, t, f"market cap ${cap / 1e9:.2f}B outside the band")
            continue
        m = scoring.compute_metrics(f, df["close"], bench, cap)
        gate = failed_gate(band, m)
        if gate:
            ctx.exclude(band.key, t, gate)
            continue
        if band.min_revenue_growth is not None and (
            m["revenue_growth_ttm"] is None or m["revenue_growth_ttm"] < band.min_revenue_growth
        ):
            g = m["revenue_growth_ttm"]
            ctx.exclude(
                band.key,
                t,
                "revenue growth "
                + ("unavailable" if g is None else f"{g:.0%}")
                + f" below the {band.min_revenue_growth:.0%} speculative-band gate",
            )
            continue
        flags = flags + cap_flags + pflags
        s = scoring.score_one(t, m, f, flags, spec.PROFILES[band.profile])
        if s.excluded_reason:
            ctx.exclude(band.key, t, s.excluded_reason)
        out.append(
            {
                "ticker": t,
                "cik": cik,
                "name": name,
                "sector": sector,
                "score": s,
                "metrics": m,
                "fundamentals": f,
                "bars": df,
                "close": close,
                "dollar_volume": dv,
            }
        )
    return one_class_per_company(ctx, band, out)


def one_class_per_company(ctx: Context, band: spec.Band, rows: list[dict]) -> list[dict]:
    """Keep the most liquid share class of each company (CIK); the others are listed as excluded."""
    best: dict[int, dict] = {}
    for r in rows:
        b = best.get(r["cik"])
        if b is None or (r["dollar_volume"], r["ticker"]) > (b["dollar_volume"], b["ticker"]):
            best[r["cik"]] = r
    keep = []
    for r in rows:
        winner = best[r["cik"]]
        if winner is r:
            keep.append(r)
        else:
            ctx.excluded[band.key].pop(r["ticker"], None)
            ctx.exclude(
                band.key,
                r["ticker"],
                f"another share class of the same company is evaluated instead ({winner['ticker']}, more liquid)",
            )
    return keep


def tradable_only(ctx: Context, band: spec.Band, ranked: list, trad: Tradability, todo: list[dict]) -> list:
    """Drop stocks without a fresh 'tradable' Robinhood verdict (fail closed) and re-rank the rest.

    Scores use fixed scales, so removing a stock never changes the order of the others. Unverified stocks
    that would have been shown, or are within TRADABILITY_CHECK_DEPTH places of the cutoff, go on the
    to-check list for the next Claude session."""
    kept, unverified = [], 0
    for s in ranked:
        ok, why = trad.check(s.ticker, ctx.as_of)
        if ok:
            kept.append(s)
            continue
        ctx.exclude(band.key, s.ticker, why)
        if ok is None and len(kept) + unverified < band.max_results + spec.TRADABILITY_CHECK_DEPTH:
            todo.append({"ticker": s.ticker, "band": band.key, "composite": s.composite, "reason": why})
        if ok is None:
            unverified += 1
    return scoring.rank(kept)
