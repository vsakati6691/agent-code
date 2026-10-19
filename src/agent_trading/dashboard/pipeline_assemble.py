"""Orchestrate weekly collection and scoring, then assemble the immutable snapshot payload."""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..market_calendar import is_trading_day
from . import options as opt
from . import spec
from .pipeline_collect import build_reference
from .pipeline_context import MIN_SP500_COVERAGE, Context, RunFailed, as_of_for
from .pipeline_details import _clean
from .pipeline_leaders import collect_inputs, retained_inputs
from .pipeline_phases import (
    ai_context,
    collect_benchmarks,
    collect_derivatives,
    collect_earnings,
    collect_events,
    prescreen_universes,
    score_bands,
)
from .pipeline_watchlist import evaluate_watchlist
from .providers import SOURCES, Providers
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
    earnings_verdicts=None,
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
    ctx.earnings_verdicts = earnings_verdicts
    if previous and previous.get("as_of", "9999") <= str(as_of):
        ctx.prior_earnings_checks = {
            c["ticker"]: c.get("earnings_check") or {}
            for b in previous.get("bands", {}).values()
            for c in b.get("candidates", [])
        }
        ctx.prior_earnings_checks.update(
            {
                e["ticker"]: e.get("earnings_check") or {}
                for e in previous.get("watchlist", {}).get("entries", [])
                if e.get("earnings_check")
            }
        )
    private_metadata = {}
    private_source: str | None = None
    if getattr(providers, "history_provider", "cboe") == "massive":
        from .massive_history import SOURCE
        from .private_research import require_local

        require_local()
        private_source = SOURCE
        private_metadata = {
            "publication": "private",
            "price_history": {"provider": "massive", "source": SOURCE, "collected_at": ctx.started, "window_days": 730},
        }
        ctx.notes.append(
            "Private personal research. Massive history covers at most two years; longer price windows remain unavailable."
        )
    ref = build_reference(ctx)

    bench = collect_benchmarks(ctx)

    earnings, earn_note, earn_status, cal = collect_earnings(ctx)

    sp, sec, sp_list, broad, broad_reasons, prelim = prescreen_universes(ctx, ref)

    payload_bands, ai_pool, ai_rejects, roles, ladder = score_bands(
        ctx, ref, sp, sec, sp_list, prelim, bench, previous, trad, todo, earnings
    )
    leader_collection = collect_inputs(ctx, ref)

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

    from . import macro, pipeline_external

    external_enabled = hasattr(providers, "fred_key") and hasattr(providers.http, "budget_group")
    macro_payload = macro.collect(providers, as_of) if external_enabled else None

    watch_payload = {"status": "no watchlist configured", "entries": []}
    if watchlist is not None:
        watch_payload = evaluate_watchlist(ctx, ref, watchlist, earnings)
    upcoming = collect_events(ctx, payload_bands, watch_payload, earnings)
    speculative_payload, options_payload = collect_derivatives(
        ctx, payload_bands, earnings, cal, options_enabled, iv_history, earn_note
    )
    external_status = (
        pipeline_external.collect(ctx, payload_bands, watch_payload, previous, aggregate_store)
        if external_enabled
        else {}
    )
    if external_enabled:
        assert macro_payload is not None
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

    if ctx.transient_failures:
        ctx.problems.append(
            f"{ctx.transient_failures} request(s) still failed after retries (rate limits or server "
            "errors); the affected stocks are listed as excluded with that reason"
        )
    ai_payload = ai_context(ctx, ai_pool, ai_rejects, roles, ladder, ai_private)
    from . import desk

    # after the external datasets, so the positioning analyst sees the stored insider and short-interest records
    desk_payload = desk.build(payload_bands, as_of)

    status = "ok" if not ctx.problems and not ctx.budget_hit else "partial"
    from . import leaders

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
            **private_metadata,
            "as_of": as_of,
            "run_started": ctx.started,
            "run_finished": datetime.now(UTC).isoformat(timespec="seconds"),
            "status": status,
            "problems": ctx.problems,
            "notes": ctx.notes + ([earn_note] if earn_note else []),
            "spec_version": spec.SPEC_VERSION,
            "spec_hash": spec.spec_hash(),
            "sources": {
                **SOURCES,
                **({"massive": private_source} if private_source else {}),
            },
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
            "benchmarks": {
                b: {
                    "close": float(s.iloc[-1]),
                    "date": as_of,
                    **({"source": private_source} if private_source else {}),
                }
                for b, s in bench.items()
            },
            "bands": payload_bands,
            "options": options_payload,
            "speculative": speculative_payload,
            "watchlist": _clean(watch_payload),
            "leaders_2030_inputs": leader_inputs,
            "leaders_2030_collection": leader_collection,
            "leaders_2030": leader_payload,
            "ai": ai_payload,
            "decision_desk": desk_payload,
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
