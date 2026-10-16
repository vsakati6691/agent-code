"""Small-bet explorer shell; selected public contract data and local-only calculators."""

from __future__ import annotations

import html
import json

from . import bets, spec
from .site_refresh import banner

E = html.escape


def methodology() -> str:
    return (
        f'<h2 id="small-bet-rules">Small-bet explorer · {E(spec.SPEC_VERSION)}</h2>'
        "<p>Underlying universe: the union of large, ai_large and ai_mid weekly candidates. "
        "The existing weekly top-five lists still use only large-list candidates.</p>"
        "<p>Core: existing rules, including |delta| 0.30–0.70, open interest ≥ 500, volume ≥ 10 and spread ≤ 10% of mid. "
        "Long-shot: 0.10 ≤ |delta| &lt; 0.30, open interest ≥ 200, volume ≥ 10 and spread ≤ 20% of mid. "
        "Both require positive bid, ask above bid, positive IV, nonzero theta, standard 100-share roots, and the "
        "same 70–110, 150–210 and 300–430 day windows. No short-dated options.</p>"
        f"<p>{E(spec.EXPLORER_SELECTION)}</p><p>Score weights and scales are unchanged: liquidity 45%, "
        "breakeven versus implied move 35%, time decay 20%. A cheaper premium does not establish lower risk. "
        "Required move is the favourable move still needed to reach expiration breakeven; implied move is IV × "
        "square root of years to expiry, a model scale, not a forecast or probability.</p>"
        f"<p>{E(spec.PROBABILITY_NOT_ESTABLISHED)} Delta is not a probability. No expiry-frequency claim is supported.</p>"
    )


def bets_page(snap: dict, daily: dict | None) -> str:
    context = daily or {}
    data = context.get("data") or {}
    explorer = data.get("explorer")
    head = (
        f'<header class="watch-heading"><p class="eyebrow">OPTIONS / BUDGET EXPLORER</p>'
        '<h1>Small-bet options research</h1><p class="lede">Compare qualifying contracts by the full premium '
        "you could lose. A lower price does not make a contract more likely to profit.</p></header>"
        f'<div class="banner bad" id="bets-warning"><strong>{E(bets.WARNING)}</strong>'
        "Premium and maximum loss = delayed ask × 100 shares. Fees are not deducted.</div>"
        f'{banner(snap, context)}<p class="small"><strong>{E(spec.PROBABILITY_NOT_ESTABLISHED)}</strong> '
        'Delta is not a probability. The weekly top-five lists remain on the <a href="options.html">Options page</a>.</p>'
    )
    if not explorer:
        return head + (
            '<div class="banner warn"><strong>Explorer data unavailable</strong>This daily record predates the '
            "explorer, options collection is disabled, or no compatible daily record exists. "
            "The explorer will appear after an enabled refresh under spec 2026-10-14.8 or later. "
            "Weekly lists are not substituted for this separately selected dataset.</div>"
            '<p><a href="methodology.html#small-bet-rules">Eligibility and selection rules</a></p>'
        )
    packed = {"as_of": data["as_of"], "columns": explorer["columns"], "rows": explorer["rows"]}
    encoded = json.dumps(packed, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    counts = f"{explorer['selected_count']} stored contracts from {explorer['eligible_count']} eligible contracts"
    return (
        head
        + f"""<p class="small">{E(counts)}. The selection retains up to 12 per tier, type, horizon and premium band.
No budget is guaranteed a match. Earnings dates are scheduled and unverified; a missing calendar reads unknown.</p>
<div class="bets-tools">
<section class="card" aria-labelledby="sizing-title"><h2 id="sizing-title">Budget and sizing</h2>
<label for="bet-budget">Most I can lose on one bet (USD)<input id="bet-budget" type="text" inputmode="decimal"
autocomplete="off" placeholder="Enter an amount" aria-describedby="budget-help"></label>
<p id="budget-help" class="small muted">Blank shows all stored contracts. Enter dollars and cents to filter by one-contract premium.
The calculator uses whole contracts and rounds costs up to the next cent.</p>
<label for="bet-contract">Contract for the calculator<select id="bet-contract"><option value="">Choose a contract</option></select></label>
<p id="bet-sizing" role="status" aria-live="polite">Enable JavaScript for the local calculator.</p>
<label for="bet-quantity">Number of contracts to save<input id="bet-quantity" type="number" min="1" max="9999" step="1" value="1"></label>
<p><button id="bet-save" class="action" type="button">Save to local slip</button></p>
<p id="bet-notice" role="status" aria-live="polite"></p></section>
<section class="card" aria-labelledby="slip-title"><h2 id="slip-title">Local bet slip</h2>
<p class="small muted">Choices stay in this browser's localStorage (betslip-v1). Nothing is uploaded.
Saved prices keep their original session and are not updated or checked for execution. This is not an order ticket.</p>
<ul id="bet-slip" class="bets-slip"></ul><p id="bet-slip-status" class="small" role="status" aria-live="polite"></p>
<button id="bet-clear" class="action" type="button">Clear local slip</button></section></div>
<h2>Explore contracts</h2><p class="small">Initially listed by premium. Sort by cost or the needed/implied move ratio;
the ratio compares contract characteristics and never estimates odds.</p>
<div class="controls bets-controls">
<label>Tier<select data-filter="bets-table" data-field="tier"><option value="">Both tiers</option><option>Core</option><option>Long-shot</option></select></label>
<label>Option type<select data-filter="bets-table" data-field="type"><option value="">Calls and puts</option><option value="call">Calls</option><option value="put">Puts</option></select></label>
<label>Expiry horizon<select data-filter="bets-table" data-field="horizon"><option value="">All horizons</option><option value="3m">70–110 days</option><option value="6m">150–210 days</option><option value="12m">300–430 days</option></select></label>
<button class="action" type="button" data-reset="bets-table">Reset table filters</button>
<span data-count="bets-table" aria-live="polite">{explorer["selected_count"]} stored</span></div>
<div class="table-wrap"><table id="bets-table" class="bets-table" data-table><caption class="sr-only">Options by premium and maximum loss</caption>
<thead><tr><th>Contract · tier · expiry · strike</th><th data-sort="num">Premium</th><th data-sort="num">Maximum loss</th>
<th>Breakeven</th><th data-sort="num">Needed / implied move</th><th>Delta · not a probability</th><th>Spread</th>
<th>Open interest</th><th>Volume</th><th>Earnings before expiry</th><th>Chain timestamp</th></tr></thead><tbody></tbody></table></div>
<p class="scan-empty" data-empty="bets-table" hidden>No stored contracts match this budget and these filters.
Eligibility rules are never loosened to fill a budget.</p>
<noscript><p>The interactive explorer needs JavaScript. <a href="data/daily/{E(data["as_of"])}/refresh.json">Download the selected public data</a>.</p></noscript>
<details><summary>Selection rules and limitations</summary>{methodology()}</details>
<script id="bets-data" type="application/json">{encoded}</script>"""
    )
