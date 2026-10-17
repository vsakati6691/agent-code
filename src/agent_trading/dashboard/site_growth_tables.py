"""Growth list tables, evidence fragments, sparklines and distribution strips."""

from __future__ import annotations

import json

from . import evidence, spec
from .fmt import cap, money, num, pct, sval
from .site_exclusions import excluded_summary
from .site_list_common import E, band_title, definition_line, ordered
from .site_research import quality_badge


def short_risk(text: str, limit: int = 90) -> str:
    """Compact form of the counterargument for the overview row (the full text is in the evidence panel)."""
    t = (text or "").replace("Weakest evidence: ", "")
    t = t.split(" (negative = ")[0].rstrip(".")  # older snapshots carry the previous wording
    t = t[0].upper() + t[1:] if t else t
    return t if len(t) <= limit else t[: limit - 1].rsplit(" ", 1)[0] + "…"


def _ret(c: dict, k: str):
    r = (c.get("history") or {}).get("returns", {}).get(k) or {}
    return r.get("stock"), r.get("excess")


def _earn_growth(m: dict) -> tuple[str, float | None]:
    f = m.get("fcf_growth_ttm")
    if f is not None and f != -1.0:
        return f"FCF {pct(f, 0, True)}", f
    o = m.get("operating_income_growth_ttm")
    if o is not None and o != -1.0:
        return f"EBIT {pct(o, 0, True)}", o
    return "n.m.", None


def _valuation(m: dict) -> str:
    parts = []
    if m.get("ev_to_sales") is not None:
        parts.append(f"EV/S {num(m['ev_to_sales'], 1)}x")
    if m.get("pe") is not None:
        parts.append(f"P/E {num(m['pe'], 0)}")
    return " · ".join(parts) or "n/a"


def sparkline(values: list, label: str) -> str:
    vals = [v for v in reversed(values) if v is not None]  # oldest -> newest
    if len(vals) < 2:
        return '<span class="muted small">n/a</span>'
    w, h = 120, 28
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or abs(hi) or 1
    pts = " ".join(f"{i * w / (len(vals) - 1):.1f},{h - 3 - (v - lo) / span * (h - 6):.1f}" for i, v in enumerate(vals))
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{E(label)}">'
        f'<polyline points="{pts}" fill="none" stroke="var(--series-1)" stroke-width="2"/></svg>'
    )


def spark_window(c: dict) -> tuple[int, str]:
    """(first chart point, window text) for the 1-year sparkline.

    Snapshots from spec 2026-10-14.5 store the exact start session of the 1-year return and include it in the
    chart, so the line starts there; older ones fall back to the last 53 weekly points (about one year)."""
    ch = c.get("chart") or {}
    dates = ch.get("dates") or []
    r = ((c.get("history") or {}).get("returns") or {}).get("1y") or {}
    if r.get("start") and r["start"] in dates:
        return dates.index(r["start"]), f"{r['start']} to {r.get('end')}"
    return max(0, len(dates) - 53), "about one year of weekly points"


def missing_note(c: dict) -> str:
    """The same missing-input indicator on every list row (spec 2026-10-14.5)."""
    n = len(c.get("missing") or [])
    level = evidence.quality_level(c.get("confidence_label"))
    return (
        f'<div class="small muted" title="evidence: {E(level)}; {n} missing input{"s" if n != 1 else ""} (scored 0)">'
        f"{E(level)}{f' · {n} missing' if n else ''}</div>"
    )


def row_spark(c: dict, bench: str) -> str:
    """1-year sparkline of the stock (solid) vs its benchmark (dashed), both rebased to 100 at the start.

    The label always shows the return table's 1-year figures, so the two can never disagree."""
    ch = c.get("chart") or {}
    i0, window = spark_window(c)
    s, b = (ch.get("stock") or [])[i0:], (ch.get("benchmark") or [])[i0:]
    if len(s) < 10:
        return '<span class="muted small">n/a</span>'
    vals = [v / s[0] * 100 for v in s]
    bvals = [v / b[0] * 100 for v in b] if len(b) == len(s) and b[0] else []
    lo, hi = min(vals + bvals), max(vals + bvals)
    span = (hi - lo) or 1
    w, h = 96, 26

    def pts(series):
        return " ".join(
            f"{i * w / (len(series) - 1):.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}" for i, v in enumerate(series)
        )

    ret = ((c.get("history") or {}).get("returns") or {}).get("1y") or {}
    r = ret.get("stock") if ret.get("stock") is not None else vals[-1] / 100 - 1
    br = ret.get("benchmark") if ret.get("stock") is not None else ((bvals[-1] / 100 - 1) if bvals else None)
    label = (
        f"1-year price: {c['ticker']} {r:+.0%}" + (f", {bench} {br:+.0%}" if br is not None else "") + f" ({window})"
    )
    bench_line = (
        (
            f'<polyline points="{pts(bvals)}" fill="none" stroke="var(--reference)" stroke-width="1.5" '
            f'stroke-dasharray="3 2"/>'
        )
        if bvals
        else ""
    )
    return (
        f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{E(label)}">'
        f'<title>{E(label)}</title>{bench_line}<polyline points="{pts(vals)}" fill="none" stroke="var(--series-1)" '
        f'stroke-width="2"/></svg>'
    )


CAP_BUCKETS = (
    (0, 2e9, "under $2B"),
    (2e9, 10e9, "$2B-$10B"),
    (10e9, 50e9, "$10B-$50B"),
    (50e9, 200e9, "$50B-$200B"),
    (200e9, float("inf"), "$200B+"),
)


def distribution_strip(cands: list[dict]) -> str:
    """Sector and market-cap mix of a list: one hue, bar length = count (no category colours needed)."""
    if not cands:
        return ""

    def strip(title, counts):
        total = sum(counts.values()) or 1
        items = "".join(
            f'<span class="chip"><span class="chipbar" style="width:{max(6, 60 * n / total):.0f}px"></span>'
            f"{E(k)} <strong>{n}</strong></span>"
            for k, n in counts.items()
            if n
        )
        return f'<div class="strip" role="group" aria-label="{E(title)}"><span class="muted">{E(title)}:</span>{items}</div>'

    sectors: dict[str, int] = {}
    for c in cands:
        sectors[c.get("sector") or "Unknown"] = sectors.get(c.get("sector") or "Unknown", 0) + 1
    sectors = dict(sorted(sectors.items(), key=lambda kv: (-kv[1], kv[0])))
    caps = {
        label: sum(1 for c in cands if c.get("market_cap") is not None and lo <= c["market_cap"] < hi)
        for lo, hi, label in CAP_BUCKETS
    }
    return strip("Sector mix", sectors) + strip("Market-cap mix", caps)


def evidence_block(key: str, c: dict, band: dict) -> str:
    comps = band.get("components") or [k for k in c.get("components", {})]
    bars = "".join(
        f'<div class="ev-row"><span>{E(k)}</span><div class="bar"><span style="width:{(c["components"].get(k) or 0) * 100:.0f}%">'
        f'</span></div><span class="num">{"n/a" if c["components"].get(k) is None else round(c["components"][k] * 100)}</span></div>'
        for k in comps
    )
    f = c.get("fundamentals") or {}
    m = c.get("metrics") or {}
    base = (c.get("scenarios") or {}).get("base") or {}
    a = base.get("assumptions") or {}
    yrs = sorted(int(y) for y in (base.get("years") or {}))
    vals = " · ".join(f"{y}y {money(base['years'][str(y)]['value_per_share'])}" for y in yrs) or "not computed"
    inval = "".join(f"<li>{E(x)}</li>" for x in c.get("invalidation", [])[:5])
    return f"""<div class="evidence">
<div><h4>Evidence (component scores)</h4>{bars}<p class="small">{
        quality_badge(
            evidence.quality_level(c.get("confidence_label")), c.get("confidence_label"), len(c.get("missing") or [])
        )
    }</p><p class="small muted">Missing inputs: {E(", ".join(c.get("missing", [])) or "none")}.</p></div>
<div><h4>Thesis</h4><p class="small">{E(c.get("thesis", ""))}</p><h4>Bear case</h4><p class="small">{
        E(c.get("bear_case", ""))
    }</p></div>
<div><h4>Financial trend (last 8 quarters, oldest → newest)</h4>
<p class="small">Revenue {sparkline(f.get("revenue", []), "revenue trend")} Operating income
{sparkline(f.get("operating_income", []), "operating income trend")}</p>
<p class="small">Gross margin {pct(m.get("gross_margin"))} · operating margin {
        pct(m.get("operating_margin"))
    } · FCF margin
{pct(m.get("fcf_margin"))} · net debt/EBITDA {num(m.get("net_debt_to_ebitda"), 1)} · dilution {
        pct(m.get("dilution"), 1)
    }</p>
<h4>Valuation assumptions (base case, conditional)</h4><p class="small">Start growth {
        pct(a.get("starting_revenue_growth"))
    }
fading to {pct(spec.SCENARIO_TERMINAL_GROWTH)}; exit EV/Sales {num(a.get("exit_ev_to_sales"), 1)}x; dilution
{pct(a.get("annual_dilution"), 1)}/yr → {vals}. {E(c.get("scenario_note") or "")}</p></div>
<div><h4>What would invalidate it</h4><ul class="tight small">{inval}</ul>
<p class="small"><a href="stock/{key}-{E(c["ticker"])}.html">Full research page →</a></p></div></div>"""


def fragment_path(key: str, ticker: str) -> str:
    """Where one candidate's evidence block lives: a small JSON file fetched when its row first opens, so the list
    pages carry only the table rows (the full research page and the file hold the same figures)."""
    return f"fragments/{key}-{E(ticker)}.json"


def evidence_fragments(bands: dict) -> dict[str, str]:
    """{published path: JSON text} for every candidate whose list page uses a lazy evidence row."""
    out = {}
    for key, band in bands.items():
        if key == "multibagger":  # its cards are shown in full on the multibagger page
            continue
        for c in band.get("candidates", []):
            out[f"fragments/{key}-{c['ticker']}.json"] = json.dumps(
                {"html": evidence_block(key, c, band)}, separators=(",", ":")
            )
    return out


def growth_table(key: str, band: dict) -> str:
    from .price_integrity import record_note

    tid = f"t-{key}"
    bodies = []
    for c in band["candidates"]:
        m = c.get("metrics") or {}
        r3, _ = _ret(c, "3m")
        r6, _ = _ret(c, "6m")
        r1, x1 = _ret(c, "1y")
        eg_txt, eg = _earn_growth(m)
        rid = f"d-{key}-{c['ticker'].replace('.', '_')}"
        short = (c.get("external") or {}).get("short_interest") or {}
        bodies.append(f"""<tbody class="item" data-sector="{E(c.get("sector") or "Unknown")}"><tr>
<td class="num" data-v="{c["rank"]}">{c["rank"]}</td>
<td class="tk"><button class="rowtoggle" type="button" aria-expanded="false" aria-controls="{rid}" title="Show evidence">
<strong>{E(c["ticker"])}</strong></button><div class="small muted">{E(c.get("name") or "")}</div>
<div class="small muted">{E(c.get("sector") or "Unknown")}</div>{f'<div class="small muted">AI role: {E(c["ai_role"])}</div>' if c.get("ai_role") else ""}</td>
<td class="num hide-sm" data-v="{sval(c.get("market_cap"))}">{cap(c.get("market_cap"))}</td>
<td class="num" data-v="{sval(c.get("price"))}">{money(c.get("price"))}<small>{E(record_note(c))}</small></td>
<td class="num hide-sm" data-v="{sval(m.get("revenue_growth_ttm"))}">{pct(m.get("revenue_growth_ttm"), 0, True)}</td>
<td class="num hide-sm" data-v="{sval(eg)}">{E(eg_txt)}</td>
<td class="num val hide-sm" data-v="{sval(m.get("ev_to_sales"))}">{E(_valuation(m))}</td>
<td class="num" data-v="{sval(c.get("composite"))}"><strong>{num(c.get("composite"), 1)}</strong>{missing_note(c)}</td>
<td class="num hide-sm" data-v="{sval(r3)}">{pct(r3, 0, True)}</td>
<td class="num hide-sm" data-v="{sval(r6)}">{pct(r6, 0, True)}</td>
<td class="num" data-v="{sval(r1)}">{pct(r1, 0, True)}</td>
<td class="num hide-sm" data-v="{sval(x1)}">{pct(x1, 0, True)}</td>
<td class="hide-sm">{row_spark(c, band.get("benchmark", "benchmark"))}</td>
<td class="num hide-sm" data-v="{sval(short.get("percent_of_diluted_shares"))}" title="{E(short.get("reason") or short.get("percent_reason") or "Settlement " + (short.get("settlement_date") or "not collected"))}">{pct(short.get("percent_of_diluted_shares"), 1)}</td>
<td class="small risk" title="{E(c.get("counterargument", ""))}">{E(short_risk(c.get("counterargument", "")))}</td></tr>
<tr id="{rid}" class="detail" hidden><td colspan="15"><div class="lazy" data-src="{fragment_path(key, c["ticker"])}"
data-page="stock/{key}-{E(c["ticker"])}.html"><p class="small"><a href="stock/{key}-{E(c["ticker"])}.html">Open {E(c["ticker"])} evidence</a></p></div></td></tr></tbody>""")
    sectors = sorted({c.get("sector") or "Unknown" for c in band["candidates"]})
    opts = "".join(f'<option value="{E(s)}">{E(s)}</option>' for s in sectors)
    head = (
        '<th class="num" data-sort="num">#</th><th class="tk" data-sort="text">Ticker / company / sector</th>'
        '<th class="num hide-sm" data-sort="num" title="Market cap: as-of close x SEC cover-page shares">Mkt cap</th>'
        '<th class="num" data-sort="num">Price</th><th class="num hide-sm" data-sort="num" title="Revenue growth over the trailing twelve months (TTM)">Rev gr.</th>'
        '<th class="num hide-sm" data-sort="num" title="TTM free-cash-flow growth, else operating income growth">Earn/FCF gr.</th>'
        '<th class="num hide-sm" data-sort="num" title="EV/S = enterprise value / sales; P/E = price / earnings">Valuation</th><th class="num" data-sort="num" title="Research score 0-100 from fixed rules (see Methodology)">Score</th>'
        '<th class="num hide-sm" data-sort="num">3M</th><th class="num hide-sm" data-sort="num">6M</th>'
        '<th class="num" data-sort="num">1Y</th><th class="num hide-sm" data-sort="num" title="1-year return minus the benchmark">vs bench</th>'
        '<th class="hide-sm" title="1-year price path: stock solid, benchmark dashed, both rebased to 100">1-yr path</th>'
        '<th class="num hide-sm" data-sort="num" title="Short interest as a percentage of XBRL diluted shares outstanding">Short / diluted shares</th>'
        '<th class="risk" title="The weakest scored evidence for this stock">Main risk / weakest evidence</th>'
    )
    return f"""<div class="controls"><input type="search" placeholder="Search ticker, name, risk" data-search="{tid}"
aria-label="Search {E(band_title(key, band))}"><select data-sector="{tid}" aria-label="Filter by sector"><option value="">All sectors</option>{opts}</select>
<span class="small muted" data-count="{tid}" aria-live="polite"></span></div>
<div class="table-wrap"><table id="{tid}" data-table data-grouped><caption class="sr-only">{E(band_title(key, band))}</caption>
<thead><tr>{head}</tr></thead>{"".join(bodies) or '<tbody><tr><td colspan="15" class="muted">No stock met every rule this week.</td></tr></tbody>'}</table></div>
<p class="small muted">Returns are trailing price returns to the as-of close (dividends excluded); "vs bench" is the 1-year
return minus {E(band.get("benchmark", ""))}. Select a ticker to show its evidence.</p>"""


def growth_section(snap: dict) -> str:
    bands = snap["bands"]
    keys = [k for k in ordered(bands) if k != "multibagger" and not k.startswith("ai_")]  # AI lists have their own page
    tabs = "".join(
        f'<button role="tab" id="tab-{k}" aria-controls="panel-{k}" data-tab="{k}" aria-selected="false">'
        f"{E(band_title(k, bands[k]))}</button>"
        for k in keys
    )
    panels = []
    for k in keys:
        b = bands[k]
        short = f'<div class="banner info small">{E(b["shortfall_note"])}</div>' if b.get("shortfall_note") else ""
        panels.append(f"""<section data-panel-of="growthtabs" data-panel="{k}" id="panel-{k}" role="tabpanel" aria-labelledby="tab-{k}" hidden>
<h3>{E(b.get("title", k))}</h3><p class="small">{E(definition_line(k, b))} Benchmark: {E(b.get("benchmark_name", b.get("benchmark", "")))}.
Showing {len(b["candidates"])} of up to {b.get("max_results", 10)}; {b.get("ranked", "?")} ranked, {len(b["excluded"])} excluded.</p>
{short}{distribution_strip(b["candidates"])}{growth_table(k, b)}
<p class="small"><a href="downloads/{E(snap["as_of"])}_{k}.csv" download>Download CSV</a></p>{excluded_summary(k, b)}</section>""")
    return f"""<h2 id="growth">Growth stocks</h2><div class="tabs" data-tabs id="growthtabs" role="tablist"
aria-label="Growth lists">{tabs}</div>{"".join(panels)}"""
