"""Overview page: compact panels, the three growth lists and the speculative multibagger candidates."""
from __future__ import annotations

import html

from . import spec
from .fmt import cap, money, num, pct, sval
from .scenarios import implied_growth_text

E = html.escape
GROWTH_KEYS = ("large", "mid", "small")
ORDER = ("large", "mid", "small", "multibagger")


def ordered(bands: dict) -> list[str]:
    """Display order: the growth lists, the multibagger list, then any retired list from an old snapshot."""
    return [k for k in ORDER if k in bands] + sorted(k for k in bands if k not in ORDER)
TIME_GUIDE = (
    "Four different time frames appear on this site and are never mixed: trailing historical returns (what "
    "already happened), conditional forward scenarios (1-10 years, or to 2030 for the watchlist), option expiry "
    "horizons (3, 6 and 12 months), and tracking periods (1-12 months after each weekly snapshot)."
)


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
<div><h4>Evidence (component scores)</h4>{bars}<p class="small muted">Confidence {E(c.get("confidence_label", "?"))};
missing inputs: {E(", ".join(c.get("missing", [])) or "none")}.</p></div>
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
<div class="small muted">{E(c.get("sector") or "Unknown")}</div></td>
<td class="num hide-sm" data-v="{sval(c.get("market_cap"))}">{cap(c.get("market_cap"))}</td>
<td class="num" data-v="{sval(c.get("price"))}">{money(c.get("price"))}</td>
<td class="num hide-sm" data-v="{sval(m.get("revenue_growth_ttm"))}">{pct(m.get("revenue_growth_ttm"), 0, True)}</td>
<td class="num hide-sm" data-v="{sval(eg)}">{E(eg_txt)}</td>
<td class="num val hide-sm" data-v="{sval(m.get("ev_to_sales"))}">{E(_valuation(m))}</td>
<td class="num" data-v="{sval(c.get("composite"))}"><strong>{num(c.get("composite"), 1)}</strong></td>
<td class="num hide-sm" data-v="{sval(r3)}">{pct(r3, 0, True)}</td>
<td class="num hide-sm" data-v="{sval(r6)}">{pct(r6, 0, True)}</td>
<td class="num" data-v="{sval(r1)}">{pct(r1, 0, True)}</td>
<td class="num hide-sm" data-v="{sval(x1)}">{pct(x1, 0, True)}</td>
<td class="small risk" title="{E(c.get("counterargument", ""))}">{E(short_risk(c.get("counterargument", "")))}</td></tr>
<tr id="{rid}" class="detail" hidden><td colspan="13">{evidence_block(key, c, band)}</td></tr></tbody>""")
    sectors = sorted({c.get("sector") or "Unknown" for c in band["candidates"]})
    opts = "".join(f'<option value="{E(s)}">{E(s)}</option>' for s in sectors)
    head = ('<th class="num" data-sort="num">#</th><th class="tk" data-sort="text">Ticker / company / sector</th>'
            '<th class="num hide-sm" data-sort="num" title="Market cap: as-of close x SEC cover-page shares">Mkt cap</th>'
            '<th class="num" data-sort="num">Price</th><th class="num hide-sm" data-sort="num" title="Revenue growth over the trailing twelve months (TTM)">Rev gr.</th>'
            '<th class="num hide-sm" data-sort="num" title="TTM free-cash-flow growth, else operating income growth">Earn/FCF gr.</th>'
            '<th class="num hide-sm" data-sort="num" title="EV/S = enterprise value / sales; P/E = price / earnings">Valuation</th><th class="num" data-sort="num" title="Research score 0-100 from fixed rules (see Methodology)">Score</th>'
            '<th class="num hide-sm" data-sort="num">3M</th><th class="num hide-sm" data-sort="num">6M</th>'
            '<th class="num" data-sort="num">1Y</th><th class="num hide-sm" data-sort="num" title="1-year return minus the benchmark">vs bench</th>'
            '<th class="risk" title="The weakest scored evidence for this stock">Main risk / weakest evidence</th>')
    return f"""<div class="controls"><input type="search" placeholder="Search ticker, name, risk" data-search="{tid}"
aria-label="Search {E(band_title(key, band))}"><select data-sector="{tid}" aria-label="Filter by sector"><option value="">All sectors</option>{opts}</select>
<span class="small muted" data-count="{tid}" aria-live="polite"></span></div>
<div class="table-wrap"><table id="{tid}" data-table data-grouped><caption class="sr-only">{E(band_title(key, band))}</caption>
<thead><tr>{head}</tr></thead>{''.join(bodies) or '<tbody><tr><td colspan="13" class="muted">No stock met every rule this week.</td></tr></tbody>'}</table></div>
<p class="small muted">Returns are trailing price returns to the as-of close (dividends excluded); "vs bench" is the 1-year
return minus {E(band.get("benchmark", ""))}. Select a ticker to show its evidence.</p>"""


def growth_section(snap: dict) -> str:
    bands = snap["bands"]
    keys = [k for k in ordered(bands) if k != "multibagger"]
    tabs = "".join(f'<button role="tab" data-tab="{k}" aria-selected="false">{E(band_title(k, bands[k]))}</button>'
                   for k in keys)
    panels = []
    for k in keys:
        b = bands[k]
        short = f'<div class="banner info small">{E(b["shortfall_note"])}</div>' if b.get("shortfall_note") else ""
        excl = "".join(f'<tr><td>{E(x["ticker"])}</td><td class="small">{E(x["reason"])}</td></tr>' for x in b["excluded"])
        panels.append(f"""<section data-panel-of="growthtabs" data-panel="{k}" role="tabpanel" hidden>
<h3>{E(b.get("title", k))}</h3><p class="small">{E(definition_line(k, b))} Benchmark: {E(b.get("benchmark_name", b.get("benchmark", "")))}.
Showing {len(b["candidates"])} of up to {b.get("max_results", 10)}; {b.get("ranked", "?")} ranked, {len(b["excluded"])} excluded.</p>
{short}{growth_table(k, b)}
<div class="small"><a href="downloads/{E(snap["as_of"])}_{k}.csv" download>Download CSV</a>
<details><summary>Excluded ({len(b["excluded"])}) with reasons</summary><div class="table-wrap"><table>
<thead><tr><th>Ticker</th><th>Reason</th></tr></thead><tbody>{excl}</tbody></table></div></details></div></section>""")
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
            scen = f'<div class="table-wrap"><table><thead><tr><th>Scenario</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
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
<h4>What must happen for a multibagger outcome</h4><p class="small">{E(multibagger_needs(c))}</p>
<h4>What would invalidate the thesis</h4><ul class="tight small">{inval}</ul></article>""")
    return f"""<h2 id="multibagger">Speculative multibagger research candidates</h2>
<div class="banner warn small"><strong>5-10 year research horizon</strong>These are long-horizon research candidates. Nothing
here implies multibagger returns within 3-12 months. {E(spec.MULTIBAGGER_DEFINITION)} {E(spec.PROBABILITY_STATEMENT)}</div>
<p class="small">{E(definition_line("multibagger", b))} Showing {len(b["candidates"])} of up to {b.get("max_results", 5)}.
<a href="methodology.html#multibagger">Criteria and rationale</a> ·
<a href="downloads/{E(snap["as_of"])}_multibagger.csv" download>CSV</a></p>
{f'<div class="banner info small">{E(b["shortfall_note"])}</div>' if b.get("shortfall_note") else ''}
<div class="mb-list">{''.join(cards) or '<p class="muted">No stock passed every gate this week.</p>'}</div>"""


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


def panels(snap: dict, tracking: dict | None) -> str:
    bands = snap["bands"]
    ev = (snap.get("events") or {})
    items = ev.get("items")
    if items is None:
        earn = '<p class="small muted">Not collected in this snapshot.</p>'
    else:
        earn = "".join(f'<li><strong>{E(i["ticker"])}</strong> {E(i["date"])} <span class="muted">({E(i["list"])})</span></li>'
                       for i in items[:12]) or '<li class="muted">No earnings scheduled in the next 45 days.</li>'
        earn = f'<ul class="tight small">{earn}</ul><p class="small muted">{E(ev.get("note", ""))}</p>'
    new, gone, moves = [], [], []
    for k, b in bands.items():
        for ch in b.get("rank_changes", []):
            if ch["change"] in ("new", "new (first snapshot)"):
                new.append(f'{ch["ticker"]} ({k})')
            elif ch["change"] == "dropped":
                gone.append(f'{ch["ticker"]} ({k})')
            elif isinstance(ch["change"], int) and ch["change"]:
                moves.append((abs(ch["change"]), f'{ch["ticker"]} {ch["change"]:+d} ({k})'))
    first = all(ch["change"] == "new (first snapshot)" for b in bands.values() for ch in b.get("rank_changes", []))
    changes = ('<p class="small muted">First snapshot: no previous week to compare.</p>' if first else
               f'<p class="small"><strong>New:</strong> {E(", ".join(new) or "none")}<br><strong>Departed:</strong> '
               f'{E(", ".join(gone) or "none")}<br><strong>Biggest moves:</strong> '
               f'{E(", ".join(t for _, t in sorted(moves, reverse=True)[:5]) or "none")}</p>')
    conc = [f"{band_title(k, bands[k])}: {w}" for k in ordered(bands) for w in bands[k].get("concentration", [])]
    groups: dict[str, list[str]] = {g: [] for g in RISK_GROUPS}
    for k in ordered(bands):
        for c in bands[k]["candidates"]:
            for g in _risk_flags(c):
                groups[g].append(c["ticker"])
    risk = ("".join(f'<li class="small">{E(w)}</li>' for w in conc) +
            "".join(f'<li class="small"><strong>{E(g)}:</strong> {E(", ".join(dict.fromkeys(ts)))}</li>'
                    for g, ts in groups.items() if ts))
    perf = '<p class="small muted">No tracking data yet.</p>'
    if tracking and tracking.get("summary"):
        rows = "".join(f'<tr><td>{E(k)}</td>' + "".join(
            f'<td class="num">{pct((v.get(h) or {}).get("mean_excess_net"), 1, True)}</td>' for h in spec.TRACK_HORIZONS) + "</tr>"
            for k, v in tracking["summary"].items())
        perf = (f'<div class="table-wrap"><table class="small"><thead><tr><th>List</th>' +
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
           '<p class="small"><a href="audit.html">Sources, timestamps and audit trail →</a></p>')
    return f"""<div class="panels">
<section class="card"><h3>Upcoming earnings (45 days)</h3>{earn}</section>
<section class="card"><h3>This week's changes</h3>{changes}</section>
<section class="card"><h3>Concentration and downside flags</h3><ul class="tight">{risk or '<li class="small muted">None triggered.</li>'}</ul></section>
<section class="card"><h3>Performance vs benchmarks</h3>{perf}</section>
<section class="card"><h3>Data coverage and freshness</h3>{cov}</section></div>"""


def overview(snap: dict, status: dict | None, dates: list[str], tracking: dict | None) -> str:
    counts = " · ".join(f'{E(band_title(k, snap["bands"][k]))}: {len(snap["bands"][k]["candidates"])}'
                        for k in ordered(snap["bands"]))
    return f"""<h1>Growth &amp; Options Research Dashboard</h1>
<p class="lede">Week ending {E(snap["as_of"])} · {counts} · <a href="options.html">Options</a> ·
<a href="watchlist.html">Watchlist 2030</a>. {E(spec.DISCLAIMER)}</p>
{panels(snap, tracking)}
<details class="card small"><summary>How to read time horizons</summary><p>{E(TIME_GUIDE)}</p></details>
{growth_section(snap)}
{multibagger_section(snap)}
<p class="small muted">{len(dates)} weekly snapshot(s) stored. <a href="history.html">History and tracking</a>.</p>"""
