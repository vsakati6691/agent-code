"""Static site for GitHub Pages, built from stored snapshots only (no network access).

The site is rebuilt from the latest snapshot that passed its integrity check.
When the newest run failed, the previous snapshot stays up with a visible
stale-data banner; a client-side check also warns when the data is older than
nine days, in case no new build was deployed at all.
"""
from __future__ import annotations

import csv
import html
import io
import json
import math
import os
import shutil
from datetime import date
from pathlib import Path

from . import spec
from .assets import CSS, JS
from .store import Store, find_private_keys

E = html.escape
NAV = [("index.html", "Overview"), ("options.html", "Options research"), ("history.html", "History & tracking"),
       ("methodology.html", "Methodology"), ("audit.html", "Audit trail")]
COMP_SHORT = {"growth": "Growth", "earnings": "Earn/FCF", "quality": "Quality", "balance": "Balance",
              "valuation": "Value", "momentum": "Mom.", "relative": "Rel."}


# --- formatting -----------------------------------------------------------------------------------

def _ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def pct(v, digits: int = 0, sign: bool = False) -> str:
    if not _ok(v):
        return "n/a"
    return f"{v:{'+' if sign else ''}.{digits}%}"


def num(v, digits: int = 2) -> str:
    return f"{v:,.{digits}f}" if _ok(v) else "n/a"


def money(v, digits: int = 2) -> str:
    return f"${v:,.{digits}f}" if _ok(v) else "n/a"


def cap(v) -> str:
    if not _ok(v):
        return "n/a"
    return f"${v / 1e12:.2f}T" if v >= 1e12 else f"${v / 1e9:.1f}B" if v >= 1e9 else f"${v / 1e6:.0f}M"


def sval(v) -> str:
    """data-v attribute for numeric sorting."""
    return f"{v:.6g}" if _ok(v) else ""


# --- page shell -------------------------------------------------------------------------------------

def page(title: str, body: str, current: str, depth: int = 0, freshness: str = "") -> str:
    up = "../" * depth
    nav = "".join(f'<a href="{up}{href}"{" aria-current=page" if href == current else ""}>{E(label)}</a>'
                  for href, label in NAV)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} · Research Dashboard</title>
<meta name="robots" content="noindex">
<link rel="stylesheet" href="{up}assets/style.css"></head>
<body><header class="site"><div class="inner"><a class="brand" href="{up}index.html">Weekly Research Dashboard</a>
<nav>{nav}</nav></div></header>
<main>{freshness}{body}
<footer>{E(spec.DISCLAIMER)} Methodology version {E(spec.SPEC_VERSION)}. Sources: SEC EDGAR, Nasdaq Trader,
Wikipedia (CC BY-SA 4.0), Cboe delayed quotes, Alpha Vantage. Built from stored weekly snapshots.</footer></main>
<script src="{up}assets/app.js"></script></body></html>"""


def freshness_banner(snap: dict, status: dict | None) -> str:
    as_of = snap["as_of"]
    parts = [f'<div class="banner info" id="freshness" data-asof="{E(as_of)}"><strong>Data as of the {E(as_of)} '
             f'close (<span id="age">{E(as_of)}</span>).</strong>Snapshot built {E(str(snap.get("run_finished", "")).replace("+00:00", ""))} UTC. '
             f'Quotes are end-of-session and delayed, never live. Run status: {E(snap.get("status", "?"))}.</div>']
    if status and status.get("status") == "failed" and str(status.get("at", "")) >= str(snap.get("run_finished", "")):
        parts.append(f'<div class="banner bad"><strong>Stale data: the latest weekly update failed.</strong>'
                     f'{E(status.get("message", ""))} (at {E(str(status.get("at")))} UTC). The research below is the '
                     f'last successful snapshot, from {E(as_of)}.</div>')
    if snap.get("status") == "partial":
        parts.append('<div class="banner warn"><strong>Partial data.</strong>Some items could not be fetched; '
                     'they are listed as excluded with the reason. ' + E("; ".join(snap.get("problems", [])[:3])) +
                     '</div>')
    parts.append('<div class="banner warn" id="stale-client" hidden><strong>This page may be out of date.</strong>'
                 'The data is more than nine days old, so at least one weekly update did not publish.</div>')
    return "".join(parts)


# --- overview ----------------------------------------------------------------------------------------

def band_table(key: str, band: dict) -> str:
    rows = []
    changes = {c["ticker"]: c for c in band.get("rank_changes", [])}
    for c in band["candidates"]:
        comps = "".join(f'<td class="num" data-v="{sval(c["components"].get(k))}">'
                        f'{"n/a" if c["components"].get(k) is None else round(c["components"][k] * 100)}</td>'
                        for k in COMP_SHORT)
        ch = changes.get(c["ticker"], {})
        mv = ch.get("change")
        mv_txt = mv if isinstance(mv, str) else ("=" if mv == 0 else f"{mv:+d}") if mv is not None else ""
        rows.append(
            f'<tr data-sector="{E(c["sector"] or "Unknown")}"><td class="num" data-v="{c["rank"]}">{c["rank"]}</td>'
            f'<td><a href="stock/{key}-{E(c["ticker"])}.html"><strong>{E(c["ticker"])}</strong></a></td>'
            f'<td>{E(c["name"] or "")}<div class="small muted">{E(c["sector"] or "Unknown")}</div></td>'
            f'<td class="num" data-v="{sval(c["composite"])}"><strong>{num(c["composite"], 1)}</strong></td>{comps}'
            f'<td><span class="pill {E(c["confidence_label"])}">{E(c["confidence_label"])}</span></td>'
            f'<td class="num" data-v="{sval(c["price"])}">{money(c["price"])}</td>'
            f'<td class="num" data-v="{sval(c["market_cap"])}">{cap(c["market_cap"])}</td>'
            f'<td class="num" title="{E(ch.get("explanation", ""))}">{E(str(mv_txt))}</td>'
            f'<td class="small">{E(c["counterargument"])}</td></tr>')
    sectors = sorted({c["sector"] or "Unknown" for c in band["candidates"]})
    opts = "".join(f'<option value="{E(s)}">{E(s)}</option>' for s in sectors)
    tid = f"t-{key}"
    head = "".join(f'<th class="num" data-sort="num" title="{E(t.title)}">{COMP_SHORT[t.key]}</th>'
                   for t in spec.COMPONENTS)
    return f"""<div class="controls"><input type="search" placeholder="Search ticker, name, reason" data-search="{tid}"
aria-label="Search candidates"><select data-sector="{tid}" aria-label="Filter by sector"><option value="">All sectors</option>{opts}</select>
<span class="small muted" data-count="{tid}"></span></div>
<div class="table-wrap"><table id="{tid}" data-table><thead><tr><th class="num" data-sort="num">Rank</th><th data-sort="text">Ticker</th>
<th data-sort="text">Company</th><th class="num" data-sort="num">Score</th>{head}<th data-sort="text">Confidence</th>
<th class="num" data-sort="num">Price</th><th class="num" data-sort="num">Mkt cap</th><th class="num">Week</th>
<th>Strongest counterargument</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"""


def overview(snap: dict, status: dict | None, dates: list[str]) -> str:
    bands = snap["bands"]
    u = snap["universe"]
    stats = "".join(
        f'<div class="card stat"><div class="label">{E(b["title"])}</div><div class="value">'
        f'{len(b["candidates"])} of {b["max_results"]}</div><div class="small muted">{b["ranked"]} ranked, '
        f'{len(b["excluded"])} excluded · benchmark {E(b["benchmark"])}</div></div>' for b in bands.values())
    tabs = "".join(f'<button data-tab="{k}" aria-selected="false">{E(b["title"].split(" research")[0])}</button>'
                   for k, b in bands.items())
    panels = []
    for k, b in bands.items():
        warn = "".join(f'<div class="banner warn"><strong>Concentration warning</strong>{E(w)}</div>'
                       for w in b.get("concentration", []))
        short = f'<div class="banner info">{E(b["shortfall_note"])}</div>' if b.get("shortfall_note") else ""
        excl = "".join(f'<tr><td>{E(x["ticker"])}</td><td class="small">{E(x["reason"])}</td></tr>'
                       for x in b["excluded"])
        changes = "".join(
            f'<tr><td>{E(c["ticker"])}</td><td>{E(str(c.get("from") or "-"))} &rarr; {E(str(c.get("to") or "-"))}</td>'
            f'<td class="small">{E(str(c["change"]))}: {E(c.get("explanation", ""))}</td></tr>'
            for c in b.get("rank_changes", []))
        runners = ", ".join(f'{E(r["ticker"])} ({num(r["composite"], 1)})' for r in b.get("runners_up", [])) or "none"
        panels.append(f"""<section data-panel-of="bandtabs" data-panel="{k}" hidden>
<h2>{E(b["title"])}</h2>{short}{warn}{band_table(k, b)}
<p class="small"><a href="downloads/{E(snap["as_of"])}_{k}.csv" download>Download this table (CSV)</a> ·
benchmark: {E(b["benchmark_name"])}</p>
<h3>Weekly rank changes</h3><div class="table-wrap"><table><thead><tr><th>Ticker</th><th>Rank</th><th>Explanation</th></tr></thead>
<tbody>{changes or '<tr><td colspan=3 class="muted">No previous snapshot to compare.</td></tr>'}</tbody></table></div>
<p class="small"><strong>Next ten by score:</strong> {runners}</p>
<details><summary>Excluded or not ranked ({len(b["excluded"])}) with reasons</summary>
<div class="table-wrap"><table><thead><tr><th>Ticker</th><th>Reason</th></tr></thead><tbody>{excl}</tbody></table></div></details>
</section>""")
    counts = "".join(f'<tr><td class="small">{E(k)}</td><td class="num">{v}</td></tr>'
                     for k, v in sorted(u["broad_exclusion_counts"].items(), key=lambda kv: -kv[1]))
    bench = " · ".join(f'{E(k)} {money(v["close"])}' for k, v in snap["benchmarks"].items())
    return f"""<h1>Weekly research overview</h1>
<p class="lede">Week ending {E(snap["as_of"])}. Rule-based research comparisons from public filings and delayed
market data. {E(spec.DISCLAIMER)}</p>
<div class="grid">{stats}</div>
<div class="card small"><strong>Universe.</strong> S&amp;P 500: {u["sp500_count"]} members, {pct(u["sp500_price_coverage"])}
with a valid as-of price. Broad universe: {u["broad_eligible"]} eligible common stocks, {u["broad_prescreen"]} in the
$300M-$10B pre-screen. Benchmarks (as-of close): {bench}.
<details><summary>Why broad-universe stocks were excluded</summary><div class="table-wrap"><table><tbody>{counts}</tbody>
</table></div></details></div>
<div class="banner info"><strong>Probabilities</strong>{E(spec.PROBABILITY_STATEMENT)}</div>
<div class="tabs" data-tabs id="bandtabs" role="tablist">{tabs}</div>{''.join(panels)}
<p class="small muted">{len(dates)} weekly snapshot(s) stored. <a href="history.html">History and tracking</a>.</p>"""


# --- detail page ----------------------------------------------------------------------------------------

def line_chart(chart: dict, ticker: str, bench: str) -> str:
    if not chart or not chart.get("stock"):
        return '<p class="muted">Price history unavailable.</p>'
    W, H, L, R, T, B = 720, 260, 48, 660, 14, 230
    vals = chart["stock"] + (chart.get("benchmark") or [])
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.06 or 1
    lo, hi = lo - pad, hi + pad
    n = len(chart["stock"])

    def xy(i, v):
        return L + (R - L) * i / max(1, n - 1), B - (B - T) * (v - lo) / (hi - lo)

    def path(series):
        return " ".join(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}' for i, (x, y) in
                        enumerate(xy(i, v) for i, v in enumerate(series)))
    ticks = []
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        _, y = xy(0, v)
        ticks.append(f'<line x1="{L}" x2="{R}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--border)" stroke-width="1"/>'
                     f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="var(--text-muted)">{v:.0f}</text>')
    xt = []
    for i in (0, n // 2, n - 1):
        x, _ = xy(i, lo)
        xt.append(f'<text x="{x:.1f}" y="{B + 18}" text-anchor="middle" font-size="11" fill="var(--text-muted)">'
                  f'{E(chart["dates"][i][:7])}</text>')
    bpath = f'<path d="{path(chart["benchmark"])}" fill="none" stroke="var(--reference)" stroke-width="2" stroke-dasharray="5 4"/>' \
        if chart.get("benchmark") else ""
    ex, ey = xy(n - 1, chart["stock"][-1])
    end = f'<text x="{ex + 6:.1f}" y="{ey + 4:.1f}" font-size="12" fill="var(--text-primary)">{E(ticker)} {chart["stock"][-1]:.0f}</text>'
    if chart.get("benchmark"):
        bx, by = xy(n - 1, chart["benchmark"][-1])
        if abs(by - ey) < 12:
            by += 12 if by >= ey else -12
        end += f'<text x="{bx + 6:.1f}" y="{by + 4:.1f}" font-size="12" fill="var(--text-secondary)">{E(bench)} {chart["benchmark"][-1]:.0f}</text>'
    data = json.dumps({**chart, "label": ticker, "benchLabel": bench})
    return f"""<div class="legend"><span><i></i>{E(ticker)}</span>{f'<span><i class="ref"></i>{E(bench)}</span>' if chart.get("benchmark") else ''}
<span class="muted">rebased to 100, price return, weekly points</span></div>
<div class="chart" data-series='{E(data)}' data-left="{L}" data-right="{R}"><svg viewBox="0 0 {W} {H}" role="img"
aria-label="{E(ticker)} price versus {E(bench)}, rebased to 100">{''.join(ticks)}{''.join(xt)}{bpath}
<path d="{path(chart["stock"])}" fill="none" stroke="var(--series-1)" stroke-width="2"/>{end}
<line class="hair" x1="0" x2="0" y1="{T}" y2="{B}" stroke="var(--text-muted)" stroke-width="1" style="display:none"/></svg>
<div class="tip"></div></div>"""


def detail(c: dict, snap: dict) -> str:
    m = c["metrics"]
    h = c["history"]
    rets = "".join(
        f'<tr><td>{k}</td><td class="num">{pct(v["stock"], 1)}</td><td class="num">{pct(v["benchmark"], 1)}</td>'
        f'<td class="num">{pct(v["excess"], 1, True)}</td></tr>' if v else
        f'<tr><td>{k}</td><td class="num muted" colspan=3>not enough history</td></tr>'
        for k, v in ((k, h["returns"].get(k)) for k in ("1m", "3m", "6m", "1y", "3y", "5y")))
    dd = h["drawdowns"]
    comp_rows = "".join(
        f'<tr><td>{E(cp.title)}{" (critical)" if cp.critical else ""}</td><td class="num">{cp.weight:.0%}</td>'
        f'<td class="num">{"missing" if c["components"].get(cp.key) is None else round(c["components"][cp.key] * 100)}</td>'
        f'<td><div class="bar"><span style="width:{(c["components"].get(cp.key) or 0) * 100:.0f}%"></span></div></td>'
        f'<td class="small">' + "; ".join(
            f'{E(mk)} = {E(_metric(m.get(mk)))}{" (missing, scored 0)" if mk in c["missing"] else ""}'
            for mk in cp.metrics) + "</td></tr>" for cp in spec.COMPONENTS)
    fund = c["fundamentals"]
    frow = lambda label, key: f'<tr><td>{label}</td>' + "".join(  # noqa: E731
        f'<td class="num">{num((v or 0) / 1e6, 0) if v is not None else "n/a"}</td>' for v in fund[key]) + "</tr>"
    fhead = "".join(f'<th class="num">{E(q)}{"*" if d else ""}</th>' for q, d in zip(fund["quarters"], fund["derived_revenue"]))
    scen_html = f'<p class="muted">{E(c.get("scenario_note") or "")}</p>'
    if c.get("scenarios"):
        sc = c["scenarios"]
        rows = ""
        for key in ("bear", "base", "bull"):
            s = sc[key]
            a = s["assumptions"]
            cells = "".join(f'<td class="num">{money(s["years"][str(y)]["value_per_share"])}<div class="small muted">'
                            f'{num(s["years"][str(y)]["multiple_of_price"], 2)}x · {pct(s["years"][str(y)]["annualized"], 0, True)}/yr</div></td>'
                            for y in spec.SCENARIO_YEARS)
            rows += (f'<tr><td><strong>{key}</strong></td>{cells}<td class="small">start growth {pct(a["starting_revenue_growth"])}'
                     f', fading to {pct(spec.SCENARIO_TERMINAL_GROWTH)}; exit EV/Sales {num(a["exit_ev_to_sales"], 1)}x; '
                     f'dilution {pct(a["annual_dilution"], 1)}/yr; FCF margin {pct(a["fcf_margin_start"])} &rarr; '
                     f'{pct(a["fcf_margin_year5"])}; net cash held {cap(a["net_cash_held"]) if (a["net_cash_held"] or 0) >= 0 else "-" + cap(-a["net_cash_held"])}</td></tr>')
        fl = sc["flags"]
        scen_html = f"""<div class="table-wrap"><table><thead><tr><th>Scenario</th><th class="num">1 year</th><th class="num">3 years</th>
<th class="num">5 years</th><th>Assumptions</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="small">Bull case reaches 2x in five years: <strong>{"yes" if fl["bull_doubles_in_5y"] else "no"}</strong> ·
5x ('multibagger' definition): <strong>{"yes" if fl["bull_multibagger_5y"] else "no"}</strong>. {E(spec.MULTIBAGGER_DEFINITION)}</p>
<p class="small muted">{E(spec.SCENARIO_METHOD)}</p>"""
    earn = c.get("next_earnings")
    flags = "".join(f'<span class="pill">{E(f)}</span>' for f in c["flags"]) or '<span class="muted">none</span>'
    ns = "".join(f'<li><strong>{E(k.replace("_", " "))}:</strong> {E(v)}</li>' for k, v in c["not_scored"].items())
    return f"""<p class="small"><a href="../index.html#{E(c["band"])}">&larr; back to the list</a></p>
<h1>{E(c["ticker"])} · {E(c["name"] or "")}</h1>
<p class="lede">{E(c["sector"] or "Unknown")} · rank {c["rank"]} in {E(snap["bands"][c["band"]]["title"].lower())} ·
score {num(c["composite"], 1)} / 100 · confidence <span class="pill {E(c["confidence_label"])}">{E(c["confidence_label"])}</span></p>
<div class="grid"><div class="card stat"><div class="label">Price ({E(c["price_date"])} close)</div><div class="value">{money(c["price"])}</div>
<div class="small muted">{E(c["sources"]["price"])}</div></div>
<div class="card stat"><div class="label">Market cap</div><div class="value">{cap(c["market_cap"])}</div>
<div class="small muted">{E(spec.MARKET_CAP_DEFINITION[:90])}…</div></div>
<div class="card stat"><div class="label">Next earnings (unverified)</div><div class="value">{E(earn or "unknown")}</div>
<div class="small muted">Alpha Vantage calendar</div></div>
<div class="card stat"><div class="label">Data timestamp</div><div class="value small">{E(str(c["data_timestamp"]).replace("+00:00", ""))} UTC</div>
<div class="small muted">fundamentals: {E(fund.get("last_form") or "?")} filed {E(fund.get("last_filed") or "?")}</div></div></div>
<p class="small">Flags: {flags}</p>
<h2>Research thesis</h2><p>{E(c["thesis"])}</p><p class="small muted">Generated by fixed rules from reported data. It is a
summary of evidence, not a recommendation.</p>
<h2>Strongest bear case</h2><p>{E(c["bear_case"])}</p>
<h2>Component scores</h2><div class="table-wrap"><table><thead><tr><th>Component</th><th class="num">Weight</th>
<th class="num">Score</th><th></th><th>Inputs</th></tr></thead><tbody>{comp_rows}</tbody></table></div>
<p class="small muted">Missing inputs score 0; weights are never redistributed.</p>
<h3>Not scored</h3><ul class="tight small">{ns}</ul>
<h2>Price vs benchmark</h2>{line_chart(c["chart"], c["ticker"], c["benchmark"])}
<div class="table-wrap"><table><thead><tr><th>Period</th><th class="num">{E(c["ticker"])}</th><th class="num">{E(c["benchmark"])}</th>
<th class="num">Difference</th></tr></thead><tbody>{rets}</tbody></table></div>
<p class="small">Max drawdown (5 years): <strong>{pct(dd["max_5y"]["value"])}</strong> ({E(str(dd["max_5y"]["peak"]))} to
{E(str(dd["max_5y"]["trough"]))}) · from 52-week high: {pct(dd["from_52w_high"])} · worst 12-month return since
{E(h["first_date"])}: {pct(dd.get("worst_1y_return"))}. Price returns exclude dividends. History starts {E(h["first_date"])}.</p>
<h2>Fundamentals and valuation</h2>
<div class="grid small">
<div class="card">Revenue TTM {cap(m.get("revenue_ttm"))} · growth {pct(m.get("revenue_growth_ttm"))} · 3-yr CAGR {pct(m.get("revenue_cagr_3y"))}</div>
<div class="card">Gross margin {pct(m.get("gross_margin"))} · operating margin {pct(m.get("operating_margin"))} · FCF margin {pct(m.get("fcf_margin"))}</div>
<div class="card">EV/Sales {num(m.get("ev_to_sales"), 1)}x · P/E {num(m.get("pe"), 1)} · FCF yield {pct(m.get("fcf_yield"), 1)} · implied revenue growth {pct(m.get("implied_revenue_cagr"))}</div>
<div class="card">Net debt {cap(m.get("net_debt")) if (m.get("net_debt") or 0) >= 0 else "net cash " + cap(-m["net_debt"])} · current ratio {num(m.get("current_ratio"))} · dilution {pct(m.get("dilution"), 1)} · SBC/revenue {pct(m.get("sbc_to_revenue"))}</div>
</div>
<div class="table-wrap"><table><thead><tr><th>USD millions</th>{fhead}</tr></thead><tbody>
{frow("Revenue", "revenue")}{frow("Gross profit", "gross_profit")}{frow("Operating income", "operating_income")}
{frow("Net income", "net_income")}{frow("Operating cash flow", "ocf")}{frow("Capital expenditure", "capex")}{frow("Stock-based comp.", "sbc")}
</tbody></table></div><p class="small muted">* quarter derived from cumulative or annual filings. Source: {E(c["sources"]["fundamentals"])},
facts filed on or before {E(snap["as_of"])} only.</p>
<h2>Bear / base / bull valuation ranges</h2>{scen_html}
<div class="banner info"><strong>Probability</strong>{E(c["probability"])}</div>
<h2>Key business risks</h2><ul class="tight">{''.join(f'<li>{E(r)}</li>' for r in c["risks"])}</ul>
<h2>What would invalidate the thesis</h2><ul class="tight">{''.join(f'<li>{E(r)}</li>' for r in c["invalidation"])}</ul>"""


def _metric(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, (int, float)):
        if not math.isfinite(v):
            return "not meaningful"
        return f"{v:.3g}"
    return str(v)


# --- options ---------------------------------------------------------------------------------------------

def options_page(snap: dict) -> str:
    o = snap.get("options") or {}
    head = f"""<h1>Options research comparisons</h1>
<p class="lede">Educational comparisons of liquid call contracts on this week's large-cap research candidates. These are
not "best calls to buy". Buying a call can lose the entire premium.</p>
<div class="banner warn"><strong>Delta is not a probability of profit</strong>{E(spec.DELTA_STATEMENT)}</div>
<div class="banner info"><strong>Data</strong>Cboe delayed quotes, end-of-session snapshot for {E(snap["as_of"])}.
Quotes are delayed and can be stale; every contract carries its flags. Black-Scholes values are model estimates.</div>"""
    if not o.get("enabled") or o.get("status") != "ok":
        return head + f'<div class="banner bad"><strong>Options data unavailable</strong>{E(o.get("status", "not collected"))}. ' \
                      'No contracts, prices or Greeks are shown rather than inventing them.</div>'
    tabs = "".join(f'<button data-tab="{h.key}" aria-selected="false">{E(h.title)}</button>' for h in spec.HORIZONS)
    panels = []
    r = spec.OPTION_RULES
    for h in spec.HORIZONS:
        hz = o.get(h.key) or {}
        rows_html = []
        for x in hz.get("rows", []):
            pay = "".join(f'<tr><td class="num">{pct(p["move"], 0, True)}</td><td class="num">{money(p["underlying"])}</td>'
                          f'<td class="num">{money(p["pl_per_contract"], 0)}</td><td class="num">{pct(p["return_on_premium"], 0, True)}</td></tr>'
                          for p in x["payoffs"])
            sens = x["sensitivity"]
            sgrid = "".join("<tr><td class='num'>" + pct(row[0]["price_move"], 0, True) + "</td>" + "".join(
                f'<td class="num">{money(cl["model_value"])} ({pct(cl["change_vs_mid"], 0, True)})</td>' for cl in row) + "</tr>"
                for row in sens["grid"])
            ivh = "".join(f'<th class="num">IV {pct(s, 0, True).replace("%", " pts")}</th>' for s in spec.SENSITIVITY["iv_shifts"])
            ev = ", ".join(f'{e["date"]} {e["event"]}' for e in x["events_before_expiry"]) or "none known"
            flags = "".join(f'<span class="pill">{E(f)}</span>' for f in x["flags"])
            rc = x["rank_components"]
            rows_html.append(f"""<tr><td class="num">{x["rank"]}</td><td><strong>{E(x["underlying"])}</strong><div class="small muted">{E(x["option"])}</div></td>
<td class="num">{money(x["strike"])}</td><td class="num">{E(x["expiration"])}<div class="small muted">{x["dte"]} days</div></td>
<td class="num">{money(x["bid"])} / {money(x["ask"])}<div class="small muted">spread {pct(x["spread_pct"], 1)}</div></td>
<td class="num">{num(x["volume"], 0)} / {num(x["open_interest"], 0)}</td><td class="num">{pct(x["iv"], 1)}</td>
<td class="num">Δ {num(x["delta"])} Γ {num(x["gamma"], 4)}<br>Θ {num(x["theta"], 3)} V {num(x["vega"], 3)}</td>
<td class="num">{money(x["premium_per_contract_ask"], 0)}<div class="small muted">x{x["multiplier"]}{" adjusted!" if x["adjusted"] else ""}</div></td>
<td class="num">{money(x["breakeven"])}<div class="small muted">{pct(x["breakeven_move"], 1, True)}</div></td>
<td class="num">{money(x["max_loss_per_contract"], 0)}</td><td class="num" data-v="{rc["total"]}">{num(rc["total"], 1)}</td></tr>
<tr><td></td><td colspan="11"><details><summary>Payoffs, sensitivity, events and flags</summary>
<p class="small">Spot {money(x["spot"])} · one-standard-deviation implied move to expiry {pct(x["implied_move_1sd"], 1)} ·
time decay {pct(x["theta_share_per_day"], 2)} of the premium per day · events before expiry: {E(ev)}. Ranking parts: liquidity
{num(rc["liquidity"])}, breakeven {num(rc["breakeven"])}, time decay {num(rc["time_decay"])}.</p><p>{flags}</p>
<div class="grid"><div><h3>At expiration (bought at the ask)</h3><div class="table-wrap"><table><thead><tr><th class="num">Stock move</th>
<th class="num">Stock price</th><th class="num">P/L per contract</th><th class="num">On premium</th></tr></thead><tbody>{pay}</tbody></table></div></div>
<div><h3>In {sens["days_forward"]} days (model estimate)</h3><div class="table-wrap"><table><thead><tr><th class="num">Stock move</th>{ivh}</tr></thead>
<tbody>{sgrid}</tbody></table></div><p class="small muted">Value per share vs today's mid. {E(sens["note"])}</p></div></div>
</details></td></tr>""")
        rej = ", ".join(f"{E(k)} ({v})" for k, v in sorted(hz.get("rejections", {}).items(), key=lambda kv: -kv[1]))
        table = (f"""<div class="table-wrap"><table><thead><tr><th class="num">#</th><th>Contract</th><th class="num">Strike</th>
<th class="num">Expiration</th><th class="num">Bid / ask</th><th class="num">Vol / OI</th><th class="num">IV</th><th class="num">Greeks</th>
<th class="num">Premium</th><th class="num">Breakeven</th><th class="num">Max loss</th><th class="num">Rank score</th></tr></thead>
<tbody>{''.join(rows_html)}</tbody></table></div>""" if rows_html else
                 f'<div class="banner warn"><strong>No comparison available</strong>{E(hz.get("status", "unavailable"))}.</div>')
        panels.append(f"""<section data-panel-of="hztabs" data-panel="{h.key}" hidden><h2>{E(h.title)}: {h.min_dte}-{h.max_dte} days to expiration</h2>
<p class="small">{hz.get("considered", 0)} calls in the window were checked. Rules: open interest ≥ {r["min_open_interest"]},
volume ≥ {r["min_volume"]}, spread ≤ {r["max_spread_pct"]:.0%} of mid, delta {r["min_delta"]}-{r["max_delta"]}, standard 100-share contracts,
at most {r["max_per_underlying_per_horizon"]} per underlying. Not eligible: {rej or "none"}.</p>{table}
<p class="small"><a href="downloads/{E(snap["as_of"])}_options_{h.key}.csv" download>Download (CSV)</a></p></section>""")
    probs = "".join(f'<li>{E(k)}: {E(v)}</li>' for k, v in (o.get("chain_problems") or {}).items())
    rank_text = "; ".join(f"{k} {w:.0%}: {E(t)}" for k, (w, t) in spec.OPTION_RANKING.items())
    return head + f"""<p class="small"><strong>Underlyings:</strong> {E(o.get("underlying_rule", ""))} Valid chains:
{E(", ".join(o.get("underlyings", [])) or "none")}. <strong>Ranking (fixed in advance):</strong> {rank_text}.</p>
{f'<div class="banner warn"><strong>Earnings dates</strong>{E(o["earnings_note"])}. Check event dates yourself.</div>' if o.get("earnings_note") else ''}
<div class="tabs" data-tabs id="hztabs">{tabs}</div>{''.join(panels)}
{f'<details><summary>Chains not used ({len(o.get("chain_problems") or {})})</summary><ul class="small">{probs}</ul></details>' if probs else ''}"""


# --- history, methodology, audit ------------------------------------------------------------------------

def history_page(dates: list[str], tracking: dict | None) -> str:
    items = "".join(f'<li><a href="reports/{d}.html">Week ending {d}</a></li>' for d in reversed(dates))
    if not tracking:
        trk = '<p class="muted">No tracking yet.</p>'
    else:
        rows = []
        for r in reversed(tracking["by_snapshot"]):
            cells = []
            for h in spec.TRACK_HORIZONS:
                x = r["horizons"].get(h, {})
                if x.get("status") == "ok":
                    cells.append(f'<td class="num">{pct(x["net"], 1, True)}<div class="small muted">vs {pct(x["benchmark"], 1, True)}'
                                 f'{f" · {len(x["unavailable"])} n/a" if x["unavailable"] else ""}</div></td>')
                else:
                    cells.append(f'<td class="num muted">{E(x.get("status", "pending"))}</td>')
            rows.append(f'<tr><td>{E(r["as_of"])}</td><td>{E(r["band"])}</td><td class="small">{E(r["spec_version"])}</td>{"".join(cells)}</tr>')
        summ = "".join(f'<tr><td>{E(k)}</td>' + "".join(
            f'<td class="num">{pct(v[h]["mean_excess_net"], 1, True)}<div class="small muted">{v[h]["snapshots_measured"]} measured</div></td>'
            for h in spec.TRACK_HORIZONS) + f'<td class="num">{pct(v.get("mean_weekly_turnover"))}</td></tr>'
            for k, v in tracking["summary"].items())
        chain = "".join(f'<li>{E(k)}: {v["weeks"]} weeks, cumulative {pct(v["cumulative_net"], 1, True)}, max drawdown '
                        f'{pct(v["max_drawdown"], 1)}</li>' for k, v in tracking.get("weekly_chain", {}).items())
        hh = "".join(f'<th class="num">{h}</th>' for h in spec.TRACK_HORIZONS)
        trk = f"""<div class="banner warn"><strong>Evidence status</strong>{E(tracking["evidence_note"])}</div>
<h3>Average excess return net of friction, by category</h3><div class="table-wrap"><table><thead><tr><th>Category</th>{hh}
<th class="num">Weekly turnover</th></tr></thead><tbody>{summ}</tbody></table></div>
<h3>Weekly one-week chain</h3><ul class="small">{chain or '<li class="muted">not enough weeks</li>'}</ul>
<h3>Each snapshot</h3><div class="table-wrap"><table><thead><tr><th>As of</th><th>Category</th><th>Spec</th>{hh}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="small">{E(tracking["method"])}</p><ul class="small">{''.join(f'<li>{E(x)}</li>' for x in tracking["limitations"])}</ul>
<p class="small">Assumed friction per side (bps): {E(json.dumps(tracking["friction"]))}.</p>"""
    return f"""<h1>History and performance tracking</h1><p class="lede">Every weekly snapshot is stored unchanged. Later prices
measure each list as it was published.</p><h2>Weekly reports</h2><ul>{items}</ul><h2>Tracking</h2>{trk}"""


def methodology_page() -> str:
    comps = "".join(
        f'<tr><td>{E(c.title)}</td><td class="num">{c.weight:.0%}</td><td>{"yes" if c.critical else "no"}</td><td class="small">' +
        "<br>".join(f'<strong>{E(k)}</strong> ({"lower is better, " if s.reverse else ""}0 at {s.lo:g}, 1 at {s.hi:g}{" reversed" if s.reverse else ""}): '
                    f'{E(spec.METRIC_NOTES[k])}' for k, s in c.metrics.items()) + "</td></tr>" for c in spec.COMPONENTS)
    bands = "".join(f'<tr><td>{E(b.title)}</td><td>{E(b.universe)}</td><td>{cap(b.min_cap) if b.min_cap else "-"} to '
                    f'{cap(b.max_cap) if b.max_cap else "-"}</td><td>${b.min_price:g}</td><td>{cap(b.min_dollar_volume)}</td>'
                    f'<td>{"revenue growth ≥ " + pct(b.min_revenue_growth) if b.min_revenue_growth else "-"}</td><td>{E(b.benchmark)}</td>'
                    f'<td>{b.max_results}</td></tr>' for b in spec.BANDS)
    hz = "".join(f'<li>{E(h.title)}: {h.min_dte}-{h.max_dte} days to expiration</li>' for h in spec.HORIZONS)
    rk = "".join(f'<li><strong>{E(k)} ({w:.0%})</strong>: {E(t)}</li>' for k, (w, t) in spec.OPTION_RANKING.items())
    log = "".join(f'<li>{E(v)}: {E(t)}</li>' for v, t in spec.SPEC_CHANGELOG)
    return f"""<h1>Methodology</h1><p class="lede">Version {E(spec.SPEC_VERSION)} (hash {E(spec.spec_hash())}). All rules were fixed
before any results were computed; a change creates a new version and results are tracked separately per version.</p>
<h2>Universes</h2><p>{E(spec.UNIVERSE_DEFINITION)}</p><p>{E(spec.MARKET_CAP_DEFINITION)}</p>
<div class="table-wrap"><table><thead><tr><th>Category</th><th>Universe</th><th>Market cap</th><th>Min price</th>
<th>Min 20-day median $ volume</th><th>Gate</th><th>Benchmark</th><th>Max shown</th></tr></thead><tbody>{bands}</tbody></table></div>
<p>Limited operating history: fewer than {spec.LIMITED_HISTORY_QUARTERS} reported quarters. Limited trading history: fewer than
{spec.LIMITED_HISTORY_DAYS} daily bars. Fundamentals older than {spec.MAX_FILING_AGE_DAYS} days exclude a stock. The as-of close
must be present. Lists are never padded: fewer than ten qualifying stocks means fewer than ten shown.</p>
<h2>Scoring</h2><p>Each input maps to 0-1 on a fixed linear scale (absolute thresholds, not ranks). A component is the average of
its inputs. A missing input scores 0 and is shown; weights are never redistributed. A stock with a critical component entirely
missing, or more than {spec.MAX_MISSING_METRICS} missing inputs, is not ranked. Ties: {E(spec.TIE_BREAK)}.</p>
<div class="table-wrap"><table><thead><tr><th>Component</th><th class="num">Weight</th><th>Critical</th><th>Inputs and scales</th></tr></thead>
<tbody>{comps}</tbody></table></div>
<p>Momentum and benchmark-relative performance are separate components. {E(spec.CONFIDENCE_RULES)}</p>
<h3>Not scored</h3><ul>{''.join(f'<li>{E(k.replace("_", " "))}: {E(v)}</li>' for k, v in spec.NOT_SCORED_FACTORS.items())}</ul>
<p>The strongest counterargument is the input with the largest weighted shortfall (missing critical data first).</p>
<h2>Scenarios</h2><p>{E(spec.SCENARIO_METHOD)}</p><p>{E(spec.MULTIBAGGER_DEFINITION)}</p><p>{E(spec.PROBABILITY_STATEMENT)}</p>
<h2>Options</h2><p>{E(spec.OPTION_UNDERLYINGS)}</p><ul>{hz}</ul><p>Eligibility: {E(json.dumps(spec.OPTION_RULES))}.</p>
<p>Ranking (higher is better; maximum upside is not an input):</p><ul>{rk}</ul><p>{E(spec.DELTA_STATEMENT)}</p>
<p>Payoffs at expiration assume the contract is bought at the ask. {E(spec.RISK_FREE_RATE_NOTE)}</p>
<h2>Performance tracking</h2><p>{E(spec.TRACKING_METHOD)}</p>
<h2>Version history</h2><ul>{log}</ul>"""


def audit_page(store: Store, snap: dict, integrity: list[str]) -> str:
    rows = "".join(f'<tr><td class="small">{E(str(e.get("at")))}</td><td>{E(str(e.get("event")))}</td><td class="small">'
                   f'{E(json.dumps({k: v for k, v in e.items() if k not in ("at", "event")}, default=str)[:400])}</td></tr>'
                   for e in reversed(store.audit_log()[-300:]))
    man = []
    for d in reversed(store.dates()):
        m = json.loads((store.root / "snapshots" / d / "manifest.json").read_text(encoding="utf-8"))
        man.append(f'<tr><td>{E(d)}</td><td class="small"><code>{E(m["sha256"][:16])}…</code></td><td>{E(str(m.get("spec_version")))}</td>'
                   f'<td class="small">{E(str(m.get("code_commit", ""))[:10])}</td><td>{E(str(m.get("status")))}</td></tr>')
    ok = '<div class="banner info"><strong>Integrity</strong>Every stored snapshot matches its manifest hash.</div>' if not integrity else \
        '<div class="banner bad"><strong>Integrity problems</strong>' + E("; ".join(integrity)) + "</div>"
    usage = snap.get("usage", {})
    return f"""<h1>Audit trail</h1>{ok}<h2>Snapshots</h2><div class="table-wrap"><table><thead><tr><th>As of</th><th>SHA-256</th>
<th>Spec</th><th>Code</th><th>Status</th></tr></thead><tbody>{''.join(man)}</tbody></table></div>
<h2>Latest run</h2><p class="small">Started {E(snap.get("run_started", ""))}, finished {E(snap.get("run_finished", ""))} UTC.
Requests by provider: {E(json.dumps(usage.get("requests", {})))}; cache hits {E(str(usage.get("cache_hits", 0)))}.
Problems: {E("; ".join(snap.get("problems", [])) or "none")}.</p>
<h2>Data sources and terms</h2><ul class="small">{''.join(f'<li><strong>{E(k)}</strong>: {E(v)}</li>' for k, v in snap.get("sources", {}).items())}</ul>
<h2>Events</h2><div class="table-wrap"><table><thead><tr><th>At (UTC)</th><th>Event</th><th>Details</th></tr></thead><tbody>{rows}</tbody></table></div>"""


def weekly_report(snap: dict) -> str:
    parts = [f'<p class="small"><a href="../history.html">&larr; all weeks</a></p><h1>Week ending {E(snap["as_of"])}</h1>'
             f'<p class="lede">Status {E(snap.get("status", "?"))} · methodology {E(snap.get("spec_version", "?"))}.</p>']
    for k, b in snap["bands"].items():
        rows = "".join(f'<tr><td class="num">{c["rank"]}</td><td>{E(c["ticker"])}</td><td>{E(c["name"] or "")}</td>'
                       f'<td class="num">{num(c["composite"], 1)}</td><td>{E(c["confidence_label"])}</td>'
                       f'<td class="num">{money(c["price"])}</td><td class="small">{E(c["counterargument"])}</td></tr>'
                       for c in b["candidates"])
        parts.append(f'<h2>{E(b["title"])}</h2><div class="table-wrap"><table><thead><tr><th class="num">#</th><th>Ticker</th><th>Company</th>'
                     f'<th class="num">Score</th><th>Confidence</th><th class="num">Price</th><th>Counterargument</th></tr></thead>'
                     f'<tbody>{rows or "<tr><td colspan=7>none qualified</td></tr>"}</tbody></table></div>'
                     f'<p class="small"><a href="../downloads/{E(snap["as_of"])}_{k}.csv" download>CSV</a></p>')
    o = snap.get("options") or {}
    for h in spec.HORIZONS:
        rows = "".join(f'<li>{E(x["option"])}: ask {money(x["ask"])}, breakeven {money(x["breakeven"])}, score {num(x["rank_components"]["total"], 1)}</li>'
                       for x in (o.get(h.key) or {}).get("rows", []))
        parts.append(f'<h3>Options, {E(h.title.lower())}</h3><ul class="small">{rows or "<li>none / unavailable</li>"}</ul>')
    return "".join(parts)


# --- CSV ----------------------------------------------------------------------------------------------------

def band_csv(band: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    keys = [m for c in spec.COMPONENTS for m in c.metrics]
    w.writerow(["rank", "ticker", "name", "sector", "composite", *[f"component_{c.key}" for c in spec.COMPONENTS],
                "confidence", "price", "market_cap", *keys, "missing", "flags", "counterargument"])
    for c in band["candidates"]:
        w.writerow([c["rank"], c["ticker"], c["name"], c["sector"], c["composite"],
                    *[c["components"].get(k.key) for k in spec.COMPONENTS], c["confidence"], c["price"], c["market_cap"],
                    *[c["metrics"].get(k) for k in keys], ";".join(c["missing"]), ";".join(c["flags"]), c["counterargument"]])
    return buf.getvalue()


def options_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["rank", "underlying", "option", "strike", "expiration", "dte", "bid", "ask", "spread_pct", "volume",
            "open_interest", "iv", "delta", "gamma", "theta", "vega", "rho", "multiplier", "adjusted",
            "premium_per_contract_ask", "breakeven", "breakeven_move", "max_loss_per_contract"]
    w.writerow(cols + ["rank_score", "flags"])
    for x in rows:
        w.writerow([x.get(c) for c in cols] + [x["rank_components"]["total"], ";".join(x["flags"])])
    return buf.getvalue()


# --- build -------------------------------------------------------------------------------------------------

def scan_for_secrets(out: Path, env_names: tuple[str, ...]) -> list[str]:
    """Files containing the value of any named environment variable (values are never printed)."""
    values = [os.environ[n] for n in env_names if len(os.environ.get(n, "")) >= 8]
    hits = []
    for p in out.rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="ignore")
            if any(v in text for v in values):
                hits.append(str(p.relative_to(out)))
    return hits


def build_site(data_dir: Path, out: Path, secret_env: tuple[str, ...] = ()) -> dict:
    store = Store(data_dir)
    integrity = store.verify_all()
    bad = {p.split()[1] for p in integrity if p.startswith("snapshot ")}
    dates = [d for d in store.dates() if d not in bad]
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    (out / "assets" / "app.js").write_text(JS, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    status = store.status()
    if not dates:
        msg = (status or {}).get("message", "no weekly snapshot has been produced yet")
        body = f'<h1>Weekly research overview</h1><div class="banner bad"><strong>No research data available</strong>{E(msg)}</div>'
        (out / "index.html").write_text(page("Overview", body, "index.html"), encoding="utf-8")
        (out / "methodology.html").write_text(page("Methodology", methodology_page(), "methodology.html"), encoding="utf-8")
        return {"pages": 2, "snapshot": None}
    snap = store.load(dates[-1])
    hits = find_private_keys(snap)
    if hits:
        raise RuntimeError(f"refusing to publish: private-looking fields {hits[:5]}")
    fresh = freshness_banner(snap, status)
    write = lambda rel, title, body, cur, depth=0, fr=fresh: (out / rel).write_text(  # noqa: E731
        page(title, body, cur, depth, fr), encoding="utf-8")
    write("index.html", "Overview", overview(snap, status, dates), "index.html")
    write("options.html", "Options research", options_page(snap), "options.html")
    write("history.html", "History", history_page(dates, store.read_json("tracking.json")), "history.html")
    write("methodology.html", "Methodology", methodology_page(), "methodology.html", fr="")
    write("audit.html", "Audit trail", audit_page(store, snap, integrity), "audit.html")
    (out / "stock").mkdir()
    (out / "reports").mkdir()
    (out / "downloads").mkdir()
    (out / "data").mkdir()
    n = 0
    for key, band in snap["bands"].items():
        for c in band["candidates"]:
            write(f"stock/{key}-{c['ticker']}.html", f"{c['ticker']} research", detail(c, snap), "", 1)
            n += 1
    for d in dates:
        s = snap if d == dates[-1] else store.load(d)
        (out / "reports" / f"{d}.html").write_text(page(f"Week ending {d}", weekly_report(s), "history.html", 1, ""),
                                                   encoding="utf-8")
        for key, band in s["bands"].items():
            (out / "downloads" / f"{d}_{key}.csv").write_text(band_csv(band), encoding="utf-8")
        for h in spec.HORIZONS:
            rows = ((s.get("options") or {}).get(h.key) or {}).get("rows", [])
            (out / "downloads" / f"{d}_options_{h.key}.csv").write_text(options_csv(rows), encoding="utf-8")
    (out / "data" / "latest.json").write_text(json.dumps(snap, default=str), encoding="utf-8")
    leaks = scan_for_secrets(out, secret_env)
    if leaks:
        shutil.rmtree(out)
        raise RuntimeError(f"refusing to publish: secret values found in {len(leaks)} file(s)")
    return {"pages": 5 + n + len(dates), "snapshot": dates[-1], "integrity_problems": integrity}
