"""Collect validated public reference, price, filing and earnings data with bounded failure handling."""

from __future__ import annotations

import re
from datetime import date, timedelta

import pandas as pd

from ..data.validation import DataQualityError, trim_bad_history, validate_bars
from . import spec
from .earnings_cadence import label as cadence_label
from .fundamentals import Fundamentals
from .fundamentals import build as build_fundamentals
from .http import BudgetExceeded, FetchError
from .pipeline_context import Context, RunFailed
from .price_integrity import quote_close_reason
from .providers import common_stock_reason


def _guard(ctx: Context, provider: str, fn, *args):
    if provider in ctx.budget_hit:
        return None, "not evaluated: request budget spent"
    try:
        return fn(*args), None
    except BudgetExceeded as exc:
        ctx.budget_hit.add(provider)
        ctx.problems.append(str(exc))
        return None, "not evaluated: request budget spent"
    except FetchError as exc:
        if provider == "alphavantage" and "quota or entitlement" in str(exc):
            ctx.budget_hit.add(provider)
            ctx.problems.append(str(exc))
        if "attempts" in str(exc):
            ctx.transient_failures += 1
        return None, f"data unavailable ({exc})"


MIN_HISTORY_BARS = 60


def latest_bars(
    ctx: Context, symbol: str, min_bars: int = MIN_HISTORY_BARS
) -> tuple[pd.DataFrame | None, str | None, list[str]]:
    """Validated daily bars ending exactly on the as-of session, or a reason.

    `min_bars` below the default only verifies the as-of price itself (spec WATCHLIST_PRICE_RULE)."""
    key = symbol if min_bars == MIN_HISTORY_BARS else (symbol, min_bars)
    if key in ctx.histories:
        return ctx.histories[key]
    flags: list[str] = []
    df, why = _guard(ctx, "cboe", ctx.providers.history, symbol)
    if df is None:
        ctx.histories[key] = (None, why, flags)
        return ctx.histories[key]
    if df.attrs.get("repaired_recent", 0) > 2:
        flags.append(
            f"{df.attrs['repaired_recent']} price bars in the last year had an open/close outside the "
            "day's range and were repaired"
        )
    df = df[df.index <= pd.Timestamp(ctx.as_of)]
    if not df.empty and df.index[-1].date() < ctx.as_of:
        # Keep the independently validated quote in ctx.quotes, but it is not an OHLCV observation.
        q, _ = _quote(ctx, symbol)
        if q is not None:
            flags.append("close-only quote available; daily OHLCV history is missing for the as-of session")
    try:
        df, trimmed = trim_bad_history(df, symbol)  # an old glitch drops older history, a recent one rejects
        if trimmed:
            flags.append(trimmed)
        df = validate_bars(df, symbol, ctx.as_of, spec.MAX_PRICE_LAG_BUSINESS_DAYS, min_bars)
    except DataQualityError as exc:
        ctx.histories[key] = (None, f"price data rejected: {exc}", flags)
        return ctx.histories[key]
    ctx.histories[key] = (df, None, flags)
    return ctx.histories[key]


SHORT_HISTORY = re.compile(r"only (\d+) bars, need (\d+)")


def watchlist_bars(ctx: Context, symbol: str) -> tuple[pd.DataFrame | None, str | None, list[str], str | None]:
    """(bars, reason, flags, short-history note): the as-of price is verified on its own when the history is too
    short for the full analysis (spec 2026-10-14.5); every other rejection still rejects the price."""
    df, why, flags = latest_bars(ctx, symbol)
    if df is not None or not why or not SHORT_HISTORY.search(why):
        return df, why, flags, None
    short, why2, flags2 = latest_bars(ctx, symbol, spec.WATCHLIST_MIN_PRICE_BARS)
    if short is None:
        return None, why2, flags2, None
    n = len(short)
    note = (
        f"only {n} daily bars since {short.index[0].date()}: the as-of price is verified, but analyses needing "
        f"more history (trailing returns over {n} sessions, volatility, momentum) are unavailable"
    )
    return short, None, flags2, note


def _quote(ctx: Context, symbol: str):
    if symbol not in ctx.quotes:
        quote, reason = _guard(ctx, "cboe", ctx.providers.quote, symbol)
        if quote is not None:
            reason = quote_close_reason(quote, ctx.as_of)
        ctx.quotes[symbol] = (None, reason) if reason else (quote, None)
    return ctx.quotes[symbol]


def _facts(ctx: Context, cik: int) -> tuple[Fundamentals | None, str | None]:
    if cik in ctx.facts:
        return ctx.facts[cik]
    raw, why = _guard(ctx, "sec", ctx.providers.company_facts, cik)
    if raw is None:
        ctx.facts[cik] = (None, why)
    elif not (raw.get("facts") or {}).get("us-gaap"):
        ctx.facts[cik] = (None, "no US-GAAP XBRL facts (likely a foreign filer using 20-F/40-F or IFRS)")
    else:
        ctx.facts[cik] = (build_fundamentals(raw, ctx.as_of, max_quarters=spec.DECISION_RULES["max_quarters"]), None)
    return ctx.facts[cik]


def build_reference(ctx: Context) -> dict:
    p = ctx.providers
    try:
        sec = p.sec_tickers()
        dirs = p.symbol_directories()
        sp = p.sp500()
        frames = p.share_frames(ctx.as_of)
    except FetchError as exc:
        raise RunFailed(f"reference data unavailable: {exc}") from None
    return {"sec": sec, "dirs": dirs, "sp500": sp, "frames": frames}


def broad_universe(ctx: Context, ref: dict) -> tuple[pd.DataFrame, dict[str, int]]:
    """Eligible common stocks (not S&P-only) with CIK and cover-page shares; reason counts for the rest."""
    sec, dirs, frames = ref["sec"], ref["dirs"], ref["frames"]
    reasons: dict[str, int] = {}
    rows = []
    for t, d in dirs.iterrows():
        why = common_stock_reason(d["name"], d["etf"], d["test_issue"], d["financial_status"])
        if why is None and d["exchange"] not in spec.LISTED_EXCHANGES:
            why = f"listed on {d['exchange']} (not an eligible exchange)"
        if why is None and t not in sec.index:
            why = "not in the SEC ticker file (no SEC registrant match)"
        if why is None and sec.loc[t, "exchange"] in ("OTC", ""):
            why = "OTC or unknown exchange in the SEC ticker file"
        if why is None:
            cik = int(sec.loc[t, "cik"])
            if cik not in frames:
                why = "no recent SEC cover-page share count (multi-class or foreign filer)"
            else:
                rows.append(
                    {
                        "ticker": t,
                        "cik": cik,
                        "name": d["name"],
                        "exchange": d["exchange"],
                        "frame_shares": frames[cik][0],
                        "frame_end": frames[cik][1],
                    }
                )
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame(), reasons


SEC_RESERVE_FOR_EARNINGS = 25  # SEC requests kept back before the optional 8-K check runs


def verify_earnings(ctx: Context, cik: int | None, next_scheduled: str | None) -> dict:
    """Last results date confirmed by an SEC 8-K item 2.02 filing, plus a cadence check of the scheduled date.

    Uses the submissions file already allowed on data.sec.gov (GET via http.py). Skipped, with a note, when the
    SEC request budget is nearly spent; the scheduled Alpha Vantage date then stays labelled unverified."""
    out = {
        "next_scheduled": next_scheduled,
        "next_status": "scheduled (Alpha Vantage, unverified)"
        if next_scheduled
        else "no scheduled date from the data source",
        "last_results": None,
        "last_results_status": None,
        "cadence_check": None,
    }
    if cik is None:
        out["last_results_status"] = "no SEC registrant, so no 8-K to check"
        return out
    left = getattr(getattr(ctx.providers, "http", None), "budget_left", None)
    if callable(left) and left("sec") <= SEC_RESERVE_FOR_EARNINGS:
        out["last_results_status"] = "not checked: SEC request budget nearly spent; the scheduled date stays unverified"
        return out
    sub, why = _guard(ctx, "sec", ctx.providers.submissions, cik)
    if sub is None:
        out["last_results_status"] = f"not checked ({why})"
        return out
    from .providers import parse_earnings_8k

    dates = parse_earnings_8k(sub, ctx.as_of)  # point in time: filings after the as-of date are ignored
    if not dates:
        out["last_results_status"] = "no 8-K item 2.02 among the recent SEC filings"
        return out
    out["last_results"], out["last_results_status"] = dates[0], "verified (8-K)"
    if next_scheduled and len(dates) >= 2:
        gaps = sorted(
            (date.fromisoformat(a) - date.fromisoformat(b)).days for a, b in zip(dates[:5], dates[1:5], strict=False)
        )
        gap = gaps[len(gaps) // 2]
        expected = date.fromisoformat(dates[0]) + timedelta(days=gap)
        out["cadence_check"] = cadence_label(expected, date.fromisoformat(next_scheduled))
    return out
