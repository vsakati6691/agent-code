"""Orchestrate weekly collection and scoring, then assemble the immutable snapshot payload."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd

from ..market_calendar import is_trading_day
from . import ai as ai_mod
from . import options as opt
from . import scoring, spec
from .pipeline_collect import _guard, _quote, broad_universe, build_reference, latest_bars, verify_earnings
from .pipeline_context import BENCHMARKS, MIN_SP500_COVERAGE, Context, RunFailed, as_of_for, log
from .pipeline_details import _clean, candidate_detail, concentration_warnings, rank_changes
from .pipeline_score import evaluate, tradable_only
from .pipeline_watchlist import evaluate_watchlist
from .providers import SOURCES, Providers, sector_from_sic
from .tradability import Tradability
from .watchlist import WatchlistConfig


def run(
    providers: Providers,
    as_of: date,
    previous: dict | None = None,
    options_enabled: bool = True,
    limit: int | None = None,
    tradability: Tradability | None = None,
    todo_out: list | None = None,
    watchlist: WatchlistConfig | None = None,
    ai_private: dict | None = None,
    iv_history: dict | None = None,
    aggregate_store=None,
    now: datetime | None = None,
) -> dict:
    """Produce the snapshot payload. Raises RunFailed when the result would not be trustworthy.

    `tradability`: stored Robinhood verdicts (None = none stored: nothing can be published).
    `todo_out`: filled with the symbols that need a Robinhood check, even when the run fails.
    `ai_private`: validated private-company records for the AI page (None = read config/ai_private_companies.json)."""
    trad = tradability or Tradability()
    todo = todo_out if todo_out is not None else []
    if not is_trading_day(as_of):
        raise RunFailed(f"{as_of} is not an NYSE trading day")
    started = now or datetime.now(UTC)
    if as_of > as_of_for(started):
        raise RunFailed(f"{as_of}: as-of close is not yet available under the completed-session collection clock")
    ctx = Context(as_of, providers, started=started.isoformat(timespec="seconds"), limit=limit)
    ref = build_reference(ctx)

    bench = {}
    for b in BENCHMARKS:
        df, why, _ = latest_bars(ctx, b)
        if df is None:
            raise RunFailed(f"benchmark {b} unavailable: {why}")
        bench[b] = df["close"]

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
    lo = min(b.min_cap for b in spec.BANDS if b.universe in ("broad", "all"))
    hi = max(b.max_cap for b in spec.BANDS if b.universe in ("broad", "all"))
    prelim = []
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

    # spec 2026-10-14.7: the AI-exposed universe is a fixed list; names that cannot be evaluated keep their reason
    ai_pool, ai_rejects, ladder = [], {}, ai_mod.size_ladder({})
    if any(b.universe == "ai" for b in spec.BANDS):
        ai_pool, ai_rejects = ai_mod.resolve_universe(sec, ref["dirs"], sp)
        if limit:
            ai_pool = ai_pool[:limit]
    roles = ai_mod.roles()

    results, payload_bands = {}, {}
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
        top = [by_t[s.ticker] for s in ranked[: band.max_results]]
        for r in top + [by_t[s.ticker] for s in ranked[band.max_results : band.max_results + 10]]:
            if r["sector"] is None:
                sub, _ = _guard(ctx, "sec", providers.submissions, r["cik"])
                r["sector"] = sector_from_sic(sub.get("sic")) if sub else "Unknown"
        results[band.key] = (rows, ranked, top)
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

    sp_ok = sum(1 for t, *_ in sp_list if ctx.histories.get(t, (None,))[0] is not None)
    coverage = sp_ok / max(1, len(sp_list))
    if coverage < MIN_SP500_COVERAGE and not limit:
        raise RunFailed(
            f"only {coverage:.0%} of S&P 500 members had a valid as-of price "
            f"(need {MIN_SP500_COVERAGE:.0%}); not publishing a partial ranking"
        )

    if not any(b["candidates"] for b in payload_bands.values()) and not any(
        v.get("tradable") for v in trad.symbols.values()
    ):
        raise RunFailed(
            "no Robinhood tradability verdicts are stored, so no stock can be published; check the "
            f"{len(todo)} symbols on the to-check list with a read-only Claude session"
        )

    from . import macro, pipeline_external, speculative

    external_enabled = hasattr(providers, "fred_key") and hasattr(providers.http, "budget_group")
    macro_payload = macro.collect(providers, as_of) if external_enabled else None

    speculative_payload = None
    options_payload = {"enabled": options_enabled, "status": "disabled in configuration"}
    if options_enabled:
        chains = {}
        large_tickers = {c["ticker"] for c in payload_bands["large"]["candidates"]}
        focus = speculative.targets({"bands": payload_bands})
        for ticker in sorted(large_tickers | set(focus)):
            ch, why = _guard(ctx, "cboe", providers.option_chain, ticker)
            chains[ticker] = ch if ch is not None else why
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

    watch_payload = {"status": "no watchlist configured", "entries": []}
    if watchlist is not None:
        watch_payload = evaluate_watchlist(ctx, ref, watchlist, earnings)
    external_status = (
        pipeline_external.collect(ctx, payload_bands, watch_payload, previous, aggregate_store)
        if external_enabled
        else {}
    )
    if external_enabled:
        rate = macro.rate_input(macro_payload)
        opt.apply_dated_rate(options_payload, rate)
        opt.apply_dated_rate(speculative_payload, rate)
        options_payload["rate_input"] = rate
        for name, dataset in external_status.items():
            if dataset["state"] != "available":
                ctx.problems.append(
                    f"{name}: {dataset['state']}; {dataset['available']}/{dataset['requested']} available; {dataset['deferred']} deferred"
                )
        if macro_payload["state"] != "available":
            ctx.problems.append(f"macro: {macro_payload['state']}; see per-series reasons")
    for _key, b in payload_bands.items():
        for c in b["candidates"]:
            c["earnings_check"] = _clean(verify_earnings(ctx, c.get("cik"), c.get("next_earnings")))
    for e in watch_payload.get("entries", []):
        if (e.get("asset_type") or "").startswith("operating company"):
            e["earnings_check"] = _clean(verify_earnings(ctx, e.get("cik"), earnings.get(e["ticker"])))
    upcoming = []
    horizon_end = as_of + timedelta(days=45)
    seen_events: dict[tuple[str, str], dict] = {}
    for key, b in payload_bands.items():
        for c in b["candidates"]:
            if c.get("next_earnings") and c["next_earnings"] <= horizon_end.isoformat():
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
        if d and d <= horizon_end.isoformat():
            upcoming.append(
                {
                    "ticker": e["ticker"],
                    "date": d,
                    "list": "watchlist",
                    "event": "earnings (scheduled; Alpha Vantage; not independently verified)",
                }
            )
    upcoming.sort(key=lambda x: (x["date"], x["ticker"]))

    if ctx.transient_failures:
        ctx.problems.append(
            f"{ctx.transient_failures} request(s) still failed after retries (rate limits or server "
            "errors); the affected stocks are listed as excluded with that reason"
        )
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
    status = "ok" if not ctx.problems and not ctx.budget_hit else "partial"
    from . import leaders
    from .pipeline_leaders import retained_inputs

    leader_inputs = retained_inputs(ctx, ref)
    leader_payload = leaders.build(
        {
            "as_of": as_of.isoformat(),
            "spec_version": spec.SPEC_VERSION,
            "universe": {"sp500_members": sorted(sp.index)},
            "leaders_2030_inputs": leader_inputs,
        },
        leaders.load_challengers(),
    )
    return _clean(
        {
            "as_of": as_of,
            "run_started": ctx.started,
            "run_finished": datetime.now(UTC).isoformat(timespec="seconds"),
            "status": status,
            "problems": ctx.problems,
            "notes": ctx.notes + ([earn_note] if earn_note else []),
            "spec_version": spec.SPEC_VERSION,
            "spec_hash": spec.spec_hash(),
            "sources": SOURCES,
            "usage": providers.http.usage(),
            "external_datasets": external_status,
            "macro": macro_payload,
            "tradability": {
                "rule": spec.TRADABILITY_RULE,
                "verdicts_stored": len(trad.symbols),
                "to_check": len(todo),
                "source": "Robinhood MCP get_equity_tradability (read-only)",
                "oldest_check": min((v.get("checked_at", "") for v in trad.symbols.values()), default=None),
                "newest_check": max((v.get("checked_at", "") for v in trad.symbols.values()), default=None),
                "max_age_days": spec.TRADABILITY_MAX_AGE_DAYS,
            },
            "universe": {
                "sp500_members": sorted(sp.index),
                "sp500_count": len(sp),
                "sp500_price_coverage": coverage,
                "broad_eligible": len(broad),
                "broad_prescreen": len(prelim),
                "broad_exclusion_counts": broad_reasons,
                "definitions": {"universe": spec.UNIVERSE_DEFINITION, "market_cap": spec.MARKET_CAP_DEFINITION},
            },
            "benchmarks": {b: {"close": float(s.iloc[-1]), "date": as_of} for b, s in bench.items()},
            "bands": payload_bands,
            "options": options_payload,
            "speculative": speculative_payload,
            "watchlist": _clean(watch_payload),
            "leaders_2030_inputs": leader_inputs,
            "leaders_2030": leader_payload,
            "ai": ai_payload,
            "events": {
                "window_days": 45,
                "items": upcoming,
                **earn_status,
                "note": earn_note
                or "Scheduled earnings dates from Alpha Vantage's calendar. They are not independently verified; "
                "other dated catalysts are not tracked.",
            },
            "disclaimer": spec.DISCLAIMER,
            "multibagger": spec.MULTIBAGGER_DEFINITION,
            "probability": spec.PROBABILITY_STATEMENT,
        }
    )
