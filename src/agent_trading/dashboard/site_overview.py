"""Overview page: compact panels, the three growth lists and the speculative multibagger candidates."""
from __future__ import annotations

import html
import json
import re

from . import changes as changes_mod, evidence, spec
from .changes import KIND_LABELS
from .fmt import SUMMARIES, cap, money, num, pct, summary_details, sval, tracking_schedule
from .scenarios import implied_growth_text
from .site_options import status_block, watchlist_cards
from .site_research import datasets_line, quality_badge

E = html.escape
GROWTH_KEYS = ("large", "mid", "small")
ORDER = ("large", "mid", "small", "multibagger", "ai_large", "ai_mid")


def ordered(bands: dict) -> list[str]:
    """Display order: the growth lists, the multibagger list, then any retired list from an old snapshot."""
    return [k for k in ORDER if k in bands] + sorted(k for k in bands if k not in ORDER)
TIME_GUIDE = (
    "Four different time frames appear on this site and are never mixed: trailing historical returns (what "
    "already happened), conditional forward scenarios (1-10 years, or to 2030 for the watchlist), option expiry "
    "horizons (3, 6 and 12 months), and tracking periods (1-12 months after each weekly snapshot)."
)


NUMBER = re.compile(r"\$?-?\d+(?:[,.]\d+)*(?:[%BMKx](?![A-Za-z]))?")
NOT_CHECKED = "not checked for Robinhood tradability (only stocks that would make the list are checked)"
# stored reason -> (group label that keeps the rule's threshold, the stock's own value); anything else falls back to NUMBER
REASON_RULES = (
    (re.compile(r"^Robinhood tradability not yet verified$"), lambda m: (NOT_CHECKED, "")),
    (re.compile(r"^too little evidence: (\d+ of \d+) sub-metrics missing$"),
     lambda m: ("too little evidence (too many sub-metrics missing)", m[1])),
    (re.compile(r"^gate failed: (.+?) (\S+) \(needs (>=|<=) (.+)\)$"),
     lambda m: (f'gate failed: {m[1]} {"below" if m[3] == ">=" else "above"} {m[4]}', m[2])),
    (re.compile(r"^illiquid: (20-day median dollar volume) (\S+) < (\S+)$"), lambda m: (f"illiquid: {m[1]} below {m[3]}", m[2])),
    (re.compile(r"^market cap (\S+) outside the band$"), lambda m: ("market cap outside the band", m[1])),
    (re.compile(r"^price (\S+) below (\S+)$"), lambda m: (f"price below ${m[2]}", f"${m[1]}")),
    (re.compile(r"^revenue growth (\S+) below the (.+)$"), lambda m: (f"revenue growth below the {m[2]}", m[1])),
    (re.compile(r"^price data rejected: [^:]+: only (\d+) bars, need (\d+)$"),
     lambda m: (f"price data rejected: too little price history (needs {m[2]} daily bars)", f"{m[1]} bars")),
    (re.compile(r"^price data rejected: [^:]+: recent data anomaly \(frozen bars (\S+) to (\S+)\); feed unreliable$"),
     lambda m: ("price data rejected: recent data anomaly (frozen bars); feed unreliable", f"{m[1]} to {m[2]}")),
    (re.compile(r"^price data rejected: [^:]+: recent data anomaly \((.+) on (\S+)\); feed unreliable$"),
     lambda m: (f"price data rejected: recent data anomaly ({m[1]}); feed unreliable", m[2])),
    (re.compile(r"^price data rejected: [^:]+: (.+)$"), lambda m: (f"price data rejected: {m[1]}", "")),
)


def reason_group(reason: str) -> tuple[str, str]:
    """('gate failed: TTM revenue growth below 15%', '6%'): a readable group label and the stock's own value.
    Reasons without a known pattern are kept word for word (their numbers are part of the rule, e.g. '10-K')."""
    for pattern, label in REASON_RULES:
        m = pattern.match(reason)
        if m:
            return label(m)
    return reason, ""


def group_exclusions(excluded: list[dict]) -> list[tuple[str, list[tuple[str, str]]]]:
    """Exclusions grouped by reason with the stock's own values taken out, largest group first:
    [(reason, [(ticker, values)])]."""
    groups: dict[str, list[tuple[str, str]]] = {}
    for x in excluded:
        key, values = reason_group(x["reason"])
        groups.setdefault(key, []).append((x["ticker"], values))
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


def excluded_summary(key: str, band: dict) -> str:
    n = len(band.get("excluded", []))
    if not n:
        return '<p class="small muted">No stock was excluded.</p>'
    top = "; ".join(f"{E(r)} ({len(t)})" for r, t in group_exclusions(band["excluded"])[:3])
    return (f'<p class="small"><a href="excluded-{E(key)}.html">{n:,} excluded or not ranked: see every stock and '
            f'reason →</a><br><span class="muted">Most common: {top}</span></p>')


def excluded_page(key: str, band: dict) -> str:
    groups = group_exclusions(band.get("excluded", []))
    blocks = "".join(
        f'<details><summary>{E(reason)} <span class="muted">({len(items):,})</span></summary><p class="small">'
        + ", ".join(f"{E(t)}" + (f" ({E(d)})" if d else "") for t, d in items) + "</p></details>"
        for reason, items in groups)
    return (f'<p class="small"><a href="index.html#{E(key)}">&larr; back to the list</a></p>'
            f'<h1>Excluded from: {E(band_title(key, band))}</h1>'
            f'<p class="lede">Every stock that was considered for this list but not ranked or not shown, grouped by '
            f'reason. Numbers in brackets are the values that failed the rule.</p>'
            f'{blocks or "<p class=muted>No stock was excluded.</p>"}')


def band_title(key: str, band: dict) -> str:
    return band.get("short_title") or spec.BAND_TITLES_SHORT.get(key) or \
        spec.LEGACY_BANDS.get(key, {}).get("title") or band.get("title", key)


def definition_line(key: str, band: dict) -> str:
    d = band.get("definition") or {}
    if key == "large" or d.get("universe") == "sp500":
        return ("Universe: current S&P 500 members only. This is not the whole large-cap market; large companies "
                "outside the index are not screened here.")
    lo, hi = d.get("min_cap"), d.get("max_cap")
    rng = f"{cap(lo) if lo else 'any'} to {cap(hi) if hi else 'any'}"
    uni = ("S&P 500 plus the broad US-listed universe" if d.get("universe") == "all" else
           "US-listed common stocks on NYSE, Nasdaq, NYSE American, NYSE Arca and Cboe BZX (excluding OTC)")
    extra = f"; price ≥ ${d['min_price']:g}; 20-day median dollar volume ≥ {cap(d['min_dollar_volume'])}" \
        if d.get("min_price") else ""
    return f"Universe: {uni}; market cap {rng}{extra}. Market cap = as-of close x SEC cover-page shares."


def short_risk(text: str, limit: int = 90) -> str:
    """Compact form of the counterargument for the overview row (the full text is in the evidence panel)."""
    t = (text or "").replace("Weakest evidence: ", "")
    t = t.split(" (negative = ")[0].rstrip(".")       # older snapshots carry the previous wording
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
    vals = [v for v in reversed(values) if v is not None]       # oldest -> newest
    if len(vals) < 2:
        return '<span class="muted small">n/a</span>'
    w, h = 120, 28
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or abs(hi) or 1
    pts = " ".join(f"{i * w / (len(vals) - 1):.1f},{h - 3 - (v - lo) / span * (h - 6):.1f}" for i, v in enumerate(vals))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{E(label)}">'
            f'<polyline points="{pts}" fill="none" stroke="var(--series-1)" stroke-width="2"/></svg>')


def spark_window(c: dict) -> tuple[int, str]:
    """(first chart point, window text) for the 1-year sparkline.

    Snapshots from spec 2026-10-14.5 store the exact start session of the 1-year return and include it in the
    chart, so the line starts there; older ones fall back to the last 53 weekly points (about one year)."""
    ch = c.get("chart") or {}
    dates = ch.get("dates") or []
    r = ((c.get("history") or {}).get("returns") or {}).get("1y") or {}
    if r.get("start") and r["start"] in dates:
        return dates.index(r["start"]), f'{r["start"]} to {r.get("end")}'
    return max(0, len(dates) - 53), "about one year of weekly points"


def missing_note(c: dict) -> str:
    """The same missing-input indicator on every list row (spec 2026-10-14.5)."""
    n = len(c.get("missing") or [])
    level = evidence.quality_level(c.get("confidence_label"))
    return (f'<div class="small muted" title="evidence: {E(level)}; {n} missing input{"s" if n != 1 else ""} (scored 0)">'
            f'{E(level)}{f" · {n} missing" if n else ""}</div>')


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
        return " ".join(f"{i * w / (len(series) - 1):.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}" for i, v in enumerate(series))
    ret = ((c.get("history") or {}).get("returns") or {}).get("1y") or {}
    r = ret.get("stock") if ret.get("stock") is not None else vals[-1] / 100 - 1
    br = ret.get("benchmark") if ret.get("stock") is not None else ((bvals[-1] / 100 - 1) if bvals else None)
    label = (f"1-year price: {c['ticker']} {r:+.0%}" + (f", {bench} {br:+.0%}" if br is not None else "") +
             f" ({window})")
    bench_line = (f'<polyline points="{pts(bvals)}" fill="none" stroke="var(--reference)" stroke-width="1.5" '
                  f'stroke-dasharray="3 2"/>') if bvals else ""
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{E(label)}">'
            f'<title>{E(label)}</title>{bench_line}<polyline points="{pts(vals)}" fill="none" stroke="var(--series-1)" '
            f'stroke-width="2"/></svg>')


CAP_BUCKETS = ((0, 2e9, "under $2B"), (2e9, 10e9, "$2B-$10B"), (10e9, 50e9, "$10B-$50B"), (50e9, 200e9, "$50B-$200B"),
               (200e9, float("inf"), "$200B+"))


def distribution_strip(cands: list[dict]) -> str:
    """Sector and market-cap mix of a list: one hue, bar length = count (no category colours needed)."""
    if not cands:
        return ""

    def strip(title, counts):
        total = sum(counts.values()) or 1
        items = "".join(f'<span class="chip"><span class="chipbar" style="width:{max(6, 60 * n / total):.0f}px"></span>'
                        f'{E(k)} <strong>{n}</strong></span>' for k, n in counts.items() if n)
        return f'<div class="strip" role="group" aria-label="{E(title)}"><span class="muted">{E(title)}:</span>{items}</div>'
    sectors: dict[str, int] = {}
    for c in cands:
        sectors[c.get("sector") or "Unknown"] = sectors.get(c.get("sector") or "Unknown", 0) + 1
    sectors = dict(sorted(sectors.items(), key=lambda kv: (-kv[1], kv[0])))
    caps = {label: sum(1 for c in cands if c.get("market_cap") is not None and lo <= c["market_cap"] < hi)
            for lo, hi, label in CAP_BUCKETS}
    return strip("Sector mix", sectors) + strip("Market-cap mix", caps)


def evidence_block(key: str, c: dict, band: dict) -> str:
    comps = band.get("components") or [k for k in c.get("components", {})]
    bars = "".join(
        f'<div class="ev-row"><span>{E(k)}</span><div class="bar"><span style="width:{(c["components"].get(k) or 0) * 100:.0f}%">'
        f'</span></div><span class="num">{"n/a" if c["components"].get(k) is None else round(c["components"][k] * 100)}</span></div>'
        for k in comps)
    f = c.get("fundamentals") or {}
    m = c.get("metrics") or {}
    base = ((c.get("scenarios") or {}).get("base") or {})
    a = base.get("assumptions") or {}
    yrs = sorted(int(y) for y in (base.get("years") or {}))
    vals = " · ".join(f'{y}y {money(base["years"][str(y)]["value_per_share"])}' for y in yrs) or "not computed"
    inval = "".join(f"<li>{E(x)}</li>" for x in c.get("invalidation", [])[:5])
    return f"""<div class="evidence">
<div><h4>Evidence (component scores)</h4>{bars}<p class="small">{quality_badge(evidence.quality_level(c.get("confidence_label")),
c.get("confidence_label"), len(c.get("missing") or []))}</p><p class="small muted">Missing inputs: {E(", ".join(c.get("missing", [])) or "none")}.</p></div>
<div><h4>Thesis</h4><p class="small">{E(c.get("thesis", ""))}</p><h4>Bear case</h4><p class="small">{E(c.get("bear_case", ""))}</p></div>
<div><h4>Financial trend (last 8 quarters, oldest → newest)</h4>
<p class="small">Revenue {sparkline(f.get("revenue", []), "revenue trend")} Operating income
{sparkline(f.get("operating_income", []), "operating income trend")}</p>
<p class="small">Gross margin {pct(m.get("gross_margin"))} · operating margin {pct(m.get("operating_margin"))} · FCF margin
{pct(m.get("fcf_margin"))} · net debt/EBITDA {num(m.get("net_debt_to_ebitda"), 1)} · dilution {pct(m.get("dilution"), 1)}</p>
<h4>Valuation assumptions (base case, conditional)</h4><p class="small">Start growth {pct(a.get("starting_revenue_growth"))}
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
        if key == "multibagger":          # its cards are shown in full on the overview
            continue
        for c in band.get("candidates", []):
            out[f"fragments/{key}-{c['ticker']}.json"] = json.dumps({"html": evidence_block(key, c, band)},
                                                                    separators=(",", ":"))
    return out


def growth_table(key: str, band: dict) -> str:
    tid = f"t-{key}"
    bodies = []
    for c in band["candidates"]:
        m = c.get("metrics") or {}
        r3, _ = _ret(c, "3m")
        r6, _ = _ret(c, "6m")
        r1, x1 = _ret(c, "1y")
        eg_txt, eg = _earn_growth(m)
        rid = f"d-{key}-{c['ticker'].replace('.', '_')}"
        bodies.append(f"""<tbody class="item" data-sector="{E(c.get("sector") or "Unknown")}"><tr>
<td class="num" data-v="{c["rank"]}">{c["rank"]}</td>
<td class="tk"><button class="rowtoggle" type="button" aria-expanded="false" aria-controls="{rid}" title="Show evidence">
<strong>{E(c["ticker"])}</strong></button><div class="small muted">{E(c.get("name") or "")}</div>
<div class="small muted">{E(c.get("sector") or "Unknown")}</div>{f'<div class="small muted">AI role: {E(c["ai_role"])}</div>' if c.get("ai_role") else ""}</td>
<td class="num hide-sm" data-v="{sval(c.get("market_cap"))}">{cap(c.get("market_cap"))}</td>
<td class="num" data-v="{sval(c.get("price"))}">{money(c.get("price"))}</td>
<td class="num hide-sm" data-v="{sval(m.get("revenue_growth_ttm"))}">{pct(m.get("revenue_growth_ttm"), 0, True)}</td>
<td class="num hide-sm" data-v="{sval(eg)}">{E(eg_txt)}</td>
<td class="num val hide-sm" data-v="{sval(m.get("ev_to_sales"))}">{E(_valuation(m))}</td>
<td class="num" data-v="{sval(c.get("composite"))}"><strong>{num(c.get("composite"), 1)}</strong>{missing_note(c)}</td>
<td class="num hide-sm" data-v="{sval(r3)}">{pct(r3, 0, True)}</td>
<td class="num hide-sm" data-v="{sval(r6)}">{pct(r6, 0, True)}</td>
<td class="num" data-v="{sval(r1)}">{pct(r1, 0, True)}</td>
<td class="num hide-sm" data-v="{sval(x1)}">{pct(x1, 0, True)}</td>
<td class="hide-sm">{row_spark(c, band.get("benchmark", "benchmark"))}</td>
<td class="small risk" title="{E(c.get("counterargument", ""))}">{E(short_risk(c.get("counterargument", "")))}</td></tr>
<tr id="{rid}" class="detail" hidden><td colspan="14"><div class="lazy" data-src="{fragment_path(key, c["ticker"])}"
data-page="stock/{key}-{E(c["ticker"])}.html"><p class="small muted">Loading the evidence…</p></div></td></tr></tbody>""")
    sectors = sorted({c.get("sector") or "Unknown" for c in band["candidates"]})
    opts = "".join(f'<option value="{E(s)}">{E(s)}</option>' for s in sectors)
    head = ('<th class="num" data-sort="num">#</th><th class="tk" data-sort="text">Ticker / company / sector</th>'
            '<th class="num hide-sm" data-sort="num" title="Market cap: as-of close x SEC cover-page shares">Mkt cap</th>'
            '<th class="num" data-sort="num">Price</th><th class="num hide-sm" data-sort="num" title="Revenue growth over the trailing twelve months (TTM)">Rev gr.</th>'
            '<th class="num hide-sm" data-sort="num" title="TTM free-cash-flow growth, else operating income growth">Earn/FCF gr.</th>'
            '<th class="num hide-sm" data-sort="num" title="EV/S = enterprise value / sales; P/E = price / earnings">Valuation</th><th class="num" data-sort="num" title="Research score 0-100 from fixed rules (see Methodology)">Score</th>'
            '<th class="num hide-sm" data-sort="num">3M</th><th class="num hide-sm" data-sort="num">6M</th>'
            '<th class="num" data-sort="num">1Y</th><th class="num hide-sm" data-sort="num" title="1-year return minus the benchmark">vs bench</th>'
            '<th class="hide-sm" title="1-year price path: stock solid, benchmark dashed, both rebased to 100">1-yr path</th>'
            '<th class="risk" title="The weakest scored evidence for this stock">Main risk / weakest evidence</th>')
    return f"""<div class="controls"><input type="search" placeholder="Search ticker, name, risk" data-search="{tid}"
aria-label="Search {E(band_title(key, band))}"><select data-sector="{tid}" aria-label="Filter by sector"><option value="">All sectors</option>{opts}</select>
<span class="small muted" data-count="{tid}" aria-live="polite"></span></div>
<div class="table-wrap"><table id="{tid}" data-table data-grouped><caption class="sr-only">{E(band_title(key, band))}</caption>
<thead><tr>{head}</tr></thead>{''.join(bodies) or '<tbody><tr><td colspan="14" class="muted">No stock met every rule this week.</td></tr></tbody>'}</table></div>
<p class="small muted">Returns are trailing price returns to the as-of close (dividends excluded); "vs bench" is the 1-year
return minus {E(band.get("benchmark", ""))}. Select a ticker to show its evidence.</p>"""


def growth_section(snap: dict) -> str:
    bands = snap["bands"]
    keys = [k for k in ordered(bands) if k != "multibagger" and not k.startswith("ai_")]     # AI lists have their own page
    tabs = "".join(f'<button role="tab" id="tab-{k}" aria-controls="panel-{k}" data-tab="{k}" aria-selected="false">'
                   f'{E(band_title(k, bands[k]))}</button>' for k in keys)
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
aria-label="Growth lists">{tabs}</div>{''.join(panels)}"""


def multibagger_needs(c: dict) -> str:
    sc = c.get("scenarios") or {}
    bull = sc.get("bull") or {}
    yrs = sorted(int(y) for y in (bull.get("years") or {}))
    if not yrs:
        return "Scenarios not computed, so the required path cannot be stated. " + (c.get("scenario_note") or "")
    last = yrs[-1]
    y = bull["years"][str(last)]
    m = c.get("metrics") or {}
    rev0 = m.get("revenue_ttm")
    a = bull.get("assumptions") or {}
    cagr = (y["revenue"] / rev0) ** (1 / last) - 1 if rev0 else None
    reach = y["multiple_of_price"]
    verdict = ("reaches" if reach >= 5 else "does NOT reach") + f" 5x ({num(reach, 1)}x) in {last} years"
    return (f"In the bull case revenue grows from {cap(rev0)} to about {cap(y['revenue'])} ({pct(cagr)} a year for "
            f"{last} years), EV/Sales holds at about {num(a.get('exit_ev_to_sales'), 1)}x and dilution stays near "
            f"{pct(a.get('annual_dilution'), 1)} a year. Under those assumptions the bull case {verdict}. All of it "
            "would have to happen together; none of it is forecast.")


def scenario_flags_html(c: dict, band: dict | None = None) -> str:
    """Passing the research screen and passing each scenario test are different things; show both, apart."""
    sc = c.get("scenarios") or {}
    fl = sc.get("flags") or {}
    gates = (band or {}).get("gates") or []
    screen = (f"passed: ranked #{c.get('rank')} with every eligibility gate met" if gates else
              f"passed: ranked #{c.get('rank')} (liquidity, data and tradability rules met)")

    def cell(key, label):
        if key not in fl:
            return f'<li>{E(label)}: <span class="pill muted">not tested</span></li>'
        return f'<li>{E(label)}: <span class="pill {"ok" if fl[key] else "muted"}">{"yes" if fl[key] else "no"}</span></li>'
    tests = (cell("bull_doubles_in_5y", "2x in 5 years (bull case)") + cell("bull_multibagger_5y", "5x in 5 years (bull case)") +
             cell("bull_5x_in_10y", "5x in 10 years (bull case)") + cell("base_2x_in_10y", "2x in 10 years (base case)"))
    note = "" if sc else ' <span class="muted">Scenarios were not computed, so every test reads "not tested".</span>'
    return (f'<div class="flags small"><p><strong>Research screen:</strong> {E(screen)}. Passing the screen is separate from '
            f'the scenario tests below.</p><p><strong>Scenario tests</strong> (conditional on the stated assumptions; not '
            f'forecasts, targets or probabilities):{note}</p><ul class="tight">{tests}</ul></div>')


def multibagger_section(snap: dict) -> str:
    b = snap["bands"].get("multibagger")
    if not b:
        return ""
    cards = []
    for c in b["candidates"]:
        m = c.get("metrics") or {}
        sc = c.get("scenarios")
        rows = ""
        if sc:
            yrs = sorted(int(y) for y in sc["base"]["years"])
            head = "".join(f'<th class="num">{y}y</th>' for y in yrs)
            for k in ("bear", "base", "bull"):
                rows += f'<tr><td>{k}</td>' + "".join(
                    f'<td class="num">{money(sc[k]["years"][str(y)]["value_per_share"])}<div class="small muted">'
                    f'{num(sc[k]["years"][str(y)]["multiple_of_price"], 1)}x</div></td>' for y in yrs) + "</tr>"
            scen = f'<div class="table-wrap"><table aria-label="Bear, base and bull values per share"><thead><tr><th>Scenario</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
        else:
            scen = f'<p class="small muted">{E(c.get("scenario_note") or "Scenarios not computed.")}</p>'
        runway = m.get("cash_runway_years")
        cash_txt = (f"FCF {cap(m.get('fcf_ttm'))} (margin {pct(m.get('fcf_margin'))})" if (m.get("fcf_ttm") or 0) > 0
                    else f"cash burn; runway about {num(runway, 1)} years" if runway is not None else "cash flow n/a")
        inval = "".join(f"<li>{E(x)}</li>" for x in c.get("invalidation", [])[:4])
        cards.append(f"""<article class="card mb"><header><span class="rank">#{c["rank"]}</span>
<a href="stock/multibagger-{E(c["ticker"])}.html"><strong>{E(c["ticker"])}</strong></a> {E(c.get("name") or "")}
<span class="small muted">{E(c.get("sector") or "")} · {cap(c.get("market_cap"))} · {money(c.get("price"))} · score {num(c.get("composite"), 1)}</span></header>
<div class="mb-grid"><div><h4>Growth opportunity and evidence</h4><p class="small">{E(c.get("thesis", ""))}</p>
<p class="small">Revenue {pct(m.get("revenue_growth_ttm"), 0, True)} TTM, {pct(m.get("revenue_cagr_3y"), 0, True)}/yr over 3 years ·
gross margin {pct(m.get("gross_margin"))} · operating margin {pct(m.get("operating_margin"))} · {E(cash_txt)}</p></div>
<div><h4>Debt, dilution and valuation risk</h4><p class="small">Net debt/EBITDA {num(m.get("net_debt_to_ebitda"), 1)} ·
dilution {pct(m.get("dilution"), 1)}/yr · SBC {pct(m.get("sbc_to_revenue"))} of revenue · EV/Sales {num(m.get("ev_to_sales"), 1)}x;
{E(implied_growth_text(m.get("implied_revenue_cagr"), m.get("revenue_growth_ttm")))}. {E(c.get("bear_case", ""))}</p></div></div>
<h4>Bear / base / bull (conditional values per share)</h4>{scen}
{scenario_flags_html(c, b)}
<h4>What must happen for a multibagger outcome</h4><p class="small">{E(multibagger_needs(c))}</p>
<h4>What would invalidate the thesis</h4><ul class="tight small">{inval}</ul></article>""")
    return f"""<h2 id="multibagger">Speculative multibagger research candidates</h2>
<div class="banner warn small"><strong>5-10 year research horizon</strong>These are long-horizon research candidates. Nothing
here implies multibagger returns within 3-12 months.
{summary_details(SUMMARIES["multibagger"], spec.MULTIBAGGER_DEFINITION)}
{summary_details(SUMMARIES["probability"], spec.PROBABILITY_STATEMENT, "Why no probabilities")}</div>
<p class="small">{E(definition_line("multibagger", b))} Showing {len(b["candidates"])} of up to {b.get("max_results", 5)}.
<a href="methodology.html#multibagger">Criteria and rationale</a> ·
<a href="downloads/{E(snap["as_of"])}_multibagger.csv" download>CSV</a></p>
{f'<div class="banner info small">{E(b["shortfall_note"])}</div>' if b.get("shortfall_note") else ''}
<div class="mb-list">{''.join(cards) or '<p class="muted">No stock passed every gate this week.</p>'}</div>
{excluded_summary("multibagger", b)}"""


# --- compact panels ------------------------------------------------------------------------------

RISK_GROUPS = ("25%+ below the 52-week high", "5-year drawdown worse than -50%", "Negative free cash flow",
               "Dilution above 5% a year", "EV/Sales above 15x")


def _risk_flags(c: dict) -> list[str]:
    """Downside-risk groups this candidate falls into (names from RISK_GROUPS)."""
    m = c.get("metrics") or {}
    dd = (c.get("history") or {}).get("drawdowns", {})
    hits = [(dd.get("from_52w_high") or 0) <= -0.25, ((dd.get("max_5y") or {}).get("value") or 0) <= -0.5,
            (m.get("fcf_ttm") or 0) < 0, (m.get("dilution") or 0) > 0.05, (m.get("ev_to_sales") or 0) > 15]
    return [g for g, hit in zip(RISK_GROUPS, hits) if hit]


def move_cause(ch: dict, list_name: str) -> str:
    """'S04 up 4 to #1 (Large cap): score +5.3; growth +12.0, valuation -1.5' (older snapshots: stored text)."""
    d = ch["change"]
    head = f'{ch["ticker"]} {"up" if d > 0 else "down"} {abs(d)} to #{ch.get("to")} ({list_name})'
    comps = ch.get("component_changes")
    if comps is None:
        return f'{head}: {ch.get("explanation", "")}'
    sc = ch.get("score_change")
    if not comps and (not isinstance(sc, (int, float)) or abs(sc) < 0.05):
        why = "other stocks scored higher this week" if d < 0 else "stocks above it fell back or left the list"
        return f"{head}: its own score was unchanged; {why}"
    parts = ([f"score {sc:+.1f}"] if isinstance(sc, (int, float)) else []) + \
        [", ".join(f"{k} {v:+.1f}" for k, v in comps.items()) or "component scores unchanged"]
    return f"{head}: " + "; ".join(parts)


FLAG_LIST_MAX = 8      # longer flag lists collapse to a count, so a flag shared by most names doesn't bury the rest
EARNINGS_SHOWN = 5     # the earnings panel shows the next five dates; the rest fold behind "N more"


def _flag_item(group: str, tickers: list[str], total: int) -> str:
    if len(tickers) <= FLAG_LIST_MAX:
        return f'<li class="small"><strong>{E(group)}:</strong> {E(", ".join(tickers))}</li>'
    return (f'<li class="small"><details><summary><strong>{E(group)}:</strong> {len(tickers)} of {total} listed '
            f'names</summary>{E(", ".join(tickers))}</details></li>')


def _last_results(i: dict) -> str:
    if i.get("last_results"):
        return (f'<br><span class="small">last results {E(i["last_results"])}, {E(i.get("last_results_status") or "")}'
                f'{"; " + E(i["cadence_check"]) if i.get("cadence_check") else ""}</span>')
    if i.get("last_results_status"):
        return f'<br><span class="small muted">{E(i["last_results_status"])}</span>'
    return ""


def panels(snap: dict, tracking: dict | None, dates: list[str] | None = None, prev_snap: dict | None = None) -> str:
    bands = snap["bands"]
    ev = (snap.get("events") or {})
    items = ev.get("items")
    if items is None:
        earn = '<p class="small muted">Not collected in this snapshot.</p>'
    elif not items and evidence.earnings_state(snap)[0] != "available":
        earn = ('<p class="small">Earnings dates could not be collected for this snapshot, so upcoming reports are '
                'not listed (this does not mean none are due).</p>'
                f'<p class="small muted">{E(ev.get("note", ""))}</p>')
    else:
        rows = [f'<li><strong>{E(i["ticker"])}</strong> {E(i["date"])} <span class="muted">(scheduled, unverified; '
                f'{E(i["list"])})</span>{_last_results(i)}</li>' for i in items[:12]]
        earn = "".join(rows[:EARNINGS_SHOWN]) or '<li class="muted">No earnings scheduled in the next 45 days.</li>'
        more = (f'<details class="small"><summary>{len(rows) - EARNINGS_SHOWN} more</summary><ul class="tight">'
                f'{"".join(rows[EARNINGS_SHOWN:])}</ul></details>' if len(rows) > EARNINGS_SHOWN else "")
        earn = f'<ul class="tight small">{earn}</ul>{more}<p class="small muted">{E(ev.get("note", ""))}</p>'
    new, gone, moves = [], [], []
    for k in ordered(bands):
        short = band_title(k, bands[k])
        for ch in bands[k].get("rank_changes", []):
            if ch["change"] in ("new", "new (first snapshot)"):
                new.append(f'{ch["ticker"]} (#{ch.get("to")}, {short})')
            elif ch["change"] == "dropped":
                gone.append(f'{ch["ticker"]} (was #{ch.get("from")}, {short})')
            elif isinstance(ch["change"], int) and ch["change"]:
                moves.append((abs(ch["change"]), move_cause(ch, short)))
    first = all(ch["change"] == "new (first snapshot)" for b in bands.values() for ch in b.get("rank_changes", []))
    summ = changes_mod.summary(snap, prev_snap)
    if prev_snap is None:
        what = ('<p class="small muted">No earlier snapshot is stored, so filings, deterioration, dilution, thesis '
                'conditions and data availability cannot be compared yet.</p>')
    else:
        counts = " · ".join(f"{KIND_LABELS[k]}: {n}" for k, n in summ["counts"].items() if n) or "nothing listed"
        top = "".join(f'<li><a href="stock/{E(r["band"])}-{E(r["ticker"])}.html">{E(r["ticker"])}</a>: {E(r["text"])}</li>'
                      for r in [r for r in summ["rows"] if r["kind"] in ("thesis", "deterioration", "filing", "dilution")][:6])
        what = (f'<p class="small"><strong>Since {E(summ["previous"])}</strong> ({E(counts)}; names on both '
                f'snapshots only)</p><ul class="tight small">{top}</ul>')
    move_items = "".join(f"<li>{E(t)}</li>" for _, t in sorted(moves, key=lambda m: -m[0])[:6])
    changes = ('<p class="small muted">First snapshot: no previous week to compare.</p>' if first else
               f'<p class="small"><strong>New:</strong> {E(", ".join(new) or "none")}<br><strong>Departed:</strong> '
               f'{E(", ".join(gone) or "none")}</p><p class="small"><strong>Biggest moves and why</strong> '
               f'(change in the 0-100 score, then the component scores that moved most):</p>'
               f'<ul class="tight small">{move_items or "<li>none</li>"}</ul>')
    conc = [f"{band_title(k, bands[k])}: {w}" for k in ordered(bands) for w in bands[k].get("concentration", [])]
    groups: dict[str, list[str]] = {g: [] for g in RISK_GROUPS}
    for k in ordered(bands):
        for c in bands[k]["candidates"]:
            for g in _risk_flags(c):
                groups[g].append(c["ticker"])
    total = len({c["ticker"] for k in ordered(bands) for c in bands[k]["candidates"]})
    risk = ("".join(f'<li class="small">{E(w)}</li>' for w in conc) +
            "".join(_flag_item(g, list(dict.fromkeys(ts)), total) for g, ts in groups.items() if ts))
    measured = any(v.get(h, {}).get("snapshots_measured") for v in ((tracking or {}).get("summary") or {}).values()
                   for h in spec.TRACK_HORIZONS)
    perf = f'<p class="small muted">{E(tracking_schedule(dates or [snap["as_of"]]))}</p>'
    if tracking and tracking.get("summary") and measured:
        rows = "".join(f'<tr><td>{E(k)}</td>' + "".join(
            f'<td class="num">{pct((v.get(h) or {}).get("mean_excess_net"), 1, True)}</td>' for h in spec.TRACK_HORIZONS) + "</tr>"
            for k, v in tracking["summary"].items())
        perf = (f'<div class="table-wrap"><table class="small" aria-label="Mean excess return by list and horizon"><thead><tr><th>List</th>' +
                "".join(f'<th class="num">{h}</th>' for h in spec.TRACK_HORIZONS) +
                f'</tr></thead><tbody>{rows}</tbody></table></div><p class="small muted">Mean excess return vs benchmark, net of '
                f'assumed friction, from immutable prior snapshots. {E(tracking.get("evidence_note", ""))}</p>')
    u = snap["universe"]
    tr = snap.get("tradability") or {}
    cov = (f'<p class="small">S&amp;P 500 price coverage {pct(u.get("sp500_price_coverage"))} of {u.get("sp500_count")} · broad '
           f'universe {u.get("broad_eligible")} eligible, {u.get("broad_prescreen")} pre-screened · Robinhood verdicts '
           f'{tr.get("verdicts_stored", "n/a")}, {tr.get("to_check", "n/a")} to check · snapshot '
           f'{E(str(snap.get("run_finished", "")).replace("+00:00", ""))} UTC.</p>'
           f'<p class="small">{E("; ".join(snap.get("problems", []) + snap.get("notes", [])) or "No missing-data warnings.")}</p>'
           f'<p class="small">{datasets_line(evidence.datasets(snap))}</p>'
           '<p class="small"><a href="audit.html#data-status">Data status, sources and audit trail →</a></p>')
    return f"""<div class="panels">
<section class="card"><h3>Upcoming earnings (45 days)</h3>{earn}</section>
<section class="card"><h3>What changed since the previous snapshot?</h3>{what}{changes}</section>
<section class="card"><h3>Concentration and downside flags</h3><ul class="tight">{risk or '<li class="small muted">None triggered.</li>'}</ul></section>
<section class="card"><h3>Performance vs benchmarks</h3>{perf}</section>
<section class="card"><h3>Data coverage and freshness</h3>{cov}</section></div>"""


def ai_teaser(snap: dict) -> str:
    """Overview block: the top 5 of each AI list, linking to the AI page (nothing for a snapshot without AI lists)."""
    bands = {k: snap["bands"][k] for k in ("ai_large", "ai_mid") if k in (snap.get("bands") or {})}
    if not bands:
        return ""
    cards = []
    for key, b in bands.items():
        items = "".join(
            f'<li><a href="stock/{key}-{E(c["ticker"])}.html"><strong>{E(c["ticker"])}</strong></a> {E(c.get("name") or "")} '
            f'<span class="muted">· {E(c.get("ai_role") or "")} · score {num(c.get("composite"), 1)}</span></li>'
            for c in b["candidates"])
        cards.append(f'<section class="card"><h3>{E(band_title(key, b))}</h3>'
                     f'<ol class="tight small">{items or "<li>none met every rule this week</li>"}</ol></section>')
    return (f'<h2 id="ai-stocks">AI stocks</h2><p class="small">The top 5 AI-exposed stocks by the same fixed rules, a scenario test '
            f'of whether any could reach the largest market caps, and private AI companies for context. Not forecasts, '
            f'and no probabilities. <a href="ai.html">Open the AI page</a>.</p><div class="ow-grid">{"".join(cards)}</div>')


def overview(snap: dict, status: dict | None, dates: list[str], tracking: dict | None,
             prev_snap: dict | None = None) -> str:
    counts = " · ".join(f'{E(band_title(k, snap["bands"][k]))}: {len(snap["bands"][k]["candidates"])}'
                        for k in ordered(snap["bands"]))
    opts = bool((snap.get("options") or {}).get("enabled"))
    o_status = status_block(snap)
    o_link = (' <a href="options.html">Options watchlist</a> ·' if o_status["state"] == "available" else
              f' <a href="options.html">Options watchlist</a> ({E(o_status["label"].lower())}) ·')
    return f"""<h1>{"Growth &amp; Options" if opts else "Growth"} Research Dashboard</h1>
<p class="lede">Week ending {E(snap["as_of"])} · {counts} ·{o_link}
<a href="watchlist.html">Watchlist 2030</a>. {E(spec.DISCLAIMER)}</p>
<div class="overview">
<div class="ov-panels">{panels(snap, tracking, dates, prev_snap)}
<details class="card small"><summary>How to read time horizons</summary><p>{E(TIME_GUIDE)}</p></details></div>
<div class="ov-lists">{watchlist_cards(snap)}
{growth_section(snap)}
{multibagger_section(snap)}
{ai_teaser(snap)}</div>
</div>
<p class="small muted">{len(dates)} weekly snapshot(s) stored. <a href="history.html">History and tracking</a>.</p>"""
