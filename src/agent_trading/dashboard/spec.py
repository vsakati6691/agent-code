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

SPEC_VERSION = "2026-10-13.2"
SPEC_CHANGELOG = [
    ("2026-10-13.1", "Initial pre-registered rules, written before any dashboard results were computed."),
    ("2026-10-13.2", "Data-integrity fix found in the first 25-stock smoke test, before any snapshot was published: "
                     "a company with several listed share classes (e.g. GOOG and GOOGL) is evaluated once, using "
                     "its most liquid class. No scoring rule, scale or weight changed."),
]

# --- Definitions -------------------------------------------------------------------

MULTIBAGGER_DEFINITION = (
    "A 'multibagger' scenario here means a bull-case value of at least 5x today's price after five years "
    "(about 38% a year). A 2x-in-five-years outcome (about 15% a year) is shown separately as 'doubling'. "
    "Scenario values are conditional on the stated assumptions; they are not maximum prices, targets or "
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
    universe: str                 # "sp500" or "broad"
    min_cap: float | None         # USD, inclusive
    max_cap: float | None         # USD, exclusive
    min_price: float
    min_dollar_volume: float      # 20-day median close x volume, USD
    max_results: int
    benchmark: str
    benchmark_name: str
    friction_bps_per_side: float  # assumed slippage + half-spread for performance tracking
    min_revenue_growth: float | None = None   # eligibility gate (TTM YoY), None = no gate


BANDS = (
    Band("large", "Large-cap growth research candidates", "sp500", None, None, 5.0, 20e6, 10,
         "SPY", "SPDR S&P 500 ETF (price return)", 15.0),
    Band("mid", "Mid-cap growth research candidates", "broad", 2e9, 10e9, 5.0, 5e6, 10,
         "IJH", "iShares Core S&P Mid-Cap ETF (price return)", 25.0),
    Band("spec", "Speculative potential multibagger research candidates", "broad", 300e6, 2e9, 2.0, 2e6, 10,
         "IWM", "iShares Russell 2000 ETF (price return)", 50.0, min_revenue_growth=0.20),
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
    "Speculative: $300M to $2B with trailing revenue growth of at least 20%. A company with several listed share "
    "classes (one SEC CIK) is evaluated once, using the class with the highest 20-day median dollar volume."
)
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
    "dilution": "Change in diluted weighted-average shares, latest quarter vs a year before.",
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
    margin_shift: float           # added to the current FCF margin by year 5 (linear)
    exit_multiple_factor: float   # x the current EV/Sales, reached by year 5 (linear)
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
    "scenario factor by year 5 (floor 0.5x). Equity value = EV + net cash (held at today's level). Shares "
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
OPTION_RULES = {
    "max_per_horizon": 5,
    "max_per_underlying_per_horizon": 2,
    "min_open_interest": 500,
    "min_volume": 10,
    "max_spread_pct": 0.10,        # (ask - bid) / mid
    "min_delta": 0.30,
    "max_delta": 0.70,
    "standard_multiplier": 100,
    "max_quote_age_business_days": 0,   # the chain's underlying quote must be from the as-of session
}
OPTION_RANKING = {
    # Weighted sum of 0..1 sub-scores; higher is better. Upside is deliberately not a ranking input.
    "liquidity": (0.45, "half spread-percentage score (0% -> 1, 10% -> 0), half open-interest score "
                        "(log scale, 500 -> 0, 20,000 -> 1)"),
    "breakeven": (0.35, "breakeven move at expiration divided by the one-standard-deviation implied move "
                        "(IV x sqrt(years)); 0 -> 1, 1.0 or more -> 0"),
    "time_decay": (0.20, "theta per day as a share of the premium; 0% -> 1, 1.0% or more -> 0"),
}
PAYOFF_MOVES = (-0.30, -0.15, 0.0, 0.10, 0.20, 0.30, 0.50)
SENSITIVITY = {"days_forward": 30, "iv_shifts": (-0.05, 0.0, 0.05), "price_moves": (-0.10, 0.0, 0.10)}
RISK_FREE_RATE_NOTE = "Black-Scholes sensitivities use a 4% risk-free rate and no dividends (model estimates)."
RISK_FREE_RATE = 0.04

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


def spec_dict() -> dict:
    return {
        "version": SPEC_VERSION,
        "bands": [asdict(b) for b in BANDS],
        "market_cap_definition": MARKET_CAP_DEFINITION,
        "universe_definition": UNIVERSE_DEFINITION,
        "limits": {"limited_history_quarters": LIMITED_HISTORY_QUARTERS, "limited_history_days": LIMITED_HISTORY_DAYS,
                   "max_filing_age_days": MAX_FILING_AGE_DAYS, "max_price_lag": MAX_PRICE_LAG_BUSINESS_DAYS},
        "components": [{"key": c.key, "title": c.title, "weight": c.weight, "critical": c.critical,
                        "metrics": {k: asdict(v) for k, v in c.metrics.items()}} for c in COMPONENTS],
        "metric_notes": METRIC_NOTES,
        "not_scored": NOT_SCORED_FACTORS,
        "max_missing_metrics": MAX_MISSING_METRICS,
        "tie_break": TIE_BREAK,
        "implied_growth": IMPLIED_GROWTH,
        "roic_tax_rate": ROIC_TAX_RATE,
        "confidence": CONFIDENCE_RULES,
        "scenarios": [asdict(s) for s in SCENARIOS],
        "scenario_params": {"years": SCENARIO_YEARS, "growth_cap": SCENARIO_GROWTH_CAP,
                            "growth_floor": SCENARIO_GROWTH_FLOOR, "fade": SCENARIO_GROWTH_FADE,
                            "terminal_growth": SCENARIO_TERMINAL_GROWTH, "min_ev_sales": SCENARIO_MIN_EV_SALES},
        "multibagger": MULTIBAGGER_DEFINITION,
        "horizons": [asdict(h) for h in HORIZONS],
        "option_rules": OPTION_RULES,
        "option_ranking": {k: v[0] for k, v in OPTION_RANKING.items()},
        "payoff_moves": PAYOFF_MOVES,
        "sensitivity": SENSITIVITY,
        "risk_free_rate": RISK_FREE_RATE,
        "track_horizons": TRACK_HORIZONS,
    }


def spec_hash() -> str:
    """Stable hash of every rule above; stored in each snapshot."""
    blob = json.dumps(spec_dict(), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _check() -> None:
    total = sum(c.weight for c in COMPONENTS)
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"component weights sum to {total}, not 1")
    missing_notes = {m for c in COMPONENTS for m in c.metrics} - set(METRIC_NOTES)
    if missing_notes:
        raise ValueError(f"metrics without a documented definition: {sorted(missing_notes)}")
    if abs(sum(w for w, _ in OPTION_RANKING.values()) - 1.0) > 1e-9:
        raise ValueError("option ranking weights do not sum to 1")


_check()
