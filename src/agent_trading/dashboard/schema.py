"""Field documentation for the published JSON (data/latest.json, data/<as-of>.json), written to data/schema.json.

A JSON-Schema-style description: types plus a plain-English description of every top-level field and of the
main nested records. Ratios are decimals (0.25 = 25%); money is USD; dates are ISO 8601; times are UTC.
"""
from __future__ import annotations


def _obj(desc: str, props: dict | None = None, **extra) -> dict:
    d = {"type": "object", "description": desc}
    if props:
        d["properties"] = props
    d.update(extra)
    return d


def _f(t: str, desc: str) -> dict:
    return {"type": t, "description": desc}


CANDIDATE = _obj("One ranked stock in a list.", {
    "ticker": _f("string", "Exchange ticker (share classes as BRK.B)."),
    "name": _f("string", "Security name from the exchange listing."),
    "sector": _f("string", "GICS sector (S&P 500) or a coarse sector from the SEC SIC code."),
    "band": _f("string", "List key: large, mid, small or multibagger."),
    "rank": _f("integer", "Rank within the list after the Robinhood tradability filter (1 = highest score)."),
    "composite": _f("number", "Research score 0-100 from the fixed component weights."),
    "components": _f("object", "Component scores 0-1 by component key (null = all inputs missing)."),
    "sub_scores": _f("object", "Each input's 0-1 score on its fixed scale (missing inputs score 0)."),
    "metrics": _f("object", "Raw inputs: ratios as decimals, money in USD, multiples as plain numbers."),
    "missing": _f("array", "Inputs that were unavailable and scored 0."),
    "confidence": _f("number", "Evidence confidence 0-1 (share of inputs present, reduced for data caveats)."),
    "confidence_label": _f("string", "high, medium or low."),
    "flags": _f("array", "Data caveats, e.g. limited history or quarters derived from annual filings."),
    "counterargument": _f("string", "The weakest scored evidence, in words."),
    "thesis": _f("string", "Rule-generated summary of the strongest evidence (not a recommendation)."),
    "bear_case": _f("string", "Rule-generated strongest bear case."),
    "risks": _f("array", "Rule-based key business risks."),
    "invalidation": _f("array", "Observable conditions that would undercut the research case."),
    "price": _f("number", "As-of close, USD (Cboe delayed, split-adjusted)."),
    "price_date": _f("string", "Date of that close."),
    "market_cap": _f("number", "Close x SEC cover-page shares outstanding, USD."),
    "history": _f("object", "Trailing price returns vs the benchmark (1m-5y) and drawdowns."),
    "chart": _f("object", "Weekly price path rebased to 100 for the stock and its benchmark."),
    "scenarios": _f("object", "Bear/base/bull values per share by year with every assumption; null when not computable."),
    "fundamentals": _f("object", "Last 8 reported quarters and the latest balance sheet (SEC XBRL, point in time)."),
    "next_earnings": _f("string", "Next scheduled earnings date (Alpha Vantage, not independently verified) or null."),
})
CONTRACT = _obj("One option contract in a ranked list.", {
    "type": _f("string", "call or put."),
    "underlying": _f("string", "Underlying ticker."),
    "option": _f("string", "OCC contract symbol."),
    "strike": _f("number", "Strike price, USD."),
    "expiration": _f("string", "Expiry date."),
    "dte": _f("integer", "Calendar days to expiry from the as-of date."),
    "bid": _f("number", "Delayed bid per share."), "ask": _f("number", "Delayed ask per share."),
    "spread_pct": _f("number", "(ask - bid) / mid."),
    "premium_basis": _f("string", "Price used for calculations: ask."),
    "premium_per_contract_ask": _f("number", "Ask x 100 shares, USD (illustrative cost of one contract)."),
    "breakeven": _f("number", "Stock price at expiry where the contract breaks even."),
    "breakeven_move": _f("number", "Signed move from the stock price to the breakeven (decimal)."),
    "required_move": _f("number", "Move still needed in the option's favourable direction (>= 0)."),
    "max_loss_per_contract": _f("number", "Most a buyer can lose: the premium paid, USD."),
    "volume": _f("number", "Contracts traded in the last session."),
    "open_interest": _f("number", "Contracts outstanding."),
    "iv": _f("number", "Implied volatility (decimal, annualised)."),
    "delta": _f("number", "Model delta; NOT a probability of profit."),
    "theta": _f("number", "Model value lost per day, per share."),
    "rank_components": _f("object", "Ranking parts (liquidity, breakeven, time_decay, 0-1) and total (0-100)."),
    "payoffs": _f("array", "Profit per contract at expiration for fixed stock moves (exact arithmetic)."),
    "sensitivity": _f("object", "Black-Scholes MODEL estimates of value after 30 days for price/IV shifts."),
    "events_before_expiry": _f("array", "Scheduled earnings before expiry (unverified)."),
    "flags": _f("array", "Data caveats: delayed quote, wide spread, low volume, adjusted contract..."),
})
WATCH_ENTRY = _obj("One watchlist symbol.", {
    "ticker": _f("string", "Symbol as imported."),
    "name": _f("string", "Official name from the listings or SEC file; null if unresolved."),
    "asset_type": _f("string", "operating company (common stock), ETF, leveraged/inverse ETF, or other."),
    "status": _f("string", "listed, OTC, or unresolved (with the reason)."),
    "price": _f("number", "Latest verified close, USD."), "price_date": _f("string", "Date of that close."),
    "price_validation": _f("string", "From 2026-10-14.5: how the as-of price was verified."),
    "history_bars": _f("integer", "Daily bars available up to the as-of date."),
    "history_note": _f("string", "Set when the price is verified but the history is too short for some analyses."),
    "method": _f("string", "Scenario method applied."),
    "scenarios": _f("object", "bear/base/bull: 2030-12-31 price, change and annualized price return, with assumptions."),
    "unavailable_reason": _f("string", "Why no scenario was computed (null when one was)."),
    "unlock": _f("array", "Exact missing inputs and what would unlock a scenario."),
    "evidence_quality": _f("string", "medium-high, medium, low or none."),
    "missing": _f("array", "Information that is missing or assumed."),
    "sources": _f("array", "Data sources used for this symbol."),
})
BAND = _obj("One ranked list.", {
    "title": _f("string", "Full list title."), "short_title": _f("string", "Short title."),
    "definition": _f("object", "Universe, market-cap range, minimum price and liquidity floor."),
    "benchmark": _f("string", "Benchmark ETF ticker."), "profile": _f("string", "Scoring weight profile."),
    "components": _f("array", "Component keys used by this list."),
    "candidates": {"type": "array", "items": CANDIDATE, "description": "Ranked stocks shown (at most max_results)."},
    "excluded": _f("array", "Every stock considered but not shown, with the reason."),
    "rank_changes": _f("array", "Moves vs the previous snapshot with score and component changes."),
    "runners_up": _f("array", "The next ten by score."),
    "concentration": _f("array", "Sector or correlation concentration warnings."),
    "history": _f("object", "Trailing price returns by window (from 2026-10-14.5 each with its start and end session "
                            "and session count; the stock and its benchmark share the same sessions) and drawdowns."),
})
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Growth Research Dashboard weekly snapshot",
    "description": "Research comparisons from public data; not advice. Ratios are decimals (0.25 = 25%), money is USD, "
                   "dates are ISO 8601 and times UTC. Snapshots are immutable once written.",
    "type": "object",
    "properties": {
        "as_of": _f("string", "NYSE session whose close the snapshot uses."),
        "run_started": _f("string", "UTC time the run started."), "run_finished": _f("string", "UTC time it finished."),
        "status": _f("string", "ok, or partial when some data could not be fetched."),
        "problems": _f("array", "Run-level problems (rate limits, budgets)."), "notes": _f("array", "Run-level notes."),
        "spec_version": _f("string", "Methodology version (spec.py)."), "spec_hash": _f("string", "Hash of every rule."),
        "sources": _f("object", "Data providers and their terms."), "usage": _f("object", "Requests by provider."),
        "tradability": _f("object", "Robinhood tradability rule, how many verdicts were stored / are to check and, from "
                                    "2026-10-14.5, the oldest and newest check times (no account data)."),
        "universe": _f("object", "Universe sizes, S&P 500 members and broad-universe exclusion counts."),
        "benchmarks": _f("object", "Benchmark closes on the as-of date."),
        "bands": {"type": "object", "additionalProperties": BAND, "description": "Lists by key: large, mid, small, multibagger."},
        "options": _obj("Option comparisons: 3m/6m/12m horizons, each with calls and puts lists.", {
            "3m": _obj("About 3 months.", {"calls": _obj("Ranked calls.", {"rows": {"type": "array", "items": CONTRACT}}),
                                           "puts": _obj("Ranked puts.", {"rows": {"type": "array", "items": CONTRACT}})}),
            "underlyings": _f("array", "Underlyings with a valid chain."),
            "chain_problems": _f("object", "Why other chains were not used."),
        }),
        "watchlist": _obj("Owner watchlist with conditional 2030 price scenarios.",
                          {"entries": {"type": "array", "items": WATCH_ENTRY},
                           "imported_at": _f("string", "When the ticker list was imported (not synchronised)."),
                           "target_date": _f("string", "2030-12-31.")}),
        "events": _obj("Upcoming scheduled earnings within 45 days (unverified source).", {
            "items": _f("array", "Scheduled report dates for listed and watchlist names."),
            "status": _f("string", "From 2026-10-14.5: ok (the lookup succeeded, even with no dates) or unavailable."),
            "state": _f("string", "Dataset state: available, missing (not configured) or provider_error."),
            "reason": _f("string", "Why the lookup was unavailable."),
            "calendar_rows": _f("integer", "Rows returned by the calendar lookup."),
        }),
        "disclaimer": _f("string", "Research only, not advice."), "multibagger": _f("string", "Multibagger definition."),
        "probability": _f("string", "Why no probabilities are shown."),
    },
}
