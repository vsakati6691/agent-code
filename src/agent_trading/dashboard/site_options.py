"""Options page and overview watchlist: Calls/Puts control x 3M/6M/1Y tabs, six lists of up to 5 contracts.

Everything shown comes from the stored snapshot. Observed facts (delayed quotes), assumptions (premium at the
ask, no fees), unknown or missing data, and the research score are kept in separate blocks. The page is built
and linked whatever the state of option collection, and explains that state in plain language.
"""

from __future__ import annotations

import html

from . import evidence, spec
from .fmt import money, num, pct, sval
from .price_integrity import record_note

E = html.escape
HZ_SHORT = {"3m": "3M", "6m": "6M", "12m": "1Y"}
STATE_CLASS = {"available": "ok", "partial": "warn", "stale": "warn", "missing": "muted", "provider_error": "bad"}
STATE_LABEL = {
    "available": "Available",
    "partial": "Partial",
    "stale": "Stale",
    "missing": "Not collected",
    "provider_error": "Collection failed",
}
MISSING_FLAG_WORDS = ("unavailable", "unknown", "unreadable")


def lists_of(hz: dict) -> dict:
    """{'calls': {...}, 'puts': {...}} for both the current and the older calls-only snapshot shape."""
    if "calls" in hz or "puts" in hz:
        return {k: hz.get(k) for k in ("calls", "puts")}
    old = {
        "rows": hz.get("rows", []),
        "count": len(hz.get("rows", [])),
        "considered": hz.get("considered", 0),
        "rejections": hz.get("rejections", {}),
        "status": hz.get("status", "unknown"),
    }
    return {
        "calls": old,
        "puts": {
            "rows": [],
            "count": 0,
            "considered": 0,
            "rejections": {},
            "status": "puts were not collected in this snapshot (before spec 2026-10-14.2)",
        },
    }


def distance_text(kind: str, signed) -> str:
    """Signed distance from the stock price to the breakeven at expiry, in words a reader parses in one pass."""
    if not isinstance(signed, (int, float)):
        return "n/a"
    if kind == "call":
        return (
            f"{signed:+.1%} (stock must rise)"
            if signed > 0
            else f"already past breakeven (breakeven {abs(signed):.1%} below the stock)"
        )
    return (
        f"{signed:+.1%} (stock must fall)"
        if signed < 0
        else f"already past breakeven (breakeven {abs(signed):.1%} above the stock)"
    )


def list_limit(snap: dict, data: dict | None) -> int:
    """The per-list limit the snapshot was built with (stored from 2026-10-14.6; by version before that)."""
    if data and isinstance(data.get("limit"), int):
        return data["limit"]
    return spec.option_list_limit(snap.get("spec_version"))


def events_status(x: dict, o: dict) -> tuple[str, str]:
    """('scheduled' | 'none scheduled' | 'unknown', text). Older snapshots carry no status: when the calendar
    was unavailable (earnings_note) the status is 'unknown', never 'none scheduled'."""
    st = x.get("events_status")
    if st is None:
        if o.get("earnings_note") or o.get("events_known") is False:
            st = "unknown"
        else:
            st = "scheduled" if x.get("events_before_expiry") else "none scheduled"
    if st == "scheduled":
        dates = ", ".join(str(e.get("date")) for e in x.get("events_before_expiry", []))
        return st, f"scheduled {dates} (unverified)"
    if st == "none scheduled":
        return st, "none scheduled (collected calendar, unverified)"
    return "unknown", "unknown (calendar not collected)"


def probability_text(x: dict) -> str:
    p = x.get("probability") or {}
    if p.get("status") == "calibrated" and isinstance(p.get("probability_of_profit"), (int, float)):
        return p.get("statement") or spec.PROBABILITY_NOT_ESTABLISHED
    return spec.PROBABILITY_NOT_ESTABLISHED


def version_line(snap: dict) -> str:
    v = snap.get("spec_version") or "unknown"
    same = v == spec.SPEC_VERSION
    tail = (
        ""
        if same
        else " The rules in force when this snapshot was collected (including its list size) are the snapshot's; "
        "this page only renders what was stored and never re-ranks or re-filters it."
    )
    return (
        f'<p class="small muted">Snapshot methodology <strong>{E(str(v))}</strong> (the rules the data was collected '
        f"and ranked under) · page renderer <strong>{E(spec.SPEC_VERSION)}</strong>.{tail}</p>"
    )


def status_block(snap: dict) -> dict:
    """{'state', 'label', 'class', 'headline', 'detail', 'action'}: the option dataset's state in plain language."""
    o = snap.get("options") or {}
    state, detail = evidence.options_state(snap)
    action = ""
    if state == "missing":
        headline = "Options data unavailable: option chains were not collected for this snapshot."
        detail = (
            "Collection is switched off for the weekly run (the owner's stocks-only choice on 2026-10-14, because "
            "of Cboe's terms for republishing delayed quotes). Nothing is invented: no contracts, prices or Greeks "
            "are shown."
        )
        action = (
            "Owner setup to enable it: set the repository variable DASHBOARD_OPTIONS to true (and review the "
            "data-source terms in docs/RESEARCH_DASHBOARD.md). The six lists then appear in the first weekly "
            "snapshot collected afterwards; earlier snapshots stay as published."
        )
    elif state == "provider_error":
        headline = "Options data unavailable: collection ran but produced no usable chain."
        detail = f"{detail}. No contracts, prices or Greeks are shown rather than inventing them."
        action = "The next weekly run retries automatically; the audit page lists the request counts and errors."
    elif state == "stale":
        headline = "Options data unavailable: every option chain was rejected as stale."
        detail = (
            f"{detail}. A chain is used only when the underlying traded in the as-of session and the chain's "
            "snapshot is not older than that session."
        )
        action = "The next weekly run retries automatically."
    elif state == "partial":
        headline = "Options collected with gaps: some chains could not be used."
        detail = f"{detail}. The lists below rank only the contracts from usable chains; nothing is filled in."
    else:
        headline = "Options collected and validated for this snapshot."
    short = []
    if o.get("enabled") and o.get("status") == "ok":
        for h in spec.HORIZONS:
            for kind, lst in lists_of(o.get(h.key) or {}).items():
                lim = list_limit(snap, lst)
                n = len((lst or {}).get("rows", []))
                if n < lim:
                    short.append(f"{kind} {HZ_SHORT[h.key]}: {n} of {lim}")
    if short:
        detail += (
            f" Lists with fewer than the limit (each one says why): {', '.join(short)}. A short list is not "
            "padded and no rule is relaxed."
        )
    return {
        "state": state,
        "label": STATE_LABEL[state],
        "class": STATE_CLASS[state],
        "headline": headline,
        "detail": detail,
        "action": action,
        "as_of": str(snap.get("as_of")),
        "collected_at": o.get("collected_at") or snap.get("run_finished"),
    }


def status_html(snap: dict, compact: bool = False) -> str:
    s = status_block(snap)
    kind = (
        "bad" if s["state"] in ("missing", "provider_error", "stale") else "warn" if s["state"] == "partial" else "info"
    )
    act = f' <span class="small">{E(s["action"])}</span>' if s["action"] and not compact else ""
    audit = ' <a href="audit.html#data-status">Data status</a>.' if not compact else ""
    return (
        f'<div class="banner {kind} small" id="options-status" data-state="{E(s["state"])}"><strong>'
        f'<span class="pill {E(s["class"])}">{E(s["label"])}</span> {E(s["headline"])}</strong>{E(s["detail"])}{act}{audit}</div>'
    )


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


def _row(x: dict, kind: str, rid: str, o: dict, snap: dict, fragments: dict | None = None) -> str:
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


def _list(snap: dict, h, kind: str, data: dict | None, o: dict, fragments: dict | None = None) -> str:
    plural = f"{kind}s"
    if not data:
        return f'<div class="banner warn"><strong>No {plural} listed</strong>Not collected in this snapshot.</div>'
    limit = list_limit(snap, data)
    rows = data.get("rows", [])
    rej = "; ".join(f"{E(k)} ({v})" for k, v in sorted(data.get("rejections", {}).items(), key=lambda kv: -kv[1]))
    count = (
        f'<p class="small"><strong>{len(rows)} of up to {limit}</strong> {plural} qualified · {data.get("considered", 0)} '
        f"{plural} in the {h.min_dte}-{h.max_dte} day window were checked.</p>"
    )
    why = data.get("shortfall")
    if not rows:
        why = why or f"{data.get('status', '')}."
        return count + (
            f'<div class="banner warn"><strong>No {kind} qualified</strong>{E(why)} Filters are not weakened and no '
            "contracts are invented to fill the list.</div>"
        )
    short = (
        f'<div class="banner info small"><strong>Fewer than {limit}</strong>{E(why)}</div>'
        if len(rows) < limit and why
        else ""
    )
    tid = f"o-{h.key}-{kind}"
    body = "".join(_row(x, kind, f"{tid}-{i}", o, snap, fragments) for i, x in enumerate(rows))
    head = (
        "<th class='num' data-sort='num'>#</th><th class='tk' data-sort='text'>Underlying</th>"
        "<th class='num' data-sort='text' title='Actual expiration date and calendar days remaining'>Expiry</th>"
        "<th class='num' data-sort='num'>Strike</th><th class='num hide-sm' data-sort='num' title='Underlying stock price at the "
        "as-of close'>Stock price</th><th class='num hide-sm' title='Delayed bid and ask per share'>Bid / ask</th>"
        "<th class='num' data-sort='num' title='Ask x 100 shares: the illustrative cost of one contract'>Premium*</th>"
        "<th class='num' data-sort='num' title='Stock price at expiry where the contract breaks even, and the move needed to get there'>Breakeven at expiry</th>"
        "<th class='num crit' data-sort='num' title='Most a buyer can lose: the entire premium paid'>Max loss</th>"
        "<th class='num hide-sm' data-sort='num' title='Ask minus bid, as a share of the mid price'>Spread</th>"
        "<th class='num hide-sm' data-sort='num' title='Contracts traded in the last session'>Volume</th>"
        "<th class='num hide-sm' data-sort='num' title='Open interest: contracts outstanding'>Open int.</th>"
        "<th class='num hide-sm' data-sort='num' title='Implied volatility: the yearly move the option price assumes'>IV</th>"
        "<th class='num hide-sm' data-sort='num' title='Price change per $1 move in the stock (model). Not a probability "
        "of profit'>Delta</th>"
        "<th class='num hide-sm' data-sort='num' title='Value lost per day from time decay, per share (model)'>Theta</th>"
        "<th class='hide-sm' title='Scheduled earnings before expiry; unknown when the calendar was not collected'>Earnings before expiry</th>"
        "<th class='num' data-sort='num' title='Liquidity, breakeven vs implied move and time decay (0-100); not a "
        "prediction of profit'>Research score</th>"
        "<th class='hide-sm' title='Shown as a percentage only with documented out-of-sample calibration'>Probability of profit</th>"
    )
    exclusions = (
        f'<details class="small"><summary>Why other {plural} in this window were left out</summary><p>{rej or "none left out"}.</p>'
        f'<p class="muted">Exclusion reasons apply the fixed rules: open interest ≥ {spec.OPTION_RULES["min_open_interest"]}, '
        f"volume ≥ {spec.OPTION_RULES['min_volume']}, spread ≤ {spec.OPTION_RULES['max_spread_pct']:.0%}, |delta| "
        f"{spec.OPTION_RULES['min_delta']}-{spec.OPTION_RULES['max_delta']}, implied volatility and theta present, standard "
        f"contracts, at most {spec.OPTION_RULES['max_per_underlying_per_horizon']} per underlying; the list limit keeps the "
        f"highest research scores.</p></details>"
    )
    return (
        count
        + short
        + f"""<div class="table-wrap wide"><table id="{tid}" data-table data-grouped><caption class="sr-only">{E(h.title)} {plural}</caption>
<thead><tr>{head}</tr></thead>{body}</table></div>
<p class="small">Select an underlying to show every fact, assumption, risk and payoff for that contract. <a href="downloads/{E(snap["as_of"])}_options_{h.key}_{plural}.csv" download>Download {plural} (CSV)</a></p>{exclusions}"""
    )


def options_page(
    snap: dict, daily: dict | None = None, fragments: dict | None = None, horizon: str | None = None
) -> str:
    from .site_external import rate_note
    from .site_refresh import options_section
    from .site_speculative import section as speculative_section

    o = snap.get("options") or {}
    horizons = [h for h in spec.HORIZONS if horizon is None or h.key == horizon]
    r = spec.OPTION_RULES
    head = f"""<h1>Options watchlist: calls and puts</h1>
<p class="lede">Six independently ranked lists of liquid contracts on this week's large-cap research candidates (S&amp;P 500
members): the top calls and the top puts for expiries about 3 months, 6 months and 1 year out. Research comparisons,
not recommendations.</p>
<div class="banner bad small" id="options-critical"><strong>Buying an option can lose the entire premium.</strong>Maximum loss
for every contract below is the premium paid (ask x 100), shown in its own column on every screen size. Figures are
before fees. Every contract here carries the risk of losing all of that premium.</div>
{speculative_section(snap, daily)}
{options_section(snap, daily or {})}
<h2>Weekly tracked view · {E(snap["as_of"])}</h2>
{rate_note(snap)}
{status_html(snap)}{version_line(snap)}
<details class="card small" open><summary>What these lists are, and what "top" means</summary>
<p>{E(spec.OPTION_UNIVERSE_TEXT)}</p><p>{E(spec.OPTION_TOP_DEFINITION)}</p><p>{E(spec.OPTION_RANKING_NOTE)}</p>
<p>Eligibility (fixed in advance): open interest ≥ {r["min_open_interest"]}, volume ≥ {r["min_volume"]}, spread ≤
{r["max_spread_pct"]:.0%} of mid, |delta| {r["min_delta"]}-{r["max_delta"]} (calls positive, puts negative), implied volatility and
theta present, standard 100-share contracts, at most {r["max_per_underlying_per_horizon"]} per underlying per list, up to
{r["max_per_type_per_horizon"]} per list. Expiry windows: {E(", ".join(f"{h.title.lower()} = {h.min_dte}-{h.max_dte} days" for h in spec.HORIZONS))}.</p>
<p>{E(spec.OPTION_THETA_RULE)} {E(spec.OPTION_QUOTE_RULE)} {E(spec.OPTION_EVENT_RULE)}</p></details>
<div class="banner warn small"><strong>Delta is not a probability of profit</strong>{E(spec.DELTA_STATEMENT)}</div>
<div class="banner info small"><strong>* Premium assumption and fees</strong>{E(spec.PREMIUM_ASSUMPTION)} {E(spec.FEE_TREATMENT)}
Quotes are delayed, end-of-session data from Cboe for {E(str(snap["as_of"]))}; payoffs at expiration are exact arithmetic on that
premium, while before-expiration values are Black-Scholes MODEL estimates.</div>
<div class="banner info small"><strong>Probability of profit: {E(spec.PROBABILITY_NOT_ESTABLISHED)}</strong>{E(spec.PROBABILITY_OF_PROFIT_DEFINITION)}
{E(spec.ITM_PROBABILITY_DEFINITION)} {E(spec.PROBABILITY_NEVER_SUBSTITUTED)} <a href="methodology.html#probability">Validation gate and missing data</a>.</div>"""
    probs = "".join(f"<li>{E(k)}: {E(v)}</li>" for k, v in (o.get("chain_problems") or {}).items())
    unused = (
        f'<details><summary>Chains not used ({len(o.get("chain_problems") or {})})</summary><ul class="small">{probs}</ul></details>'
        if probs
        else ""
    )
    if not o.get("enabled") or o.get("status") != "ok" or not o.get("underlyings"):
        return head + (
            '<h2>The six lists</h2><p class="small">Top 5 calls and top 5 puts for about 3 months, 6 months and 1 year '
            "to expiry will appear here once option chains are collected and validated for a snapshot (see the "
            'status above). The <a href="methodology.html">methodology</a> page has every rule.</p>' + unused
        )
    # ARIA tabs pattern over two dimensions: a type tab controls that type's three panels, a horizon tab the two
    # panels in that window, and each panel names both tabs; the ids never collide with the #call-3m view hashes
    if horizon:
        head += (
            '<nav aria-label="Option expiry lists">'
            + " ".join(f'<a class="action" href="options-{h.key}.html">{E(h.title)}</a>' for h in spec.HORIZONS)
            + "</nav><p>These larger historical lists are split by expiry. Every stored contract remains available.</p>"
        )
    hz_tabs = "".join(
        f'<button role="tab" id="otab-hz-{h.key}" aria-controls="{" ".join(f"opanel-{k}-{h.key}" for k in spec.OPTION_TYPES)}" '
        f'data-dim="hz" data-val="{h.key}" aria-selected="false">{E(HZ_SHORT[h.key])} · {E(h.title.lower())} '
        f'<span class="small muted">({h.min_dte}-{h.max_dte} d)</span></button>'
        for h in horizons
    )
    type_tabs = "".join(
        f'<button role="tab" id="otab-type-{k}" aria-controls="{" ".join(f"opanel-{k}-{h.key}" for h in horizons)}" '
        f'data-dim="type" data-val="{k}" aria-selected="false">{k.capitalize()}s</button>'
        for k in spec.OPTION_TYPES
    )
    panels = []
    for h in horizons:
        ls = lists_of(o.get(h.key) or {})
        for kind in spec.OPTION_TYPES:
            panels.append(
                f'<section data-hz="{h.key}" data-type="{kind}" id="opanel-{kind}-{h.key}" role="tabpanel" '
                f'aria-labelledby="otab-type-{kind} otab-hz-{h.key}" hidden><h2>{E(h.title)} · {kind}s · '
                f"{h.min_dte}-{h.max_dte} days to expiry</h2>{_list(snap, h, kind, ls.get(f'{kind}s'), o, fragments)}</section>"
            )
    quotes = o.get("quotes") or {}
    qrows = "".join(
        f"<li>{E(s)}: {E(q.get('quote_status', ''))}; snapshot {E(str(q.get('quote_time_utc') or 'not stored').replace('+00:00', ''))} UTC; "
        f"underlying last trade {E(str(q.get('underlying_last_trade') or 'not stored'))}</li>"
        for s, q in sorted(quotes.items())
    )
    earn = (
        f'<div class="banner warn small"><strong>Earnings dates</strong>{E(o["earnings_note"])} Every contract\'s earnings status reads "unknown".</div>'
        if o.get("earnings_note")
        else ""
    )
    return (
        head
        + f"""{summary_strip(snap)}
<p class="small">Underlyings with a valid chain: {E(", ".join(o.get("underlyings", [])) or "none")}. Use the controls to choose calls or puts and an expiry window; arrow keys move between tabs.</p>{earn}
<div data-matrix><div class="tabs seg" role="tablist" aria-label="Option type">{type_tabs}</div>
<div class="tabs" role="tablist" aria-label="Expiry horizon">{hz_tabs}</div>{"".join(panels)}</div>
<details><summary>Quote snapshot times by underlying ({len(quotes)})</summary><ul class="small">{qrows or '<li class="muted">not stored in this snapshot</li>'}</ul></details>
{unused}"""
    )


def summary_strip(snap: dict) -> str:
    """One line per option type: how many contracts each horizon list holds, linking to that view."""
    o = snap.get("options") or {}
    parts = []
    for kind in spec.OPTION_TYPES:
        cells = []
        for h in spec.HORIZONS:
            lst = lists_of(o.get(h.key) or {}).get(f"{kind}s") or {}
            n, lim = len(lst.get("rows", [])), list_limit(snap, lst)
            cells.append(f'<a href="#{kind}-{h.key}">{E(HZ_SHORT[h.key])} <strong>{n}</strong>/{lim}</a>')
        parts.append(f'<span class="chip"><strong>{kind.capitalize()}s</strong> {" · ".join(cells)}</span>')
    return f'<div class="strip" aria-label="Contracts per list">{"".join(parts)}</div>'


# --- overview: the options watchlist block --------------------------------------------------------------


def watchlist_cards(snap: dict) -> str:
    """Prominent overview block: six compact lists (or the plain-language status when none can be shown)."""
    o = snap.get("options") or {}
    intro = (
        '<p class="small">Top calls and top puts on this week\'s large-cap candidates for about 3 months, 6 months and 1 year '
        "to expiry, each list ranked on its own by liquidity, breakeven vs the implied move and time decay. Not "
        'recommendations; a long option can lose its entire premium. <a href="options.html">Full options page</a>.</p>'
    )
    if not o.get("enabled") or o.get("status") != "ok":
        return f'<h2 id="options-watchlist">Options watchlist</h2>{intro}{status_html(snap, compact=True)}'
    cards = []
    for kind in spec.OPTION_TYPES:
        for h in spec.HORIZONS:
            lst = lists_of(o.get(h.key) or {}).get(f"{kind}s") or {}
            rows = lst.get("rows", [])
            lim = list_limit(snap, lst)
            items = "".join(
                f'<li><a href="symbol/{E(x["underlying"])}.html"><strong>{E(x["underlying"])}</strong></a> {money(x["strike"])} {kind} · '
                f"exp {E(x['expiration'])} ({x['dte']}d) · premium {money(x['premium_per_contract_ask'], 0)} · "
                f'{E(distance_text(kind, x.get("breakeven_move")).split(" (")[0])} to breakeven · <span class="crit">max loss '
                f"{money(x['max_loss_per_contract'], 0)}</span> · score {num((x.get('rank_components') or {}).get('total'), 1)}</li>"
                for x in rows
            )
            body = (
                f'<ol class="tight small">{items}</ol>'
                if items
                else f'<p class="small muted">{E(lst.get("shortfall") or lst.get("status") or "none qualified")}</p>'
            )
            short = (
                f'<p class="small muted">{len(rows)} of up to {lim}: {E(lst.get("shortfall") or "")}</p>'
                if items and len(rows) < lim
                else ""
            )
            cards.append(
                f'<section class="card"><h3>{kind.capitalize()}s · {E(h.title.lower())} <span class="small muted">'
                f"({h.min_dte}-{h.max_dte} days)</span></h3>{body}{short}"
                f'<p class="small"><a href="options.html#{kind}-{h.key}">Details, risks and payoffs →</a></p></section>'
            )
    return (
        f'<h2 id="options-watchlist">Options watchlist</h2>{intro}{status_html(snap, compact=True)}'
        f'<div class="ow-grid">{"".join(cards)}</div>'
    )
