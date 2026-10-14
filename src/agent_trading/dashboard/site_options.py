"""Options page: Calls/Puts toggle x 3/6/12-month expiry tabs (six lists of up to 10 contracts)."""
from __future__ import annotations

import html

from . import spec
from .fmt import money, num, pct, sval

E = html.escape


def lists_of(hz: dict) -> dict:
    """{'calls': {...}, 'puts': {...}} for both the current and the older calls-only snapshot shape."""
    if "calls" in hz or "puts" in hz:
        return {k: hz.get(k) for k in ("calls", "puts")}
    old = {"rows": hz.get("rows", []), "count": len(hz.get("rows", [])), "considered": hz.get("considered", 0),
           "rejections": hz.get("rejections", {}), "status": hz.get("status", "unknown")}
    return {"calls": old, "puts": {"rows": [], "count": 0, "considered": 0, "rejections": {},
                                   "status": "puts were not collected in this snapshot (before spec 2026-10-14.2)"}}


def _row(x: dict, kind: str, rid: str) -> str:
    rc = x.get("rank_components", {})
    ev = ", ".join(f'{e["date"]}' for e in x.get("events_before_expiry", [])) or "none scheduled"
    req = x.get("required_move", abs(x.get("breakeven_move") or 0))
    direction = "up" if kind == "call" else "down"
    pay = "".join(f'<tr><td class="num">{pct(p["move"], 0, True)}</td><td class="num">{money(p["underlying"])}</td>'
                  f'<td class="num">{money(p["pl_per_contract"], 0)}</td><td class="num">{pct(p["return_on_premium"], 0, True)}</td></tr>'
                  for p in x.get("payoffs", []))
    sens = x.get("sensitivity") or {}
    ivh = "".join(f'<th class="num">IV {pct(s, 0, True).replace("%", " pts")}</th>' for s in spec.SENSITIVITY["iv_shifts"])
    sgrid = "".join("<tr><td class='num'>" + pct(row[0]["price_move"], 0, True) + "</td>" + "".join(
        f'<td class="num">{money(cl["model_value"])} ({pct(cl["change_vs_mid"], 0, True)})</td>' for cl in row) + "</tr>"
        for row in sens.get("grid", []))
    flags = "".join(f'<span class="pill">{E(f)}</span>' for f in x.get("flags", []))
    return f"""<tbody class="item" data-sector="{E(x["underlying"])}"><tr>
<td class="num sticky" data-v="{x.get("rank")}">{x.get("rank")}</td>
<td class="sticky2"><button class="rowtoggle" type="button" aria-expanded="false" aria-controls="{rid}">
<strong>{E(x["underlying"])}</strong></button><div class="small muted">{kind}</div></td>
<td class="num" data-v="{E(x["expiration"])}">{E(x["expiration"])}</td><td class="num" data-v="{x["dte"]}">{x["dte"]}</td>
<td class="num" data-v="{sval(x["strike"])}">{money(x["strike"])}</td>
<td class="num" data-v="{sval(x.get("spot"))}">{money(x.get("spot"))}</td>
<td class="num">{money(x["bid"])} / {money(x["ask"])}</td>
<td class="num" data-v="{sval(x["spread_pct"])}">{pct(x["spread_pct"], 1)}</td>
<td class="num" data-v="{sval(x["premium_per_contract_ask"])}">{money(x["premium_per_contract_ask"], 0)}</td>
<td class="num" data-v="{sval(x["breakeven"])}">{money(x["breakeven"])}</td>
<td class="num" data-v="{sval(req)}">{pct(req, 1)} {direction}</td>
<td class="num" data-v="{sval(x["max_loss_per_contract"])}">{money(x["max_loss_per_contract"], 0)}</td>
<td class="num" data-v="{sval(x.get("volume"))}">{num(x.get("volume"), 0)}</td>
<td class="num" data-v="{sval(x.get("open_interest"))}">{num(x.get("open_interest"), 0)}</td>
<td class="num" data-v="{sval(x.get("iv"))}">{pct(x.get("iv"), 1)}</td>
<td class="num" data-v="{sval(x.get("delta"))}">{num(x.get("delta"))}</td>
<td class="num" data-v="{sval(x.get("theta"))}">{num(x.get("theta"), 3)}</td>
<td class="num" data-v="{sval(rc.get("total"))}"><strong>{num(rc.get("total"), 1)}</strong></td>
<td class="small">{E(ev)}</td></tr>
<tr id="{rid}" class="detail" hidden><td colspan="19"><div class="pin">
<p class="small"><strong>{E(x["option"])}</strong> · multiplier {x.get("multiplier", 100)}{" · ADJUSTED contract" if x.get("adjusted") else ""}
· mid {money(x.get("mid"))} (reference only) · one-standard-deviation implied move {pct(x.get("implied_move_1sd"), 1)} ·
time decay {pct(x.get("theta_share_per_day"), 2)} of the mid per day · ranking parts: liquidity {num(rc.get("liquidity"))},
breakeven {num(rc.get("breakeven"))}, time decay {num(rc.get("time_decay"))}.</p><p>{flags}</p>
<div class="grid"><div><h4>At expiration: payoff (premium paid at the ask)</h4><div class="table-wrap"><table>
<thead><tr><th class="num">Stock move</th><th class="num">Stock price</th><th class="num">P/L per contract</th><th class="num">On premium</th></tr></thead>
<tbody>{pay}</tbody></table></div></div>
<div><h4>Before expiration: model estimate in {sens.get("days_forward", 30)} days</h4><div class="table-wrap"><table>
<thead><tr><th class="num">Stock move</th>{ivh}</tr></thead><tbody>{sgrid}</tbody></table></div>
<p class="small muted">Black-Scholes MODEL estimate of value per share vs today's mid; not a quote. {E(sens.get("note", ""))}</p></div></div>
</div></td></tr></tbody>"""


def _list(snap: dict, h, kind: str, data: dict | None) -> str:
    limit = spec.OPTION_RULES["max_per_type_per_horizon"]
    plural = f"{kind}s"
    if not data:
        return f'<div class="banner warn"><strong>No {plural} listed</strong>Not collected in this snapshot.</div>'
    rows = data.get("rows", [])
    rej = ", ".join(f"{E(k)} ({v})" for k, v in sorted(data.get("rejections", {}).items(), key=lambda kv: -kv[1]))
    count = (f'<p class="small"><strong>{len(rows)} of up to {limit}</strong> {plural} qualified · {data.get("considered", 0)} '
             f'{plural} in the {h.min_dte}-{h.max_dte} day window were checked · not shown: {rej or "none"}.</p>')
    if not rows:
        return count + f'<div class="banner warn"><strong>No {kind} qualified</strong>{E(data.get("status", ""))}. Filters are not ' \
                       'weakened and no contracts are invented to fill the list.</div>'
    tid = f"o-{h.key}-{kind}"
    body = "".join(_row(x, kind, f"{tid}-{i}") for i, x in enumerate(rows))
    head = ("<th class='num sticky' data-sort='num'>#</th><th class='sticky2' data-sort='text'>Underlying</th>"
            "<th class='num' data-sort='text'>Expiry</th><th class='num' data-sort='num'>Days</th>"
            "<th class='num' data-sort='num'>Strike</th><th class='num' data-sort='num'>Underlying</th><th class='num'>Bid / ask</th>"
            "<th class='num' data-sort='num'>Spread</th><th class='num' data-sort='num' title='Ask x 100 shares'>Premium*</th>"
            "<th class='num' data-sort='num'>Breakeven at expiry</th><th class='num' data-sort='num'>Required move</th>"
            "<th class='num' data-sort='num'>Max loss</th><th class='num' data-sort='num'>Volume</th>"
            "<th class='num' data-sort='num'>Open int.</th><th class='num' data-sort='num'>IV</th><th class='num' data-sort='num'>Delta</th>"
            "<th class='num' data-sort='num'>Theta</th><th class='num' data-sort='num'>Research score</th>"
            "<th>Earnings before expiry (unverified)</th>")
    return count + f"""<div class="table-wrap wide"><table id="{tid}" data-table data-grouped><caption class="sr-only">{E(h.title)} {plural}</caption>
<thead><tr>{head}</tr></thead>{body}</table></div>
<p class="small"><a href="downloads/{E(snap["as_of"])}_options_{h.key}_{plural}.csv" download>Download {plural} (CSV)</a></p>"""


def options_page(snap: dict) -> str:
    o = snap.get("options") or {}
    head = f"""<h1>Options research: calls and puts</h1>
<p class="lede">Educational comparisons of liquid contracts on this week's large-cap research candidates (S&amp;P 500 members).
Not recommendations. Buying an option can lose the entire premium.</p>
<div class="banner info small"><strong>What the ranking means</strong>{E(spec.OPTION_RANKING_NOTE)}</div>
<div class="banner warn small"><strong>Delta is not a probability of profit</strong>{E(spec.DELTA_STATEMENT)}</div>
<div class="banner info small"><strong>* Premium assumption</strong>{E(spec.PREMIUM_ASSUMPTION)} Quotes are delayed,
end-of-session data from Cboe for {E(snap["as_of"])}; payoffs at expiration are exact arithmetic on that premium, while
before-expiration values are Black-Scholes MODEL estimates.</div>"""
    if not o.get("enabled") or o.get("status") != "ok":
        return head + f'<div class="banner bad"><strong>Options data unavailable</strong>{E(o.get("status", "not collected"))}. ' \
                      'No contracts, prices or Greeks are shown rather than inventing them.</div>'
    hz_tabs = "".join(f'<button role="tab" data-dim="hz" data-val="{h.key}" aria-selected="false">{E(h.title)}</button>'
                      for h in spec.HORIZONS)
    type_tabs = ('<button role="tab" data-dim="type" data-val="call" aria-selected="false">Calls</button>'
                 '<button role="tab" data-dim="type" data-val="put" aria-selected="false">Puts</button>')
    panels = []
    for h in spec.HORIZONS:
        ls = lists_of(o.get(h.key) or {})
        for kind in spec.OPTION_TYPES:
            panels.append(f'<section data-hz="{h.key}" data-type="{kind}" hidden><h2>{E(h.title)} · {kind}s · '
                          f'{h.min_dte}-{h.max_dte} days to expiry</h2>{_list(snap, h, kind, ls.get(f"{kind}s"))}</section>')
    probs = "".join(f'<li>{E(k)}: {E(v)}</li>' for k, v in (o.get("chain_problems") or {}).items())
    r = spec.OPTION_RULES
    rules = (f"Rules (fixed in advance): open interest ≥ {r['min_open_interest']}, volume ≥ {r['min_volume']}, spread ≤ "
             f"{r['max_spread_pct']:.0%} of mid, |delta| {r['min_delta']}-{r['max_delta']} (calls positive, puts negative), "
             f"standard 100-share contracts, at most {r['max_per_underlying_per_horizon']} per underlying per list, up to "
             f"{r['max_per_type_per_horizon']} per list.")
    earn = f'<div class="banner warn small"><strong>Earnings dates</strong>{E(o["earnings_note"])}</div>' if o.get("earnings_note") else ""
    return head + f"""<p class="small">{E(rules)} Underlyings with a valid chain: {E(", ".join(o.get("underlyings", [])) or "none")}.</p>{earn}
<div data-matrix><div class="tabs seg" role="tablist" aria-label="Option type">{type_tabs}</div>
<div class="tabs" role="tablist" aria-label="Expiry horizon">{hz_tabs}</div>{''.join(panels)}</div>
{f'<details><summary>Chains not used ({len(o.get("chain_problems") or {})})</summary><ul class="small">{probs}</ul></details>' if probs else ''}"""
