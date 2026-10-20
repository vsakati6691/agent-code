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


LEADERS_CHALLENGER = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "name",
        "ticker",
        "listing_status",
        "assumed_2030_market_cap_usd",
        "assumption_source",
        "assumption_date",
        "growth_drivers",
        "notes",
    ],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "ticker": {"type": ["string", "null"], "pattern": "^[A-Z][A-Z0-9.-]{0,14}$"},
        "listing_status": {"enum": ["listed_non_index", "private", "pre_ipo"]},
        "assumed_2030_market_cap_usd": {"type": "number", "exclusiveMinimum": 0},
        "assumption_source": {"type": "string", "minLength": 1, "description": "Source URL or identified document."},
        "assumption_date": {"type": "string", "format": "date"},
        "growth_drivers": {
            "type": "array",
            "items": {"type": "string", "description": "ISO date followed by text; no later than the assumption date."},
        },
        "notes": {"type": "string"},
    },
}

# spec 2026-10-19.5 (LEADERS_OUTSIDE_RULES): config/leaders_outside_index.json entries
LEADERS_OUTSIDE = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "name",
        "kind",
        "ticker",
        "valuation_usd",
        "valuation_date",
        "valuation_basis",
        "valuation_source",
        "valuation_url",
        "valuation_confirmed",
        "status",
        "status_date",
        "status_source",
        "status_url",
        "status_confirmed",
        "notes",
    ],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "kind": {"enum": ["private", "listed_non_index"]},
        "ticker": {"type": ["string", "null"], "pattern": "^[A-Z][A-Z0-9.-]{0,14}$"},
        "valuation_usd": {"type": "number", "exclusiveMinimum": 0},
        "valuation_date": {"type": "string", "format": "date"},
        "valuation_basis": {
            "type": "string",
            "minLength": 1,
            "description": "Priced round, tender, secondary, IPO price.",
        },
        "valuation_source": {"type": "string", "minLength": 1},
        "valuation_url": {"type": "string", "pattern": "^https://"},
        "valuation_confirmed": {"type": "boolean", "description": "True only when read on the company's own page."},
        "status": {"type": "string", "minLength": 1, "description": "Listing or IPO status as reported."},
        "status_date": {"type": "string", "format": "date"},
        "status_source": {"type": "string", "minLength": 1},
        "status_url": {"type": "string", "pattern": "^https://"},
        "status_confirmed": {"type": "boolean"},
        "notes": {"type": "string"},
    },
}

EXTERNAL = _obj(
    "Optional dated public datasets, collected prospectively from version 2026-10-16.2; absent in older snapshots.",
    {
        "insiders": _obj(
            "Non-derivative Form 4 P/S purchases/sales (open market or private). Incomplete windows have null totals.",
            {
                "state": _f(
                    "string",
                    "available, partial, missing or provider_error; budget exhaustion says deferred to next run.",
                ),
                "classification_basis": _f(
                    "string", "Form 4 codes P/S (open market or private); A, M, F, G and derivative rows excluded"
                ),
                "as_of": _f("string", "Inclusive filing and transaction cutoff date."),
                "windows": _obj(
                    "90d and 12m; each has start/end, signed net_shares/net_dollars, distinct buyers/sellers and separate missing-value reasons."
                ),
                "filings": _f(
                    "array",
                    "Accessions, filing dates, source URLs, 10b5-1 checkbox (null when absent), owner CIKs and parsed transactions, including excluded codes/derivatives; reused prospectively.",
                ),
                "excluded_rows": _f("object", "Counts by excluded transaction code and derivative status."),
                "latest_transaction_date": _f(
                    "string", "Latest reported transaction in the eligible 12-month window; null if none."
                ),
            },
        ),
        "institutions": _obj(
            "SEC 13F report-quarter aggregates, not total institutional ownership; reporting managers may overlap.",
            {
                "neutral_fallback": _f(
                    "boolean",
                    "True when holdings are unavailable; null counts and zero score adjustment, never fabricated ownership.",
                ),
                "scoring_required": _f(
                    "boolean", "Always false; this dataset is display-only and creates no missing scoring inputs."
                ),
                "score_adjustment": _f("number", "Always zero, including provider failures."),
                "report_quarter_end": _f("string", "Holdings date, distinct from archive filing-window date."),
                "holder_count": _f(
                    "integer", "Distinct filing-manager CIKs with positive long SH holdings, excluding puts/calls."
                ),
                "reported_shares": _f("integer", "Sum of reported shares after manager amendment handling."),
                "top_holders": _f(
                    "array", "Up to ten manager names/CIKs and reported shares, descending shares then CIK."
                ),
                "holder_count_change": _f(
                    "integer", "Current less immediately preceding quarter; null if not comparable."
                ),
                "reported_shares_change": _f(
                    "integer", "Current less immediately preceding quarter shares; null if not comparable."
                ),
                "mapping_date": _f(
                    "string", "SEC FTD mapping file period end; mapping_url identifies its dated source."
                ),
                "mapping_settlement_date": _f("string", "Latest observation supporting this ticker-CUSIP mapping."),
                "stale_after": _f(
                    "string", "Following report-quarter end plus 45 days; stale after that date without newer holdings."
                ),
            },
        ),
        "risk_excerpt": _obj(
            "Issuer quotation through the existing filing-text parser; source, date, form and accession retained.",
            {
                "excerpt": _f("string", "Exact quoted substring; never paraphrased."),
                "character_range": _f(
                    "array", "Zero-based [start,end), end exclusive, in whitespace-normalized FilingText output."
                ),
                "range_basis": _f("string", "Text normalization used to reproduce offsets."),
                "text_sha256": _f("string", "SHA-256 of normalized filing text, UTF-8."),
                "parser_version": _f("string", "Offset normalization/extraction version."),
            },
        ),
        "short_interest": _obj(
            "FINRA settlement reports; unknown symbols are not zero.",
            {
                "settlement_date": _f("string", "FINRA report's settlement date."),
                "shares_short": _f("integer", "Current reported short shares."),
                "change_shares": _f(
                    "integer", "Current minus FINRA's published prior quantity, retaining its revision/split basis."
                ),
                "percent_of_diluted_shares": _f(
                    "number",
                    "Short interest as a percentage of XBRL diluted shares outstanding; decimal ratio, not float.",
                ),
                "diluted_shares": _f("number", "Latest stored quarterly diluted weighted-average XBRL share count."),
                "shares_date": _f(
                    "string", "Period end of denominator; shares_basis discloses weighted-average proxy."
                ),
                "days_to_cover": _f(
                    "number",
                    "Short shares divided by existing stored average daily share volume; null without that input, with reason.",
                ),
            },
        ),
    },
)

LEADER_ENTRY = _obj(
    "Conditional 2030 size comparison; derived from stored inputs, never a tracked historical selection.",
    {
        **{
            key: {"type": ["string", "null"]}
            for key in (
                "ticker",
                "company_name",
                "sector",
                "listing_status",
                "market_cap_date",
                "price_date",
                "shares_date",
                "shares_basis",
                "shares_assumption",
                "movement",
                "evidence_grade",
                "unavailable_reason",
                "scenario_basis",
                "methodology_version",
                "snapshot_id",
                "snapshot_methodology_version",
                "assumption_source",
                "assumption_date",
                "notes",
            )
        },
        **{key: {"type": ["integer", "null"]} for key in ("current_rank", "rank_2030", "rank_delta")},
        **{key: {"type": ["number", "null"]} for key in ("current_market_cap_usd", "shares_outstanding")},
        "scenario_2030": _obj(
            "USD caps/prices and projected shares; implied_cagr is cap CAGR (decimal), not share-price return. Curated records have only a base cap.",
            {
                f"{case}_{field}": {"type": ["number", "null"]}
                for case in ("bear", "base", "bull")
                for field in ("cap", "price", "shares", "implied_cagr")
            },
        ),
        "scenario_assumptions": _obj(
            "Per-case three-year growth basis, growth path, fade, valuation inputs, horizon, raw cap and explicit bear stress adjustment; empty if unavailable/curated."
        ),
        "aggressive_assumption": _f("boolean", "True when computed base cap CAGR strictly exceeds 25%/yr."),
        "growth_drivers": {"type": "array", "items": {"type": "string"}},
        "missing_inputs": {"type": "array", "items": {"type": "string"}},
        "other_share_classes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "From 2026-10-19.4: other index tickers of the same SEC registrant, not ranked separately.",
        },
        "gap_kind": {
            "type": ["string", "null"],
            "description": "From 2026-10-19.4: coarse cause of the first missing input (share count, SEC statements, "
            "price or other inputs); null when nothing is missing.",
        },
        "is_scenario": {"const": True},
    },
)


CANDIDATE = _obj(
    "One ranked stock in a list.",
    {
        "external": EXTERNAL,
        "ticker": _f("string", "Exchange ticker (share classes as BRK.B)."),
        "name": _f("string", "Security name from the exchange listing."),
        "sector": _f("string", "GICS sector (S&P 500) or a coarse sector from the SEC SIC code."),
        "band": _f("string", "List key: large, mid, small, multibagger, ai_large or ai_mid."),
        "ai_role": _f("string", "AI lists only: where the company sits in the AI supply chain (spec.AI_UNIVERSE)."),
        "top20_test": _f(
            "object",
            "AI lists only: bear, base and bull scenario market caps at 5 and 10 years against today's "
            "20th-largest S&P 500 market cap; conditional scenarios, never a probability.",
        ),
        "rank": _f("integer", "Rank within the list after the Robinhood tradability filter (1 = highest score)."),
        "composite": _f("number", "Research score 0-100 from the fixed component weights."),
        "components": _f("object", "Component scores 0-1 by component key (null = all inputs missing)."),
        "sub_scores": _f("object", "Each input's 0-1 score on its fixed scale (missing inputs score 0)."),
        "metrics": _f("object", "Raw inputs: ratios as decimals, money in USD, multiples as plain numbers."),
        "decision_research": _f(
            "object",
            "Dated valuation/growth/balance/ownership/timing/quality field groups; each field has value, reason and as_of. Valuation percentiles are within-list. Includes attributed 10-K excerpts and a 1Y price sparkline.",
        ),
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
        "scenarios": _f(
            "object", "Bear/base/bull values per share by year with every assumption; null when not computable."
        ),
        "fundamentals": _f(
            "object", "Last 8 reported quarters and the latest balance sheet (SEC XBRL, point in time)."
        ),
        "next_earnings": _f(
            "string", "Next scheduled earnings date (Alpha Vantage, not independently verified) or null."
        ),
    },
)
CONTRACT = _obj(
    "One option contract in a ranked list.",
    {
        "type": _f("string", "call or put."),
        "underlying": _f("string", "Underlying ticker."),
        "option": _f("string", "OCC contract symbol."),
        "strike": _f("number", "Strike price, USD."),
        "expiration": _f("string", "Expiry date."),
        "dte": _f("integer", "Calendar days to expiry from the as-of date."),
        "bid": _f("number", "Delayed bid per share."),
        "ask": _f("number", "Delayed ask per share."),
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
        "sensitivity": _f(
            "object",
            "Black-Scholes MODEL estimates after 30 days for price/IV shifts. From 2026-10-16.2, rate_input stores DGS1MO value/100, date, source, series and reason; missing rate means empty grid with reason. Older stored estimates keep their original rate assumption.",
        ),
        "events_before_expiry": _f("array", "Scheduled earnings before expiry (unverified)."),
        "events_status": _f(
            "string", "From 2026-10-14.6: scheduled, none scheduled, or unknown (calendar not collected)."
        ),
        "flags": _f("array", "Data caveats: delayed quote, wide spread, low volume, adjusted contract..."),
        "horizon": _f("string", "From 2026-10-14.6: the expiry window key (3m, 6m, 12m)."),
        "theta_available": _f(
            "boolean", "From 2026-10-14.6: false means theta was missing; such contracts are not listed."
        ),
        "theta_share_per_day": _f(
            "number", "|theta| / mid per day; null when theta is unavailable (never zero-filled)."
        ),
        "quote_time_utc": _f(
            "string", "From 2026-10-14.6: the chain snapshot time (UTC) = when the bid/ask were quoted."
        ),
        "quote_date_ny": _f("string", "That snapshot's New York date."),
        "quote_status": _f("string", "Freshness verdict of the snapshot relative to the as-of session."),
        "quote_source": _f("string", "Cboe delayed quotes (end-of-session snapshot; never live)."),
        "contract_last_trade": _f(
            "string", "When the CONTRACT last traded (not its quote time); null when never recorded."
        ),
        "underlying_last_trade": _f("string", "When the underlying last traded (must be the as-of session)."),
        "risks": _f(
            "object", "From 2026-10-14.6: plain-language liquidity, time_decay, volatility, event and max_loss notes."
        ),
        "fees": _f("string", "Fee treatment of every payoff figure (none deducted)."),
        "probability": _f(
            "object",
            "From 2026-10-14.6: the probability gate's verdict; status 'not_established' with the "
            "statement, the definition, why, and the missing data. A percentage appears only for a "
            "record that passes spec.PROBABILITY_GATE.",
        ),
    },
)
WATCH_ENTRY = _obj(
    "One watchlist symbol.",
    {
        "external": EXTERNAL,
        "ticker": _f("string", "Symbol as imported."),
        "name": _f("string", "Official name from the listings or SEC file; null if unresolved."),
        "asset_type": _f("string", "operating company (common stock), ETF, leveraged/inverse ETF, or other."),
        "status": _f("string", "listed, OTC, or unresolved (with the reason)."),
        "price": _f("number", "Latest verified close, USD."),
        "price_date": _f("string", "Date of that close."),
        "price_validation": _f("string", "From 2026-10-14.5: how the as-of price was verified."),
        "history_bars": _f("integer", "Daily bars available up to the as-of date."),
        "history_note": _f("string", "Set when the price is verified but the history is too short for some analyses."),
        "method": _f("string", "Scenario method applied."),
        "scenarios": _f(
            "object", "bear/base/bull: 2030-12-31 price, change and annualized price return, with assumptions."
        ),
        **{
            key: {
                "type": ["number", "null"],
                "description": "Percentage points (24 = 24%), derived from stored scenario returns; also exported for older snapshots.",
            }
            for key in ("upside_bear_pct", "upside_base_pct", "upside_bull_pct", "cagr_base_pct")
        },
        "unavailable_reason": _f("string", "Why no scenario was computed (null when one was)."),
        "unlock": _f("array", "Exact missing inputs and what would unlock a scenario."),
        "evidence_quality": _f("string", "medium-high, medium, low or none."),
        "missing": _f("array", "Information that is missing or assumed."),
        "sources": _f("array", "Data sources used for this symbol."),
    },
)
BAND = _obj(
    "One ranked list.",
    {
        "title": _f("string", "Full list title."),
        "short_title": _f("string", "Short title."),
        "definition": _f("object", "Universe, market-cap range, minimum price and liquidity floor."),
        "benchmark": _f("string", "Benchmark ETF ticker."),
        "profile": _f("string", "Scoring weight profile."),
        "components": _f("array", "Component keys used by this list."),
        "candidates": {
            "type": "array",
            "items": CANDIDATE,
            "description": "Ranked stocks shown (at most max_results).",
        },
        "excluded": _f("array", "Every stock considered but not shown, with the reason."),
        "rank_changes": _f("array", "Moves vs the previous snapshot with score and component changes."),
        "runners_up": _f("array", "The next ten by score."),
        "concentration": _f("array", "Sector or correlation concentration warnings."),
        "history": _f(
            "object",
            "Trailing price returns by window (from 2026-10-14.5 each with its start and end session "
            "and session count; the stock and its benchmark share the same sessions) and drawdowns.",
        ),
    },
)
SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Tikasa Stock Research weekly snapshot",
    "description": "Research comparisons from public data; not advice. Ratios are decimals (0.25 = 25%), money is USD, "
    "dates are ISO 8601 and times UTC. Snapshots are immutable once written.",
    "type": "object",
    "properties": {
        "as_of": _f("string", "NYSE session whose close the snapshot uses."),
        "external_datasets": _f(
            "object",
            "Per-dataset status, coverage, deferred count, reasons, source and retrieval time; optional in older snapshots.",
        ),
        "macro": _obj(
            "Optional FRED as-of observations, with per-series states and reasons.",
            {
                "series": _f(
                    "object",
                    "DGS1MO/DGS3MO/DGS2/DGS10/FEDFUNDS/CPIAUCSL/UNRATE: value, observation_date, last_updated, vintage_date, units, source. CPI also stores observations, decimal yoy and its two yoy_dates.",
                ),
            },
        ),
        "run_started": _f("string", "UTC time the run started."),
        "run_finished": _f("string", "UTC time it finished."),
        "status": _f("string", "ok, or partial when some data could not be fetched."),
        "problems": _f("array", "Run-level problems (rate limits, budgets)."),
        "notes": _f("array", "Run-level notes."),
        "spec_version": _f("string", "Methodology version (spec.py)."),
        "spec_hash": _f("string", "Hash of every rule."),
        "sources": _f("object", "Data providers and their terms."),
        "usage": _f("object", "Requests by provider."),
        "tradability": _f(
            "object",
            "Robinhood tradability rule, how many verdicts were stored / are to check and, from "
            "2026-10-14.5, the oldest and newest check times (no account data).",
        ),
        "universe": _f("object", "Universe sizes, S&P 500 members and broad-universe exclusion counts."),
        "benchmarks": _f("object", "Benchmark closes on the as-of date."),
        "bands": {
            "type": "object",
            "additionalProperties": BAND,
            "description": "Lists by key: large, mid, small, multibagger and, from 2026-10-14.7, ai_large and ai_mid.",
        },
        "ai": _obj(
            "From 2026-10-14.7: the AI page's data (null in older snapshots).",
            {
                "definition": _f("string", "How the AI-exposed universe is defined (spec.AI_UNIVERSE_DEFINITION)."),
                "top20_rule": _f("string", "How the top-20 market-cap scenario test works (spec.AI_TOP20_RULE)."),
                "private_rule": _f("string", "Rules for the private-company context (spec.AI_PRIVATE_RULE)."),
                "probability_note": _f("string", "Why no probability is shown (spec.AI_PROBABILITY_NOTE)."),
                "universe": _f(
                    "object",
                    "How many names the fixed universe defines and resolved, those that could not be "
                    "evaluated with their reasons, and each name's role in the AI chain.",
                ),
                "ladder": _f(
                    "object",
                    "The largest S&P 500 market caps in the run and the 20th-largest as the bar "
                    "(threshold, threshold_ticker, members).",
                ),
                "private": _f(
                    "object",
                    "Private AI companies: reviewed_on, note and companies. A valuation always has a "
                    "currency (in billions), basis, date, source label and https source link, and is "
                    "reported and unverified; a company without one gives the reason.",
                ),
            },
        ),
        "options": _obj(
            "Option comparisons: 3m/6m/12m horizons, each with calls and puts lists.",
            {
                "rate_input": _f(
                    "object",
                    "Optional dated FRED DGS1MO input: decimal value, observation date, source, series, reason. Applies only to new weekly sensitivities, never rankings or old stored estimates.",
                ),
                "3m": _obj(
                    "About 3 months.",
                    {
                        "calls": _obj("Ranked calls.", {"rows": {"type": "array", "items": CONTRACT}}),
                        "puts": _obj("Ranked puts.", {"rows": {"type": "array", "items": CONTRACT}}),
                    },
                ),
                "underlyings": _f("array", "Underlyings with a valid chain."),
                "chain_problems": _f("object", "Why other chains were not used."),
                "quotes": _f(
                    "object",
                    "From 2026-10-14.6: per underlying, the chain snapshot time, its New York date, the "
                    "freshness status and the underlying's last trade.",
                ),
                "events_known": _f("boolean", "From 2026-10-14.6: false when the earnings calendar was not collected."),
                "rules": _f(
                    "object", "From 2026-10-14.6: the OPTION_RULES the snapshot was built with (list size included)."
                ),
                "spec_version": _f("string", "Methodology version the option lists were built under."),
                "collected_at": _f("string", "UTC time the chains were collected."),
                "probability": _f(
                    "object",
                    "Calibration status per option type and horizon (all 'not established'), the "
                    "gate, the data contract and the missing data.",
                ),
            },
        ),
        "speculative": {
            "type": ["object", "null"],
            "description": "Optional 30–90 DTE research on the top three names in each growth list. At most three contracts per ticker, IV context and reasons for missing data. Separate from weekly tracked lists. Same iv_method identifies comparable daily IV observations.",
        },
        "watchlist": _obj(
            "Owner watchlist with conditional 2030 price scenarios.",
            {
                "entries": {"type": "array", "items": WATCH_ENTRY},
                "imported_at": _f("string", "When the ticker list was imported (not synchronised)."),
                "target_date": _f("string", "2030-12-31."),
            },
        ),
        "leaders_2030_inputs": _f(
            "array",
            "Prospectively retained S&P 500 inputs. From 2026-10-17.1, missing prices and SEC facts are attempted for every member within existing budgets; prior versions only reused collected inputs.",
        ),
        "leaders_2030_collection": _obj(
            "Optional from 2026-10-17.1: members requested, total universe, development limit flag and additional_requests by provider during the index completion phase. Attempts include retries; cache hits consume no budget."
        ),
        "leaders_2030": _obj(
            "Conditional size comparison, with coverage and gap reasons. Code-only rebuilds export a separate derived JSON without rewriting the source snapshot.",
            {
                "entries": {"type": "array", "items": LEADER_ENTRY},
                "partial": _f("boolean", "Ranks and movement labels cover available inputs only when true."),
                "gaps": _f(
                    "array",
                    "Index members without sufficient stored inputs and their specific reasons; from 2026-10-19.4 "
                    "also a coarse kind and whether the member still has a current rank.",
                ),
                "share_classes": _f(
                    "array",
                    "From 2026-10-19.4: extra share classes ranked with their company ({ticker, ranked_as}).",
                ),
                "company_count": _f("integer", "From 2026-10-19.4: index companies after merging share classes."),
                "outside_index": _f(
                    "array",
                    "From 2026-10-19.5: owner-curated private or non-index listed companies (LEADERS_OUTSIDE) with "
                    "would_rank among current caps for scale only; never ranked and no 2030 scenario.",
                ),
                "omitted_outside": _f("array", "From 2026-10-19.5: outside-index entries left out and why."),
            },
        ),
        "decision_desk": _obj(
            "Optional from 2026-10-17.5: rule-based Buy/Sell desk ratings for every research-list stock "
            "(spec.DESK_RULE). Research labels, not advice; older snapshots have none and are never backfilled.",
            {
                "entries": _f(
                    "array",
                    "One record per ticker: analysts (key, vote +1/0/-1 or null when abstaining, points, inputs, "
                    "reason), debate (net vote, verdict, bull and bear evidence), trader proposal, risk (flags, "
                    "unchecked, reviews by aggressive/neutral/conservative), manager (median, capped), rating "
                    "(Buy, Overweight, Hold, Underweight, Sell or null when not rated), summary, lists and benchmark.",
                ),
                "counts": _f("object", "Number of stocks per rating, plus 'Not rated'."),
                "spec_version": _f("string", "Methodology version the ratings were computed under."),
            },
        ),
        "events": _obj(
            "Upcoming scheduled earnings within 45 days (unverified source).",
            {
                "items": _f("array", "Scheduled report dates for listed and watchlist names."),
                "status": _f(
                    "string", "From 2026-10-14.5: ok (the lookup succeeded, even with no dates) or unavailable."
                ),
                "state": _f("string", "Dataset state: available, missing (not configured) or provider_error."),
                "reason": _f("string", "Why the lookup was unavailable."),
                "calendar_rows": _f("integer", "Rows returned by the calendar lookup."),
            },
        ),
        "disclaimer": _f("string", "Research only, not advice."),
        "multibagger": _f("string", "Multibagger definition."),
        "probability": _f("string", "Why no probabilities are shown."),
    },
}
