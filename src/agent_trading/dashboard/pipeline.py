"""Weekly research run: universes -> fundamentals -> scores -> details -> options -> snapshot payload.

The run never touches the brokerage account or any private data. Every stock
that is considered but not ranked keeps its reason (missing data, stale data,
not common stock, out of band, budget spent), so exclusions are visible.
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import options as opt
from . import scenarios, scoring, spec
from .fundamentals import Fundamentals, build as build_fundamentals
from .http import BudgetExceeded, FetchError
from .providers import SOURCES, Providers, common_stock_reason, sector_from_sic
from ..data.validation import DataQualityError, trim_bad_history, validate_bars
from ..market_calendar import is_trading_day, previous_trading_day

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
BENCHMARKS = sorted({b.benchmark for b in spec.BANDS})
MIN_SP500_COVERAGE = 0.90


class RunFailed(RuntimeError):
    """The run cannot produce a trustworthy snapshot (the last good dashboard stays up)."""


def as_of_for(now: datetime) -> date:
    """The latest completed NYSE session at `now`: today after 18:00 ET on a trading day, else the one before."""
    et = now.astimezone(ET)
    d = et.date()
    if is_trading_day(d) and et.hour >= 18:
        return d
    return previous_trading_day(d)


@dataclass
class Context:
    as_of: date
    providers: Providers
    started: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    excluded: dict[str, dict[str, str]] = field(default_factory=lambda: {b.key: {} for b in spec.BANDS})
    budget_hit: set[str] = field(default_factory=set)
    limit: int | None = None
    quotes: dict = field(default_factory=dict)
    histories: dict = field(default_factory=dict)
    facts: dict = field(default_factory=dict)

    def exclude(self, band: str, ticker: str, reason: str) -> None:
        self.excluded[band].setdefault(ticker, reason)


# --- fetch helpers (errors become reasons, never crashes) --------------------------------------

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
        return None, f"data unavailable ({exc})"


def latest_bars(ctx: Context, symbol: str) -> tuple[pd.DataFrame | None, str | None, list[str]]:
    """Validated daily bars ending exactly on the as-of session, or a reason."""
    if symbol in ctx.histories:
        return ctx.histories[symbol]
    flags: list[str] = []
    df, why = _guard(ctx, "cboe", ctx.providers.history, symbol)
    if df is None:
        ctx.histories[symbol] = (None, why, flags)
        return ctx.histories[symbol]
    if df.attrs.get("repaired_recent", 0) > 2:
        flags.append(f"{df.attrs['repaired_recent']} price bars in the last year had an open/close outside the "
                     "day's range and were repaired")
    df = df[df.index <= pd.Timestamp(ctx.as_of)]
    if not df.empty and df.index[-1].date() < ctx.as_of:
        # the history file can lag the close by a day; the end-of-session quote fills the as-of bar
        q, _ = _quote(ctx, symbol)
        if q is not None and q.last_trade and q.last_trade.date() == ctx.as_of and q.close:
            prev = float(df["close"].iloc[-1])
            row = pd.DataFrame({"open": [q.close], "high": [max(q.close, prev)], "low": [min(q.close, prev)],
                                "close": [q.close], "volume": [float(df["volume"].iloc[-20:].median())]},
                               index=pd.DatetimeIndex([pd.Timestamp(ctx.as_of)]))
            df = pd.concat([df, row])
            flags.append("as-of close taken from the end-of-session quote (history file lagged)")
    try:
        df, trimmed = trim_bad_history(df, symbol)     # an old glitch drops older history, a recent one rejects
        if trimmed:
            flags.append(trimmed)
        df = validate_bars(df, symbol, ctx.as_of, spec.MAX_PRICE_LAG_BUSINESS_DAYS, 60)
    except DataQualityError as exc:
        ctx.histories[symbol] = (None, f"price data rejected: {exc}", flags)
        return ctx.histories[symbol]
    ctx.histories[symbol] = (df, None, flags)
    return ctx.histories[symbol]


def _quote(ctx: Context, symbol: str):
    if symbol not in ctx.quotes:
        ctx.quotes[symbol] = _guard(ctx, "cboe", ctx.providers.quote, symbol)
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
        ctx.facts[cik] = (build_fundamentals(raw, ctx.as_of), None)
    return ctx.facts[cik]


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


# --- universes ---------------------------------------------------------------------------------

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
                rows.append({"ticker": t, "cik": cik, "name": d["name"], "exchange": d["exchange"],
                             "frame_shares": frames[cik][0], "frame_end": frames[cik][1]})
        if why:
            reasons[why] = reasons.get(why, 0) + 1
    return pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame(), reasons


# --- scoring a band ------------------------------------------------------------------------------

def evaluate(ctx: Context, band: spec.Band, tickers: list[tuple[str, int, str, str]],
             bench: pd.Series) -> list[dict]:
    """Score each (ticker, cik, name, sector) for `band`; exclusions are recorded on ctx."""
    out = []
    for t, cik, name, sector in tickers:
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
            ctx.exclude(band.key, t, f"illiquid: 20-day median dollar volume ${dv / 1e6:.1f}M "
                                     f"< ${band.min_dollar_volume / 1e6:g}M")
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
        if band.min_revenue_growth is not None and (m["revenue_growth_ttm"] is None
                                                    or m["revenue_growth_ttm"] < band.min_revenue_growth):
            g = m["revenue_growth_ttm"]
            ctx.exclude(band.key, t, "revenue growth " + ("unavailable" if g is None else f"{g:.0%}") +
                        f" below the {band.min_revenue_growth:.0%} speculative-band gate")
            continue
        flags = flags + cap_flags + pflags
        s = scoring.score_one(t, m, f, flags)
        if s.excluded_reason:
            ctx.exclude(band.key, t, s.excluded_reason)
        out.append({"ticker": t, "cik": cik, "name": name, "sector": sector, "score": s, "metrics": m,
                    "fundamentals": f, "bars": df, "close": close, "dollar_volume": dv})
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
            ctx.exclude(band.key, r["ticker"], f"another share class of the same company is evaluated instead "
                                               f"({winner['ticker']}, more liquid)")
    return keep


def _clean(x):
    if isinstance(x, float):
        return None if not math.isfinite(x) else x
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return _clean(x.item())
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    return x


def candidate_detail(ctx: Context, band: spec.Band, row: dict, bench: pd.Series, earnings: dict) -> dict:
    s: scoring.Score = row["score"]
    m, f, df = row["metrics"], row["fundamentals"], row["bars"]
    hist = scenarios.history_stats(df["close"], bench)
    scen = None
    scen_note = None
    try:
        if m["ev_to_sales"] and m["revenue_growth_ttm"] is not None and m["revenue_ttm"]:
            shares = m["market_cap"] / row["close"]
            scen = scenarios.scenario_table(row["close"], shares, m["revenue_ttm"], m["revenue_growth_ttm"],
                                            m["ev_to_sales"], -(m["net_debt"] or 0.0), m.get("fcf_margin"),
                                            m.get("dilution"))
        else:
            scen_note = "Scenarios not computed: revenue, growth or EV/Sales unavailable."
    except ValueError as exc:
        scen_note = f"Scenarios not computed: {exc}"
    q = f.quarters
    fundamentals_table = {
        "quarters": q[:8],
        **{k: f.flows[k][:8] for k in ("revenue", "gross_profit", "operating_income", "net_income", "ocf", "capex",
                                         "sbc")},
        "derived_revenue": f.derived["revenue"][:8],
        "diluted_shares": f.diluted_shares[:8],
        "balance_sheet": f.instants, "last_filed": f.last_filed, "last_form": f.last_form,
        "cover_shares": f.cover_shares, "cover_shares_date": f.cover_shares_date,
    }
    next_earn = earnings.get(row["ticker"])
    return _clean({
        "ticker": row["ticker"], "name": row["name"], "sector": row["sector"], "band": band.key, "rank": s.rank,
        "price": row["close"], "price_date": ctx.as_of, "market_cap": m["market_cap"], "cik": row["cik"],
        "sources": {"price": SOURCES["cboe"], "fundamentals": SOURCES["sec"]},
        "data_timestamp": ctx.started, "composite": s.composite, "components": s.components,
        "sub_scores": s.sub_scores, "metrics": m, "missing": s.missing, "confidence": s.confidence,
        "confidence_label": s.confidence_label, "flags": s.flags, "counterargument": s.counterargument,
        "thesis": scenarios.thesis(m, s.components), "bear_case": scenarios.bear_case(m, s.counterargument),
        "risks": scenarios.key_risks(m, s.flags, hist, f.concentration), "invalidation": scenarios.invalidation(m, scen),
        "history": hist, "chart": scenarios.chart_series(df["close"], bench), "benchmark": band.benchmark,
        "scenarios": scen, "scenario_note": scen_note, "fundamentals": fundamentals_table,
        "next_earnings": next_earn, "not_scored": spec.NOT_SCORED_FACTORS, "dollar_volume": row["dollar_volume"],
        "probability": spec.PROBABILITY_STATEMENT,
    })


def concentration_warnings(cands: list[dict]) -> list[str]:
    out = []
    if not cands:
        return out
    sectors = pd.Series([c["sector"] for c in cands]).value_counts()
    top, n = sectors.index[0], int(sectors.iloc[0])
    if n / len(cands) > 0.4:
        out.append(f"{n} of {len(cands)} candidates are in {top}: the list is concentrated in one sector.")
    rets = pd.DataFrame({c["ticker"]: c["bars"]["close"].pct_change().iloc[-252:] for c in cands}).dropna(how="all")
    if rets.shape[1] >= 3:
        corr = rets.corr().to_numpy()
        avg = float(corr[np.triu_indices_from(corr, 1)].mean())
        if avg > 0.6:
            out.append(f"Average pairwise correlation of daily returns is {avg:.2f}: the candidates tend to move "
                       "together, so they diversify each other little.")
    return out


def rank_changes(current: list[dict], previous: list[dict] | None) -> list[dict]:
    """Per-ticker movement vs the previous snapshot, explained by component-score changes."""
    if previous is None:
        return [{"ticker": c["ticker"], "change": "new (first snapshot)", "explanation": ""} for c in current]
    prev = {p["ticker"]: p for p in previous}
    out = []
    for c in current:
        p = prev.get(c["ticker"])
        if p is None:
            out.append({"ticker": c["ticker"], "change": "new", "from": None, "to": c["rank"],
                        "explanation": "entered the top list this week"})
            continue
        deltas = {k: (c["components"].get(k) or 0) - (p["components"].get(k) or 0) for k in c["components"]}
        top = sorted(deltas.items(), key=lambda kv: -abs(kv[1]))[:2]
        expl = ", ".join(f"{k} {v * 100:+.1f}" for k, v in top if abs(v) >= 0.005) or "component scores unchanged"
        out.append({"ticker": c["ticker"], "change": p["rank"] - c["rank"], "from": p["rank"], "to": c["rank"],
                    "explanation": f"component score changes (points of 100): {expl}"})
    for t, p in prev.items():
        if t not in {c["ticker"] for c in current}:
            out.append({"ticker": t, "change": "dropped", "from": p["rank"], "to": None,
                        "explanation": "no longer in the top list (lower score, excluded or out of band)"})
    return out


# --- the run ---------------------------------------------------------------------------------------

def run(providers: Providers, as_of: date, previous: dict | None = None, options_enabled: bool = True,
        limit: int | None = None) -> dict:
    """Produce the snapshot payload. Raises RunFailed when the result would not be trustworthy."""
    if not is_trading_day(as_of):
        raise RunFailed(f"{as_of} is not an NYSE trading day")
    ctx = Context(as_of, providers, limit=limit)
    ref = build_reference(ctx)

    bench = {}
    for b in BENCHMARKS:
        df, why, _ = latest_bars(ctx, b)
        if df is None:
            raise RunFailed(f"benchmark {b} unavailable: {why}")
        bench[b] = df["close"]

    earnings, earn_note = {}, None
    cal, why = _guard(ctx, "alphavantage", providers.earnings_calendar)
    if cal is None:
        earn_note = f"Earnings dates unavailable: {why}"
    else:
        for sym, grp in cal.groupby("symbol"):
            future = sorted(d for d in grp["reportDate"] if d > as_of)
            if future:
                earnings[sym] = future[0].isoformat()

    sp = ref["sp500"]
    sec = ref["sec"]
    sp_list = []
    for t, r in sp.iterrows():
        cik = int(r["cik"]) if pd.notna(r.get("cik")) else (int(sec.loc[t, "cik"]) if t in sec.index else None)
        if cik is None:
            ctx.exclude("large", t, "no CIK for this S&P 500 member")
            continue
        sp_list.append((t, cik, r.get("name", t), r.get("sector", "Unknown")))
    if limit:
        sp_list = sp_list[:limit]

    broad, broad_reasons = broad_universe(ctx, ref)
    lo = min(b.min_cap for b in spec.BANDS if b.universe == "broad")
    hi = max(b.max_cap for b in spec.BANDS if b.universe == "broad")
    prelim = []
    for t, r in broad.iterrows():
        q, why = _quote(ctx, t)
        if q is None or not q.close:
            broad_reasons[why or "no quote"] = broad_reasons.get(why or "no quote", 0) + 1
            continue
        if q.last_trade is None or q.last_trade.date() != as_of:
            broad_reasons["stale quote (no trade in the as-of session)"] = \
                broad_reasons.get("stale quote (no trade in the as-of session)", 0) + 1
            continue
        cap = q.close * r["frame_shares"]
        if 0.8 * lo <= cap < 1.25 * hi:      # buffer: the final band test uses point-in-time XBRL shares
            prelim.append((t, int(r["cik"]), r["name"], None))
        else:
            k = "outside the $300M-$10B pre-screen (cover-page shares x close)"
            broad_reasons[k] = broad_reasons.get(k, 0) + 1
        if limit and len(prelim) >= limit:
            break

    results, payload_bands = {}, {}
    for band in spec.BANDS:
        if band.universe == "sp500":
            rows = evaluate(ctx, band, sp_list, bench[band.benchmark])
        else:
            sp_set = set(sp.index)
            rows = evaluate(ctx, band, [p for p in prelim], bench[band.benchmark])
            for r in rows:
                if r["ticker"] in sp_set:
                    r["sector"] = sp.loc[r["ticker"], "sector"]
        ranked = scoring.rank([r["score"] for r in rows])
        by_t = {r["ticker"]: r for r in rows}
        top = [by_t[s.ticker] for s in ranked[: band.max_results]]
        for r in top + [by_t[s.ticker] for s in ranked[band.max_results: band.max_results + 10]]:
            if r["sector"] is None:
                sub, _ = _guard(ctx, "sec", providers.submissions, r["cik"])
                r["sector"] = sector_from_sic(sub.get("sic")) if sub else "Unknown"
        results[band.key] = (rows, ranked, top)
        details = [candidate_detail(ctx, band, r, bench[band.benchmark], earnings) for r in top]
        prev_band = None
        if previous:
            prev_band = [{"ticker": c["ticker"], "rank": c["rank"], "components": c["components"]}
                         for c in previous.get("bands", {}).get(band.key, {}).get("candidates", [])]
        payload_bands[band.key] = {
            "title": band.title, "benchmark": band.benchmark, "benchmark_name": band.benchmark_name,
            "max_results": band.max_results, "candidates": details,
            "shortfall_note": None if len(top) >= band.max_results else
            f"Only {len(top)} stocks met every rule; the list is not padded to {band.max_results}.",
            "runners_up": [{"ticker": s.ticker, "rank": s.rank, "composite": s.composite,
                            "confidence": s.confidence_label} for s in ranked[band.max_results: band.max_results + 10]],
            "excluded": [{"ticker": t, "reason": why} for t, why in sorted(ctx.excluded[band.key].items())],
            "evaluated": len(rows), "ranked": len(ranked),
            "concentration": concentration_warnings(top),
            "rank_changes": rank_changes([{"ticker": d["ticker"], "rank": d["rank"], "components": d["components"]}
                                          for d in details], prev_band),
        }

    sp_ok = sum(1 for t, *_ in sp_list if ctx.histories.get(t, (None,))[0] is not None)
    coverage = sp_ok / max(1, len(sp_list))
    if coverage < MIN_SP500_COVERAGE and not limit:
        raise RunFailed(f"only {coverage:.0%} of S&P 500 members had a valid as-of price "
                        f"(need {MIN_SP500_COVERAGE:.0%}); not publishing a partial ranking")

    options_payload = {"enabled": options_enabled, "status": "disabled in configuration"}
    if options_enabled:
        chains = {}
        for c in payload_bands["large"]["candidates"]:
            ch, why = _guard(ctx, "cboe", providers.option_chain, c["ticker"])
            chains[c["ticker"]] = ch if ch is not None else why
        ev = {t: [{"date": date.fromisoformat(d), "event": "earnings (scheduled, unverified)"}]
              for t, d in earnings.items()}
        options_payload = _clean({"enabled": True, **opt.build_horizons(chains, as_of, ev),
                                  "earnings_note": earn_note, "delta_statement": spec.DELTA_STATEMENT,
                                  "underlying_rule": spec.OPTION_UNDERLYINGS, "status": "ok"})

    status = "ok" if not ctx.problems and not ctx.budget_hit else "partial"
    return _clean({
        "as_of": as_of, "run_started": ctx.started,
        "run_finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": status, "problems": ctx.problems, "notes": ctx.notes + ([earn_note] if earn_note else []),
        "spec_version": spec.SPEC_VERSION, "spec_hash": spec.spec_hash(),
        "sources": SOURCES, "usage": providers.http.usage(),
        "universe": {
            "sp500_members": sorted(sp.index), "sp500_count": len(sp), "sp500_price_coverage": coverage,
            "broad_eligible": len(broad), "broad_prescreen": len(prelim), "broad_exclusion_counts": broad_reasons,
            "definitions": {"universe": spec.UNIVERSE_DEFINITION, "market_cap": spec.MARKET_CAP_DEFINITION},
        },
        "benchmarks": {b: {"close": float(s.iloc[-1]), "date": as_of} for b, s in bench.items()},
        "bands": payload_bands, "options": options_payload,
        "disclaimer": spec.DISCLAIMER, "multibagger": spec.MULTIBAGGER_DEFINITION,
        "probability": spec.PROBABILITY_STATEMENT,
    })
