"""Stored option contract rows and detail fragments; no data calculations."""

from __future__ import annotations

import html

from . import spec
from .fmt import money, num, pct, sval
from .price_integrity import record_note
from .site_options_status import MISSING_FLAG_WORDS, distance_text, events_status, probability_text

E = html.escape

# --- contract rows ----------------------------------------------------------------------------------


def _missing_items(x: dict, o: dict) -> list[str]:
    items = [f for f in x.get("flags", []) if any(w in f for w in MISSING_FLAG_WORDS)]
    st, _ = events_status(x, o)
    if st == "unknown":
        items.append("earnings before expiry unknown (calendar not collected)")
    if not x.get("quote_time_utc"):
        items.append("chain snapshot time not stored (older snapshot or no timestamp from the source)")
    if x.get("gamma") is None or x.get("vega") is None or x.get("rho") is None:
        items.append("some Greeks unavailable")
    return items


def _score_cells(rc: dict) -> str:
    w = spec.OPTION_RANKING
    parts = []
    for k, label in (
        ("liquidity", "liquidity"),
        ("breakeven", "breakeven vs implied move"),
        ("time_decay", "time decay"),
    ):
        v = rc.get(k)
        parts.append(f"<li>{E(label)} ({w[k][0]:.0%}): {num(v) if isinstance(v, (int, float)) else 'missing'}</li>")
    return "".join(parts)


def _row(x: dict, kind: str, rid: str, o: dict, fragments: dict | None = None) -> str:
    rc = x.get("rank_components", {})
    ev_state, ev_text = events_status(x, o)
    signed = x.get("breakeven_move")
    pay = "".join(
        f'<tr><td class="num">{pct(p["move"], 0, True)}</td><td class="num">{money(p["underlying"])}</td>'
        f'<td class="num">{money(p["pl_per_contract"], 0)}</td><td class="num">{pct(p["return_on_premium"], 0, True)}</td></tr>'
        for p in x.get("payoffs", [])
    )
    sens = x.get("sensitivity") or {}
    ivh = "".join(
        f'<th class="num">IV {pct(s, 0, True).replace("%", " pts")}</th>' for s in spec.SENSITIVITY["iv_shifts"]
    )
    sgrid = "".join(
        "<tr><td class='num'>"
        + pct(row[0]["price_move"], 0, True)
        + "</td>"
        + "".join(
            f'<td class="num">{money(cl["model_value"])} ({pct(cl["change_vs_mid"], 0, True)})</td>' for cl in row
        )
        + "</tr>"
        for row in sens.get("grid", [])
    )
    risks = x.get("risks") or {}
    risk_items = "".join(
        f"<li><strong>{E(k.replace('_', ' ').capitalize())}:</strong> {E(v)}</li>"
        for k, v in risks.items()
        if k != "max_loss"
    )
    if not risk_items:
        risk_items = (
            '<li class="muted">Plain-language risk notes were not stored in this snapshot; the flags and '
            "figures above still apply.</li>"
        )
    missing = _missing_items(x, o)
    miss_html = "".join(f"<li>{E(m)}</li>" for m in missing) or '<li class="muted">none</li>'
    flags = "".join(
        f'<span class="pill">{E(record_note(x) if record_note(x) and "end-of-session" in f else f)}</span>'
        for f in x.get("flags", [])
    )
    p = x.get("probability") or {}
    why = "; ".join(p.get("why") or ["no calibration record exists"])
    greeks = " · ".join(
        f"{g} {num(x.get(g), 3) if x.get(g) is not None else 'n/a'}" for g in ("delta", "gamma", "theta", "vega", "rho")
    )
    q_time = f"{E(str(x.get('quote_time_utc')).replace('+00:00', ''))} UTC" if x.get("quote_time_utc") else "not stored"
    under_lt = x.get("underlying_last_trade") or "not stored"
    c_lt = x.get("contract_last_trade") or "none recorded"
    c_lp = (
        f" (last price {money(x['contract_last_price'])})"
        if isinstance(x.get("contract_last_price"), (int, float))
        else ""
    )
    maxloss = x.get("max_loss_per_contract")
    side = "at or below" if kind == "call" else "at or above"
    score_tip = (
        f"liquidity {num(rc.get('liquidity'))}, breakeven {num(rc.get('breakeven'))}, "
        f"time decay {num(rc.get('time_decay')) if isinstance(rc.get('time_decay'), (int, float)) else 'missing'}"
    )
    markup = f"""<tbody class="item" data-sector="{E(x["underlying"])}"><tr>
<td class="num" data-v="{x.get("rank")}">{x.get("rank")}</td>
<td class="tk"><button class="rowtoggle" type="button" aria-expanded="false" aria-controls="{rid}">
<strong>{E(x["underlying"])}</strong></button><div class="small muted">{kind} · {E(x["option"])}</div></td>
<td class="num" data-v="{E(x["expiration"])}">{E(x["expiration"])}<div class="small muted">{x["dte"]} days</div></td>
<td class="num" data-v="{sval(x["strike"])}">{money(x["strike"])}</td>
<td class="num hide-sm" data-v="{sval(x.get("spot"))}">{money(x.get("spot"))}<small>{E(record_note(x))}</small></td>
<td class="num hide-sm">{money(x["bid"])} / {money(x["ask"])}</td>
<td class="num" data-v="{sval(x["premium_per_contract_ask"])}">{money(x["premium_per_contract_ask"], 0)}<div class="small muted">{money(x["ask"])}/share</div></td>
<td class="num" data-v="{sval(x["breakeven"])}">{money(x["breakeven"])}<div class="small muted dist">{E(distance_text(kind, signed))}</div><small>{E(record_note(x))}</small></td>
<td class="num crit" data-v="{sval(maxloss)}">{money(maxloss, 0)}<div class="small muted">entire premium</div></td>
<td class="num hide-sm" data-v="{sval(x["spread_pct"])}">{pct(x["spread_pct"], 1)}</td>
<td class="num hide-sm" data-v="{sval(x.get("volume"))}">{num(x.get("volume"), 0)}</td>
<td class="num hide-sm" data-v="{sval(x.get("open_interest"))}">{num(x.get("open_interest"), 0)}</td>
<td class="num hide-sm" data-v="{sval(x.get("iv"))}">{pct(x.get("iv"), 1)}</td>
<td class="num hide-sm" data-v="{sval(x.get("delta"))}">{num(x.get("delta"))}</td>
<td class="num hide-sm" data-v="{sval(x.get("theta"))}">{num(x.get("theta"), 3)}</td>
<td class="small hide-sm ev-{E(ev_state.replace(" ", "-"))}">{E(ev_text)}</td>
<td class="num" data-v="{sval(rc.get("total"))}"><strong title="{E(score_tip)}">{num(rc.get("total"), 1)}</strong>
<div class="small muted">L {num(rc.get("liquidity"), 2)} · B {num(rc.get("breakeven"), 2)} · D {num(rc.get("time_decay"), 2) if isinstance(rc.get("time_decay"), (int, float)) else "n/a"}</div></td>
<td class="small hide-sm">{E(probability_text(x))}</td></tr>
<tr id="{rid}" class="detail" hidden><td colspan="18"><div class="pin">
<p class="crit"><strong>Maximum loss {money(maxloss, 0)}</strong>: the entire premium (ask {money(x["ask"])} x {x.get("multiplier", 100)} shares),
lost if the stock is {side} {money(x["strike"])} at expiry. Before fees. Nothing about this contract is without risk.</p>
<div class="facts">
<div><h4>Observed (delayed quote)</h4><ul class="tight small">
<li>Contract <strong>{E(x["option"])}</strong>: {E(x["underlying"])} {kind}, strike {money(x["strike"])}, expires {E(x["expiration"])} ({x["dte"]} calendar days){" · ADJUSTED contract" if x.get("adjusted") else ""}</li>
<li>Underlying price {money(x.get("spot"))} ({E(record_note(x) or x.get("underlying_price_source") or "as-of close")}); underlying last trade {E(str(under_lt))}</li>
<li>Bid {money(x["bid"])} / ask {money(x["ask"])} per share · mid {money(x.get("mid"))} (reference only) · spread {pct(x["spread_pct"], 1)} of mid</li>
<li>Quote: {E(x.get("quote_status") or "status not stored")}; snapshot time {q_time}; {E(x.get("quote_source") or "Cboe delayed quotes")}; {E(x.get("quote_delay") or "delayed")}</li>
<li>Contract last trade: {E(str(c_lt))}{c_lp}. This is when it last traded, not when it was quoted.</li>
<li>Volume {num(x.get("volume"), 0)} · open interest {num(x.get("open_interest"), 0)} · implied volatility {pct(x.get("iv"), 1)} · {E(greeks)}</li>
<li>Earnings before expiry: {E(ev_text)}; Alpha Vantage calendar, not independently verified</li></ul></div>
<div><h4>Assumptions</h4><ul class="tight small">
<li>Premium = ask x {x.get("multiplier", 100)} = {money(x["premium_per_contract_ask"], 0)} ({money(x["ask"])} per share; mid would be {money(x.get("premium_per_contract_mid"), 0)})</li>
<li>Breakeven at expiry {money(x["breakeven"])}. Distance to breakeven: {E(distance_text(kind, signed))}; required move {pct(x.get("required_move"), 1)}</li>
<li>One-standard-deviation implied move to expiry {pct(x.get("implied_move_1sd"), 1)} (IV x square root of time)</li>
<li>Fees: none deducted; every figure is before fees (see the premium and fee note at the top of the page)</li>
<li>Before-expiration figures: Black-Scholes model estimates ({E(sens.get("assumptions") or spec.RISK_FREE_RATE_NOTE)})</li></ul></div>
<div><h4>Unknown or missing</h4><ul class="tight small">{miss_html}</ul><p>{flags}</p></div>
<div><h4>Research score {num(rc.get("total"), 1)} / 100 (not a prediction)</h4><ul class="tight small">{_score_cells(rc)}</ul>
<p class="small muted">Weighted sum of the three parts. Upside is not an input, and a high score for a put is not a view that the stock will fall.</p></div>
</div>
<h4>Risks in plain language</h4><ul class="tight small">{risk_items}</ul>
<div class="grid"><div><h4>At expiration: payoff (exact arithmetic, premium at the ask, before fees)</h4><div class="table-wrap"><table aria-label="Payoff at expiration">
<thead><tr><th class="num">Stock move</th><th class="num">Stock price</th><th class="num">P/L per contract</th><th class="num">On premium</th></tr></thead>
<tbody>{pay}</tbody></table></div></div>
<div><h4>Before expiration: MODEL estimate in {sens.get("days_forward", 30)} days (not a quote)</h4><div class="table-wrap"><table aria-label="Model value before expiration">
<thead><tr><th class="num">Stock move</th>{ivh}</tr></thead><tbody>{sgrid}</tbody></table></div>
<p class="small muted">Black-Scholes estimate of value per share vs today's mid, before fees. {E(sens.get("note", ""))}</p></div></div>
<p class="small"><strong>Probability of profit: {E(probability_text(x))}</strong> {E(why)}. Definition, validation gate and
missing data: the note at the top of this page and the <a href="methodology.html#probability">methodology</a>.</p>
</div></td></tr></tbody>"""
    if fragments is None:
        return markup
    opening = f'<tr id="{rid}" class="detail" hidden><td colspan="18">'
    summary, detail = markup.split(opening, 1)
    fragments[rid] = detail.removesuffix("</td></tr></tbody>")
    fallback = f"option/{rid}.html"
    summary = summary.replace(
        "</button>", f'</button><noscript><a href="{fallback}">Full contract research</a></noscript>', 1
    )
    return (
        summary
        + opening
        + f'<div class="lazy" data-src="fragments/{rid}.json" data-page="{fallback}">'
        + f'<p>Loading contract research… <a href="{fallback}">Read the full page</a></p></div></td></tr></tbody>'
    )
