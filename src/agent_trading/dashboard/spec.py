"""Pre-registered methodology for the weekly research dashboard.

Every rule that decides which stocks and option contracts appear, and in what
order, lives here and is fixed BEFORE results are looked at. The spec is
hashed (`spec_hash`) and the hash is written into every weekly snapshot, so a
later change to any rule shows up as a new spec version in the audit trail and
in performance tracking (results are never pooled across versions).

Changing a number here after seeing results is tuning on the outcome. Do it
only as a new, dated version with the reason recorded in SPEC_CHANGELOG.

The outputs are research comparisons, not advice or instructions to trade.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

SPEC_VERSION = "2026-10-14.9"
SPEC_CHANGELOG = [
    ("2026-10-13.1", "Initial pre-registered rules, written before any dashboard results were computed."),
    ("2026-10-13.2", "Data-integrity fix found in the first 25-stock smoke test, before any snapshot was published: "
                     "a company with several listed share classes (e.g. GOOG and GOOGL) is evaluated once, using "
                     "its most liquid class. No scoring rule, scale or weight changed."),
    ("2026-10-14.1", "Owner requests (2026-10-14), written before any data was run with them: (1) only stocks "
                     "Robinhood reports as tradable are published; a read-only Robinhood check no older than 35 "
                     "days is required, and unverified stocks are excluded with that reason. (2) New list: "
                     "long-horizon multibagger research candidates (5-10 years), $500M-$50B, with growth, margin, "
                     "track-record, dilution and survival gates, a long-horizon weight profile with a new runway "
                     "and operating-leverage component, and 10-year scenarios. The existing lists' rules, scales "
                     "and weights did not change; fixed scales mean removing untradable stocks leaves the order "
                     "of the others unchanged."),
    ("2026-10-14.2", "Owner redesign request (2026-10-14), written before any data was evaluated with it: "
                     "(1) three growth lists of up to 10: large cap (S&P 500 members), mid cap ($2B-$10B) and a "
                     "new small-cap list ($300M-$2B; the former 'speculative' list's price and liquidity floors, "
                     "without its 20% growth gate, and scored like the other growth lists); (2) the long-horizon "
                     "list is renamed 'Speculative multibagger research candidates' and shows up to 5; (3) options "
                     "cover calls AND puts, up to 10 per type per horizon (was 5 calls), with the same windows, "
                     "liquidity filters and per-underlying limit; put deltas use their absolute value; (4) a "
                     "separate owner watchlist with conditional year-end-2030 price scenarios (companies, "
                     "unleveraged ETFs and leveraged ETFs each with their own method). Scoring scales and "
                     "weights did not change."),
    ("2026-10-14.3", "Watchlist only, from the owner's watchlist requirements (connect margins to per-share "
                     "value): each company scenario now carries an explicit free-cash-flow margin path to "
                     "2030 (today's TTM FCF margin, or operating margin when FCF is unavailable, plus the "
                     "scenario's margin shift) and the EV/FCF multiple that the 2030 value implies. A value "
                     "with negative 2030 FCF or an implied EV/FCF above 60x is flagged as not supported by "
                     "cash generation. Scenario prices, growth lists, options and scoring are unchanged."),
    ("2026-10-14.4", "Data-gap fix approved by the owner on 2026-10-14 after the first live snapshot (2026-10-13), "
                     "not to improve tracked results: companies tag diluted weighted-average shares for a fiscal "
                     "fourth quarter only as a full-year figure, so the share-count change was missing whenever the "
                     "latest quarter was a fiscal Q4 (seen for MU, STX and WDC). That scored the dilution input as 0 "
                     "and failed the multibagger dilution gate as 'input unavailable'. Dilution now uses the newest "
                     "quarter that has a quarterly diluted share count and the same quarter a year earlier (at most "
                     "one quarter back). Scales, weights, gates and every other rule are unchanged; the 2026-10-13 "
                     "snapshot stays as published under 2026-10-14.3."),
    ("2026-10-14.5", "Owner request (2026-10-14), registered before any snapshot was evaluated with it. Display "
                     "and data-quality rules only: no ranking rule, scale, weight, gate, threshold or list size "
                     "changes, so the published lists and scores are unaffected. (1) Watchlist: the as-of price is "
                     "validated on its own (WATCHLIST_PRICE_RULE); too little history no longer hides a verified "
                     "price, and only the analyses that need history become unavailable, each naming the missing "
                     "input. (2) Return windows are stored with their start and end sessions, and list sparklines "
                     "use the same 1-year window and figures as the return table. (3) Freshness is counted in NYSE "
                     "sessions in New York time (FRESHNESS_RULE). (4) Each dataset gets one state (DATASET_STATES). "
                     "(5) A company research panel with deterministic trend, forensic (FORENSIC_RULES) and thesis "
                     "checks: thesis conditions are those recorded when a name first appeared on a list "
                     "(THESIS_TRACKING_RULE). (6) 'What changed since the previous snapshot?' (CHANGE_RULES). "
                     "(7) A comparison page (COMPARE_RULES) and an interactive scenario calculator whose results "
                     "are never stored or ranked (SCENARIO_LAB_BOUNDS). Several structures are adapted from "
                     "filingcopilot, ticker-dossier and cc-equity-research (see THIRD_PARTY_NOTICES.md)."),
    ("2026-10-14.6", "Owner request (2026-10-14), registered before any snapshot was evaluated with it. Options "
                     "watchlist: (1) each of the six option lists (calls and puts x 3, 6 and 12 months) shows up to "
                     "5 contracts instead of 10 (OPTION_RULES max_per_type_per_horizon); the windows, liquidity, "
                     "spread, delta, standard-contract and per-underlying rules and the ranking weights are "
                     "unchanged, and a list with fewer qualifying contracts is never padded. (2) Correctness: a "
                     "contract whose theta is missing (or reported as exactly zero) is not eligible, with the reason "
                     "'theta unavailable'; before this version a missing theta became zero and earned the maximum "
                     "time-decay score (OPTION_THETA_RULE). (3) Quote freshness is validated from the chain's own "
                     "snapshot timestamp (UTC, converted to the New York session date) as well as the underlying's "
                     "last trade; a contract's last trade time is reported separately and never used as its quote "
                     "time (OPTION_QUOTE_RULE). (4) A contract's earnings status is 'unknown' when the calendar was "
                     "not collected, never 'none scheduled' (OPTION_EVENT_RULE). (5) Probability of profit is "
                     "defined (PROBABILITY_OF_PROFIT_DEFINITION) and gated: a percentage may be shown only for a "
                     "calibration record that passes PROBABILITY_GATE; none exists, so every contract shows "
                     "PROBABILITY_NOT_ESTABLISHED. (6) Payoffs state their fee treatment (FEE_TREATMENT). Display "
                     "rules: the options page is always listed with its status; scenario-test flags are shown "
                     "separately from passing the research screen; pages name both the snapshot's methodology "
                     "version and the renderer version."),
    ("2026-10-14.7", "Owner request (2026-10-14), registered before any snapshot was evaluated with it. New AI "
                     "page with two new lists: (1) AI-exposed large cap (market cap of $10B or more) and AI-exposed "
                     "mid cap ($2B to $10B), up to 5 stocks each, drawn from a fixed, curated universe of US-listed "
                     "common stocks (AI_UNIVERSE) and evaluated by exactly the same data, liquidity, tradability and "
                     "fixed-scale scoring rules as the growth lists (standard profile, same scales and weights); "
                     "membership is a recorded judgement, and changing it needs a new version. (2) A top-20 "
                     "market-cap scenario test (AI_TOP20_RULE): each listed AI stock's bear, base and bull scenario "
                     "market caps at 5 and 10 years are compared with today's 20th-largest S&P 500 market cap, "
                     "conditional and never a probability. (3) A context section for private AI companies "
                     "(AI_PRIVATE_RULE): sourced, dated, labelled-unverified valuations from "
                     "config/ai_private_companies.json; not ranked, scored or tradable. No probability of reaching "
                     "the top 20 is shown, because none has out-of-sample calibration (PROBABILITY_GATE). The "
                     "existing lists, scales, weights, gates, option rules and tracking rules are unchanged; the "
                     "2026-10-13 snapshot stays as published under 2026-10-14.3. Display and reliability changes in "
                     "the same release (lazy evidence rows, sortable header buttons, saved filters) carry no "
                     "methodology change."),
    ("2026-10-14.8", "Owner request (2026-10-14), registered before any explorer data was evaluated. A separate "
                     "small-bet options explorer uses the union of large, ai_large and ai_mid weekly candidates. "
                     "Core uses existing OPTION_RULES. Long-shot requires 0.10 <= absolute delta < 0.30, open "
                     "interest >= 200, volume >= 10, positive bid and ask above bid, spread <= 20% of mid, "
                     "positive IV, nonzero theta and standard 100-share roots. Both use the existing 70-110, "
                     "150-210 and 300-430 day windows. Per tier, type, horizon and premium band, keep at most "
                     "12 contracts by the unchanged research score, ties by underlying, expiration, strike and "
                     "OCC symbol. Ask x 100 premium bands are [0,100), [100,250), [250,500), [500,1000], and "
                     "(1000,infinity). No padding, no per-underlying limit in the explorer, no short-dated "
                     "contracts. Existing weekly top-five lists, OPTION_RULES, ranking weights, stock scores "
                     "and tracking are unchanged. Browser budget filters and local slips do not rank or upload "
                     "choices. No probability is established; no unsupported expiry-frequency assertion is made."),
    ("2026-10-14.9", "Owner decision-research request, registered before any data is evaluated with these rules. "
                     "Future large/mid/small growth lists use fundamental_growth: growth 25%, earnings, quality, "
                     "balance and valuation 18.75% each, with existing scales/gates. Price momentum and relative "
                     "performance are displayed separately, never added to this score. Other lists and existing "
                     "option explorers stay unchanged. Extended means 1Y price return >150%. Annual revenue/EPS "
                     "CAGR uses matched reported fiscal years 3/5 years apart; positive endpoints required. "
                     "Quarterly growth trend compares latest YoY with previous-quarter YoY, stable within 2pp. "
                     "Margin trends compare TTM with prior TTM, stable within 1pp. Valuation percentiles use "
                     "same-list nonmissing observations, average ties, 0-100, at least two observations. "
                     "Current Alpha Vantage estimates and six-calendar-month reported insider activity are "
                     "display-only, never historical backfills or scoring inputs. SEC 10-K excerpts are dated "
                     "and attributed; unsupported fields remain n/a. Up to 61 Alpha Vantage attempts per weekly "
                     "run at existing pacing; daily earnings remain one request. New speculative options section "
                     "uses top three candidates in each growth list, up to three contracts per ticker, 30-90 DTE, "
                     "absolute delta 0.25-0.40, OI >500, volume >=10, positive two-sided markets, spread <=10% "
                     "of mid, positive IV, nonzero theta and standard 100-share roots. Select by existing score, "
                     "ties by expiry, strike, type, OCC. IV proxy averages ATM call/put IV in the nearest 20-40 "
                     "DTE expiry to 30 days; IV rank needs 252 stored comparable sessions in 366 days. Earnings "
                     "move uses ATM IV at the first expiry on/after the event within 90 days times sqrt(days/365). "
                     "Put/call ratio is standard-contract 30-90 DTE volume. Local hypothetical budgets default "
                     "to 5% overall and 1% per trade, with warnings, no storage/upload and no trading-limit "
                     "changes. Exit examples are +100%, -50% and 21 DTE, never automated or claimed optimal."),
]

DECISION_RULES = {
    "growth_bands": ("large", "mid", "small"), "max_quarters": 24,
    "growth_weights": {"growth": .25, "earnings": .1875, "quality": .1875, "balance": .1875, "valuation": .1875},
    "extended_return": 1.5, "growth_trend_band": .02, "margin_trend_band": .01,
    "cagr_years": (3, 5), "annual_match_days": 45, "insider_months": 6, "weekly_av_attempts": 61,
    "percentile": "100*(count below + (count equal-1)/2)/(n-1); same list, finite values, n>=2",
}
SPECULATIVE_RULES = {
    "top_per_list": 3, "per_ticker": 3, "min_dte": 30, "max_dte": 90,
    "min_delta": .25, "max_delta": .40, "open_interest_above": 500, "min_volume": 10,
    "max_spread_pct": .10, "iv_min_dte": 20, "iv_max_dte": 40, "iv_target_dte": 30,
    "iv_rank_sessions": 252, "iv_rank_days": 366, "options_cap_pct": 5, "trade_cap_pct": 1,
    "profit_exit": 1.0, "loss_exit": -.5, "exit_dte": 21,
}

# --- Definitions -------------------------------------------------------------------

MULTIBAGGER_DEFINITION = (
    "A 'multibagger' scenario here means a bull-case value of at least 5x today's price after five years "
    "(about 38% a year). A 2x-in-five-years outcome (about 15% a year) is shown separately as 'doubling'. "
    "For the long-horizon list the test also runs at ten years: a bull case of at least 5x (about 17.5% a "
    "year) and a base case of at least 2x (about 7% a year) within ten years. Scenario values are conditional on the stated assumptions; they are not maximum prices, targets or "
    "predictions."
)
PROBABILITY_STATEMENT = (
    "Probability not established. No model in this project has credible out-of-sample calibration, so no "
    "probability of any scenario, return or price is shown. Option deltas are not probabilities of profit."
)
DELTA_STATEMENT = (
    "Delta measures how much the option's price moves for a $1 move in the stock under a pricing model. It is "
    "sometimes read as a rough risk-neutral chance of finishing in the money, but it is NOT a calibrated "
    "probability of profit: it ignores the premium paid, uses market-implied (not real-world) odds, and "
    "changes every day."
)
DISCLAIMER = (
    "Research comparisons only. Not personalized advice, not a recommendation or an instruction to buy, sell "
    "or hold any security or option. Data can be delayed, incomplete or wrong; verify everything independently."
)

# --- Universes --------------------------------------------------------------------


@dataclass(frozen=True)
class Band:
    key: str
    title: str
    universe: str                 # "sp500", "broad", "all" (both, de-duplicated) or "ai" (AI_UNIVERSE)
    min_cap: float | None         # USD, inclusive
    max_cap: float | None         # USD, exclusive
    min_price: float
    min_dollar_volume: float      # 20-day median close x volume, USD
    max_results: int
    benchmark: str
    benchmark_name: str
    friction_bps_per_side: float  # assumed slippage + half-spread for performance tracking
    min_revenue_growth: float | None = None   # eligibility gate (TTM YoY), None = no gate
    profile: str = "standard"                 # which component weights score this list (PROFILES)
    gates: tuple = ()                         # extra eligibility gates: (metric, ">=" or "<=", value)
    scenario_years: tuple = (1, 3, 5)


BAND_TITLES_SHORT = {"large": "Large cap (S&P 500 members)", "mid": "Mid cap ($2B-$10B)",
                     "small": "Small cap ($300M-$2B)", "multibagger": "Speculative multibagger (5-10 yr)",
                     "ai_large": "AI large cap ($10B+)", "ai_mid": "AI mid cap ($2B-$10B)"}
# lists retired by a later spec version; old snapshots that contain them still render and are still tracked
LEGACY_BANDS = {"spec": {"title": "Speculative potential multibagger research candidates (retired 2026-10-14.2)",
                         "benchmark": "IWM", "friction_bps_per_side": 50.0}}

BANDS = (
    Band("large", "Large-cap growth research candidates", "sp500", None, None, 5.0, 20e6, 10,
         "SPY", "SPDR S&P 500 ETF (price return)", 15.0),
    Band("mid", "Mid-cap growth research candidates", "broad", 2e9, 10e9, 5.0, 5e6, 10,
         "IJH", "iShares Core S&P Mid-Cap ETF (price return)", 25.0),
    Band("small", "Small-cap growth research candidates", "broad", 300e6, 2e9, 2.0, 2e6, 10,
         "IWM", "iShares Russell 2000 ETF (price return)", 50.0),
    Band("multibagger", "Speculative multibagger research candidates (5-10 year horizon)", "all", 500e6, 50e9, 5.0,
         5e6, 5, "IWM", "iShares Russell 2000 ETF (price return)", 35.0, profile="long_horizon",
         gates=(("revenue_growth_ttm", ">=", 0.15), ("revenue_cagr_3y", ">=", 0.15), ("gross_margin", ">=", 0.35),
                ("reported_quarters", ">=", 12), ("dilution", "<=", 0.08), ("survival", ">=", 1)),
         scenario_years=(1, 3, 5, 10)),
    # 2026-10-14.7: AI-exposed lists. Same scoring profile, scales and weights as the growth lists; only the
    # universe (AI_UNIVERSE) and the market-cap bands differ. Benchmarks are the growth lists' own.
    Band("ai_large", "AI-exposed large-cap research candidates", "ai", 10e9, None, 5.0, 20e6, 5,
         "SPY", "SPDR S&P 500 ETF (price return)", 15.0, scenario_years=(1, 3, 5, 10)),
    Band("ai_mid", "AI-exposed mid-cap research candidates", "ai", 2e9, 10e9, 5.0, 5e6, 5,
         "IJH", "iShares Core S&P Mid-Cap ETF (price return)", 25.0, scenario_years=(1, 3, 5, 10)),
)

# --- AI-exposed universe (2026-10-14.7) ------------------------------------------------------------
# A curated, fixed list of US-listed common stocks, grouped by where the company sits in the AI supply chain.
# Membership is a judgement recorded in advance: it is hashed with the rest of the spec, so adding or removing a
# name is a new methodology version. A name that cannot be scored (a foreign filer, a new listing with little
# history, a market cap outside both bands) stays visible on the excluded page with its reason.
AI_ROLES = ("Accelerators and AI chips", "Memory and storage", "Chip equipment and test", "Networking and optical",
            "Servers and systems", "Cloud and platforms", "AI software and data", "Neoclouds and data centers",
            "Power, cooling and electrical", "Diversified, includes a frontier AI lab")
AI_UNIVERSE = (
    ("NVDA", "Accelerators and AI chips"), ("AMD", "Accelerators and AI chips"), ("AVGO", "Accelerators and AI chips"),
    ("MRVL", "Accelerators and AI chips"), ("ARM", "Accelerators and AI chips"), ("CBRS", "Accelerators and AI chips"),
    ("MU", "Memory and storage"), ("SNDK", "Memory and storage"), ("STX", "Memory and storage"),
    ("WDC", "Memory and storage"), ("P", "Memory and storage"),     # Everpure, formerly Pure Storage (PSTG until April 2026)
    ("AMAT", "Chip equipment and test"), ("LRCX", "Chip equipment and test"), ("KLAC", "Chip equipment and test"),
    ("TER", "Chip equipment and test"), ("ONTO", "Chip equipment and test"),
    ("ANET", "Networking and optical"), ("CIEN", "Networking and optical"), ("COHR", "Networking and optical"),
    ("LITE", "Networking and optical"), ("CRDO", "Networking and optical"), ("ALAB", "Networking and optical"),
    ("APH", "Networking and optical"), ("GLW", "Networking and optical"),
    ("SMCI", "Servers and systems"), ("DELL", "Servers and systems"), ("HPE", "Servers and systems"),
    ("MSFT", "Cloud and platforms"), ("GOOGL", "Cloud and platforms"), ("AMZN", "Cloud and platforms"),
    ("META", "Cloud and platforms"), ("ORCL", "Cloud and platforms"),
    ("PLTR", "AI software and data"), ("SNOW", "AI software and data"), ("NOW", "AI software and data"),
    ("DDOG", "AI software and data"), ("MDB", "AI software and data"), ("AI", "AI software and data"),
    ("PATH", "AI software and data"), ("SOUN", "AI software and data"), ("BBAI", "AI software and data"),
    ("TEM", "AI software and data"),
    ("CRWV", "Neoclouds and data centers"), ("NBIS", "Neoclouds and data centers"),
    ("IREN", "Neoclouds and data centers"), ("APLD", "Neoclouds and data centers"),
    ("CORZ", "Neoclouds and data centers"), ("EQIX", "Neoclouds and data centers"),
    ("DLR", "Neoclouds and data centers"),
    ("VRT", "Power, cooling and electrical"), ("ETN", "Power, cooling and electrical"),
    ("GEV", "Power, cooling and electrical"), ("CEG", "Power, cooling and electrical"),
    ("VST", "Power, cooling and electrical"), ("TLN", "Power, cooling and electrical"),
    ("FIX", "Power, cooling and electrical"), ("PWR", "Power, cooling and electrical"),
    ("EME", "Power, cooling and electrical"),
    ("SPCX", "Diversified, includes a frontier AI lab"),
)
AI_UNIVERSE_DEFINITION = (
    "AI-exposed universe: a fixed, curated list of US-listed common stocks (registered on the methodology page), grouped by where each "
    "company sits in the AI supply chain: chips and accelerators, memory and storage, chip equipment, networking "
    "and optical, servers, cloud platforms, AI software and data, neoclouds and data centers, power and cooling, "
    "and a diversified group that includes a frontier AI lab. Membership is a judgement recorded in advance, not a "
    "measurement and not a claim that any company will grow; adding or removing a name needs a new methodology "
    "version. Foreign filers without US-GAAP XBRL (for example TSMC and ASML) cannot be scored and are left out. "
    "Every name is then evaluated by exactly the rules of the growth lists (price and fundamentals data, liquidity, "
    "Robinhood tradability, fixed-scale scoring with the same weights). AI large cap means a market cap of $10B or "
    "more and AI mid cap $2B to $10B; the top 5 of each are shown. Where a company sits in the AI chain does not "
    "say whether it gains or loses from AI growth, and none of this predicts that any company will rank among the "
    "largest."
)
AI_TOP20_RULE = (
    "Top-20 market-cap test: the threshold is the 20th-largest market cap among the S&P 500 members that have valid "
    "data in the same weekly run (as-of close x SEC cover-page shares). For each listed AI candidate the test "
    "compares the market cap implied by its bear, base and bull scenario values at 5 and 10 years (value per share "
    "x the scenario's share count) with that threshold held at today's level. The threshold itself will probably "
    "rise over the years, so passing means 'above today's bar', not 'a top-20 company'. Scenario values are "
    "conditional on the stated assumptions; they are not forecasts and not probabilities."
)
AI_PRIVATE_RULE = (
    "Private AI companies are shown for context only: they are not ranked, scored or tradable here, and have no "
    "price, SEC financial statements or Robinhood tradability check. Each reported valuation comes from a named "
    "press or law-firm source with its date and link, is labelled unverified, and is the value at the company's "
    "last priced round or announcement, not a market capitalization. A record with a valuation but no source and "
    "date is rejected. A reported valuation is compared with the current S&P 500 market caps only when it is in US "
    "dollars. When a private company lists its shares, it joins the ranked lists only through a new methodology "
    "version."
)
AI_PROBABILITY_NOTE = (
    "No probability that any company reaches the top 20 by market cap is shown. A probability needs an "
    "out-of-sample calibration record (the methodology page lists the gate) and none exists for this question, so the page shows "
    "conditional scenarios and the scenario test instead."
)
MULTIBAGGER_RATIONALE = (
    "Why these criteria: research on the stocks that compounded many-fold over 5-10 years (for example "
    "Bessembinder's work on how concentrated long-run stock returns are, and Mayer's book 100 Baggers) finds "
    "that they usually started small enough to have room to grow, grew revenue fast for many years, had gross "
    "margins high enough to scale, did not dilute shareholders away, survived without distress, and were not "
    "priced for perfection at the start. The gates encode those minimums; the long-horizon score ranks on growth "
    "durability first and weights short-term momentum lightly. Most stocks that pass these screens will NOT "
    "become multibaggers, and no probability is estimated."
)

MARKET_CAP_DEFINITION = (
    "Market capitalization = the as-of closing price x common shares outstanding from the latest SEC cover "
    "page (dei:EntityCommonStockSharesOutstanding) filed on or before the as-of date, summed over the share "
    "classes the filing reports without class dimensions. When the cover-page count is missing, the latest "
    "diluted weighted-average share count from the income statement is used and the value is flagged."
)
LISTED_EXCHANGES = ("NYSE", "Nasdaq", "NYSE American", "NYSE Arca", "Cboe BZX")
UNIVERSE_DEFINITION = (
    "Large cap: current S&P 500 members (Wikipedia constituent list, CC BY-SA), whatever their market cap. "
    "Broad universe (mid cap and speculative): every common stock or ordinary share listed on NYSE, Nasdaq, "
    "NYSE American, NYSE Arca or Cboe BZX in the Nasdaq Trader symbol directories that is also in the SEC "
    "ticker file with a non-OTC exchange. Excluded: OTC securities, ETFs and funds, test issues, warrants, "
    "rights, units, preferred shares, notes, depositary shares, blank-check companies (names containing "
    "'Acquisition Corp'), companies in bankruptcy, and companies without US-GAAP 10-K/10-Q XBRL data (most "
    "foreign private issuers file 20-F/40-F and cannot be compared on the same basis). Mid cap: $2B to $10B. "
    "Small cap: $300M to $2B. These lists cover the screened universes only: the large-cap list is S&P 500 "
    "members, not every large company. Speculative multibagger list: "
    "the S&P 500 and the broad universe together, $500M to $50B, passing every gate in its band definition. "
    "A company with several listed share "
    "classes (one SEC CIK) is evaluated once, using the class with the highest 20-day median dollar volume. Only "
    "stocks verified as tradable on Robinhood are published (see TRADABILITY_RULE)."
)
TRADABILITY_RULE = (
    "Published only if Robinhood's read-only get_equity_tradability check reports tradeable = true, state = "
    "active, and 'tradable' for an individual account (regular hours), and the check is at most 35 days old. "
    "Not tradable, not found, unverified or stale checks exclude the stock with that reason (fail closed)."
)
TRADABILITY_MAX_AGE_DAYS = 35
TRADABILITY_CHECK_DEPTH = 15      # unverified names this far below each list's cutoff go on the to-check list
LIMITED_HISTORY_QUARTERS = 8     # fewer reported quarters than this -> 'limited operating history' flag
LIMITED_HISTORY_DAYS = 504       # fewer price bars than this (about 2 years) -> 'limited trading history' flag
MAX_FILING_AGE_DAYS = 200        # latest 10-Q/10-K older than this -> fundamentals stale, excluded
MAX_PRICE_LAG_BUSINESS_DAYS = 0  # the as-of close must be present (0 = exactly the as-of session)

# --- Stock scoring ------------------------------------------------------------------
#
# Each sub-metric maps a raw value to 0..1 with a fixed piecewise-linear scale
# (absolute thresholds, not ranks, so a score does not move because other stocks
# moved). A component is the plain average of its sub-metrics; a MISSING
# sub-metric counts as 0 and is listed - weights are never redistributed. The
# composite is the weighted sum of components x 100.
#
# Critical components: if any is entirely missing the stock is not ranked and is
# listed under 'excluded' with the reason.


@dataclass(frozen=True)
class Scale:
    lo: float          # raw value scoring 0 (or 1 when reverse)
    hi: float          # raw value scoring 1 (or 0 when reverse)
    reverse: bool = False


@dataclass(frozen=True)
class Component:
    key: str
    title: str
    weight: float
    critical: bool
    metrics: dict[str, Scale] = field(default_factory=dict)


COMPONENTS = (
    Component("growth", "Revenue growth and durability", 0.20, True, {
        "revenue_growth_ttm": Scale(0.0, 0.40),            # TTM vs prior TTM
        "revenue_cagr_3y": Scale(0.0, 0.30),
        "growth_consistency": Scale(0.25, 1.0),            # share of last 8 quarters with YoY growth > 0
        "growth_acceleration": Scale(-0.15, 0.10),         # latest-quarter YoY minus the year-earlier quarter's YoY
    }),
    Component("earnings", "Earnings and free-cash-flow growth", 0.15, False, {
        "operating_income_growth_ttm": Scale(0.0, 0.50),   # only on a positive base; negative base -> 0
        "fcf_growth_ttm": Scale(0.0, 0.50),                # only on a positive base; negative base -> 0
        "fcf_margin_change": Scale(-0.05, 0.05),           # TTM FCF margin minus prior-TTM FCF margin
    }),
    Component("quality", "Margins, return on capital and financial quality", 0.15, False, {
        "gross_margin": Scale(0.20, 0.70),
        "operating_margin": Scale(-0.10, 0.30),
        "roic": Scale(0.0, 0.25),                          # TTM operating income x (1 - 21%) / invested capital
        "accruals": Scale(0.10, -0.05),                     # (net income - operating cash flow) / assets; lower is better
    }),
    Component("balance", "Debt, liquidity, dilution and stock-based pay", 0.15, True, {
        "net_debt_to_ebitda": Scale(0.0, 4.0, reverse=True),   # net cash -> 1
        "current_ratio": Scale(0.8, 2.0),
        "dilution": Scale(0.0, 0.08, reverse=True),            # YoY change in diluted shares
        "sbc_to_revenue": Scale(0.0, 0.20, reverse=True),
    }),
    Component("valuation", "Valuation and expectations in the price", 0.15, True, {
        "ev_to_sales_per_growth": Scale(0.10, 0.60, reverse=True),  # EV/Sales / (revenue growth x 100)
        "fcf_yield": Scale(-0.02, 0.06),
        "implied_growth_gap": Scale(-0.20, 0.10),  # trailing revenue growth minus the growth the price implies
    }),
    Component("momentum", "Price momentum (12-1 month)", 0.10, True, {
        "return_12_1": Scale(-0.20, 0.60),                 # 12-month return excluding the latest month
    }),
    Component("relative", "Benchmark-relative performance", 0.10, False, {
        "excess_6m": Scale(-0.20, 0.30),
        "excess_12m": Scale(-0.30, 0.50),
    }),
)
_BY_KEY = {c.key: c for c in COMPONENTS}
LONG_HORIZON_COMPONENTS = (
    Component("growth", _BY_KEY["growth"].title, 0.30, True, _BY_KEY["growth"].metrics),
    Component("earnings", _BY_KEY["earnings"].title, 0.10, False, _BY_KEY["earnings"].metrics),
    Component("quality", _BY_KEY["quality"].title, 0.15, False, _BY_KEY["quality"].metrics),
    Component("balance", _BY_KEY["balance"].title, 0.15, True, _BY_KEY["balance"].metrics),
    Component("valuation", _BY_KEY["valuation"].title, 0.15, True, _BY_KEY["valuation"].metrics),
    Component("runway", "Runway and operating leverage", 0.10, False, {
        "log_market_cap": Scale(8.7, 10.7, reverse=True),     # $500M -> 1, $50B -> 0: room to compound
        "operating_margin_change": Scale(-0.05, 0.05),        # TTM operating margin vs the prior TTM
    }),
    Component("momentum", _BY_KEY["momentum"].title, 0.05, False, _BY_KEY["momentum"].metrics),
)
PROFILES = {"standard": COMPONENTS, "long_horizon": LONG_HORIZON_COMPONENTS}
GATE_NOTES = {
    "reported_quarters": "Number of reported quarters available (at least three years of history).",
    "survival": "1 when TTM free cash flow is positive, or cash and short-term investments cover at least two "
                "years of the current free-cash-flow burn; 0 otherwise.",
}

METRIC_NOTES = {
    "revenue_growth_ttm": "Trailing-twelve-month revenue vs the prior twelve months, from 10-Q/10-K XBRL facts.",
    "revenue_cagr_3y": "Annual revenue growth over three years (TTM vs the TTM three years earlier).",
    "growth_consistency": "Share of the last 8 reported quarters whose revenue beat the same quarter a year before.",
    "growth_acceleration": "Latest quarter's YoY revenue growth minus the YoY growth of the quarter a year before.",
    "operating_income_growth_ttm": "TTM operating income growth. A zero or negative prior-year base is "
                                   "'not meaningful' and scores 0 (it is not treated as missing).",
    "fcf_growth_ttm": "TTM free cash flow (operating cash flow minus capital expenditure) growth; a zero or "
                      "negative base scores 0.",
    "fcf_margin_change": "TTM FCF margin minus the prior TTM's FCF margin.",
    "gross_margin": "TTM gross profit / revenue (revenue minus cost of revenue when gross profit is not tagged).",
    "operating_margin": "TTM operating income / revenue.",
    "roic": "TTM operating income x (1 - 21%) / (total debt + equity - cash), latest balance sheet.",
    "accruals": "(TTM net income - TTM operating cash flow) / total assets; high accruals mean earnings are not "
                "backed by cash.",
    "net_debt_to_ebitda": "(Debt - cash and short-term investments) / TTM EBITDA (operating income + D&A). Net "
                          "cash scores 1; net debt with zero or negative EBITDA scores 0.",
    "current_ratio": "Current assets / current liabilities.",
    "dilution": "Change in diluted weighted-average shares over one year: the latest quarter vs the same quarter "
                "a year before, or the quarter before that when the latest (a fiscal Q4) has only a full-year "
                "share count.",
    "sbc_to_revenue": "TTM share-based compensation / TTM revenue.",
    "ev_to_sales_per_growth": "(EV / TTM revenue) / (TTM revenue growth in percent). Zero or negative growth "
                              "scores 0.",
    "fcf_yield": "TTM free cash flow / market capitalization.",
    "implied_growth_gap": "Trailing revenue growth minus the 5-year revenue growth the current EV implies (see "
                          "IMPLIED_GROWTH). Negative means the price already assumes faster growth than recent "
                          "results.",
    "return_12_1": "Price return from 252 to 21 trading days before the as-of date (skips the latest month).",
    "excess_6m": "6-month price return minus the benchmark's.",
    "excess_12m": "12-month price return minus the benchmark's.",
    "log_market_cap": "log10 of market capitalization; smaller companies have more room to compound "
                      "(long-horizon list only).",
    "operating_margin_change": "TTM operating margin minus the prior TTM's; positive means operating leverage "
                               "(long-horizon list only).",
}
NOT_SCORED_FACTORS = {
    "competitive_position": "Not scored: no reliable structured data source. Read the 10-K business and "
                            "competition sections.",
    "catalysts": "Not scored. The next earnings date is shown when a source provides it; other catalysts are "
                 "not tracked.",
    "customer_concentration": "Not scored. Disclosed only when the filing's XBRL tags a concentration "
                              "percentage without dimensions (rare); otherwise read the 10-K.",
}
MAX_MISSING_METRICS = 4   # more missing sub-metrics than this -> not ranked (too little evidence)
TIE_BREAK = "composite desc, then growth component desc, then ticker asc"
IMPLIED_GROWTH = {
    # 'growth the price implies': revenue CAGR needed over 5 years so that, at an exit EV/Sales of
    # `exit_ev_sales`, enterprise value grows at the discount rate.
    "discount_rate": 0.09,
    "exit_ev_sales": 3.0,
    "years": 5,
}
ROIC_TAX_RATE = 0.21
DILUTION_LOOKBACK_QUARTERS = 1   # a fiscal Q4 has only a full-year share count: compare the quarter before (2026-10-14.4)

# --- Evidence confidence ---------------------------------------------------------------
CONFIDENCE_RULES = (
    "Confidence starts at the share of sub-metrics with data. It is multiplied by 0.85 when any quarter is "
    "derived by subtracting cumulative figures, by 0.8 for a limited operating or trading history, by 0.9 "
    "when shares come from the weighted-average fallback, and by 0.9 when the latest filing is older than "
    "120 days. High >= 0.8, medium >= 0.6, otherwise low."
)

# --- Scenarios ----------------------------------------------------------------------
SCENARIO_YEARS = (1, 3, 5)


@dataclass(frozen=True)
class ScenarioRule:
    key: str
    growth_multiplier: float      # x the starting growth rate (which is capped, below)
    growth_shift: float           # added to the starting growth rate
    margin_shift: float           # added to the current FCF margin by the last scenario year (linear)
    exit_multiple_factor: float   # x the current EV/Sales, reached by the last scenario year (linear)
    dilution_shift: float         # added to the trailing annual dilution rate


SCENARIOS = (
    ScenarioRule("bear", 0.5, -0.05, -0.05, 0.5, 0.01),
    ScenarioRule("base", 1.0, 0.0, 0.0, 0.75, 0.0),
    ScenarioRule("bull", 1.3, 0.03, 0.05, 1.0, -0.005),
)
SCENARIO_GROWTH_CAP = 0.60        # starting growth rate is min(TTM revenue growth, 60%)
SCENARIO_GROWTH_FLOOR = -0.30
SCENARIO_GROWTH_FADE = 0.20       # each year, growth moves 20% of the way to the terminal rate
SCENARIO_TERMINAL_GROWTH = 0.04
SCENARIO_MIN_EV_SALES = 0.5
SCENARIO_METHOD = (
    "Revenue starts at trailing-twelve-month revenue and grows at a starting rate that fades 20% a year "
    "toward 4%. The starting rate is TTM revenue growth (capped at 60%, floored at -30%) times the scenario "
    "multiplier plus the shift. The exit EV/Sales multiple moves linearly from today's to today's x the "
    "scenario factor by the last scenario year (year 5, or year 10 for the long-horizon list; floor 0.5x). Equity value = EV + net cash (held at today's level). Shares "
    "grow at the trailing dilution rate plus the scenario shift. FCF margin assumptions are shown for "
    "transparency and consistency checks; the value itself comes from the EV/Sales path. Every number is "
    "conditional on these assumptions; none is a forecast, a target or a maximum."
)

# --- Options ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Horizon:
    key: str
    title: str
    min_dte: int
    max_dte: int


HORIZONS = (
    Horizon("3m", "About 3 months", 70, 110),
    Horizon("6m", "About 6 months", 150, 210),
    Horizon("12m", "About 12 months", 300, 430),
)
OPTION_UNDERLYINGS = (
    "The large-cap research candidates of the same week (S&P 500 members only), scored before any option "
    "data is read."
)
OPTION_TYPES = ("call", "put")
OPTION_RULES = {
    "max_per_type_per_horizon": 5,        # up to 5 calls and 5 puts per horizon (30 contracts overall; 2026-10-14.6)
    "max_per_underlying_per_horizon": 2,  # per option type
    "min_open_interest": 500,
    "min_volume": 10,
    "max_spread_pct": 0.10,        # (ask - bid) / mid
    "min_delta": 0.30,                    # applied to |delta|: calls 0.30..0.70, puts -0.70..-0.30
    "max_delta": 0.70,
    "standard_multiplier": 100,
    "max_quote_age_business_days": 0,   # the chain's underlying quote must be from the as-of session
    "require_theta": True,              # 2026-10-14.6: no theta -> not eligible (never scored as zero decay)
}

# Registered before the explorer engine exists or any contracts are evaluated with these rules.
EXPLORER_BANDS = ("large", "ai_large", "ai_mid")
EXPLORER_LONG_RULES = {"min_delta": 0.10, "max_delta_exclusive": 0.30, "min_open_interest": 200,
                       "min_volume": 10, "max_spread_pct": 0.20, "standard_multiplier": 100,
                       "require_theta": True}
EXPLORER_PREMIUM_BANDS = (("under100", 0, 100, False), ("100to250", 100, 250, False),
                          ("250to500", 250, 500, False), ("500to1000", 500, 1000, True),
                          ("over1000", 1000, None, False))
EXPLORER_PER_BAND = 12
EXPLORER_SELECTION = (
    "Separate Core and Long-shot tiers; within each tier, option type, existing expiry horizon and premium "
    "band, keep up to 12 by descending existing research score, then ascending underlying, expiration, strike "
    "and OCC symbol. Duplicate OCC symbols appear once. No padding or per-underlying cap. Premium = ask x 100: "
    "under $100; $100 to under $250; $250 to under $500; $500 through $1,000; over $1,000. "
    "Selection preserves affordable qualifying contracts but does not guarantee any contract fits a budget."
)
# list size per option type and horizon by methodology version (older snapshots render with their own limit)
OPTION_LIST_SIZE_HISTORY = (("2026-10-13.1", 5, "calls only"), ("2026-10-14.2", 10, "calls and puts"),
                            ("2026-10-14.6", 5, "calls and puts"))


def option_list_limit(version: str | None) -> int:
    """The per-list limit in force for a snapshot's methodology version."""
    limit = OPTION_LIST_SIZE_HISTORY[0][1]
    for v, n, _ in OPTION_LIST_SIZE_HISTORY:
        if version and str(version) >= v:
            limit = n
    return limit


OPTION_UNIVERSE_TEXT = (
    "Screened universe: the option chains of this week's large-cap research candidates only (up to 10 S&P 500 "
    "members, chosen by the stock screen before any option data is read). Within each chain, only standard "
    "100-share contracts expiring in the window are considered. This is not the whole option market: a contract "
    "on any other stock is never seen."
)
OPTION_TOP_DEFINITION = (
    "'Top' means the highest research score among the contracts that pass every eligibility rule. The score "
    "compares liquidity (spread and open interest), how far the stock must move to break even relative to the "
    "move the option market itself implies, and time decay. It does not forecast the stock, the option's price "
    "or the chance of a profit; the lists are a comparison of contract characteristics, not a trade list."
)
OPTION_THETA_RULE = (
    "Theta is required. A contract whose theta is missing or reported as exactly zero cannot be scored on time "
    "decay and is not eligible (rejection reason 'theta unavailable'). Missing values are kept as missing; they "
    "are never replaced by zero, which would have earned the best possible time-decay score."
)
OPTION_QUOTE_RULE = (
    "Quote freshness uses the chain's own snapshot timestamp (Cboe reports it in UTC; it is converted to the New "
    "York date) and the underlying's last trade time: the underlying must have traded in the as-of session, and "
    "the snapshot must not predate it. A contract's own last trade time only says when it last traded; an illiquid "
    "contract can carry a current bid and ask without trading for days, so that time is shown separately and is "
    "never treated as the quote time. Quotes are delayed, end-of-session values, never live."
)
OPTION_EVENT_RULE = (
    "Earnings before expiry are checked against the scheduled dates collected for the snapshot. When that calendar "
    "was not collected or failed, the status is 'unknown': it never reads as 'none scheduled'. Dates come from Alpha "
    "Vantage and are not independently verified; dividends and other events are not checked."
)
FEE_TREATMENT = (
    "No commissions, per-contract fees, regulatory fees or assignment and exercise costs are deducted: every "
    "payoff, breakeven and maximum-loss figure is before fees, so a real position loses slightly more and breaks "
    "even slightly later. Maximum loss is the premium paid at the ask x 100 shares, and a long option can lose all "
    "of it."
)
OPTION_RISK_THRESHOLDS = {
    # plain-language risk notes (display only; the ranking uses the OPTION_RANKING scales, not these)
    "spread_wide": 0.05,            # ask - bid above 5% of mid: costly to enter and exit
    "open_interest_thin": 2000,     # fewer outstanding contracts: harder to exit at a fair price
    "decay_fast": 0.003,            # theta above 0.3% of the mid per day: time works against the holder quickly
    "iv_high": 0.50,                # implied volatility above 50%: the market expects very large moves
}

# --- Probability of profit: definition, validation gate and data contract -----------------------------------
PROBABILITY_OF_PROFIT_DEFINITION = (
    "Probability of profit = the probability that the position's net profit or loss is positive at expiration "
    "after the stated premium (ask x 100) and the stated costs (here: none). It is NOT the probability of "
    "finishing in the money: a contract can expire in the money and still lose money when the intrinsic value is "
    "below the premium paid."
)
ITM_PROBABILITY_DEFINITION = (
    "Probability of finishing in the money = the probability that the stock closes beyond the strike at "
    "expiration, ignoring the premium. Even this is not shown: no calibrated estimate of it exists here either."
)
PROBABILITY_NEVER_SUBSTITUTED = (
    "Delta, the research score, the scenario weights and unvalidated pricing-model outputs (Black-Scholes "
    "sensitivities) are never shown or used as a probability of profit."
)
PROBABILITY_NOT_ESTABLISHED = "Probability not established — insufficient validated evidence."
PROBABILITY_GATE = {
    # a percentage may be displayed only for a calibration record that satisfies every rule below
    "required_fields": ("model_version", "option_type", "horizon", "evaluation_start", "evaluation_end",
                        "sample_size", "out_of_sample", "holdout_consumed", "calibration_error", "brier_score",
                        "uncertainty", "data_source"),
    "min_sample_size": 200,         # resolved contracts per option type and horizon
    "min_evaluation_days": 365,     # the evaluation period must cover at least a year of expirations
    "max_calibration_error": 0.05,  # expected calibration error (reliability gap) across probability bins
    "require_out_of_sample": True,  # forecasts recorded before outcomes were known
    "forbid_consumed_holdout": True,  # the 2022+ equity holdout evaluated on 2026-10-12 is not reusable
    "require_uncertainty": True,    # an interval, not a point, must accompany every percentage
    "per_type_and_horizon": True,   # calls and puts, and each expiry window, are calibrated separately
}
PROBABILITY_MISSING_DATA = (
    "Historical option chains with bid and ask at each weekly as-of date: none are stored (Cboe provides current "
    "chains only, and option collection was off for every published snapshot).",
    "Realized underlying prices at each contract's expiration, matched to the contracts that were listed: none, "
    "because no contracts have been listed and expired yet.",
    "A model that records a probability for each listed contract BEFORE its expiration, so the forecast can be "
    "scored against the outcome.",
    "An out-of-sample evaluation period of at least a year per option type and horizon with at least 200 resolved "
    "contracts, which cannot exist before the lists have run for that long.",
    "Transaction-cost assumptions that match the broker actually used (fees are currently not deducted).",
)
OPTION_RANKING = {
    # Weighted sum of 0..1 sub-scores; higher is better. Upside is deliberately not a ranking input.
    "liquidity": (0.45, "half spread-percentage score (0% -> 1, 10% -> 0), half open-interest score "
                        "(log scale, 500 -> 0, 20,000 -> 1)"),
    "breakeven": (0.35, "required move to breakeven at expiration (up for calls, down for puts) divided by "
                        "the one-standard-deviation implied move (IV x sqrt(years)); 0 -> 1, 1.0 or more -> 0"),
    "time_decay": (0.20, "theta per day as a share of the premium; 0% -> 1, 1.0% or more -> 0"),
}
PREMIUM_ASSUMPTION = (
    "Illustrative premium = the quoted ASK x 100 shares (the cost to open at the delayed ask). Breakevens, "
    "payoffs and maximum loss use that premium; the mid price is shown for reference only."
)
OPTION_RANKING_NOTE = (
    "Rankings compare liquidity and contract characteristics (spread, open interest, breakeven vs the implied "
    "move, time decay). They do not predict profitability. A put listed here does not mean the underlying is "
    "expected to fall: puts are ranked on the same contract characteristics for the same underlyings, not by "
    "reversing the growth rankings."
)
PAYOFF_MOVES = (-0.50, -0.30, -0.15, 0.0, 0.10, 0.20, 0.30, 0.50)
SENSITIVITY = {"days_forward": 30, "iv_shifts": (-0.05, 0.0, 0.05), "price_moves": (-0.10, 0.0, 0.10)}
RISK_FREE_RATE_NOTE = "Black-Scholes sensitivities use a 4% risk-free rate and no dividends (model estimates)."
RISK_FREE_RATE = 0.04

# --- Owner watchlist: conditional 2030 price scenarios ---------------------------------------
WATCHLIST_TARGET_DATE = "2030-12-31"
WATCHLIST_STATEMENT = (
    "Conditional 2030 price scenarios: what the price would be on December 31, 2030 IF the stated assumptions "
    "held. They are not predictions, targets, guarantees or analyst consensus; the base case is not "
    "necessarily the most likely outcome, and no probability is assigned. Horizon = the actual time from the "
    "valuation date to December 31, 2030. All figures are PRICE scenarios (distributions excluded), on the "
    "split-adjusted price basis used everywhere on this site."
)
WATCHLIST_SEPARATION = (
    "The watchlist is a custom research universe imported from the owner's list. It is kept separate from the "
    "ranked growth screens: being on the watchlist never qualifies a stock for a ranked list."
)
WATCHLIST_COMPANY_METHOD = (
    "Operating companies: revenue x EV/Sales path (the same bear/base/bull rules as the growth lists: starting "
    "growth = TTM revenue growth capped at 60% x the scenario multiplier + shift, fading 20% a year toward 4%; "
    "EV/Sales moves from today's to today's x the scenario factor by December 31, 2030), plus net cash held "
    "flat, divided by shares growing at the trailing dilution rate + the scenario shift. Margins are linked "
    "through a cross-check: each scenario's 2030 free-cash-flow margin (today's TTM FCF margin, or operating "
    "margin when FCF is unavailable, plus the scenario's margin shift: bear -5 points, base 0, bull +5) gives "
    "2030 FCF, and the implied EV/FCF multiple shows whether the value is supported by cash generation (flagged "
    "when 2030 FCF is negative or EV/FCF exceeds 60x). Requires positive TTM revenue, positive enterprise value "
    "and at least 4 reported quarters; otherwise 'Scenario unavailable'."
)
WATCHLIST_MAX_SUPPORTED_EV_FCF = 60.0
# annual TOTAL-return assumptions for the fund's underlying exposure (before fees), by exposure class;
# price return = total return - assumed fee - assumed distribution yield
ETF_EXPOSURE_RULES = (
    # (class, title, name keywords, (bear, base, bull) annual total return, assumed fee, assumed distribution yield)
    ("broad_us", "Broad US equity index", ("nasdaq-100", "nasdaq 100", "s&p 500", "total stock market",
                                            "total market", "qqq"), (0.00, 0.06, 0.10), 0.0020, 0.006),
    ("semis", "Semiconductor industry", ("semiconductor",), (-0.03, 0.06, 0.13), 0.0035, 0.004),
    ("thematic", "Single theme or industry", ("space", "artificial intelligence", " ai ", "memory", "nuclear",
                                              "uranium", "robot", "quantum", "cyber", "cloud", "ipo", "innovation",
                                              "lithography", "dram", "aerospace"), (-0.08, 0.04, 0.14), 0.0065, 0.002),
)
LEVERAGED_KEYWORDS = {"ultrapro": 3, "3x": 3, "2x": 2, "ultra ": 2, "-1x": -1, "-2x": -2, "-3x": -3,
                      "short": -1, "inverse": -1, "bear": -1}
LEVERAGED_METHOD = (
    "Leveraged and inverse ETFs: the fund resets its leverage L daily, so its long-run growth depends on the "
    "path, not just the index's cumulative return. Scenario growth rate = L x mu - L^2 x sigma^2 / 2 - (L - 1) x "
    "financing rate - fee, where mu is the underlying index's arithmetic annual return for the scenario (its "
    "exposure-class total return + sigma^2/2) and sigma its volatility (trailing 3-year realized volatility of "
    "the tracked index fund; x1.25 in the bear case, x0.85 in the bull case). This is a constant-volatility "
    "approximation: real paths differ widely, and a deep drawdown may never be recovered. If the leverage, the "
    "underlying index or its price history cannot be identified, the scenario is unavailable."
)
LEVERAGED_FINANCING_RATE = 0.04
LEVERAGED_ASSUMED_FEE = 0.0095
LEVERAGED_VOL_FACTORS = {"bear": 1.25, "base": 1.0, "bull": 0.85}
LEVERAGED_UNDERLYING_HINTS = {"qqq": "QQQ", "nasdaq-100": "QQQ", "nasdaq 100": "QQQ", "s&p 500": "SPY",
                              "semiconductor": "SOXX"}
FEE_NOTE = (
    "Fund fees and distribution yields are ASSUMED by exposure class (no permitted source provides them in the "
    "automated run); each fund's assumption is shown and flagged as unverified."
)

# --- Performance tracking ---------------------------------------------------------
TRACK_HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}   # trading days after the snapshot's as-of close
MIN_SNAPSHOTS_FOR_EVIDENCE = 52
TRACKING_METHOD = (
    "Each weekly snapshot's ranked candidates form an equal-weighted research basket per category, bought at "
    "the as-of close and held for 1, 3, 6 and 12 months. Returns are PRICE returns (dividends excluded) "
    "minus the category's assumed friction on entry and exit, compared with the category benchmark over the "
    "same days. A candidate whose prices stop (delisting, ticker change) is reported as 'return unavailable' "
    "and counted in a separate column, never silently dropped; delisting returns are not available from "
    "the data sources. Turnover is the share of a category's names that changed from the previous week. No "
    "edge is claimed before at least 52 weekly snapshots exist, and none is claimed afterwards without a "
    "statistical test."
)


# --- Display and data-quality rules (2026-10-14.5) -----------------------------------------------------
# None of these feed a score, gate or ranking. They decide how evidence is labelled and compared.

WATCHLIST_PRICE_RULE = (
    "A watchlist price is verified on its own: the latest daily bar must be the as-of session, with positive, "
    "internally consistent open/high/low/close, no unadjusted-split gap and no frozen feed. Analyses that need "
    "history (trailing returns, volatility, momentum) each require their own window and are shown as "
    "unavailable, naming the missing bars, when it is too short."
)
WATCHLIST_MIN_PRICE_BARS = 1          # bars needed to verify the as-of price itself
FRESHNESS_RULE = (
    "Data age is counted in completed NYSE sessions after the as-of session, in New York time (a session counts "
    "as completed at 16:00 ET). The page warns when more than FRESHNESS_STALE_SESSIONS sessions have passed."
)
FRESHNESS_STALE_SESSIONS = 6          # a weekly update normally lags at most five sessions
FRESHNESS_CALENDAR_DAYS = 120         # sessions listed in each page for the browser to count
DATASET_STATES = {
    "available": "Collected for the snapshot and passed validation.",
    "partial": "Collected, but some requested items failed validation or were not returned.",
    "stale": "Collected earlier than the freshness rule allows for this dataset.",
    "missing": "Not collected: disabled, not configured, or not provided by any permitted source.",
    "provider_error": "The source was called and failed (error, rejected response or request budget spent).",
}
DATASET_PARTIAL_BELOW = 0.98          # coverage below this share of requested items -> 'partial'
FORENSIC_RULES = {
    # adapted from cc-equity-research community-skills/analyze/financial-forensics.md (Apache-2.0)
    "fcf_to_net_income": {"clean_at_least": 0.85, "concerning_below": 0.70,
                          "note": "TTM free cash flow / TTM net income (not meaningful when net income <= 0)."},
    "sbc_to_revenue": {"clean_below": 0.05, "concerning_above": 0.10,
                       "note": "TTM stock-based compensation / TTM revenue."},
    "not_collected": ["receivables (days sales outstanding)", "inventory days", "non-GAAP reconciliation",
                      "deferred revenue", "capitalised software and R&D"],
}
TREND_FLAT_BAND = 0.02                # quarter-over-quarter moves within +/-2 points read as flat
THESIS_TRACKING_RULE = (
    "A name's thesis conditions are those recorded in the first snapshot where it appeared on that list, and "
    "every later snapshot checks them against current data (not a refreshed thesis). Each condition reads "
    "breached, holding or not measurable."
)
CHANGE_RULES = {
    "revenue_growth_drop": 0.05,      # TTM revenue growth down at least 5 points
    "operating_margin_drop": 0.03,
    "fcf_margin_drop": 0.03,
    "dilution_rise": 0.02,            # one-year share-count change up at least 2 points
    "score_move": 5.0,                # composite score change worth listing
}
COMPARE_RULES = {
    "max_names": 4, "min_names": 2,
    "max_quarter_end_gap_days": 45,   # TTM windows ending further apart are flagged as different periods
    "note": ("All figures come from one snapshot: prices at its as-of close, fundamentals from SEC facts filed by "
             "that date, in USD as reported. Fiscal quarters can end on different dates; windows ending more than "
             "45 days apart are flagged. Score components are comparable only between lists with the same profile "
             "and benchmark-relative figures only between names with the same benchmark."),
}
SCENARIO_LAB_BOUNDS = {
    # inputs a visitor may set; adapted from filingcopilot scenarios.py bounds (MIT)
    "starting_revenue_growth": (-0.50, 1.00), "exit_ev_to_sales": (0.1, 100.0),
    "annual_dilution": (-0.10, 0.20), "fcf_margin": (-0.50, 0.80),
    "note": ("Your inputs, not the published assumptions. The calculator applies the published scenario formula "
             "to them in your browser; nothing is stored, ranked or published, and the result is a conditional "
             "calculation, not a forecast, target or probability."),
}


def spec_dict() -> dict:
    return {
        "version": SPEC_VERSION,
        "decision_research": DECISION_RULES,
        "speculative_options": SPECULATIVE_RULES,
        "bands": [asdict(b) for b in BANDS],
        "market_cap_definition": MARKET_CAP_DEFINITION,
        "tradability": {"rule": TRADABILITY_RULE, "max_age_days": TRADABILITY_MAX_AGE_DAYS,
                        "check_depth": TRADABILITY_CHECK_DEPTH},
        "universe_definition": UNIVERSE_DEFINITION,
        "limits": {"limited_history_quarters": LIMITED_HISTORY_QUARTERS, "limited_history_days": LIMITED_HISTORY_DAYS,
                   "max_filing_age_days": MAX_FILING_AGE_DAYS, "max_price_lag": MAX_PRICE_LAG_BUSINESS_DAYS},
        "components": [{"key": c.key, "title": c.title, "weight": c.weight, "critical": c.critical,
                        "metrics": {k: asdict(v) for k, v in c.metrics.items()}} for c in COMPONENTS],
        "profiles": {name: [{"key": c.key, "weight": c.weight, "critical": c.critical,
                             "metrics": {k: asdict(v) for k, v in c.metrics.items()}} for c in comps]
                     for name, comps in PROFILES.items()},
        "gate_notes": GATE_NOTES, "multibagger_rationale": MULTIBAGGER_RATIONALE,
        "metric_notes": METRIC_NOTES,
        "not_scored": NOT_SCORED_FACTORS,
        "max_missing_metrics": MAX_MISSING_METRICS,
        "tie_break": TIE_BREAK,
        "implied_growth": IMPLIED_GROWTH,
        "roic_tax_rate": ROIC_TAX_RATE,
        "dilution_lookback_quarters": DILUTION_LOOKBACK_QUARTERS,
        "confidence": CONFIDENCE_RULES,
        "scenarios": [asdict(s) for s in SCENARIOS],
        "scenario_params": {"years": SCENARIO_YEARS, "growth_cap": SCENARIO_GROWTH_CAP,
                            "growth_floor": SCENARIO_GROWTH_FLOOR, "fade": SCENARIO_GROWTH_FADE,
                            "terminal_growth": SCENARIO_TERMINAL_GROWTH, "min_ev_sales": SCENARIO_MIN_EV_SALES},
        "multibagger": MULTIBAGGER_DEFINITION,
        "horizons": [asdict(h) for h in HORIZONS],
        "option_types": OPTION_TYPES, "premium_assumption": PREMIUM_ASSUMPTION,
        "option_rules": OPTION_RULES, "option_list_size_history": OPTION_LIST_SIZE_HISTORY,
        "explorer": {"bands": EXPLORER_BANDS, "long_shot": EXPLORER_LONG_RULES,
                     "premium_bands": EXPLORER_PREMIUM_BANDS, "per_band": EXPLORER_PER_BAND,
                     "selection": EXPLORER_SELECTION},
        "option_ranking": {k: v[0] for k, v in OPTION_RANKING.items()},
        "option_texts": {"universe": OPTION_UNIVERSE_TEXT, "top": OPTION_TOP_DEFINITION, "theta": OPTION_THETA_RULE,
                         "quote": OPTION_QUOTE_RULE, "event": OPTION_EVENT_RULE, "fees": FEE_TREATMENT,
                         "risk_thresholds": OPTION_RISK_THRESHOLDS},
        "probability_contract": {"pop": PROBABILITY_OF_PROFIT_DEFINITION, "itm": ITM_PROBABILITY_DEFINITION,
                                 "never_substituted": PROBABILITY_NEVER_SUBSTITUTED,
                                 "not_established": PROBABILITY_NOT_ESTABLISHED, "gate": PROBABILITY_GATE,
                                 "missing_data": PROBABILITY_MISSING_DATA},
        "payoff_moves": PAYOFF_MOVES,
        "sensitivity": SENSITIVITY,
        "risk_free_rate": RISK_FREE_RATE,
        "track_horizons": TRACK_HORIZONS,
        "watchlist": {"target": WATCHLIST_TARGET_DATE, "company_method": WATCHLIST_COMPANY_METHOD,
                      "max_supported_ev_fcf": WATCHLIST_MAX_SUPPORTED_EV_FCF,
                      "etf_rules": ETF_EXPOSURE_RULES, "leveraged": LEVERAGED_METHOD,
                      "leveraged_params": [LEVERAGED_KEYWORDS, LEVERAGED_FINANCING_RATE, LEVERAGED_ASSUMED_FEE,
                                           LEVERAGED_VOL_FACTORS, LEVERAGED_UNDERLYING_HINTS]},
        "legacy_bands": LEGACY_BANDS,
        "ai": {"universe": [list(x) for x in AI_UNIVERSE], "roles": AI_ROLES, "definition": AI_UNIVERSE_DEFINITION,
               "top20_rule": AI_TOP20_RULE, "private_rule": AI_PRIVATE_RULE, "probability_note": AI_PROBABILITY_NOTE},
        "display_rules": {"watchlist_price": [WATCHLIST_PRICE_RULE, WATCHLIST_MIN_PRICE_BARS],
                          "freshness": [FRESHNESS_RULE, FRESHNESS_STALE_SESSIONS, FRESHNESS_CALENDAR_DAYS],
                          "dataset_states": DATASET_STATES, "dataset_partial_below": DATASET_PARTIAL_BELOW,
                          "forensics": FORENSIC_RULES, "trend_flat_band": TREND_FLAT_BAND,
                          "thesis_tracking": THESIS_TRACKING_RULE, "changes": CHANGE_RULES,
                          "compare": COMPARE_RULES, "scenario_lab": SCENARIO_LAB_BOUNDS},
    }


def spec_hash() -> str:
    """Stable hash of every rule above; stored in each snapshot."""
    blob = json.dumps(spec_dict(), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _check() -> None:
    for name, comps in PROFILES.items():
        total = sum(c.weight for c in comps)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"{name} component weights sum to {total}, not 1")
    for b in BANDS:
        if b.profile not in PROFILES:
            raise ValueError(f"band {b.key}: unknown profile {b.profile}")
    missing_notes = {m for comps in PROFILES.values() for c in comps for m in c.metrics} - set(METRIC_NOTES)
    if missing_notes:
        raise ValueError(f"metrics without a documented definition: {sorted(missing_notes)}")
    if abs(sum(w for w, _ in OPTION_RANKING.values()) - 1.0) > 1e-9:
        raise ValueError("option ranking weights do not sum to 1")
    tickers = [t for t, _ in AI_UNIVERSE]
    if len(tickers) != len(set(tickers)):
        raise ValueError("AI_UNIVERSE lists a ticker twice")
    if {r for _, r in AI_UNIVERSE} - set(AI_ROLES):
        raise ValueError("AI_UNIVERSE uses a role that is not in AI_ROLES")


_check()
