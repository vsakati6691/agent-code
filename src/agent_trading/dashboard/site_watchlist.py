"""Watchlist — 2030 Outlook page: verified symbols and conditional year-end-2030 price scenarios."""

from __future__ import annotations

import html

from . import spec
from .evidence import quality_level
from .fmt import cap, money, net_position, num, ok, pct, sval
from .site_downloads import watchlist_csv as watchlist_csv
from .site_research import quality_badge
from .site_scan import pin_button
from .watchlist import upside_fields

E = html.escape
OLD_TYPE_DETAIL = " (warrant, right, unit, preferred, note, fund or blank-check)"


def tidy(text: str | None) -> str:
    """Drop the nested type list older snapshots stored ('other security (not common stock (warrant, ...))')."""
    return (text or "").replace(OLD_TYPE_DETAIL, "")


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
        ticks.append(
            f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="18" y2="{H - 6}" stroke="var(--border)" '
            f'stroke-width="{2 if v == 0 else 1}"/><text x="{x(v):.1f}" y="12" text-anchor="middle" font-size="11" '
            f'fill="var(--text-muted)">{v:+.0%}</text>'
        )
    marks = []
    for i, e in enumerate(rows):
        y = 30 + i * rowh
        marks.append(
            f'<text x="{L - 8}" y="{y + 4}" text-anchor="end" font-size="12" fill="var(--text-primary)">{E(e["ticker"])}</text>'
        )
        sc = e.get("scenarios")
        if not sc:
            marks.append(
                f'<text x="{L + 4}" y="{y + 4}" font-size="11" fill="var(--text-muted)">scenario unavailable</text>'
            )
            continue
        b0, b1, base = sc["bear"]["change"], sc["bull"]["change"], sc["base"]["change"]
        tip = f"{e['ticker']}: bear {b0:+.0%}, base {base:+.0%}, bull {b1:+.0%}"
        marks.append(
            f'<g><title>{E(tip)}</title><rect x="{x(min(b0, b1)):.1f}" y="{y - 5}" width="{max(2, abs(x(b1) - x(b0))):.1f}" '
            f'height="10" rx="4" fill="var(--series-1)" opacity="0.35"/>'
            f'<circle cx="{x(base):.1f}" cy="{y}" r="5" fill="var(--series-1)" stroke="var(--surface-1)" stroke-width="2"/></g>'
        )
    return (
        f'<div class="legend"><span><i></i>bear-to-bull range</span><span>● base case</span>'
        f'<span class="muted">% change from the latest price to 2030-12-31 (price only)</span></div>'
        f'<div class="chart range"><svg viewBox="0 0 {W} {H}" role="img" aria-label="2030 scenario ranges by ticker">'
        f"{''.join(ticks)}{''.join(marks)}</svg></div>"
    )


def _scen_cells(e: dict) -> str:
    sc = e.get("scenarios")
    if not sc:
        # Keep all three cells so sorting later columns uses the correct index.
        return (
            '<td class="small muted" data-v="">Scenario unavailable</td>'
            '<td class="small muted" data-v="">—</td><td class="small muted" data-v="">—</td>'
        )
    return "".join(
        f'<td class="num" data-v="{sval(sc[k]["change"])}">{money(sc[k]["price"])}<div class="small muted">'
        f"{pct(sc[k]['change'], 0, True)} · {pct(sc[k]['annualized'], 1, True)}/yr</div></td>"
        for k in ("bear", "base", "bull")
    )


def _upside_cell(entry: dict) -> str:
    values = upside_fields(entry)
    base, annual = values["upside_base_pct"], values["cagr_base_pct"]
    if not ok(base):
        reason = tidy(entry.get("unavailable_reason")) or "Base 2030 scenario unavailable in this stored snapshot"
        return f'<td data-v=""><span>—</span><div class="small muted upside-reason">{E(reason)}</div></td>'
    color = "positive" if base > 0 else "negative" if base < 0 else ""
    bar = ""
    bear, bull = values["upside_bear_pct"], values["upside_bull_pct"]
    if ok(bear) and ok(bull):
        lo, hi = min(bear, base, bull, 0), max(bear, base, bull, 0)

        def x(value):
            return 6 + 108 * (value - lo) / (hi - lo) if hi > lo else 60

        label = f"Bear {bear:+.0f}%, base {base:+.0f}%, bull {bull:+.0f}%; tick at 0% is the latest price. Row scale."
        bar = (
            f'<svg class="upside-range" viewBox="0 0 120 22" width="120" height="22" role="img" aria-label="{E(label)}">'
            f'<title>{E(label)}</title><line class="upside-span" x1="{x(min(bear, bull)):.2f}" x2="{x(max(bear, bull)):.2f}" y1="11" y2="11"/>'
            f'<line class="upside-zero" x1="{x(0):.2f}" x2="{x(0):.2f}" y1="3" y2="19"/>'
            f'<circle class="upside-base" cx="{x(base):.2f}" cy="11" r="4"/></svg>'
        )
    annual_text = f"{annual:+.1f}%/yr" if ok(annual) else "annualized rate unavailable"
    return f'<td class="num" data-v="{sval(base)}"><span class="{color}">{base:+.0f}%</span><div class="small muted">{annual_text}</div>{bar}</td>'


def _assumptions(e: dict) -> str:
    fee_label = "dated expense input (owner-supplied, unverified)" if e.get("etf_metadata") else "assumed fee"
    sc = e.get("scenarios") or {}
    if not sc:
        return ""
    rows = []
    for k in ("bear", "base", "bull"):
        a = sc[k]["assumptions"]
        if "starting_revenue_growth" in a:
            txt = (
                f"revenue growth starts at {pct(a['starting_revenue_growth'])} and fades toward "
                f"{pct(spec.SCENARIO_TERMINAL_GROWTH)}; 2030 revenue {cap(a['revenue_2030'])}; exit EV/Sales "
                f"{num(a['exit_ev_to_sales'], 1)}x; {net_position(-a['net_cash_held'], False)} held flat; dilution "
                f"{pct(a['annual_dilution'], 1)}/yr"
            )
            if a.get("margin_2030") is not None:
                txt += (
                    f"; {a.get('margin_source')} margin {pct(a['margin_today'])} → {pct(a['margin_2030'])} by 2030 "
                    f"(2030 FCF {cap(a['fcf_2030'])}); cash check: {a['cash_support']}"
                )
            elif a.get("cash_support"):
                txt += f"; cash check: {a['cash_support']}"
        elif "leverage" in a:
            txt = (
                f"{a['leverage']}x daily; index total return {pct(a['index_total_return'], 1)}/yr; index volatility "
                f"{pct(a['index_volatility'])}; volatility drag {pct(a['volatility_drag'], 1)}/yr; financing "
                f"{pct(a['financing_cost'], 1)}/yr; {fee_label} {pct(a['assumed_fee'], 2)}"
            )
        else:
            txt = (
                f"{a['exposure']}: total return {pct(a['total_return_assumption'], 1)}/yr; {fee_label} "
                f"{pct(a['assumed_fee'], 2)} − assumed distribution yield {pct(a['assumed_distribution_yield'], 1)} "
                f"= price return {pct(a['price_return'], 1)}/yr"
            )
        rows.append(f"<li><strong>{k}</strong>: {E(txt)}</li>")
    return f'<ul class="tight small">{"".join(rows)}</ul>'


def _earnings_line(e: dict) -> str:
    ec = e.get("earnings_check") or {}
    if ec.get("last_results"):
        return f'<p class="small">Last results {E(ec["last_results"])}: verified (8-K).</p>'
    if ec.get("last_results_status"):
        return f'<p class="small muted">{E(ec["last_results_status"])}.</p>'
    return ""


def etf_metadata_line(entry: dict) -> str:
    if entry.get("asset_type") not in ("ETF", "leveraged/inverse ETF"):
        return ""
    meta = entry.get("etf_metadata") or {}
    if not meta:
        return '<p class="small">Expense ratio: unavailable · inception date: unavailable in this stored snapshot. Fund fee and yield are methodology assumptions.</p>'
    young = " · launched less than 12 months ago" if meta.get("launched_under_12_months") else ""
    return (
        f'<p class="small">Expense ratio: {pct(meta.get("expense_ratio"), 2)} · inception: '
        f"{E(meta['inception_date'])}{young}. {E(meta['label'])} as of {E(meta['as_of'])}. "
        f'<a href="{E(meta["source_url"])}">Issuer source</a>.</p>'
    )


def etf_sources(entry: dict) -> str:
    meta = entry.get("etf_metadata")
    if not meta:
        return ""
    filing = entry.get("sec_fund_filing") or {}
    detail = (
        f'<p class="small">Issuer: {E(meta["issuer"])} · index: {E(meta["index_tracked"])}. {E(meta["expense_basis"])} '
    )
    detail += "The expense ratio is a dated input; distribution yield remains assumed and is not a sourced return estimate.</p>"
    if filing.get("status") == "available":
        detail += (
            f'<p class="small"><a href="{E(filing["source_url"])}">SEC {E(filing["form"])} filing</a> '
            f"filed {E(filing['filed_at'])}; holdings reported {E(filing['reported_at'])}. "
            f'{E(filing["fee_note"])}</p><ul class="small">'
            + "".join(
                f"<li>{E(h['name'])}: {pct(h['weight'], 2)} of reported fund net assets</li>"
                for h in filing["top_holdings"]
            )
            + "</ul>"
        )
    else:
        detail += f'<p class="small">SEC enrichment unavailable: {E(filing.get("reason") or "not collected in this snapshot")}.</p>'
    return detail


def _unlock(e: dict) -> str:
    if not e.get("unlock"):
        return ""
    items = "".join(f"<li>{E(u)}</li>" for u in e["unlock"])
    return f'<h4>Why unavailable, and what would unlock it</h4><ul class="tight small">{items}</ul>'


def watchlist_page(snap: dict) -> str:
    from .price_integrity import SHORT_NOTE, preclose

    price_note = SHORT_NOTE if preclose(snap) else ""
    w = snap.get("watchlist")
    head = (
        '<div class="section-heading watch-heading"><div><p class="eyebrow">RESEARCH DESK / LONG VIEW</p>'
        '<h1>Watchlist — 2030 Outlook</h1><p class="lede">Scan the evidence. Explore the assumptions.</p></div>'
        '<a class="action" href="index.html">← Market overview</a></div>'
    )
    if not w or w.get("status") != "ok":
        return (
            head + '<div class="banner warn"><strong>Watchlist not available</strong>This snapshot has no watchlist '
            "section (it predates spec 2026-10-14.2 or no list is configured).</div>"
        )
    entries = w["entries"]
    bodies = []
    for i, e in enumerate(entries):
        rid = f"w-{i}"
        status = tidy(e.get("unavailable_reason")) or (e.get("history_note") or "")
        km = e.get("key_metrics") or {}
        km_txt = " · ".join(
            t
            for t in (
                f"revenue {cap(km.get('revenue_ttm'))} ({pct(km.get('revenue_growth_ttm'), 0, True)})"
                if km.get("revenue_ttm")
                else "",
                f"operating margin {pct(km.get('operating_margin'))}" if ok(km.get("operating_margin")) else "",
                f"FCF {cap(km.get('fcf_ttm'))}" if ok(km.get("fcf_ttm")) else "",
                f"EV/Sales {num(km.get('ev_to_sales'), 1)}x" if ok(km.get("ev_to_sales")) else "",
                net_position(km.get("net_debt"), False) if ok(km.get("net_debt")) else "",
                f"dilution {pct(km.get('dilution'), 1)}/yr" if ok(km.get("dilution")) else "",
            )
            if t
        )
        bodies.append(f"""<tbody class="item" data-ticker="{E(e["ticker"])}" data-scenario="{"available" if e.get("scenarios") else "unavailable"}" data-sector="{E(e.get("sector") or "Unknown")}"><tr>
<td class="tk" data-v="{E(e["ticker"])}">{pin_button(e["ticker"])}<button class="rowtoggle" type="button" aria-expanded="false" aria-controls="{rid}"><strong>{E(e["ticker"])}</strong></button>
<div class="small muted">{E(e.get("name") or "name not resolved")}</div></td>
<td class="small hide-sm" data-v="{E(tidy(e.get("asset_type")))}">{E(tidy(e.get("asset_type")) or "unresolved")}<div class="muted">{E(e.get("exchange") or "")}</div></td>
<td class="num" data-v="{sval(e.get("price"))}">{money(e.get("price"))}<div class="small muted">{E(str(e.get("price_date") or ""))} · {price_note}</div></td>
{_upside_cell(e)}
{_scen_cells(e)}
<td class="small hide-sm">{E(e.get("method") or "")}</td><td class="small" data-v="{E(e.get("evidence_quality") or "")}">{quality_badge(quality_level(e.get("evidence_quality")), e.get("evidence_quality"), len(e.get("missing") or []))}</td>
<td class="small">{E(status)}{etf_metadata_line(e)}</td></tr>
<tr id="{rid}" class="detail" hidden><td colspan="10"><div class="evidence">
<div><h4>Identity</h4><p class="small">{E(e.get("name") or "unresolved")} · {E(tidy(e.get("asset_type")))} · {E(e.get("exchange") or "")} ·
status: {E(e.get("status") or "")}{" · CIK " + str(e["cik"]) if e.get("cik") else ""}. Sector/theme: {E(e.get("sector") or "n/a")}.</p>
<p class="small">{E(km_txt)}</p><p class="small">Trailing price returns: 1y {pct((e.get("returns") or {}).get("1y"), 0, True)},
3y {pct((e.get("returns") or {}).get("3y"), 0, True)} (history from {E(str(e.get("history_start") or "n/a"))}).</p></div>
<div><h4>Valuation method and assumptions</h4><p class="small">{E(e.get("assumptions_note") or status or "")}</p>{_assumptions(e)}
{_unlock(e)}{etf_sources(e)}</div>
<div><h4>Catalysts</h4><ul class="tight small">{"".join(f"<li>{E(c)}</li>" for c in e.get("catalysts", []))}</ul>
{_earnings_line(e)}<h4>Strongest bear case</h4><p class="small">{E(e.get("bear_case") or "n/a")}</p></div>
<div><h4>Thesis invalidation</h4><ul class="tight small">{"".join(f"<li>{E(c)}</li>" for c in e.get("invalidation", []))}</ul>
<h4>Sources, evidence and gaps</h4><p class="small">Evidence quality: {E(e.get("evidence_quality") or "none")}. Sources:
{E("; ".join(dict.fromkeys(e.get("sources", []))))}.</p><ul class="tight small">{"".join(f"<li>{E(m)}</li>" for m in e.get("missing", []))}</ul></div>
</div></td></tr></tbody>""")
    conc = " · ".join(f"{E(k)}: {v}" for k, v in sorted(w.get("concentration", {}).items(), key=lambda kv: -kv[1]))
    themes = sorted({e.get("sector") or "Unknown" for e in entries})
    opts = "".join(f'<option value="{E(s)}">{E(s)}</option>' for s in themes)
    available = sum(bool(e.get("scenarios")) for e in entries)
    priced = sum(ok(e.get("price")) for e in entries)
    return (
        head
        + f"""<div class="watch-summary scan-stats">
<div class="scan-stat"><span>Symbols</span><strong>{len(entries)}</strong><small>Separate research universe</small></div>
<div class="scan-stat"><span>With a recorded price</span><strong>{priced}</strong><small>Check each row's price date</small></div>
<div class="scan-stat"><span>Scenarios available</span><strong>{available}</strong><small>Conditional calculations</small></div>
<div class="scan-stat"><span>Scenarios unavailable</span><strong>{len(entries) - available}</strong><small>Reasons stay visible in each row</small></div></div>
<div class="banner warn small"><strong>Conditional 2030 price scenarios</strong>Assumption-based price outcomes; probability is not established.
<details><summary>Read the scenario limits</summary><p>{E(w["statement"].replace("predictions, ", ""))}</p></details></div>
<details class="small"><summary>About this watchlist and its concentration</summary><p><strong>Separate research universe</strong> {E(w["separation"])} The ticker list was imported on
{E(w["imported_at"])} and is not synchronized with any account; it works without a Robinhood login.</p>
<p class="small">Valuation date {E(snap["as_of"])} close · target {E(w["target_date"])} · horizon {num(w["years_to_target"], 2)} years ·
theme concentration: {conc}.</p></details>
<div class="controls"><input type="search" placeholder="Search ticker, name, reason" data-search="t-watch" aria-label="Search watchlist">
<select data-sector="t-watch" aria-label="Filter by sector or theme"><option value="">All sectors and themes</option>{opts}</select>
<select data-filter="t-watch" data-field="scenario" aria-label="Filter scenario availability"><option value="">All scenario states</option><option value="available">Scenarios available</option><option value="unavailable">Scenarios unavailable</option></select>
<select data-filter="t-watch" data-field="pinned" aria-label="Filter pinned watchlist"><option value="">All tickers</option><option value="yes">Pinned tickers</option></select>
<button class="action" type="button" data-reset="t-watch">Reset filters</button>
<span class="small muted" data-count="t-watch" aria-live="polite"></span></div>
<div class="table-wrap"><table id="t-watch" data-table data-grouped><caption class="sr-only">Watchlist 2030 scenarios</caption>
<thead><tr><th class="tk" data-sort="text">Ticker / name</th><th class="hide-sm" data-sort="text">Type</th><th class="num" data-sort="num">Latest price</th>
<th class="num" data-sort="num">Upside to base 2030</th>
<th class="num" data-sort="num">Bear 2030</th><th class="num" data-sort="num">Base 2030</th><th class="num" data-sort="num">Bull 2030</th>
<th class="hide-sm">Method</th><th data-sort="text">Evidence</th><th>Unavailable / notes</th></tr></thead>{"".join(bodies)}</table></div>
<p class="scan-empty" data-empty="t-watch" hidden>No symbols match these filters. Reset filters or pin a ticker with its star first.</p>
<p class="small muted" data-pin-status>Pins are saved only on this device.</p>
<details class="context-details"><summary>Compare all 2030 scenario ranges</summary>{range_chart(entries)}</details>
<details class="context-details"><summary>Valuation methods and assumptions</summary>
<p class="small"><a href="downloads/{E(snap["as_of"])}_watchlist_2030.csv" download>Download (CSV)</a> · Prices are split-adjusted
price data; scenarios are PRICE outcomes and exclude distributions (total return would add dividends). The upside bar uses a separate scale per row; its zero tick marks the latest price. Methods:
{E(spec.WATCHLIST_COMPANY_METHOD)} {E(spec.LEVERAGED_METHOD)} {E(spec.FEE_NOTE)}</p></details>
<p class="small"><a class="action" href="downloads/{E(snap["as_of"])}_watchlist_2030.csv" download>Download watchlist CSV ↓</a></p>"""
    )
