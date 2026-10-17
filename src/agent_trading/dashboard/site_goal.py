"""Plan 2030: a local calculator comparing required returns with stored research assumptions."""

import json
from datetime import date
from html import escape

from . import spec
from .fmt import money, pct, sval
from .goal import finite, required_rate
from .site_watchlist import _assumptions


def payload(snap: dict, start: date | None = None) -> dict:
    entries = (snap.get("watchlist") or {}).get("entries") or []
    candidates = {c["ticker"]: c for band in snap.get("bands", {}).values() for c in band.get("candidates", [])}
    assets, classes = [], {}
    for entry in entries:
        ticker = entry["ticker"]
        asset_class = (
            (entry.get("etf_metadata") or {}).get("exposure_class") or entry.get("asset_type") or "Unclassified"
        )
        history = entry.get("history") or (candidates.get(ticker) or {}).get("history") or {}
        observed = (history.get("drawdowns", {}).get("max_5y") or {}).get("value")
        cls = classes.setdefault(asset_class, {"name": asset_class, "drawdown": None, "basis": []})
        if finite(observed) and -1 <= observed <= 0:
            cls["drawdown"] = max(cls["drawdown"] or 0, -observed)
            cls["basis"].append(f"{ticker}: {pct(observed, 1)} over available history (up to five years)")
        scenarios = entry.get("scenarios") or {}
        rates = {key: scenarios.get(key, {}).get("annualized") for key in ("bear", "base", "bull")}
        assets.append(
            {
                "ticker": ticker,
                "asset_class": asset_class,
                "rates": rates,
                "watchlist": True,
                "price": entry.get("price"),
                "price_date": entry.get("price_date"),
                "prices": {key: scenarios.get(key, {}).get("price") for key in ("bear", "base", "bull")},
                "reason": entry.get("unavailable_reason") or "No scenario stored",
            }
        )
    for ticker in ("SPY", "QQQ"):
        if not any(a["ticker"] == ticker for a in assets):
            assets.append(
                {"ticker": ticker, "asset_class": "ETF (no stored watchlist scenario)", "rates": {}, "watchlist": False}
            )
            classes.setdefault(
                assets[-1]["asset_class"], {"name": assets[-1]["asset_class"], "drawdown": None, "basis": []}
            )
    assets.append(
        {"ticker": "Cash", "asset_class": "Cash", "rates": {k: 0 for k in ("bear", "base", "bull")}, "watchlist": False}
    )
    classes["Cash"] = {
        "name": "Cash",
        "drawdown": 0,
        "basis": ["Nominal cash: 0% return and 0% drawdown assumption; inflation excluded."],
    }
    return {
        "start_date": (start or date.today()).isoformat(),
        "snapshot_date": snap.get("as_of"),
        "assets": assets,
        "classes": list(classes.values()),
    }


def _latest_close(asset: dict, daily: dict | None) -> str:
    """Show a newer verified delayed close as context, never as a calculator input."""
    data = (daily or {}).get("data") or {}
    quote = (data.get("quotes") or {}).get(asset["ticker"]) or {}
    try:
        newer = date.fromisoformat(data["as_of"]) > date.fromisoformat(asset["price_date"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not newer or quote.get("status") != "available" or not finite(quote.get("close")) or quote["close"] <= 0:
        return ""
    return f'<div class="small muted">Latest close {money(quote["close"])} ({escape(data["as_of"])})</div>'


def _scenario_row(asset: dict, index: int, required: float | None, daily: dict | None) -> str:
    rates, prices = asset["rates"], asset["prices"]
    reason = str(asset["reason"])
    short_reason = reason if len(reason) <= 72 else reason[:69].rstrip() + "…"
    missing = f'<span title="{escape(reason)}">—</span>'
    cells = []
    for case in ("bear", "base", "bull"):
        value = prices.get(case)
        label = money(value) if finite(value) else missing
        if finite(rates.get(case)):
            label += f'<div class="small muted">{pct(rates[case], 2)}/yr</div>'
        elif case == "bear" and not any(finite(v) for v in prices.values()):
            label += f'<div class="small muted" title="{escape(reason)}">{escape(short_reason)}</div>'
        cells.append(f'<td class="num" data-v="{sval(value)}">{label}</td>')
    flag = "—"
    if finite(rates.get("base")) and required is not None:
        flag = "Meets required rate" if rates["base"] >= required else "Below required rate"
    current = money(asset["price"]) if finite(asset["price"]) else "—"
    stamp = escape(str(asset["price_date"] or "Date not stored"))
    base = f"{pct(rates['base'], 2)}/yr" if finite(rates.get("base")) else missing
    return (
        f'<tr><td>{escape(asset["ticker"])}</td><td class="num" data-v="{sval(asset["price"])}">'
        f'{current}<div class="small muted">{stamp}</div>{_latest_close(asset, daily)}</td>{"".join(cells)}'
        f'<td class="num" data-v="{sval(rates.get("base"))}">{base}</td>'
        f'<td id="goal-rate-{index}" data-v="{sval(required)}">{pct(required, 2)}/yr</td>'
        f'<td id="goal-meets-{index}" data-v="{escape(flag)}">{flag}</td></tr>'
    )


def goal_page(snap: dict, start: date | None = None, *, daily: dict | None = None) -> str:
    data = payload(snap, start)
    years = (date(2030, 12, 31) - date.fromisoformat(data["start_date"])).days / 365.25
    required = required_rate(10000, 20000, 0, years)
    weights, stress = [], []
    for i, asset in enumerate(data["assets"]):
        ticker = escape(asset["ticker"])
        weights.append(
            f'<label>{ticker} weight (%) <input id="goal-weight-{i}" type="number" min="0" max="100" step="0.01" value="0" required></label>'
        )
    # Sort display rows only: saved allocation input IDs retain their original ticker mapping.
    ordered = sorted(
        ((i, asset) for i, asset in enumerate(data["assets"]) if asset["watchlist"]),
        key=lambda item: not finite(item[1]["prices"].get("base")),
    )
    rows = [_scenario_row(asset, i, required, daily) for i, asset in ordered]
    for i, cls in enumerate(data["classes"]):
        value = f"{cls['drawdown'] * 100:.2f}" if cls["drawdown"] is not None else ""
        basis = (
            "; ".join(cls["basis"])
            or "No observed drawdown stored for this class; enter a stress assumption to compute it."
        )
        stress.append(
            f'<label>{escape(cls["name"])} drawdown (%) <input id="goal-stress-{i}" type="number" min="0" max="100" step="0.01" value="{value}"></label>'
            f'<p class="small muted">{escape(basis)}</p>'
        )
    assumptions = "".join(
        f"<details><summary>{escape(e['ticker'])}</summary>{_assumptions(e)}"
        f"<p>{escape(e.get('assumptions_note') or e.get('unavailable_reason') or 'No assumptions stored.')}</p></details>"
        for e in (snap.get("watchlist") or {}).get("entries", [])
    )
    encoded = json.dumps(data, allow_nan=False).replace("<", "\\u003c")
    return f"""<h1>Plan 2030</h1><p>Compare stored 2030 prices with the return your plan requires.</p>
<form id="goal-form"><fieldset><legend>Target and contributions</legend><div class="controls">
<label>Starting capital ($) <input id="goal-capital" type="number" min="0.01" max="1000000000000" step="0.01" value="10000" required></label>
<label>Target ($) <input id="goal-target" type="number" min="0.01" max="1000000000000" step="0.01" value="20000" required></label>
<label>Target date <input id="goal-date" type="date" value="2030-12-31" required></label>
<label>Monthly contribution ($) <input id="goal-monthly" type="number" min="0" max="1000000000000" step="0.01" value="0" required></label>
</div></fieldset><p id="goal-storage" class="small">Inputs stay in this browser and are never uploaded or stored in snapshots.</p>
<p id="goal-error" role="status"></p><section id="required-rate"><h2>Required compound annual return</h2>
<p>With contributions: <strong id="goal-required">{pct(required, 2)}/yr</strong>.
Without contributions: <strong id="goal-no-contributions">{pct(required, 2)}/yr</strong>.</p>
<p id="goal-horizon">{years:.2f} years; {int(years * 12 + 1e-9)} end-of-month contributions.</p>
<p><a href="evidence.html">Compare this required rate with what the evidence says</a>.</p></section>
<div class="controls"><span class="count" data-count="t-goal"></span><button type="button" data-reset="t-goal">Reset sort</button></div>
<div class="table-wrap"><table id="t-goal" data-table><caption>2030 price scenarios (conditional, not predictions)</caption>
<thead><tr><th data-sort="text">Ticker</th><th data-sort="num">Current price (date)</th><th data-sort="num">2030 Bear</th>
<th data-sort="num">2030 Base</th><th data-sort="num">2030 Bull</th><th data-sort="num">Base %/yr</th>
<th data-sort="num">Required %/yr</th><th data-sort="text">Base vs required</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<details><summary>How this is calculated</summary>
<p>Plan start: {data["start_date"]}. Stored scenario snapshot: {escape(str(data["snapshot_date"] or "unavailable"))}.
Current price and date are the stored scenario inputs. A newer delayed close is context only and never changes the calculation.
Changing the target date holds each stored annualised price rate constant; it does not recompute a company valuation or the displayed 2030 price.
Distributions, taxes, inflation and transaction costs are excluded. Cash earns 0%.</p>
<p>Contributions arrive at the end of each completed month. A fractional final month adds growth, but no extra contribution.
Rows with stored scenarios appear first. The flag compares only the stored base price rate with the requirement including contributions;
it does not establish feasibility or recommend a holding.</p></details>
<fieldset><legend>Optional allocation weights</legend><p>Enter weights totalling 100%. No allocation is selected by default.
Weights split the starting capital and every contribution; holdings compound separately without rebalancing.
Any weighted ticker without all three stored scenarios makes the result unavailable. SPY or QQQ may lack a stored watchlist scenario.</p>
<div class="controls">{"".join(weights)}</div></fieldset>
<h2>Portfolio ending values</h2><p id="goal-portfolio-reason">Weights must total 100%.</p>
<ul><li>Bear: <strong id="goal-ending-bear">Unavailable</strong></li><li>Base: <strong id="goal-ending-base">Unavailable</strong></li><li>Bull: <strong id="goal-ending-bull">Unavailable</strong></li></ul>
<fieldset><legend>Year-one drawdown stress</legend><p>Defaults use the largest observed drawdown among the stored watchlist members
in each asset class with available observations, over at most five years. Missing observations require an explicit input.
This stress assumes no growth in year one, applies the loss at its end to initial capital and the first twelve contributions,
then compounds at the base price rate with continuing contributions. It requires at least a one-year horizon.</p>
{"".join(stress)}<p>Stressed ending value: <strong id="goal-stress-ending">Unavailable</strong></p><p id="goal-stress-reason"></p></fieldset>
<button id="goal-reset" type="button">Reset inputs</button></form><noscript><p>JavaScript is required to change inputs and calculate portfolio and stress values. The default required rate and stored scenarios above remain readable.</p></noscript>
<h2>What would have to be true</h2><p>The target requires the compound rate above, the stated contribution schedule and the selected
scenario assumptions to hold. Company scenarios depend on revenue growth, exit multiples, margin paths and dilution.
ETF scenarios depend on their stated exposure returns, fees and distribution assumptions.</p>{assumptions}
<p>{escape(spec.PROBABILITY_STATEMENT)}</p><p>{escape(spec.DISCLAIMER)}</p>
<script id="goal-data" type="application/json">{encoded}</script>"""
