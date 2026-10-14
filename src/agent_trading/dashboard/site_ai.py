"""AI page (spec 2026-10-14.7): two top-5 lists (large and mid cap), the top-20 market-cap scenario test, the curated
AI universe by role, and private AI companies for context.

Everything shown comes from the stored snapshot. The scenario test compares conditional market caps with today's
20th-largest S&P 500 market cap and never states a probability; private valuations are shown as reported, with their
source, and are not market caps.
"""
from __future__ import annotations

import html

from . import ai as ai_mod, spec
from .fmt import cap, num, sval
from .site_overview import band_title, distribution_strip, excluded_summary, growth_table

E = html.escape
AI_KEYS = ("ai_large", "ai_mid")
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


def ai_bands(snap: dict) -> dict:
    return {k: snap["bands"][k] for k in AI_KEYS if k in (snap.get("bands") or {})}


def _definition(band: dict) -> str:
    d = band.get("definition") or {}
    lo, hi = d.get("min_cap"), d.get("max_cap")
    rng = f"{cap(lo)} or more" if lo and not hi else f"{cap(lo)} to {cap(hi)}"
    return (f"Universe: the fixed AI-exposed list below; market cap {rng}; price ≥ ${d.get('min_price', 5):g}; 20-day "
            f"median dollar volume ≥ {cap(d.get('min_dollar_volume'))}. Market cap = as-of close x SEC cover-page shares.")


# --- the top-20 market-cap scenario test -------------------------------------------------------------------------

def _cell(t: dict, case: str, year: int) -> str:
    r = next((x for x in t.get("rows", []) if x["case"] == case and x["year"] == year), None)
    if not r:
        return '<td class="num muted">n/a</td>'
    above = r["above_today_bar"]
    return (f'<td class="num" data-v="{sval(r["market_cap"])}">{cap(r["market_cap"])}<div class="small muted">'
            f'{num(r["multiple_of_threshold"], 2)}x the bar · <span class="pill {"ok" if above else "muted"}">'
            f'{"above" if above else "below"}</span></div></td>')


def top20_block(c: dict) -> str:
    """The scenario test for one AI candidate (detail page); empty for any other stock."""
    t = c.get("top20_test")
    if not t:
        return ""
    if t.get("status") != "ok":
        return (f'<h2>Top-20 market-cap scenario test</h2><p class="small muted">Not available this week: '
                f'{E(t.get("reason") or "no threshold")}.</p>')
    rows = "".join(f'<tr><td><strong>{case}</strong></td>{_cell(t, case, 5)}{_cell(t, case, 10)}</tr>'
                   for case in ("bear", "base", "bull"))
    return f"""<h2>Top-20 market-cap scenario test</h2>
<p class="small">Today's bar: the 20th-largest S&amp;P 500 member by market cap is {E(t.get("threshold_ticker") or "")} at
<strong>{cap(t.get("threshold"))}</strong>. This stock's market cap today is {cap(t.get("market_cap_now"))}
({num(t.get("current_vs_threshold"), 2)}x the bar).</p>
<div class="table-wrap"><table aria-label="Scenario market caps against today's top-20 bar"><thead><tr><th>Scenario</th>
<th class="num">Market cap in 5 years</th><th class="num">Market cap in 10 years</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="small muted">{E(spec.AI_TOP20_RULE)} {E(spec.AI_PROBABILITY_NOTE)}</p>"""


def _top20_table(bands: dict, ladder: dict) -> str:
    rows = []
    for key in AI_KEYS:
        for c in (bands.get(key) or {}).get("candidates", []):
            t = c.get("top20_test") or {}
            now = c.get("market_cap")
            ok10 = next((x for x in t.get("rows", []) if x["case"] == "bull" and x["year"] == 10), None)
            verdict = ("n/a" if ok10 is None else
                       f'<span class="pill {"ok" if ok10["above_today_bar"] else "muted"}">'
                       f'{"above" if ok10["above_today_bar"] else "below"} the bar</span>')
            rows.append(f'<tr><td class="tk"><a href="stock/{E(key)}-{E(c["ticker"])}.html"><strong>{E(c["ticker"])}</strong></a>'
                        f'<div class="small muted">{E(band_title(key, bands[key]))}</div></td>'
                        f'<td class="small hide-sm">{E(c.get("ai_role") or "")}</td>'
                        f'<td class="num" data-v="{sval(now)}">{cap(now)}<div class="small muted">'
                        f'{num(t.get("current_vs_threshold"), 2)}x the bar</div></td>'
                        f'{_cell(t, "base", 5)}{_cell(t, "bull", 5)}{_cell(t, "base", 10)}{_cell(t, "bull", 10)}'
                        f'<td class="small">{verdict}</td></tr>')
    if not rows:
        return ""
    if ladder.get("threshold"):
        bar = (f'<p class="small">Today\'s bar: the 20th-largest S&amp;P 500 member by market cap is '
               f'<strong>{E(ladder.get("threshold_ticker") or "")}</strong> at <strong>{cap(ladder["threshold"])}</strong> '
               f'({ladder.get("n_with_cap")} members with valid data this week).</p>')
        top = ", ".join(f'#{m["rank"]} {E(m["ticker"])} {cap(m["market_cap"])}' for m in ladder.get("members", [])[:20])
        bar += f'<details class="small"><summary>The 20 largest today</summary><p>{top}</p></details>'
    else:
        bar = f'<p class="small muted">No bar this week: {E(ladder.get("reason") or "not computed")}.</p>'
    return f"""<h2 id="top20">Could they reach the top 20? A scenario test, not a prediction</h2>
<p class="small">{E(spec.AI_TOP20_RULE)}</p>{bar}
<div class="table-wrap"><table aria-label="Top-20 market-cap scenario test for the listed AI stocks"><thead><tr>
<th class="tk">Stock</th><th class="hide-sm">Role in the AI chain</th><th class="num">Market cap today</th>
<th class="num">Base, 5 years</th><th class="num">Bull, 5 years</th><th class="num">Base, 10 years</th>
<th class="num">Bull, 10 years</th><th>Bull case, 10 years</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p class="small muted">Each figure is the market cap implied by that scenario's value per share and share count; "x the bar"
divides it by today's 20th-largest market cap. The bar will probably rise, so "above" does not mean a top-20 company.
Scenario assumptions are on each stock's page.</p>"""


# --- universe and private companies ---------------------------------------------------------------------------------

def _universe_table(snap: dict, ai: dict | None) -> str:
    roles = ((ai or {}).get("universe") or {}).get("roles") or dict(spec.AI_UNIVERSE)
    listed = {}
    for key in AI_KEYS:
        for c in (ai_bands(snap).get(key) or {}).get("candidates", []):
            listed[c["ticker"]] = f'#{c["rank"]} {band_title(key, snap["bands"][key])}'
    unresolved = ((ai or {}).get("universe") or {}).get("unresolved") or {}
    by_role: dict[str, list[str]] = {}
    for t, role in roles.items():
        by_role.setdefault(role, []).append(t)
    rows = []
    for role in spec.AI_ROLES:
        names = by_role.get(role)
        if not names:
            continue
        chips = " ".join(
            (f'<span class="pill ok" title="{E(listed[t])}">{E(t)}</span>' if t in listed else
             f'<span class="pill muted" title="{E(unresolved[t])}">{E(t)}</span>' if t in unresolved else
             f'<span class="pill">{E(t)}</span>') for t in names)
        rows.append(f"<tr><td>{E(role)}</td><td>{chips}</td></tr>")
    note = ("Green: in this week's top 5. Grey with a reason on hover: could not be evaluated (not listed, foreign filer...). "
            "Plain: evaluated but not in a top 5, or outside both market-cap bands; the excluded pages give each reason.")
    return (f'<h2 id="universe">The AI-exposed universe, by role</h2><p class="small">{E(spec.AI_UNIVERSE_DEFINITION)}</p>'
            f'<div class="table-wrap"><table aria-label="AI-exposed universe by role"><thead><tr><th>Role in the AI chain</th>'
            f'<th>Stocks</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div><p class="small muted">{E(note)}</p>')


def _link(label: str | None, url: str | None) -> str:
    return (f'<a href="{E(url)}" rel="noopener">{E(label or "source")}</a>' if url and str(url).startswith("https://")
            else E(label or ""))


def _private_section(ai: dict | None) -> str:
    p = (ai or {}).get("private") or {}
    comps = p.get("companies") or []
    ladder = (ai or {}).get("ladder") or {}
    if not comps:
        return (f'<h2 id="private">Private AI companies</h2><p class="small muted">None are configured in this snapshot. '
                f'{E(spec.AI_PRIVATE_RULE)}</p>')
    priced = [c for c in comps if c.get("valuation") is not None]
    rows = []
    for c in priced:
        sym = SYMBOLS.get(c["currency"], f'{c["currency"]} ')
        place = ai_mod.place_in_ladder(c, ladder)
        compared = (E(place) if place else f'not compared: reported in {E(c["currency"])} and no exchange rate is collected')
        status = (f'{E(c["status_note"])} ({_link(c.get("status_source_label"), c.get("status_source_url"))})'
                  if c.get("status_note") else '<span class="muted">none reported</span>')
        rows.append(f'<tr><td class="tk"><strong>{E(c["name"])}</strong><div class="small muted">{E(c["what"])}</div></td>'
                    f'<td class="num" data-v="{sval(c["valuation"])}">{sym}{c["valuation"]:g}B<div class="small muted">'
                    f'{E(c.get("basis") or "")}</div></td><td class="small">{E(str(c.get("valuation_date") or ""))}</td>'
                    f'<td class="small">{_link(c.get("source_label"), c.get("source_url"))}<div class="muted">reported, unverified</div></td>'
                    f'<td class="small hide-sm">{compared}</td><td class="small hide-sm">{status}</td></tr>')
    table = (f'<div class="table-wrap"><table aria-label="Private AI companies with a reported valuation"><thead><tr>'
             f'<th class="tk">Company</th><th class="num">Reported valuation</th><th>As of</th><th>Source</th>'
             f'<th class="hide-sm">Against today\'s S&amp;P 500 market caps</th><th class="hide-sm">IPO status</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>') if rows else ""
    watched = "".join(
        f'<li><strong>{E(c["name"])}</strong>: {E(c["what"])} <span class="muted">{E(c.get("no_valuation_reason") or "")}</span>'
        f'{" (" + _link(c.get("status_source_label"), c.get("status_source_url")) + ")" if c.get("status_source_url") else ""}</li>'
        for c in comps if c.get("valuation") is None)
    return (f'<h2 id="private">Private AI companies, for context</h2>'
            f'<div class="banner warn small"><strong>Reported figures, not market prices</strong>{E(spec.AI_PRIVATE_RULE)}</div>'
            f'<p class="small">File reviewed {E(str(p.get("reviewed_on") or "n/a"))}. {E(p.get("note") or "")}</p>{table}'
            f'<h3>Also watched: no corroborated valuation</h3><ul class="tight small">{watched or "<li>none</li>"}</ul>')


# --- the page ----------------------------------------------------------------------------------------------------------

def ai_page(snap: dict) -> str:
    ai = snap.get("ai")
    bands = ai_bands(snap)
    head = """<h1>AI stocks</h1>
<p class="lede">Public AI-exposed stocks ranked by the same fixed rules as the growth lists, whether today's AI companies could
reach the largest market caps in scenario tests, and private AI companies for context. Research comparisons only.</p>
<div class="banner warn"><strong>This is not a forecast and not advice</strong>Which companies sit on the list is a recorded
judgement. A company in a top 5 scored well on today's reported data; it is not predicted to become a top-20 company, and
none of these numbers is a probability.</div>"""
    prob = f'<div class="banner info small"><strong>Probability not established</strong>{E(spec.AI_PROBABILITY_NOTE)}</div>'
    if not bands:
        v = snap.get("spec_version") or "unknown"
        missing = (f'<div class="banner info"><strong>No AI lists in this snapshot</strong>This snapshot was collected under '
                   f'methodology {E(str(v))}, before the AI lists existed (2026-10-14.7). The first weekly snapshot collected under the '
                   f'new methodology adds them. The universe and rules below are the ones that run will use.</div>')
        return head + prob + missing + _universe_table(snap, ai) + _private_section(ai)
    panels = []
    for key in AI_KEYS:
        b = bands.get(key)
        if not b:
            continue
        short = f'<div class="banner info small">{E(b["shortfall_note"])}</div>' if b.get("shortfall_note") else ""
        panels.append(f"""<section id="{key}" aria-labelledby="h-{key}"><h2 id="h-{key}">{E(band_title(key, b))}: top {b.get("max_results", 5)}</h2>
<p class="small">{E(_definition(b))} Benchmark: {E(b.get("benchmark_name", b.get("benchmark", "")))}. Showing {len(b["candidates"])} of up to
{b.get("max_results", 5)}; {b.get("ranked", "?")} ranked, {len(b["excluded"])} excluded.</p>{short}{distribution_strip(b["candidates"])}
{growth_table(key, b)}<p class="small"><a href="downloads/{E(snap["as_of"])}_{key}.csv" download>Download CSV</a></p>
{excluded_summary(key, b)}</section>""")
    ladder = (ai or {}).get("ladder") or {}
    return (head + prob + f'<p class="small">Week ending {E(snap["as_of"])}. Quotes are end-of-session and delayed.</p>' +
            "".join(panels) + _top20_table(bands, ladder) + _universe_table(snap, ai) + _private_section(ai))


def methodology_ai() -> str:
    """The AI rules as the methodology page shows them."""
    rows = "".join(f"<tr><td>{E(role)}</td><td>{E(', '.join(t for t, r in spec.AI_UNIVERSE if r == role))}</td></tr>"
                   for role in spec.AI_ROLES)
    return (f'<h2 id="ai">AI-exposed lists (2026-10-14.7)</h2><p>{E(spec.AI_UNIVERSE_DEFINITION)}</p>'
            f'<div class="table-wrap"><table aria-label="Registered AI universe"><thead><tr><th>Role</th><th>Registered stocks</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div><p>{E(spec.AI_TOP20_RULE)}</p><p>{E(spec.AI_PRIVATE_RULE)}</p>'
            f'<p>{E(spec.AI_PROBABILITY_NOTE)}</p>')
