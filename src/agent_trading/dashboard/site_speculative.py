"""The speculative small-bet section on options.html, separate from tracked option lists."""

from __future__ import annotations

import html
import os

from . import spec
from .fmt import money, num, pct
from .site_scan import pin_button

E = html.escape


def metric(label: str, item: dict | None, percent: bool = False) -> str:
    item = item or {}
    value = item.get("value")
    rendered = (pct(value, 1) if percent else num(value, 1)) if value is not None else "n/a"
    note = item.get("reason") if value is None else item.get("model") or item.get("basis", "")
    if label == "IV rank" and value is not None:
        note = f"{item.get('sessions', 0)} comparable sessions; 0–100"
    if label == "Expected earnings move" and value is not None:
        rendered = f"±{rendered} / ±{money(item.get('dollars'))}"
        note = f"To {item.get('earnings')}; {note}"
    return f"<div><span>{E(label)}</span><strong>{E(rendered)}</strong><small>{E(note or '')}</small></div>"


def contract(row: dict) -> str:
    cells = (
        ("Cost / contract", money(row["premium"])),
        ("Max loss (100%)", money(row["max_loss"])),
        ("Breakeven at expiry", money(row["breakeven"])),
        ("Move needed", pct(row["required_move"], 1) + (" down" if row["type"] == "put" else " up")),
        ("Delta", num(row["delta"], 2)),
        ("Theta / share / day", num(row["theta"], 3)),
        ("Bid / ask", f"{money(row['bid'])} / {money(row['ask'])}"),
        ("Spread / mid", pct(row["spread_pct"], 1)),
        ("Open interest", num(row["open_interest"], 0)),
    )
    values = "".join(f"<dt>{label}</dt><dd>{E(value)}</dd>" for label, value in cells)
    ex = row["exits"]
    return f'''<article class="small-contract" data-spec-premium="{row["premium"]}">
<h4>{E(row["type"].title())} · {money(row["strike"])} strike</h4><p class="small">{E(row["expiration"])} · {row["dte"]} DTE · <span class="muted">{E(row["option"])}</span></p>
<dl class="contract-metrics">{values}</dl><p class="budget-verdict" data-budget-verdict aria-live="polite">Enter a hypothetical account value to check caps.</p>
<details class="small"><summary>Illustrative exit rules</summary><p>Take profit at +100% (premium {money(ex["profit_premium"])}),
cut at −50% ({money(ex["loss_premium"])}), or close at 21 DTE ({E(ex["close_date"])}).</p></details></article>'''


def section(snap: dict, daily: dict | None = None) -> str:
    active = daily.get("data") if daily and daily.get("data") else snap
    # Daily is authoritative when available, including when options were disabled or collection failed.
    if os.environ.get("DASHBOARD_OPTIONS", "").lower() == "false" or not (active.get("options") or {}).get("enabled"):
        return '<section id="speculative-bets"><h2>Speculative small bets</h2><p>Disabled by DASHBOARD_OPTIONS. No speculative contracts collected.</p></section>'
    focus = active.get("speculative") or {}
    tickers = focus.get("tickers") or {}
    cards = []
    for symbol, item in tickers.items():
        reason = item.get("reason")
        contexts = "".join(
            metric(label, item.get(key), percent)
            for key, label, percent in (
                ("iv", "ATM implied volatility", True),
                ("iv_rank", "IV rank", False),
                ("expected_move", "Expected earnings move", True),
                ("put_call_ratio", "Put/call volume ratio", False),
            )
        )
        if reason and not item.get("iv"):
            contexts = f'<p class="small">n/a · {E(reason)}</p>'
        contracts = "".join(contract(r) for r in item.get("contracts", []))
        if not contracts:
            contracts = f'<p class="small muted">Contracts: n/a · {E(reason or "No eligible contracts")}</p>'
        rejects = item.get("rejections") or {}
        rejection_text = "; ".join(f"{count} {why}" for why, count in sorted(rejects.items()))
        cards.append(f'''<article class="card speculative-ticker" data-ticker="{E(symbol)}">
<h3>{pin_button(symbol)}{E(symbol)}</h3><p class="small muted">Quote data as of {E(item.get("quote_time") or "n/a · source timestamp missing")}.
Underlying last trade {E(item.get("underlying_last_trade") or "n/a")}. Earnings calendar as of {E(item.get("earnings_as_of") or "n/a")}.</p>
<div class="volatility-grid">{contexts}</div><div class="contract-grid">{contracts}</div>
<details class="small"><summary>Screen exclusions</summary><p>{E(rejection_text or "n/a · no chain evaluated")}</p></details></article>''')
    if not cards:
        cards.append(
            '<p class="card">n/a · This snapshot has no speculative 30–90 DTE research. A new options-enabled collection is required.</p>'
        )
    return f'''<section id="speculative-bets" class="speculative-section">
<p class="eyebrow">SPECULATIVE / LIMITED PREMIUM / FULL LOSS POSSIBLE</p><h2>Small bets · research before risk</h2>
<p class="lede">Up to three contracts per company from the top three names in each growth list. Compare the premium at risk before exploring a contract.</p>
<div class="banner bad"><strong>Speculative: capable of a 100% loss.</strong> Long calls and puts only. Costs assume the displayed ask × 100 shares, before fees. Quotes are delayed, not live.</div>
<p class="small muted">Data as of {E(focus.get("as_of") or "n/a · not collected")}. 30–90 DTE · |delta| 0.25–0.40 · spread ≤10% of mid · OI &gt;500 · volume ≥10.
ATM IV uses paired call/put IV in a 20–40 DTE expiry nearest 30 days. IV rank needs 252 comparable stored sessions.
Pinned names outside this published top-ranked coverage have no option research here.</p>
<p class="small muted">Exit rules are planning examples, not validated or automated strategies. Gaps, spreads and IV changes can prevent the intended exit. A 100% loss remains possible.</p>
<div class="card risk-budget"><h3>Hypothetical risk budget</h3><p class="small muted">Inputs stay in this page only. This calculator does not know existing option exposure or connect to an account.</p>
<div class="budget-inputs controls"><label>Hypothetical account size (USD)<input id="spec-size" type="number" min="0" step="0.01" inputmode="decimal" placeholder="Enter a hypothetical value" autocomplete="off"></label>
<label>Options cap (%)<input id="spec-cap" type="number" min="0" max="100" step="0.1" value="{spec.SPECULATIVE_RULES["options_cap_pct"]}"></label>
<label>Per-trade cap (%)<input id="spec-trade" type="number" min="0" max="100" step="0.1" value="{spec.SPECULATIVE_RULES["trade_cap_pct"]}"></label></div>
<p id="spec-budget-summary" aria-live="polite">Enter a hypothetical account value to calculate the two caps.</p></div>
<label class="small">Ticker view <select id="spec-pin-filter"><option value="all">All top-ranked tickers</option><option value="pinned">Pinned in this coverage</option></select></label>
<p id="spec-empty" hidden>No pinned tickers in this coverage. Pin one of the names below or choose All top-ranked tickers.</p>
{"".join(cards)}<noscript><p>Enable JavaScript for hypothetical budget warnings and pin filtering.</p></noscript></section>'''
