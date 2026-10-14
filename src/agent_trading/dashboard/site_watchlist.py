"""Watchlist — 2030 Outlook page: verified symbols and conditional year-end-2030 price scenarios."""
from __future__ import annotations

import csv
import html
import io

from . import spec
from .fmt import cap, money, num, ok, pct, sval

E = html.escape


def range_chart(entries: list[dict]) -> str:
    """Horizontal bear-to-bull ranges of % change to 2030, base marked; unavailable rows labelled."""
    rows = [e for e in entries]
    vals = [e["scenarios"][k]["change"] for e in rows if e.get("scenarios") for k in ("bear", "base", "bull")]
    if not vals:
        return '<p class="muted small">No scenarios to chart.</p>'
    lo, hi = min(min(vals), -0.5), max(max(vals), 0.5)
    W, L, R, rowh = 720, 92, 700, 26
    H = 30 + rowh * len(rows)

    def x(v):
        return L + (R - L) * (v - lo) / (hi - lo)
    ticks = []
    for v in [t for t in (-0.75, -0.5, -0.25, 0.0, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0) if lo <= t <= hi]:
        ticks.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="18" y2="{H - 6}" stroke="var(--border)" '
                     f'stroke-width="{2 if v == 0 else 1}"/><text x="{x(v):.1f}" y="12" text-anchor="middle" font-size="11" '
                     f'fill="var(--text-muted)">{v:+.0%}</text>')
    marks = []
    for i, e in enumerate(rows):
        y = 30 + i * rowh
        marks.append(f'<text x="{L - 8}" y="{y + 4}" text-anchor="end" font-size="12" fill="var(--text-primary)">{E(e["ticker"])}</text>')
        sc = e.get("scenarios")
        if not sc:
            marks.append(f'<text x="{L + 4}" y="{y + 4}" font-size="11" fill="var(--text-muted)">scenario unavailable</text>')
            continue
        b0, b1, base = sc["bear"]["change"], sc["bull"]["change"], sc["base"]["change"]
        tip = f'{e["ticker"]}: bear {b0:+.0%}, base {base:+.0%}, bull {b1:+.0%}'
        marks.append(f'<g><title>{E(tip)}</title><rect x="{x(min(b0, b1)):.1f}" y="{y - 5}" width="{max(2, abs(x(b1) - x(b0))):.1f}" '
                     f'height="10" rx="4" fill="var(--series-1)" opacity="0.35"/>'
                     f'<circle cx="{x(base):.1f}" cy="{y}" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/></g>')
    return (f'<div class="legend"><span><i></i>bear-to-bull range</span><span>● base case</span>'
            f'<span class="muted">% change from the latest price to 2030-12-31 (price only)</span></div>'
            f'<div class="chart range"><svg viewBox="0 0 {W} {H}" role="img" aria-label="2030 scenario ranges by ticker">'
            f'{"".join(ticks)}{"".join(marks)}</svg></div>')


def _scen_cells(e: dict) -> str:
    sc = e.get("scenarios")
    if not sc:
        return '<td colspan="3" class="small muted">Scenario unavailable</td>'
    return "".join(f'<td class="num" data-v="{sval(sc[k]["change"])}">{money(sc[k]["price"])}<div class="small muted">'
                   f'{pct(sc[k]["change"], 0, True)} · {pct(sc[k]["annualized"], 1, True)}/yr</div></td>'
                   for k in ("bear", "base", "bull"))


def _assumptions(e: dict) -> str:
    sc = e.get("scenarios") or {}
    if not sc:
        return ""
    rows = []
    for k in ("bear", "base", "bull"):
        a = sc[k]["assumptions"]
        if "starting_revenue_growth" in a:
            txt = (f"revenue growth starts at {pct(a['starting_revenue_growth'])} and fades toward "
                   f"{pct(spec.SCENARIO_TERMINAL_GROWTH)}; 2030 revenue {cap(a['revenue_2030'])}; exit EV/Sales "
                   f"{num(a['exit_ev_to_sales'], 1)}x; net cash held {cap(a['net_cash_held'])}; dilution "
                   f"{pct(a['annual_dilution'], 1)}/yr")
        elif "leverage" in a:
            txt = (f"{a['leverage']}x daily; index total return {pct(a['index_total_return'], 1)}/yr; index volatility "
                   f"{pct(a['index_volatility'])}; volatility drag {pct(a['volatility_drag'], 1)}/yr; financing "
                   f"{pct(a['financing_cost'], 1)}/yr; assumed fee {pct(a['assumed_fee'], 2)}")
        else:
            txt = (f"{a['exposure']}: total return {pct(a['total_return_assumption'], 1)}/yr − assumed fee "
                   f"{pct(a['assumed_fee'], 2)} − assumed distribution yield {pct(a['assumed_distribution_yield'], 1)} "
                   f"= price return {pct(a['price_return'], 1)}/yr")
        rows.append(f"<li><strong>{k}</strong>: {E(txt)}</li>")
    return f'<ul class="tight small">{"".join(rows)}</ul>'


def watchlist_page(snap: dict) -> str:
    w = snap.get("watchlist")
    head = """<h1>Watchlist — 2030 Outlook</h1>"""
    if not w or w.get("status") != "ok":
        return head + '<div class="banner warn"><strong>Watchlist not available</strong>This snapshot has no watchlist ' \
                      'section (it predates spec 2026-10-14.2 or no list is configured).</div>'
    entries = w["entries"]
    bodies = []
    for i, e in enumerate(entries):
        rid = f"w-{i}"
        status = e.get("unavailable_reason") or ""
        km = e.get("key_metrics") or {}
        km_txt = " · ".join(t for t in (
            f"revenue {cap(km.get('revenue_ttm'))} ({pct(km.get('revenue_growth_ttm'), 0, True)})" if km.get("revenue_ttm") else "",
            f"operating margin {pct(km.get('operating_margin'))}" if ok(km.get("operating_margin")) else "",
            f"FCF {cap(km.get('fcf_ttm'))}" if ok(km.get("fcf_ttm")) else "",
            f"EV/Sales {num(km.get('ev_to_sales'), 1)}x" if ok(km.get("ev_to_sales")) else "",
            f"net debt {cap(km.get('net_debt'))}" if ok(km.get("net_debt")) else "",
            f"dilution {pct(km.get('dilution'), 1)}/yr" if ok(km.get("dilution")) else "") if t)
        bodies.append(f"""<tbody class="item" data-sector="{E(e.get("sector") or "Unknown")}"><tr>
<td><button class="rowtoggle" type="button" aria-expanded="false" aria-controls="{rid}"><strong>{E(e["ticker"])}</strong></button>
<div class="small muted">{E(e.get("name") or "name not resolved")}</div></td>
<td class="small hide-sm" data-v="{E(e.get("asset_type") or "")}">{E(e.get("asset_type") or "unresolved")}<div class="muted">{E(e.get("exchange") or "")}</div></td>
<td class="num" data-v="{sval(e.get("price"))}">{money(e.get("price"))}<div class="small muted">{E(str(e.get("price_date") or ""))}</div></td>
{_scen_cells(e)}
<td class="small hide-sm">{E(e.get("method") or "")}</td><td class="small" data-v="{E(e.get("evidence_quality") or "")}">{E(e.get("evidence_quality") or "")}</td>
<td class="small">{E(status)}</td></tr>
<tr id="{rid}" class="detail" hidden><td colspan="9"><div class="evidence">
<div><h4>Identity</h4><p class="small">{E(e.get("name") or "unresolved")} · {E(e.get("asset_type") or "")} · {E(e.get("exchange") or "")} ·
status: {E(e.get("status") or "")}{" · CIK " + str(e["cik"]) if e.get("cik") else ""}. Sector/theme: {E(e.get("sector") or "n/a")}.</p>
<p class="small">{E(km_txt)}</p><p class="small">Trailing price returns: 1y {pct((e.get("returns") or {}).get("1y"), 0, True)},
3y {pct((e.get("returns") or {}).get("3y"), 0, True)} (history from {E(str(e.get("history_start") or "n/a"))}).</p></div>
<div><h4>Valuation method and assumptions</h4><p class="small">{E(e.get("assumptions_note") or status or "")}</p>{_assumptions(e)}</div>
<div><h4>Catalysts</h4><ul class="tight small">{''.join(f"<li>{E(c)}</li>" for c in e.get("catalysts", []))}</ul>
<h4>Strongest bear case</h4><p class="small">{E(e.get("bear_case") or "n/a")}</p></div>
<div><h4>Thesis invalidation</h4><ul class="tight small">{''.join(f"<li>{E(c)}</li>" for c in e.get("invalidation", []))}</ul>
<h4>Sources, evidence and gaps</h4><p class="small">Evidence quality: {E(e.get("evidence_quality") or "none")}. Sources:
{E("; ".join(dict.fromkeys(e.get("sources", []))))}.</p><ul class="tight small">{''.join(f"<li>{E(m)}</li>" for m in e.get("missing", []))}</ul></div>
</div></td></tr></tbody>""")
    conc = " · ".join(f"{E(k)}: {v}" for k, v in sorted(w.get("concentration", {}).items(), key=lambda kv: -kv[1]))
    themes = sorted({e.get("sector") or "Unknown" for e in entries})
    opts = "".join(f'<option value="{E(s)}">{E(s)}</option>' for s in themes)
    return head + f"""<div class="banner warn"><strong>Conditional 2030 price scenarios</strong>{E(w["statement"])}</div>
<div class="banner info small"><strong>Separate research universe</strong>{E(w["separation"])} The ticker list was imported on
{E(w["imported_at"])} and is not synchronized with any account; it works without a Robinhood login.</div>
<p class="small">Valuation date {E(snap["as_of"])} close · target {E(w["target_date"])} · horizon {num(w["years_to_target"], 2)} years ·
theme concentration: {conc}.</p>
{range_chart(entries)}
<div class="controls"><input type="search" placeholder="Search ticker, name, reason" data-search="t-watch" aria-label="Search watchlist">
<select data-sector="t-watch" aria-label="Filter by sector or theme"><option value="">All sectors and themes</option>{opts}</select>
<span class="small muted" data-count="t-watch" aria-live="polite"></span></div>
<div class="table-wrap"><table id="t-watch" data-table data-grouped><caption class="sr-only">Watchlist 2030 scenarios</caption>
<thead><tr><th data-sort="text">Ticker / name</th><th class="hide-sm" data-sort="text">Type</th><th class="num" data-sort="num">Latest price</th>
<th class="num" data-sort="num">Bear 2030</th><th class="num" data-sort="num">Base 2030</th><th class="num" data-sort="num">Bull 2030</th>
<th class="hide-sm">Method</th><th data-sort="text">Evidence</th><th>Unavailable / notes</th></tr></thead>{''.join(bodies)}</table></div>
<p class="small"><a href="downloads/{E(snap["as_of"])}_watchlist_2030.csv" download>Download (CSV)</a> · Prices are split-adjusted
price data; scenarios are PRICE outcomes and exclude distributions (total return would add dividends). Methods:
{E(spec.WATCHLIST_COMPANY_METHOD)} {E(spec.LEVERAGED_METHOD)} {E(spec.FEE_NOTE)}</p>"""


def watchlist_csv(snap: dict) -> str:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["ticker", "name", "asset_type", "exchange", "status", "price", "price_date", "method", "evidence_quality",
                 "bear_2030", "base_2030", "bull_2030", "bear_change", "base_change", "bull_change", "bear_annualized",
                 "base_annualized", "bull_annualized", "unavailable_reason"])
    for e in (snap.get("watchlist") or {}).get("entries", []):
        sc = e.get("scenarios") or {}
        g = lambda k, f: (sc.get(k) or {}).get(f)  # noqa: E731
        wr.writerow([e["ticker"], e.get("name"), e.get("asset_type"), e.get("exchange"), e.get("status"), e.get("price"),
                     e.get("price_date"), e.get("method"), e.get("evidence_quality"),
                     *[g(k, "price") for k in ("bear", "base", "bull")], *[g(k, "change") for k in ("bear", "base", "bull")],
                     *[g(k, "annualized") for k in ("bear", "base", "bull")], e.get("unavailable_reason")])
    return buf.getvalue()
