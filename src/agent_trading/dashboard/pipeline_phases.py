"""Ordered weekly collection/scoring phases; no change to requests, rules or serialization."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from . import ai as ai_mod
from . import options as opt
from . import scoring, spec
from .earnings_cadence import event_eligible
from .earnings_cadence import validate as validate_earnings
from .pipeline_collect import _guard, _quote, broad_universe, latest_bars, verify_earnings
from .pipeline_context import BENCHMARKS, Context, RunFailed, log
from .pipeline_details import _clean, candidate_detail, concentration_warnings, rank_changes
from .pipeline_score import evaluate, tradable_only
from .providers import SOURCES, sector_from_sic
from .tradability import Tradability


def collect_benchmarks(ctx: Context) -> dict[str, pd.Series]:
    bench = {}
    for b in BENCHMARKS:
        df, why, _ = latest_bars(ctx, b)
        if df is None:
            raise RunFailed(f"benchmark {b} unavailable: {why}")
        bench[b] = df["close"]
    return bench


def collect_earnings(ctx: Context) -> tuple[dict[str, str], str | None, dict, pd.DataFrame | None]:
    providers, as_of = ctx.providers, ctx.as_of
    earnings, earn_note = {}, None
    cal, why = _guard(ctx, "alphavantage", providers.earnings_calendar)
    # spec 2026-10-14.5: a failed or unconfigured lookup is never shown as "no earnings scheduled"
    earn_status = {"status": "ok", "state": "available", "calendar_rows": 0, "retrieved_at": ctx.started}
    if cal is None:
        earn_note = f"Earnings dates unavailable: {why}"
        ctx.earnings_reason = earn_note
        earn_status = {
            "status": "unavailable",
            "retrieved_at": ctx.started,
            "reason": why,
            "state": "missing" if "not configured" in str(why) else "provider_error",
        }
    else:
        earn_status["calendar_rows"] = int(len(cal))
        for sym, grp in cal.groupby("symbol"):
            future = sorted(d for d in grp["reportDate"] if d > as_of)
            if future:
                earnings[sym] = future[0].isoformat()
    return earnings, earn_note, earn_status, cal


def prescreen_universes(ctx: Context, ref: dict) -> tuple[pd.DataFrame, pd.DataFrame, list, pd.DataFrame, dict, list]:
    as_of, limit = ctx.as_of, ctx.limit
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
    log.info(
        "reference data: %d S&P 500 members, %d listings, %d eligible broad-universe stocks",
        len(sp),
        len(ref["dirs"]),
        len(broad),
    )
    lower: list[float] = []
    upper: list[float] = []
    for band in spec.BANDS:
        if band.universe in ("broad", "all"):
            assert band.min_cap is not None and band.max_cap is not None
            lower.append(band.min_cap)
            upper.append(band.max_cap)
    lo, hi = min(lower), max(upper)
    prelim: list[tuple[str, int, str, str | None]] = []
    for n, (t, r) in enumerate(broad.iterrows(), 1):
        if n % 500 == 0:
            log.info("broad pre-screen: %d of %d quoted, %d in range", n, len(broad), len(prelim))
        q, why = _quote(ctx, t)
        if q is None or not q.close:
            broad_reasons[why or "no quote"] = broad_reasons.get(why or "no quote", 0) + 1
            continue
        if q.last_trade is None or q.last_trade.date() != as_of:
            broad_reasons["stale quote (no trade in the as-of session)"] = (
                broad_reasons.get("stale quote (no trade in the as-of session)", 0) + 1
            )
            continue
        cap = q.close * r["frame_shares"]
        if 0.8 * lo <= cap < 1.25 * hi:  # buffer: the final band test uses point-in-time XBRL shares
            prelim.append((t, int(r["cik"]), r["name"], None))
        else:
            k = f"outside the ${lo / 1e6:,.0f}M-${hi / 1e9:,.0f}B pre-screen (cover-page shares x close)"
            broad_reasons[k] = broad_reasons.get(k, 0) + 1
        if limit and len(prelim) >= limit:
            break
    return sp, sec, sp_list, broad, broad_reasons, prelim


def score_bands(
    ctx: Context,
    ref: dict,
    sp: pd.DataFrame,
    sec: pd.DataFrame,
    sp_list: list,
    prelim: list,
    bench: dict,
    previous: dict | None,
    trad: Tradability,
    todo: list,
    earnings: dict,
) -> tuple[dict, list, dict, dict, dict]:
    providers, limit = ctx.providers, ctx.limit
    # spec 2026-10-14.7: the AI-exposed universe is a fixed list; names that cannot be evaluated keep their reason
    ai_pool: list[tuple[str, int, str, str | None]] = []
    ai_rejects: dict[str, str] = {}
    ladder = ai_mod.size_ladder({})
    if any(b.universe == "ai" for b in spec.BANDS):
        ai_pool, ai_rejects = ai_mod.resolve_universe(sec, ref["dirs"], sp)
        if limit:
            ai_pool = ai_pool[:limit]
    roles = ai_mod.roles()

    payload_bands = {}
    for band in spec.BANDS:
        if band.universe == "sp500":
            rows = evaluate(ctx, band, sp_list, bench[band.benchmark])
            # today's size ladder (top-20 market-cap bar) from the S&P 500 members evaluated in this run
            ladder = ai_mod.size_ladder({r["ticker"]: r["metrics"].get("market_cap") for r in rows})
        elif band.universe == "ai":
            for t, why in ai_rejects.items():
                ctx.exclude(band.key, t, why)
            rows = evaluate(ctx, band, ai_pool, bench[band.benchmark])
        else:
            sp_set = set(sp.index)
            pool = list(prelim)
            if band.universe == "all":
                pool = sp_list + [p for p in pool if p[0] not in {s[0] for s in sp_list}]
            rows = evaluate(ctx, band, pool, bench[band.benchmark])
            for r in rows:
                if r["ticker"] in sp_set:
                    r["sector"] = sp.loc[r["ticker"], "sector"]
        ranked = tradable_only(ctx, band, scoring.rank([r["score"] for r in rows]), trad, todo)
        by_t = {r["ticker"]: r for r in rows}
        for r in [by_t[s.ticker] for s in ranked]:
            if r["sector"] is None:
                sub, _ = _guard(ctx, "sec", providers.submissions, r["cik"])
                r["sector"] = sector_from_sic(sub.get("sic")) if sub else "Unknown"
        from .sector_balance import sector_penalty

        ranked = sector_penalty(ranked, {t: r["sector"] for t, r in by_t.items()}, band.max_results)
        for s in ranked:
            by_t[s.ticker]["score"] = s
        top = [by_t[s.ticker] for s in ranked[: band.max_results]]
        details = [candidate_detail(ctx, band, r, bench[band.benchmark], earnings) for r in top]
        from .decisions import add_percentiles

        add_percentiles(details)
        if band.universe == "ai":
            for d in details:
                d["ai_role"] = roles.get(d["ticker"])
                d["top20_test"] = ai_mod.top20_test(d, ladder)
        prev_band = None
        if previous:
            prev_band = [
                {
                    "ticker": c["ticker"],
                    "rank": c["rank"],
                    "components": c["components"],
                    "composite": c.get("composite"),
                }
                for c in previous.get("bands", {}).get(band.key, {}).get("candidates", [])
            ]
        payload_bands[band.key] = {
            "title": band.title,
            "benchmark": band.benchmark,
            "benchmark_name": band.benchmark_name,
            "profile": band.profile,
            "components": [c.key for c in spec.PROFILES[band.profile]],
            "gates": [list(g) for g in band.gates],
            "scenario_years": list(band.scenario_years),
            "max_results": band.max_results,
            "candidates": details,
            "short_title": spec.BAND_TITLES_SHORT.get(band.key),
            "definition": {
                "universe": band.universe,
                "min_cap": band.min_cap,
                "max_cap": band.max_cap,
                "min_price": band.min_price,
                "min_dollar_volume": band.min_dollar_volume,
            },
            "shortfall_note": None
            if len(top) >= band.max_results
            else f"Only {len(top)} stocks met every rule; the list is not padded to {band.max_results}.",
            "runners_up": [
                {"ticker": s.ticker, "rank": s.rank, "composite": s.composite, "confidence": s.confidence_label}
                for s in ranked[band.max_results : band.max_results + 10]
            ],
            "excluded": [{"ticker": t, "reason": why} for t, why in sorted(ctx.excluded[band.key].items())],
            "evaluated": len(rows),
            "ranked": len(ranked),
            "concentration": concentration_warnings(top),
            "rank_changes": rank_changes(
                [
                    {
                        "ticker": d["ticker"],
                        "rank": d["rank"],
                        "components": d["components"],
                        "composite": d.get("composite"),
                    }
                    for d in details
                ],
                prev_band,
            ),
        }
    return payload_bands, ai_pool, ai_rejects, roles, ladder


def collect_derivatives(
    ctx: Context,
    payload_bands: dict,
    earnings: dict,
    cal: pd.DataFrame | None,
    options_enabled: bool,
    iv_history: dict | None,
    earn_note: str | None,
) -> tuple[dict | None, dict]:
    from . import speculative

    providers, as_of = ctx.providers, ctx.as_of
    speculative_payload = None
    options_payload = {"enabled": options_enabled, "status": "disabled in configuration"}
    if options_enabled:
        chains: dict[str, tuple[dict, list[dict]] | str] = {}
        large_tickers = {c["ticker"] for c in payload_bands["large"]["candidates"]}
        focus = speculative.targets({"bands": payload_bands})
        for ticker in sorted(large_tickers | set(focus)):
            checks = [
                c.get("earnings_check")
                for b in payload_bands.values()
                for c in b["candidates"]
                if c["ticker"] == ticker
            ]
            if any(not event_eligible(check) for check in checks if check and check.get("next_scheduled")):
                chains[ticker] = "Review Required: earnings date excluded from automated event research"
                continue
            ch, why = _guard(ctx, "cboe", providers.option_chain, ticker)
            chains[ticker] = ch if ch is not None else (why or "option chain unavailable")
        ev = {
            t: [{"date": date.fromisoformat(d), "event": "earnings (scheduled, unverified)"}]
            for t, d in earnings.items()
        }
        # spec 2026-10-14.6: without a collected calendar every contract's earnings status is 'unknown'
        speculative_payload = speculative.build(
            {t: chains[t] for t in focus}, as_of, ev, iv_history, events_known=cal is not None
        )
        options_payload = _clean(
            {
                "enabled": True,
                **opt.build_horizons(
                    {t: ch for t, ch in chains.items() if t in large_tickers}, as_of, ev, events_known=cal is not None
                ),
                "earnings_note": earn_note,
                "delta_statement": spec.DELTA_STATEMENT,
                "underlying_rule": spec.OPTION_UNDERLYINGS,
                "status": "ok",
                "premium_assumption": spec.PREMIUM_ASSUMPTION,
                "ranking_note": spec.OPTION_RANKING_NOTE,
                "collected_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "source": SOURCES["cboe"],
            }
        )
    return speculative_payload, options_payload


def collect_events(ctx: Context, payload_bands: dict, watch_payload: dict, earnings: dict) -> list[dict]:
    as_of = ctx.as_of

    def check(c: dict, scheduled: str | None) -> dict:
        key = (c.get("cik"), scheduled)
        if key not in ctx.earnings_checks:
            ctx.earnings_checks[key] = _clean(verify_earnings(ctx, key[0], scheduled))
        record = dict(ctx.earnings_checks[key])
        prior = ctx.prior_earnings_checks.get(c["ticker"], {})
        if prior.get("outlier") and prior.get("next_scheduled") == scheduled:
            record["latest_cadence_estimate"] = record.get("expected_date")
            record["expected_date"] = prior.get("expected_date")
            record["cadence_check"] = prior.get("cadence_check")
        verdicts = ctx.earnings_verdicts
        manual = verdicts.check(c["ticker"], scheduled, as_of) if verdicts and scheduled else None
        record.update(validate_earnings(scheduled, record.get("expected_date"), as_of, manual))
        return record

    for _key, b in payload_bands.items():
        for c in b["candidates"]:
            c["earnings_check"] = check(c, c.get("next_earnings"))
    for e in watch_payload.get("entries", []):
        if (e.get("asset_type") or "").startswith("operating company"):
            e["earnings_check"] = check(e, earnings.get(e["ticker"]))
    upcoming = []
    horizon_end = as_of + timedelta(days=45)
    seen_events: dict[tuple[str, str], dict] = {}
    for key, b in payload_bands.items():
        for c in b["candidates"]:
            if (
                c.get("next_earnings")
                and event_eligible(c.get("earnings_check"))
                and as_of.isoformat() < c["next_earnings"] <= horizon_end.isoformat()
            ):
                ev_key = (c["ticker"], c["next_earnings"])
                if ev_key in seen_events:  # a stock on two lists (for example large and AI large) is listed once
                    seen_events[ev_key]["list"] += f", {key}"
                    continue
                ec = c.get("earnings_check") or {}
                seen_events[ev_key] = {
                    "ticker": c["ticker"],
                    "date": c["next_earnings"],
                    "list": key,
                    "event": "earnings (scheduled; Alpha Vantage; not independently verified)",
                    "last_results": ec.get("last_results"),
                    "last_results_status": ec.get("last_results_status"),
                    "cadence_check": ec.get("cadence_check"),
                }
                upcoming.append(seen_events[ev_key])
    for e in watch_payload.get("entries", []):
        d = earnings.get(e["ticker"])
        if d and event_eligible(e.get("earnings_check")) and as_of.isoformat() < d <= horizon_end.isoformat():
            upcoming.append(
                {
                    "ticker": e["ticker"],
                    "date": d,
                    "list": "watchlist",
                    "event": "earnings (scheduled; Alpha Vantage; not independently verified)",
                }
            )
    upcoming.sort(key=lambda x: (x["date"], x["ticker"]))
    return upcoming


def ai_context(
    ctx: Context, ai_pool: list, ai_rejects: dict, roles: dict, ladder: dict, ai_private: dict | None
) -> dict | None:
    ai_payload = None
    if any(b.universe == "ai" for b in spec.BANDS):
        try:
            private = ai_private if ai_private is not None else ai_mod.load_private()
        except (ai_mod.PrivateConfigError, ValueError, OSError) as exc:  # never crash the run over context data
            private = {"reviewed_on": None, "note": None, "companies": []}
            ctx.problems.append(f"the private-company file was rejected and no private companies are shown: {exc}")
        ai_payload = {
            "definition": spec.AI_UNIVERSE_DEFINITION,
            "top20_rule": spec.AI_TOP20_RULE,
            "private_rule": spec.AI_PRIVATE_RULE,
            "probability_note": spec.AI_PROBABILITY_NOTE,
            "universe": {
                "defined": len(spec.AI_UNIVERSE),
                "resolved": len(ai_pool),
                "unresolved": ai_rejects,
                "roles": roles,
            },
            "ladder": ladder,
            "private": private,
        }
    return ai_payload
