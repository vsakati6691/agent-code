"""Render the registered methodology; all rule values remain in spec.py."""

from __future__ import annotations

from . import (
    probability,
    site_bets,
    spec,
)
from .fmt import (
    cap,
    pct,
)
from .fmt import (
    sval as sval,
)
from .site_ai import methodology_ai
from .site_layout import E
from .site_leaders import methodology as leaders_methodology

_R = spec.OPTION_RULES


OPTION_RULES_TEXT = (
    f"up to {_R['max_per_type_per_horizon']} calls and {_R['max_per_type_per_horizon']} puts per expiry window, at most "
    f"{_R['max_per_underlying_per_horizon']} per underlying per list; open interest at least {_R['min_open_interest']}; "
    f"volume at least {_R['min_volume']}; bid-ask spread at most {_R['max_spread_pct']:.0%} of the mid price; |delta| "
    f"{_R['min_delta']:g} to {_R['max_delta']:g}; standard {_R['standard_multiplier']}-share contracts only; the "
    f"underlying must have traded in the as-of session"
)


def _component_rows(components) -> str:
    return "".join(
        f'<tr><td>{E(c.title)}</td><td class="num">{c.weight:.0%}</td><td>{"yes" if c.critical else "no"}</td><td class="small">'
        + "<br>".join(
            f"<strong>{E(k)}</strong> ({'lower is better, ' if s.reverse else ''}0 at {s.lo:g}, 1 at {s.hi:g}{' reversed' if s.reverse else ''}): "
            f"{E(spec.METRIC_NOTES[k])}"
            for k, s in c.metrics.items()
        )
        + "</td></tr>"
        for c in components
    )


def methodology_page() -> str:
    external_rules = "".join(
        f"<li><strong>{E(key.replace('_', ' '))}:</strong> "
        + E(
            ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in value.items())
            if isinstance(value, dict)
            else ", ".join(value)
            if isinstance(value, tuple)
            else value
        )
        + "</li>"
        for key, value in spec.EXTERNAL_DATA_RULES.items()
    )
    comps = _component_rows(spec.COMPONENTS)
    long_comps = _component_rows(spec.LONG_HORIZON_COMPONENTS)
    growth_comps = _component_rows(spec.GROWTH_COMPONENTS)
    gates = "".join(
        f"<li>{E(spec.METRIC_NOTES.get(m, spec.GATE_NOTES.get(m, m)))} Gate: {E(op)} {v:g}</li>"
        for b in spec.BANDS
        for m, op, v in b.gates
    )
    bands = "".join(
        f"<tr><td>{E(b.title)}</td><td>{E(b.universe)}</td><td>{cap(b.min_cap) if b.min_cap else '-'} to "
        f"{cap(b.max_cap) if b.max_cap else '-'}</td><td>${b.min_price:g}</td><td>{cap(b.min_dollar_volume)}</td>"
        f"<td>{'revenue growth ≥ ' + pct(b.min_revenue_growth) if b.min_revenue_growth else '-'}</td><td>{E(b.benchmark)}</td>"
        f"<td>{b.max_results}</td></tr>"
        for b in spec.BANDS
    )
    hz = "".join(f"<li>{E(h.title)}: {h.min_dte}-{h.max_dte} days to expiration</li>" for h in spec.HORIZONS)
    rk = "".join(f"<li><strong>{E(k)} ({w:.0%})</strong>: {E(t)}</li>" for k, (w, t) in spec.OPTION_RANKING.items())
    sizes = "; ".join(f"from {v}: up to {n} per list ({what})" for v, n, what in spec.OPTION_LIST_SIZE_HISTORY)
    ps = probability.status_summary()
    cells = ", ".join(f"{k} {v}" for k, v in ps["cells"].items())
    g = spec.PROBABILITY_GATE
    gate = "".join(
        f"<li>{E(x)}</li>"
        for x in (
            f"required fields: {', '.join(g['required_fields'])}",
            f"at least {g['min_sample_size']} resolved contracts per option type and horizon",
            f"an evaluation period of at least {g['min_evaluation_days']} days of expirations",
            f"expected calibration error at most {g['max_calibration_error']:.2f}",
            "forecasts recorded out of sample, before their outcomes were known",
            "no reuse of a holdout already consumed by another decision (the 2022+ equity holdout was evaluated on 2026-10-12)",
            "an uncertainty interval accompanies every percentage",
            "calls and puts, and each expiry window, calibrated separately",
        )
    )
    missing = "".join(f"<li>{E(x)}</li>" for x in spec.PROBABILITY_MISSING_DATA)
    log = "".join(f"<li>{E(v)}: {E(t)}</li>" for v, t in spec.SPEC_CHANGELOG)
    etf = "".join(
        f'<tr><td>{E(r[1])}</td><td class="small">{E(", ".join(k.strip() for k in r[2]))}</td>'
        f'<td class="num">{" / ".join(pct(x, 0, True) for x in r[3])}</td><td class="num">{pct(r[4], 2)}</td>'
        f'<td class="num">{pct(r[5], 1)}</td></tr>'
        for r in spec.ETF_EXPOSURE_RULES
    )
    return f"""<h1>Methodology</h1><p>Registered universes, scoring rules and conditional scenario assumptions.</p>
<div class="table-wrap"><table aria-label="List definitions"><thead><tr><th>Category</th><th>Universe</th><th>Market cap</th><th>Min price</th>
<th>Min 20-day median $ volume</th><th>Gate</th><th>Benchmark</th><th>Max shown</th></tr></thead><tbody>{bands}</tbody></table></div>
<details><summary>Registration and universe definitions</summary><p>Version {E(spec.SPEC_VERSION)} (hash {E(spec.spec_hash())}). All rules were fixed
before any results were computed; a change creates a new version and results are tracked separately per version.</p>
<p>{E(spec.UNIVERSE_DEFINITION)}</p><p>{E(spec.MARKET_CAP_DEFINITION)}</p></details>
<p>Limited operating history: fewer than {spec.LIMITED_HISTORY_QUARTERS} reported quarters. Limited trading history: fewer than
{spec.LIMITED_HISTORY_DAYS} daily bars. Fundamentals older than {spec.MAX_FILING_AGE_DAYS} days exclude a stock. The as-of close
must be present. Lists are never padded: fewer than ten qualifying stocks means fewer than ten shown.</p>
<p id="price-bars">{E(spec.PRICE_BAR_RULE.replace("PRICE_RANGE_CHECK_BARS", str(spec.PRICE_RANGE_CHECK_BARS)).replace("PRICE_LISTING_GAP_DAYS", str(spec.PRICE_LISTING_GAP_DAYS)).replace("PRIVATE_HISTORY_RULE", "the private-history rule"))}</p>
<h2 id="decision-research">Growth decision research · version 2026-10-14.9</h2>
<p>New large, mid and small lists rank fundamental quality alone. Price momentum and benchmark-relative returns
are displayed separately. Annual price returns over 150% are flagged extended. Existing snapshots retain their original ranks.</p>
<div class="table-wrap"><table aria-label="Growth quality weights"><thead><tr><th>Component</th><th>Weight</th><th>Critical</th><th>Inputs and scales</th></tr></thead><tbody>{growth_comps}</tbody></table></div>
<p>Annual revenue and diluted EPS CAGR require positive full fiscal-year endpoints, matched within 45 days of
3 or 5 years apart. Latest-quarter revenue acceleration compares its YoY rate with the preceding quarter's YoY rate;
within 2 percentage points is stable. TTM margin trends compare the previous four quarters; within 1 point is stable.
Interest coverage is TTM operating income / positive interest expense. Net debt / EBITDA uses signed debt less cash
and equivalents and positive operating income plus depreciation/amortization. Incomplete debt inputs are n/a.</p>
<p>Valuation percentiles are average ranks of finite values in the same published list, scaled from 0 to 100,
with at least two observations. A higher percentile means a higher numerical value, not a better investment.
Forward P/E, PEG, analyst targets and five-category rating counts are current Alpha Vantage observations, never used
for historical backfills or scores. Insider acquisitions/disposals without Form 4 P/S codes cannot establish net market buying.
Business, growth and risk text is excerpted from identified 10-K sections and may be unavailable. Missing values always carry reasons.</p>
<h2>Legacy / AI scoring</h2><p>Each input maps to 0-1 on a fixed linear scale (absolute thresholds, not ranks). A component is the average of
its inputs. A missing input scores 0 and is shown; weights are never redistributed. A stock with a critical component entirely
missing, or more than {spec.MAX_MISSING_METRICS} missing inputs, is not ranked. Ties: {E(spec.TIE_BREAK)}.</p>
<div class="table-wrap"><table aria-label="Scoring components and scales"><thead><tr><th>Component</th><th class="num">Weight</th><th>Critical</th><th>Inputs and scales</th></tr></thead>
<tbody>{comps}</tbody></table></div>
<p>Momentum and benchmark-relative performance are separate components. {E(spec.CONFIDENCE_RULES)}</p>
<h3 id="multibagger">Speculative multibagger research candidates (5-10 years)</h3><p>{E(spec.MULTIBAGGER_RATIONALE)}</p>
<p>Eligibility gates (all must hold; a missing input fails the gate):</p><ul class="small">{gates}</ul>
<p>Weights for the multibagger list:</p>
<div class="table-wrap"><table aria-label="Long-horizon scoring components"><thead><tr><th>Component</th><th class="num">Weight</th><th>Critical</th><th>Inputs and scales</th></tr></thead>
<tbody>{long_comps}</tbody></table></div>
<h3>Robinhood tradability</h3><p>{E(spec.TRADABILITY_RULE)} Because scores use fixed scales, removing a stock that is not
tradable does not change the order of the others. Checks run in a Claude session with the read-only Robinhood tool, since
GitHub Actions cannot reach it; no account data is stored.</p>
<h3>Not scored</h3><ul>{"".join(f"<li>{E(k.replace('_', ' '))}: {E(v)}</li>" for k, v in spec.NOT_SCORED_FACTORS.items())}</ul>
<p>The strongest counterargument is the input with the largest weighted shortfall (missing critical data first).</p>
<h2>Scenarios</h2><p>{E(spec.SCENARIO_METHOD)}</p><p>{E(spec.MULTIBAGGER_DEFINITION)}</p><p>{E(spec.PROBABILITY_STATEMENT)}</p>
{methodology_ai()}
<h2>Speculative small bets · 30–90 DTE</h2>
<p>The new options section covers the top three names per growth list, up to three contracts each. Standard calls and puts
require 30–90 DTE, |delta| 0.25–0.40, OI above 500, volume at least 10, positive bid/ask, spread at most 10% of mid,
positive IV and nonzero theta. Existing liquidity/breakeven/decay ranking applies. These contracts can lose 100%.</p>
<p>ATM IV averages paired call and put IV at the closest strike, in the 20–40 DTE expiry nearest 30 days.
IV rank needs 252 comparable stored sessions within 366 days; insufficient history is n/a. Earnings move is a
constant-IV square-root-time model to the scheduled event using the first expiry at/after it, not a calibrated forecast.
Put/call ratio uses 30–90 DTE contract volumes. The browser-only hypothetical 5%/1% caps check one premium, not existing exposure.
Exit examples (+100%, −50%, 21 DTE) are illustrative and cannot guarantee execution or limit loss.</p>
<h2>Options (calls and puts)</h2><p>{E(spec.OPTION_UNDERLYINGS)}</p><ul>{hz}</ul><p>Eligibility: {E(OPTION_RULES_TEXT)}.</p>
<p>Ranking (higher is better; maximum upside is not an input):</p><ul>{rk}</ul><p>{E(spec.OPTION_RANKING_NOTE)}</p>
<p>{E(spec.DELTA_STATEMENT)}</p><p>{E(spec.PREMIUM_ASSUMPTION)} Puts: breakeven = strike - premium; payoff = max(strike - price, 0) -
premium; the required move is measured downward. {E(spec.RISK_FREE_RATE_NOTE)}</p>
<p>{E(spec.OPTION_UNIVERSE_TEXT)} {E(spec.OPTION_TOP_DEFINITION)}</p>
<p>{E(spec.OPTION_THETA_RULE)}</p><p>{E(spec.OPTION_QUOTE_RULE)}</p><p>{E(spec.OPTION_EVENT_RULE)}</p><p>{E(spec.FEE_TREATMENT)}</p>
<p>List size by methodology version (older snapshots render with the limit they were built under): {E(sizes)}.</p>
<h3 id="probability">Probability of profit: definition, validation gate and missing data</h3>
<p>{E(spec.PROBABILITY_OF_PROFIT_DEFINITION)}</p><p>{E(spec.ITM_PROBABILITY_DEFINITION)}</p><p>{E(spec.PROBABILITY_NEVER_SUBSTITUTED)}</p>
<p><strong>{E(spec.PROBABILITY_NOT_ESTABLISHED)}</strong> Status by option type and horizon: {E(cells)}.</p>
<p>A percentage may be displayed only for a calibration record that passes every rule of the gate, and the page must then show
the model version, evaluation period, sample size, calibration result and uncertainty next to it:</p><ul>{gate}</ul>
<p>Data contract for a future calibration (one append-only record per listed contract, written at listing time and completed
at expiration): {E(", ".join(probability.DATA_CONTRACT["record_fields"]))}. {E(probability.DATA_CONTRACT["resolution"])}
{E(probability.DATA_CONTRACT["storage"])} {E(probability.DATA_CONTRACT["evaluation"])}</p>
<p>Missing today, so no probability can be established:</p><ul>{missing}</ul>
<h2 id="watchlist">Watchlist: conditional 2030 price scenarios</h2><p>{E(spec.WATCHLIST_STATEMENT)}</p><p>{E(spec.WATCHLIST_SEPARATION)}</p>
<p>{E(spec.WATCHLIST_COMPANY_METHOD)}</p><p>{E(spec.LEVERAGED_METHOD)}</p><p>{E(spec.FEE_NOTE)}</p>
<div class="table-wrap"><table aria-label="ETF exposure-class assumptions"><thead><tr><th>ETF exposure class</th><th>Name keywords</th><th class="num">Bear / base / bull total return</th>
<th class="num">Assumed fee</th><th class="num">Assumed distribution yield</th></tr></thead><tbody>{etf}</tbody></table></div>
{site_bets.methodology()}
<h2>Performance tracking</h2><p>{E(spec.TRACKING_METHOD)}</p><p id="snapshot-cadence">{E(spec.SNAPSHOT_CADENCE_RULE.replace("MIN_SNAPSHOTS_FOR_EVIDENCE requirement", f"{spec.MIN_SNAPSHOTS_FOR_EVIDENCE}-snapshot requirement").replace("PUBLISHED_RECENT_SNAPSHOTS", str(spec.PUBLISHED_RECENT_SNAPSHOTS)))}</p>
<h2 id="buy-sell-desk">Buy/Sell desk · version 2026-10-17.5</h2><p>{E(spec.DESK_RULE)}</p><p>{E(spec.DESK_TRACKING)}</p>
{leaders_methodology()}
<h2 id="display-rules">Data states, research panel and comparisons</h2>
<p>These rules decide how evidence is labelled and compared. No score, gate or ranking uses them.</p>
<ul>{"".join(f"<li><strong>{E(k.replace('_', ' '))}</strong>: {E(v)}</li>" for k, v in spec.DATASET_STATES.items())}</ul>
<p>{E(spec.FRESHNESS_RULE.replace("FRESHNESS_STALE_SESSIONS", str(spec.FRESHNESS_STALE_SESSIONS)))}</p>
<p>{E(spec.WATCHLIST_PRICE_RULE.replace("PRICE_BAR_RULE", "the daily price-bar rule"))}</p>
<p>Earnings-quality checks: free cash flow / net income (clean at {spec.FORENSIC_RULES["fcf_to_net_income"]["clean_at_least"]:.2f}x
or more, concerning below {spec.FORENSIC_RULES["fcf_to_net_income"]["concerning_below"]:.2f}x) and stock-based pay / revenue
(clean below {pct(spec.FORENSIC_RULES["sbc_to_revenue"]["clean_below"])}, concerning above
{pct(spec.FORENSIC_RULES["sbc_to_revenue"]["concerning_above"])}). Not collected, so not checked:
{E(", ".join(spec.FORENSIC_RULES["not_collected"]))}.</p>
<p>{E(spec.THESIS_TRACKING_RULE)}</p>
<p>What changed: listed when trailing revenue growth falls {pct(spec.CHANGE_RULES["revenue_growth_drop"])} or more, the operating or
free-cash-flow margin falls {pct(spec.CHANGE_RULES["operating_margin_drop"])} or more, the one-year share-count change rises
{pct(spec.CHANGE_RULES["dilution_rise"])} or more, free cash flow turns negative, a new filing or quarter appears, a thesis
condition is breached, an input becomes available or unavailable, or the score moves {spec.CHANGE_RULES["score_move"]:.0f}
points or more.</p>
<p>{E(spec.COMPARE_RULES["note"])}</p><p>{E(spec.SCENARIO_LAB_BOUNDS["note"])}</p>
<p class="small">Some of these structures are adapted from open-source projects: filingcopilot (MIT; comparison on common
dates, bounded scenario inputs), ticker-dossier (MIT; dataset coverage records and evidence checks) and cc-equity-research
(Apache-2.0; thesis tracking, earnings-quality and catalyst templates, turned into fixed rules). See
<a href="https://github.com/vsakati6691/agent-code/blob/main/THIRD_PARTY_NOTICES.md" rel="noopener">THIRD_PARTY_NOTICES.md</a>.</p>
<h2>Dated public datasets · 2026-10-16.2</h2><ul>{external_rules}</ul>
<h2>Version history</h2><ul>{log}</ul>
<p><a href="https://github.com/vsakati6691/agent-code/blob/main/docs/SPEC_CHANGELOG.md">Full registration reasons and historical changelog</a>.</p>"""
