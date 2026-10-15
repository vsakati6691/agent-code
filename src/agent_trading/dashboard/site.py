"""Static site for GitHub Pages, built from stored snapshots only (no network access).

The site is rebuilt from the latest snapshot that passed its integrity check.
When the newest run failed, the previous snapshot stays up with a visible
stale-data banner; a client-side check also warns when more than
spec.FRESHNESS_STALE_SESSIONS NYSE sessions have passed, in case no new build
was deployed at all.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import os
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from ..market_calendar import is_trading_day
from . import assets_bets, assets_research, changes, compare, evidence, lab, probability, research, spec
from .assets import CSS, JS
from .fmt import (SUMMARIES, cap, csv_value, metric, money, net_position, num, ok as _ok, pct, summary_details, sval,
                  tracking_schedule)
from .scenarios import RETURN_WINDOWS, implied_growth_text
from .site_ai import ai_page, methodology_ai, top20_block
from .site_compare import compare_page
from .site_lists import growth_page, multibaggers_page
from . import site_bets
from . import site_refresh
from .site_options import lists_of, options_page
from .site_research import changes_section, datasets_table, lab_section, quality_block, research_section
from .site_overview import band_title, evidence_fragments, excluded_page, list_page, overview, scenario_flags_html
from .site_symbol import symbol_index, symbol_page

_SYMBOLS: dict[str, str] = {}      # ticker -> name, for the header search (set by build_site)
_SITE = {"v": ""}   # asset version for cache busting (set by build_site)
from .site_watchlist import watchlist_csv, watchlist_page
from .store import Store, find_private_keys

E = html.escape
NAV = [("index.html", "Overview"), ("growth.html", "Growth Stocks"), ("multibaggers.html", "Multibaggers"),
       ("ai.html", "AI stocks"), ("options.html", "Options"), ("bets.html", "Small bets"), ("watchlist.html", "Watchlist 2030"),
       ("compare.html", "Compare"),
       ("history.html", "History & tracking"), ("methodology.html", "Methodology"), ("audit.html", "Audit trail")]
COMP_SHORT = {"growth": "Growth", "earnings": "Earn/FCF", "quality": "Quality", "balance": "Balance", "runway": "Runway",
              "valuation": "Value", "momentum": "Mom.", "relative": "Rel."}


# --- page shell -------------------------------------------------------------------------------------

TH_WITHOUT_SCOPE = re.compile(r"<th\b(?![^>]*\bscope=)")


def column_headers(markup: str) -> str:
    """Every <th> on this site is a column header: give each one scope="col" so screen readers announce the
    column for a cell in a wide, sideways-scrolling table. Headers that already declare a scope are left alone."""
    return TH_WITHOUT_SCOPE.sub('<th scope="col"', markup)


def brand() -> str:
    """The public site name stays consistent across pages and dataset states."""
    return "Tikasa Stock Research"


def page(title: str, body: str, current: str, depth: int = 0, freshness: str = "", scripts: tuple = ()) -> str:
    up = "../" * depth
    # the options page is always listed: it explains its own state when nothing was collected (2026-10-14.6)
    nav = "".join(f'<a href="{up}{href}"{" aria-current=page" if href == current else ""}>{E(label)}</a>'
                  for href, label in NAV)
    opts = "".join(f'<option value="{E(t)}">{E(n)}</option>' for t, n in _SYMBOLS.items())
    search = (f'<form class="symsearch" role="search" data-base="{up}symbol/" onsubmit="return false">'
              f'<label class="sr-only" for="symq">Find a ticker</label><input id="symq" type="search" list="symlist" '
              f'placeholder="Find a ticker" autocomplete="off" aria-describedby="symhint">'
              f'<span id="symhint" class="sr-only">Choose a ticker from the list to open its page</span>'
              f'<datalist id="symlist">{opts}</datalist></form>' if _SYMBOLS else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} · {E(brand())}</title>
<meta name="robots" content="noindex">
<script>try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
<link rel="stylesheet" href="{up}assets/style.css{_SITE["v"]}">
<link rel="alternate" type="application/atom+xml" title="Weekly research reports" href="{up}feed.xml"></head>
<body><a class="skip" href="#main">Skip to content</a><header class="site"><div class="inner"><a class="brand" href="{up}index.html">{E(brand())}</a>
<nav>{nav}</nav>{search}<button class="themebtn" type="button" aria-label="Colour theme: automatic">Theme: auto</button></div></header>
<main id="main" tabindex="-1">{column_headers(freshness + body)}
<footer>{E(spec.DISCLAIMER)} Methodology version {E(spec.SPEC_VERSION)}. Sources: SEC EDGAR, Nasdaq Trader,
Wikipedia (CC BY-SA 4.0), Cboe delayed quotes, Alpha Vantage. Built from stored weekly snapshots.</footer></main>
<script src="{up}assets/app.js{_SITE["v"]}"></script>{"".join(f'<script src="{up}{s}{_SITE["v"]}"></script>' for s in scripts)}</body></html>"""


def sessions_after(as_of: str, days: int = spec.FRESHNESS_CALENDAR_DAYS) -> list[str]:
    """NYSE sessions after the as-of session, for the browser to count the data's age (spec FRESHNESS_RULE)."""
    start = date.fromisoformat(str(as_of)[:10])
    return [(start + timedelta(days=i)).isoformat() for i in range(1, days + 1)
            if is_trading_day(start + timedelta(days=i))]


def window_text(key: str, r: dict, as_of: str) -> str:
    """The sessions a stored return covers; snapshots before spec 2026-10-14.5 stored no start date."""
    n = r.get("sessions") or dict(RETURN_WINDOWS).get(key)
    if r.get("start"):
        return f"{r['start']} to {r['end']} ({n} sessions)"
    return f"{n} trading sessions to {as_of}"


def freshness_banner(snap: dict, status: dict | None) -> str:
    as_of = snap["as_of"]
    parts = [f'<div class="banner info" id="freshness" data-asof="{E(as_of)}" '
             f'data-sessions="{E(",".join(sessions_after(as_of)))}" data-stale-after="{spec.FRESHNESS_STALE_SESSIONS}">'
             f'<strong>Data as of the {E(as_of)} close (<span id="age">age counted in NYSE sessions when scripts run'
             f'</span>).</strong>Snapshot built {E(str(snap.get("run_finished", "")).replace("+00:00", ""))} UTC. '
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
                 f'More than {spec.FRESHNESS_STALE_SESSIONS} NYSE sessions have passed since the as-of close, so at '
                 'least one weekly update did not publish.</div>')
    return "".join(parts)


# --- overview ----------------------------------------------------------------------------------------

def profile_of(band: dict) -> tuple:
    return spec.PROFILES.get(band.get("profile", "standard"), spec.COMPONENTS)





# --- detail page ----------------------------------------------------------------------------------------

NICE_STEPS = (10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


def nice_ticks(lo: float, hi: float, max_ticks: int = 7) -> list[float]:
    """Round axis ticks (multiples of 10/25/50/100/250/500...) covering [lo, hi], at most `max_ticks`."""
    import math as _m
    for step in NICE_STEPS:
        start, end = _m.floor(lo / step) * step, _m.ceil(hi / step) * step
        if end == start:
            end = start + step
        if (end - start) / step + 1 <= max_ticks:
            return [start + i * step for i in range(int(round((end - start) / step)) + 1)]
    step = NICE_STEPS[-1]
    return [_m.floor(lo / step) * step, _m.ceil(hi / step) * step]


def line_chart(chart: dict, ticker: str, bench: str) -> str:
    if not chart or not chart.get("stock"):
        return '<p class="muted">Price history unavailable.</p>'
    W, H, L, R, T, B = 720, 260, 48, 660, 14, 230
    vals = chart["stock"] + (chart.get("benchmark") or [])
    tick_values = nice_ticks(min(vals), max(vals))
    lo, hi = tick_values[0], tick_values[-1]
    n = len(chart["stock"])

    def xy(i, v):
        return L + (R - L) * i / max(1, n - 1), B - (B - T) * (v - lo) / (hi - lo)

    def path(series):
        return " ".join(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}' for i, (x, y) in
                        enumerate(xy(i, v) for i, v in enumerate(series)))
    ticks = []
    for v in tick_values:
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


def detail(c: dict, snap: dict, history: list[dict] | None = None, prev_snap: dict | None = None) -> str:
    from . import site_decisions
    m = c["metrics"]
    h = c["history"]
    rets = "".join(
        f'<tr><td>{k}<div class="small muted">{E(window_text(k, v, snap["as_of"]))}</div></td>'
        f'<td class="num">{pct(v["stock"], 1)}</td><td class="num">{pct(v["benchmark"], 1)}</td>'
        f'<td class="num">{pct(v["excess"], 1, True)}</td></tr>' if v else
        f'<tr><td>{k}</td><td class="num muted" colspan=3>not enough history</td></tr>'
        for k, v in ((k, h["returns"].get(k)) for k in ("1m", "3m", "6m", "1y", "3y", "5y")))
    dd = h["drawdowns"]
    comp_rows = "".join(
        f'<tr><td>{E(cp.title)}{" (critical)" if cp.critical else ""}</td><td class="num">{cp.weight:.0%}</td>'
        f'<td class="num">{"missing" if c["components"].get(cp.key) is None else round(c["components"][cp.key] * 100)}</td>'
        f'<td><div class="bar"><span style="width:{(c["components"].get(cp.key) or 0) * 100:.0f}%"></span></div></td>'
        f'<td class="small">' + "; ".join(
            f'<abbr title="{E(spec.METRIC_NOTES.get(mk, ""))}">{E(mk.replace("_", " "))}</abbr> = {E(metric(mk, m.get(mk)))}'
            f'{" (missing, scored 0)" if mk in c["missing"] else ""}'
            for mk in cp.metrics) + "</td></tr>" for cp in profile_of(snap["bands"][c["band"]]))
    fund = c["fundamentals"]
    frow = lambda label, key: f'<tr><td>{label}</td>' + "".join(  # noqa: E731
        f'<td class="num">{num((v or 0) / 1e6, 0) if v is not None else "n/a"}</td>' for v in fund[key]) + "</tr>"
    fhead = "".join(f'<th class="num">{E(q)}{"*" if d else ""}</th>' for q, d in zip(fund["quarters"], fund["derived_revenue"]))
    scen_html = f'<p class="muted">{E(c.get("scenario_note") or "")}</p>'
    if c.get("scenarios"):
        sc = c["scenarios"]
        years = sorted(int(y) for y in sc["base"]["years"])
        rows = ""
        for key in ("bear", "base", "bull"):
            s = sc[key]
            a = s["assumptions"]
            cells = "".join(f'<td class="num">{money(s["years"][str(y)]["value_per_share"])}<div class="small muted">'
                            f'{num(s["years"][str(y)]["multiple_of_price"], 2)}x · {pct(s["years"][str(y)]["annualized"], 0, True)}/yr</div></td>'
                            for y in years)
            rows += (f'<tr><td><strong>{key}</strong></td>{cells}<td class="small">start growth {pct(a["starting_revenue_growth"])}'
                     f', fading to {pct(spec.SCENARIO_TERMINAL_GROWTH)}; exit EV/Sales {num(a["exit_ev_to_sales"], 1)}x; '
                     f'dilution {pct(a["annual_dilution"], 1)}/yr; FCF margin {pct(a["fcf_margin_start"])} &rarr; '
                     f'{pct(a.get("fcf_margin_end", a.get("fcf_margin_year5")))} by year {years[-1]}; {net_position(-a["net_cash_held"] if _ok(a.get("net_cash_held")) else None, False)} held flat</td></tr>')
        yh = "".join(f'<th class="num">{y} year{"s" if y > 1 else ""}</th>' for y in years)
        scen_html = f"""<div class="table-wrap"><table aria-label="Bear, base and bull scenario values"><thead><tr><th>Scenario</th>{yh}<th>Assumptions</th></tr></thead>
<tbody>{rows}</tbody></table></div>
{scenario_flags_html(c, snap["bands"][c["band"]])}
{summary_details(SUMMARIES["multibagger"], spec.MULTIBAGGER_DEFINITION)}
{summary_details(SUMMARIES["scenario_method"], spec.SCENARIO_METHOD, "How the scenarios are built")}"""
    earn = c.get("next_earnings")
    flags = "".join(f'<span class="pill">{E(f)}</span>' for f in c["flags"]) or '<span class="muted">none</span>'
    ns = "".join(f'<li><strong>{E(k.replace("_", " "))}:</strong> {E(v)}</li>' for k, v in c["not_scored"].items())
    return f"""<p class="small"><a href="../{list_page(c["band"])}#{E(c["band"])}">&larr; back to the list</a></p>
<h1>{E(c["ticker"])} · {E(c["name"] or "")}</h1>
<p class="lede">{E(c["sector"] or "Unknown")} · rank {c["rank"]} in the {E(band_title(c["band"], snap["bands"][c["band"]]))} list ·
score {num(c["composite"], 1)} / 100 · confidence <span class="pill {E(c["confidence_label"])}">{E(c["confidence_label"])}</span></p>
<div class="grid"><div class="card stat"><div class="label">Price ({E(c["price_date"])} close)</div><div class="value">{money(c["price"])}</div>
<div class="small muted">{E(c["sources"]["price"])}</div></div>
<div class="card stat"><div class="label">Market cap</div><div class="value">{cap(c["market_cap"])}</div>
<div class="small muted">{E(spec.MARKET_CAP_DEFINITION[:90])}…</div></div>
<div class="card stat"><div class="label">Earnings dates</div><div class="value">{E(earn or "unknown")}</div>
<div class="small muted">next: scheduled, Alpha Vantage, unverified</div>{_earnings_check(c)}</div>
<div class="card stat"><div class="label">Data timestamp</div><div class="value small">{E(str(c["data_timestamp"]).replace("+00:00", ""))} UTC</div>
<div class="small muted">fundamentals: {E(fund.get("last_form") or "?")} filed {E(fund.get("last_filed") or "?")}</div></div></div>
<p class="small">Flags: {flags}</p>
{site_decisions.detail(c)}
{changes_section(changes.compare(c, snap, prev_snap))}
{research_section(research.panel(c, snap, history or [snap], profile_of(snap["bands"][c["band"]])))}
{quality_block(evidence.company_check(c, str(snap["as_of"])))}
<h2>Research thesis</h2><p>{E(c["thesis"])}</p><p class="small muted">Generated by fixed rules from reported data. It is a
summary of evidence, not a recommendation.</p>
<h2>Strongest bear case</h2><p>{E(c["bear_case"])}</p>
<h2>Component scores</h2><div class="table-wrap"><table aria-label="Component scores and inputs"><thead><tr><th>Component</th><th class="num">Weight</th>
<th class="num">Score</th><th></th><th>Inputs</th></tr></thead><tbody>{comp_rows}</tbody></table></div>
<p class="small muted">Missing inputs score 0; weights are never redistributed.</p>
<h3>Not scored</h3><ul class="tight small">{ns}</ul>
<h2>Price vs benchmark</h2>{line_chart(c["chart"], c["ticker"], c["benchmark"])}
<div class="table-wrap"><table aria-label="Trailing price returns vs benchmark"><thead><tr><th>Period</th><th class="num">{E(c["ticker"])}</th><th class="num">{E(c["benchmark"])}</th>
<th class="num">Difference</th></tr></thead><tbody>{rets}</tbody></table></div>
<p class="small">Max drawdown (5 years): <strong>{pct(dd["max_5y"]["value"])}</strong> ({E(str(dd["max_5y"]["peak"]))} to
{E(str(dd["max_5y"]["trough"]))}) · from 52-week high: {pct(dd["from_52w_high"])} · worst 12-month return since
{E(h["first_date"])}: {pct(dd.get("worst_1y_return"))}. Price returns exclude dividends. History starts {E(h["first_date"])}.</p>
<h2>Fundamentals and valuation</h2>
<div class="grid small">
<div class="card">Revenue TTM {cap(m.get("revenue_ttm"))} · growth {pct(m.get("revenue_growth_ttm"))} · 3-yr CAGR {pct(m.get("revenue_cagr_3y"))}</div>
<div class="card">Gross margin {pct(m.get("gross_margin"))} · operating margin {pct(m.get("operating_margin"))} · FCF margin {pct(m.get("fcf_margin"))}</div>
<div class="card">EV/Sales {num(m.get("ev_to_sales"), 1)}x · P/E {num(m.get("pe"), 1)} · FCF yield {pct(m.get("fcf_yield"), 1)} · {E(implied_growth_text(m.get("implied_revenue_cagr"), m.get("revenue_growth_ttm")))}</div>
<div class="card">{net_position(m.get("net_debt"))} · current ratio {num(m.get("current_ratio"))} · dilution {pct(m.get("dilution"), 1)} · SBC/revenue {pct(m.get("sbc_to_revenue"))}</div>
</div>
<div class="table-wrap"><table aria-label="Quarterly fundamentals in USD millions"><thead><tr><th>USD millions</th>{fhead}</tr></thead><tbody>
{frow("Revenue", "revenue")}{frow("Gross profit", "gross_profit")}{frow("Operating income", "operating_income")}
{frow("Net income", "net_income")}{frow("Operating cash flow", "ocf")}{frow("Capital expenditure", "capex")}{frow("Stock-based comp.", "sbc")}
</tbody></table></div><p class="small muted">* quarter derived from cumulative or annual filings. Source: {E(c["sources"]["fundamentals"])},
facts filed on or before {E(snap["as_of"])} only.</p>
<h2>Bear / base / bull valuation ranges</h2>{scen_html}
{top20_block(c)}
{lab_section(lab.inputs(c))}
<div class="banner info"><strong>Probability</strong>{summary_details(SUMMARIES["probability"], c["probability"], "Why")}</div>
<h2>Key business risks</h2><ul class="tight">{''.join(f'<li>{E(r)}</li>' for r in c["risks"])}</ul>
<h2>What would invalidate the thesis</h2><ul class="tight">{''.join(f'<li>{E(r)}</li>' for r in c["invalidation"])}</ul>"""


# --- history, methodology, audit ------------------------------------------------------------------------

def history_page(dates: list[str], tracking: dict | None) -> str:
    items = "".join(f'<li><a href="reports/{d}.html">Week ending {d}</a></li>' for d in reversed(dates))
    if not tracking:
        trk = f'<p class="small">{E(tracking_schedule(dates))}</p>'
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
<p class="small">{E(tracking_schedule(dates))}</p>
<h3>Average excess return net of friction, by category</h3><div class="table-wrap"><table aria-label="Average excess return by list"><thead><tr><th>Category</th>{hh}
<th class="num">Weekly turnover</th></tr></thead><tbody>{summ}</tbody></table></div>
<h3>Weekly one-week chain</h3><ul class="small">{chain or '<li class="muted">Appears once a weekly list has been held for 5 trading sessions with prices for every name.</li>'}</ul>
<h3>Each snapshot</h3><div class="table-wrap"><table aria-label="Tracking result for each snapshot"><thead><tr><th>As of</th><th>Category</th><th>Spec</th>{hh}</tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class="small">{E(tracking["method"])}</p><ul class="small">{''.join(f'<li>{E(x)}</li>' for x in tracking["limitations"])}</ul>
<p class="small">Assumed trading friction per side: {E(", ".join(f"{k} {v:g} bps" for k, v in tracking["friction"].items()))}
(bps = hundredths of a percent).</p>"""
    return f"""<h1>History and performance tracking</h1><p class="lede">Every weekly snapshot is stored unchanged. Later prices
measure each list as it was published.</p><h2>Weekly reports</h2><ul>{items}</ul><h2>Tracking</h2>{trk}"""


_R = spec.OPTION_RULES
OPTION_RULES_TEXT = (
    f"up to {_R['max_per_type_per_horizon']} calls and {_R['max_per_type_per_horizon']} puts per expiry window, at most "
    f"{_R['max_per_underlying_per_horizon']} per underlying per list; open interest at least {_R['min_open_interest']}; "
    f"volume at least {_R['min_volume']}; bid-ask spread at most {_R['max_spread_pct']:.0%} of the mid price; |delta| "
    f"{_R['min_delta']:g} to {_R['max_delta']:g}; standard {_R['standard_multiplier']}-share contracts only; the "
    f"underlying must have traded in the as-of session"
)


def _component_rows(components) -> str:
    return "".join(
        f'<tr><td>{E(c.title)}</td><td class="num">{c.weight:.0%}</td><td>{"yes" if c.critical else "no"}</td><td class="small">' +
        "<br>".join(f'<strong>{E(k)}</strong> ({"lower is better, " if s.reverse else ""}0 at {s.lo:g}, 1 at {s.hi:g}{" reversed" if s.reverse else ""}): '
                    f'{E(spec.METRIC_NOTES[k])}' for k, s in c.metrics.items()) + "</td></tr>" for c in components)


def methodology_page() -> str:
    comps = _component_rows(spec.COMPONENTS)
    long_comps = _component_rows(spec.LONG_HORIZON_COMPONENTS)
    growth_comps = _component_rows(spec.GROWTH_COMPONENTS)
    gates = "".join(f'<li>{E(spec.METRIC_NOTES.get(m, spec.GATE_NOTES.get(m, m)))} Gate: {E(op)} {v:g}</li>'
                    for b in spec.BANDS for m, op, v in b.gates)
    bands = "".join(f'<tr><td>{E(b.title)}</td><td>{E(b.universe)}</td><td>{cap(b.min_cap) if b.min_cap else "-"} to '
                    f'{cap(b.max_cap) if b.max_cap else "-"}</td><td>${b.min_price:g}</td><td>{cap(b.min_dollar_volume)}</td>'
                    f'<td>{"revenue growth ≥ " + pct(b.min_revenue_growth) if b.min_revenue_growth else "-"}</td><td>{E(b.benchmark)}</td>'
                    f'<td>{b.max_results}</td></tr>' for b in spec.BANDS)
    hz = "".join(f'<li>{E(h.title)}: {h.min_dte}-{h.max_dte} days to expiration</li>' for h in spec.HORIZONS)
    rk = "".join(f'<li><strong>{E(k)} ({w:.0%})</strong>: {E(t)}</li>' for k, (w, t) in spec.OPTION_RANKING.items())
    sizes = "; ".join(f"from {v}: up to {n} per list ({what})" for v, n, what in spec.OPTION_LIST_SIZE_HISTORY)
    ps = probability.status_summary()
    cells = ", ".join(f"{k} {v}" for k, v in ps["cells"].items())
    g = spec.PROBABILITY_GATE
    gate = "".join(f"<li>{E(x)}</li>" for x in (
        f"required fields: {', '.join(g['required_fields'])}",
        f"at least {g['min_sample_size']} resolved contracts per option type and horizon",
        f"an evaluation period of at least {g['min_evaluation_days']} days of expirations",
        f"expected calibration error at most {g['max_calibration_error']:.2f}",
        "forecasts recorded out of sample, before their outcomes were known",
        "no reuse of a holdout already consumed by another decision (the 2022+ equity holdout was evaluated on 2026-10-12)",
        "an uncertainty interval accompanies every percentage",
        "calls and puts, and each expiry window, calibrated separately"))
    missing = "".join(f"<li>{E(x)}</li>" for x in spec.PROBABILITY_MISSING_DATA)
    log = "".join(f'<li>{E(v)}: {E(t)}</li>' for v, t in spec.SPEC_CHANGELOG)
    etf = "".join(f'<tr><td>{E(r[1])}</td><td class="small">{E(", ".join(k.strip() for k in r[2]))}</td>'
                  f'<td class="num">{" / ".join(pct(x, 0, True) for x in r[3])}</td><td class="num">{pct(r[4], 2)}</td>'
                  f'<td class="num">{pct(r[5], 1)}</td></tr>' for r in spec.ETF_EXPOSURE_RULES)
    return f"""<h1>Methodology</h1><p class="lede">Version {E(spec.SPEC_VERSION)} (hash {E(spec.spec_hash())}). All rules were fixed
before any results were computed; a change creates a new version and results are tracked separately per version.</p>
<h2>Universes</h2><p>{E(spec.UNIVERSE_DEFINITION)}</p><p>{E(spec.MARKET_CAP_DEFINITION)}</p>
<div class="table-wrap"><table aria-label="List definitions"><thead><tr><th>Category</th><th>Universe</th><th>Market cap</th><th>Min price</th>
<th>Min 20-day median $ volume</th><th>Gate</th><th>Benchmark</th><th>Max shown</th></tr></thead><tbody>{bands}</tbody></table></div>
<p>Limited operating history: fewer than {spec.LIMITED_HISTORY_QUARTERS} reported quarters. Limited trading history: fewer than
{spec.LIMITED_HISTORY_DAYS} daily bars. Fundamentals older than {spec.MAX_FILING_AGE_DAYS} days exclude a stock. The as-of close
must be present. Lists are never padded: fewer than ten qualifying stocks means fewer than ten shown.</p>
<h2 id="decision-research">Growth decision research · version 2026-10-14.9</h2>
<p>New large, mid and small lists rank fundamental quality alone. Price momentum and benchmark-relative returns
are displayed separately. Annual price returns over 150% are flagged extended. Existing snapshots retain their original ranks.</p>
<div class="table-wrap"><table aria-label="Growth quality weights"><thead><tr><th>Component</th><th>Weight</th><th>Critical</th><th>Inputs and scales</th></tr></thead><tbody>{growth_comps}</tbody></table></div>
<p>Annual revenue and diluted EPS CAGR require positive full fiscal-year endpoints, matched within 45 days of
3 or 5 years apart. Latest-quarter revenue acceleration compares its YoY rate with the preceding quarter's YoY rate;
within 2 percentage points is stable. TTM margin trends compare the previous four quarters; within 1 point is stable.
Interest coverage is TTM operating income / positive interest expense. Net debt / EBITDA uses signed debt less cash
and equivalents and positive operating income plus depreciation/amortization. Incomplete debt inputs are n/a.</p>
<p>Valuation percentiles are average ranks of finite values in the same published list, scaled from 0 to 100,
with at least two observations. A higher percentile means a higher numerical value, not a better investment.
Forward P/E, PEG, analyst targets and five-category rating counts are current Alpha Vantage observations, never used
for historical backfills or scores. Insider acquisitions/disposals without Form 4 P/S codes cannot establish net market buying.
Business, growth and risk text is excerpted from identified 10-K sections and may be unavailable. Missing values always carry reasons.</p>
<h2>Legacy / AI scoring</h2><p>Each input maps to 0-1 on a fixed linear scale (absolute thresholds, not ranks). A component is the average of
its inputs. A missing input scores 0 and is shown; weights are never redistributed. A stock with a critical component entirely
missing, or more than {spec.MAX_MISSING_METRICS} missing inputs, is not ranked. Ties: {E(spec.TIE_BREAK)}.</p>
<div class="table-wrap"><table aria-label="Scoring components and scales"><thead><tr><th>Component</th><th class="num">Weight</th><th>Critical</th><th>Inputs and scales</th></tr></thead>
<tbody>{comps}</tbody></table></div>
<p>Momentum and benchmark-relative performance are separate components. {E(spec.CONFIDENCE_RULES)}</p>
<h3 id="multibagger">Speculative multibagger research candidates (5-10 years)</h3><p>{E(spec.MULTIBAGGER_RATIONALE)}</p>
<p>Eligibility gates (all must hold; a missing input fails the gate):</p><ul class="small">{gates}</ul>
<p>Weights for the multibagger list:</p>
<div class="table-wrap"><table aria-label="Long-horizon scoring components"><thead><tr><th>Component</th><th class="num">Weight</th><th>Critical</th><th>Inputs and scales</th></tr></thead>
<tbody>{long_comps}</tbody></table></div>
<h3>Robinhood tradability</h3><p>{E(spec.TRADABILITY_RULE)} Because scores use fixed scales, removing a stock that is not
tradable does not change the order of the others. Checks run in a Claude session with the read-only Robinhood tool, since
GitHub Actions cannot reach it; no account data is stored.</p>
<h3>Not scored</h3><ul>{''.join(f'<li>{E(k.replace("_", " "))}: {E(v)}</li>' for k, v in spec.NOT_SCORED_FACTORS.items())}</ul>
<p>The strongest counterargument is the input with the largest weighted shortfall (missing critical data first).</p>
<h2>Scenarios</h2><p>{E(spec.SCENARIO_METHOD)}</p><p>{E(spec.MULTIBAGGER_DEFINITION)}</p><p>{E(spec.PROBABILITY_STATEMENT)}</p>
{methodology_ai()}
<h2>Speculative small bets · 30–90 DTE</h2>
<p>The new options section covers the top three names per growth list, up to three contracts each. Standard calls and puts
require 30–90 DTE, |delta| 0.25–0.40, OI above 500, volume at least 10, positive bid/ask, spread at most 10% of mid,
positive IV and nonzero theta. Existing liquidity/breakeven/decay ranking applies. These contracts can lose 100%.</p>
<p>ATM IV averages paired call and put IV at the closest strike, in the 20–40 DTE expiry nearest 30 days.
IV rank needs 252 comparable stored sessions within 366 days; insufficient history is n/a. Earnings move is a
constant-IV square-root-time model to the scheduled event using the first expiry at/after it, not a calibrated forecast.
Put/call ratio uses 30–90 DTE contract volumes. The browser-only hypothetical 5%/1% caps check one premium, not existing exposure.
Exit examples (+100%, −50%, 21 DTE) are illustrative and cannot guarantee execution or limit loss.</p>
<h2>Options (calls and puts)</h2><p>{E(spec.OPTION_UNDERLYINGS)}</p><ul>{hz}</ul><p>Eligibility: {E(OPTION_RULES_TEXT)}.</p>
<p>Ranking (higher is better; maximum upside is not an input):</p><ul>{rk}</ul><p>{E(spec.OPTION_RANKING_NOTE)}</p>
<p>{E(spec.DELTA_STATEMENT)}</p><p>{E(spec.PREMIUM_ASSUMPTION)} Puts: breakeven = strike - premium; payoff = max(strike - price, 0) -
premium; the required move is measured downward. {E(spec.RISK_FREE_RATE_NOTE)}</p>
<p>{E(spec.OPTION_UNIVERSE_TEXT)} {E(spec.OPTION_TOP_DEFINITION)}</p>
<p>{E(spec.OPTION_THETA_RULE)}</p><p>{E(spec.OPTION_QUOTE_RULE)}</p><p>{E(spec.OPTION_EVENT_RULE)}</p><p>{E(spec.FEE_TREATMENT)}</p>
<p>List size by methodology version (older snapshots render with the limit they were built under): {E(sizes)}.</p>
<h3 id="probability">Probability of profit: definition, validation gate and missing data</h3>
<p>{E(spec.PROBABILITY_OF_PROFIT_DEFINITION)}</p><p>{E(spec.ITM_PROBABILITY_DEFINITION)}</p><p>{E(spec.PROBABILITY_NEVER_SUBSTITUTED)}</p>
<p><strong>{E(spec.PROBABILITY_NOT_ESTABLISHED)}</strong> Status by option type and horizon: {E(cells)}.</p>
<p>A percentage may be displayed only for a calibration record that passes every rule of the gate, and the page must then show
the model version, evaluation period, sample size, calibration result and uncertainty next to it:</p><ul>{gate}</ul>
<p>Data contract for a future calibration (one append-only record per listed contract, written at listing time and completed
at expiration): {E(", ".join(probability.DATA_CONTRACT["record_fields"]))}. {E(probability.DATA_CONTRACT["resolution"])}
{E(probability.DATA_CONTRACT["storage"])} {E(probability.DATA_CONTRACT["evaluation"])}</p>
<p>Missing today, so no probability can be established:</p><ul>{missing}</ul>
<h2 id="watchlist">Watchlist: conditional 2030 price scenarios</h2><p>{E(spec.WATCHLIST_STATEMENT)}</p><p>{E(spec.WATCHLIST_SEPARATION)}</p>
<p>{E(spec.WATCHLIST_COMPANY_METHOD)}</p><p>{E(spec.LEVERAGED_METHOD)}</p><p>{E(spec.FEE_NOTE)}</p>
<div class="table-wrap"><table aria-label="ETF exposure-class assumptions"><thead><tr><th>ETF exposure class</th><th>Name keywords</th><th class="num">Bear / base / bull total return</th>
<th class="num">Assumed fee</th><th class="num">Assumed distribution yield</th></tr></thead><tbody>{etf}</tbody></table></div>
{site_bets.methodology()}
<h2>Performance tracking</h2><p>{E(spec.TRACKING_METHOD)}</p>
<h2 id="display-rules">Data states, research panel and comparisons</h2>
<p>These rules decide how evidence is labelled and compared. No score, gate or ranking uses them.</p>
<ul>{''.join(f'<li><strong>{E(k.replace("_", " "))}</strong>: {E(v)}</li>' for k, v in spec.DATASET_STATES.items())}</ul>
<p>{E(spec.FRESHNESS_RULE.replace("FRESHNESS_STALE_SESSIONS", str(spec.FRESHNESS_STALE_SESSIONS)))}</p>
<p>{E(spec.WATCHLIST_PRICE_RULE)}</p>
<p>Earnings-quality checks: free cash flow / net income (clean at {spec.FORENSIC_RULES["fcf_to_net_income"]["clean_at_least"]:.2f}x
or more, concerning below {spec.FORENSIC_RULES["fcf_to_net_income"]["concerning_below"]:.2f}x) and stock-based pay / revenue
(clean below {pct(spec.FORENSIC_RULES["sbc_to_revenue"]["clean_below"])}, concerning above
{pct(spec.FORENSIC_RULES["sbc_to_revenue"]["concerning_above"])}). Not collected, so not checked:
{E(", ".join(spec.FORENSIC_RULES["not_collected"]))}.</p>
<p>{E(spec.THESIS_TRACKING_RULE)}</p>
<p>What changed: listed when trailing revenue growth falls {pct(spec.CHANGE_RULES["revenue_growth_drop"])} or more, the operating or
free-cash-flow margin falls {pct(spec.CHANGE_RULES["operating_margin_drop"])} or more, the one-year share-count change rises
{pct(spec.CHANGE_RULES["dilution_rise"])} or more, free cash flow turns negative, a new filing or quarter appears, a thesis
condition is breached, an input becomes available or unavailable, or the score moves {spec.CHANGE_RULES["score_move"]:.0f}
points or more.</p>
<p>{E(spec.COMPARE_RULES["note"])}</p><p>{E(spec.SCENARIO_LAB_BOUNDS["note"])}</p>
<p class="small">Some of these structures are adapted from open-source projects: filingcopilot (MIT; comparison on common
dates, bounded scenario inputs), ticker-dossier (MIT; dataset coverage records and evidence checks) and cc-equity-research
(Apache-2.0; thesis tracking, earnings-quality and catalyst templates, turned into fixed rules). See
<a href="https://github.com/vsakati6691/agent-code/blob/main/THIRD_PARTY_NOTICES.md" rel="noopener">THIRD_PARTY_NOTICES.md</a>.</p>
<h2>Version history</h2><ul>{log}</ul>"""


def _earnings_check(c: dict) -> str:
    ec = c.get("earnings_check") or {}
    if ec.get("last_results"):
        tail = f" · {E(ec['cadence_check'])}" if ec.get("cadence_check") else ""
        return f'<div class="small">last results {E(ec["last_results"])}: <strong>verified (8-K)</strong>{tail}</div>'
    if ec.get("last_results_status"):
        return f'<div class="small muted">{E(ec["last_results_status"])}</div>'
    return ""


def _readable(d) -> str:
    """Audit details as 'key: value' text (no raw JSON on the page)."""
    if isinstance(d, dict):
        return "; ".join(f"{str(k).replace('_', ' ')}: {_readable(v)}" for k, v in d.items() if v not in (None, "", {}, []))
    if isinstance(d, (list, tuple)):
        return ", ".join(_readable(v) for v in d)
    if isinstance(d, float):
        return metric("", d)
    return str(d)


def audit_page(store: Store, snap: dict, integrity: list[str]) -> str:
    rows = "".join(f'<tr><td class="small">{E(str(e.get("at")).replace("+00:00", ""))}</td><td>{E(str(e.get("event")).replace("_", " "))}</td>'
                   f'<td class="small">{E(_readable({k: v for k, v in e.items() if k not in ("at", "event")})[:400])}</td></tr>'
                   for e in reversed(store.audit_log()[-300:]))
    man = []
    for d in reversed(store.dates()):
        m = json.loads((store.root / "snapshots" / d / "manifest.json").read_text(encoding="utf-8"))
        man.append(f'<tr><td>{E(d)}</td><td class="small"><code>{E(m["sha256"][:16])}…</code></td><td>{E(str(m.get("spec_version")))}</td>'
                   f'<td class="small">{E(str(m.get("code_commit") or "local build")[:10])}</td><td>{E(str(m.get("status")))}</td></tr>')
    ok = '<div class="banner info"><strong>Integrity</strong>Every stored snapshot matches its manifest hash.</div>' if not integrity else \
        '<div class="banner bad"><strong>Integrity problems</strong>' + E("; ".join(integrity)) + "</div>"
    usage = snap.get("usage", {})
    return f"""<h1>Audit trail</h1>{ok}<h2 id="data-status">Data status</h2>
<p class="small">One state per dataset behind the {E(str(snap["as_of"]))} snapshot. Nothing falls back to sample or
estimated data: anything not collected is shown as missing.</p>{datasets_table(evidence.datasets(snap))}<h2>Snapshots</h2><div class="table-wrap"><table aria-label="Stored snapshots"><thead><tr><th>As of</th><th>SHA-256</th>
<th>Spec</th><th>Code</th><th>Status</th></tr></thead><tbody>{''.join(man)}</tbody></table></div>
<h2>Latest run</h2><p class="small">Started {E(snap.get("run_started", ""))}, finished {E(snap.get("run_finished", ""))} UTC.
Requests by provider: {E(", ".join(f"{k} {v}" for k, v in usage.get("requests", {}).items()) or "none (all answered from cache)")};
cache hits {E(str(usage.get("cache_hits", 0)))}.
Problems: {E("; ".join(snap.get("problems", [])) or "none")}.</p>
<h2>Data sources and terms</h2><ul class="small">{''.join(f'<li><strong>{E(k)}</strong>: {E(v)}</li>' for k, v in snap.get("sources", {}).items())}</ul>
<h2>Machine-readable data</h2><ul class="small"><li><a href="data/schema.json">data/schema.json</a>: what every field means
(ratios are decimals, money is USD, times are UTC)</li><li><a href="data/latest.json">data/latest.json</a>: the latest snapshot</li>
{''.join(f'<li><a href="data/{E(d)}.json">data/{E(d)}.json</a>: week ending {E(d)}</li>' for d in reversed(store.dates()))}</ul>
<h2>Events</h2><div class="table-wrap"><table aria-label="Audit events"><thead><tr><th>At (UTC)</th><th>Event</th><th>Details</th></tr></thead><tbody>{rows}</tbody></table></div>"""


def weekly_report(snap: dict) -> str:
    parts = [f'<p class="small"><a href="../history.html">&larr; all weeks</a></p><h1>Week ending {E(snap["as_of"])}</h1>'
             f'<p class="lede">Status {E(snap.get("status", "?"))} · methodology {E(snap.get("spec_version", "?"))}.</p>']
    for k, b in snap["bands"].items():
        rows = "".join(f'<tr><td class="num">{c["rank"]}</td><td>{E(c["ticker"])}</td><td>{E(c["name"] or "")}</td>'
                       f'<td class="num">{num(c["composite"], 1)}</td><td>{E(c["confidence_label"])}</td>'
                       f'<td class="num">{money(c["price"])}</td><td class="small">{E(c["counterargument"])}</td></tr>'
                       for c in b["candidates"])
        parts.append(f'<h2>{E(band_title(k, b))}</h2><div class="table-wrap"><table aria-label="Weekly list"><thead><tr><th class="num">#</th><th>Ticker</th><th>Company</th>'
                     f'<th class="num">Score</th><th>Confidence</th><th class="num">Price</th><th>Counterargument</th></tr></thead>'
                     f'<tbody>{rows or "<tr><td colspan=7>none qualified</td></tr>"}</tbody></table></div>'
                     f'<p class="small"><a href="../downloads/{E(snap["as_of"])}_{k}.csv" download>CSV</a></p>')
    o = snap.get("options") or {}
    for h in spec.HORIZONS:
        for kind, lst in lists_of(o.get(h.key) or {}).items():
            rows = "".join(f'<li>{E(x["option"])}: ask {money(x["ask"])}, breakeven {money(x["breakeven"])}, score '
                           f'{num(x["rank_components"]["total"], 1)}</li>' for x in (lst or {}).get("rows", []))
            parts.append(f'<h3>Options, {E(h.title.lower())}, {kind}</h3><ul class="small">{rows or "<li>none / unavailable</li>"}</ul>')
    return "".join(parts)


# --- CSV ----------------------------------------------------------------------------------------------------

def band_csv(band: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    comps = profile_of(band)
    keys = [m for c in comps for m in c.metrics]
    w.writerow(["rank", "ticker", "name", "sector", "composite", *[f"component_{c.key}" for c in comps],
                "confidence", "price", "market_cap", *keys, "missing", "flags", "counterargument"])
    for c in band["candidates"]:
        w.writerow([csv_value(x) for x in [c["rank"], c["ticker"], c["name"], c["sector"], c["composite"],
                    *[c["components"].get(k.key) for k in comps], c["confidence"], c["price"], c["market_cap"],
                    *[c["metrics"].get(k) for k in keys], ";".join(c["missing"]), ";".join(c["flags"]), c["counterargument"]]])
    return buf.getvalue()


def options_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["rank", "type", "underlying", "option", "strike", "expiration", "dte", "spot", "bid", "ask", "spread_pct",
            "volume", "open_interest", "iv", "delta", "gamma", "theta", "vega", "rho", "multiplier", "adjusted",
            "premium_basis", "premium_per_contract_ask", "breakeven", "breakeven_move", "required_move",
            "max_loss_per_contract"]
    extra = ["horizon", "mid", "premium_per_contract_mid", "implied_move_1sd", "theta_available", "theta_share_per_day",
             "quote_time_utc", "quote_date_ny", "quote_status", "quote_source", "underlying_last_trade",
             "contract_last_trade", "events_status"]
    w.writerow(cols + ["rank_score", "earnings_before_expiry", "flags"] + extra +
               ["score_liquidity", "score_breakeven", "score_time_decay", "probability_status", "probability_of_profit",
                "fees"])
    for x in rows:
        rc = x.get("rank_components") or {}
        p = x.get("probability") or {}
        w.writerow([csv_value(v) for v in [x.get(c, "call" if c == "type" else None) for c in cols] +
                   [rc.get("total"), ";".join(str(e["date"]) for e in x.get("events_before_expiry", [])),
                    ";".join(x.get("flags", []))] + [x.get(c) for c in extra] +
                   [rc.get("liquidity"), rc.get("breakeven"), rc.get("time_decay"),
                    p.get("status") or "not_established", p.get("probability_of_profit"),
                    "before fees (none deducted)"]])
    return buf.getvalue()


# --- build -------------------------------------------------------------------------------------------------

def atom_feed(snaps: list[dict]) -> str:
    """Static Atom feed of the weekly reports (newest first). Links are relative to the site root."""
    from xml.sax.saxutils import escape as x

    def stamp(s):
        t = str(s.get("run_finished") or f"{s['as_of']}T21:00:00+00:00")
        return t if ("+" in t[10:] or t.endswith("Z")) else t + "Z"
    entries = []
    for s in sorted(snaps, key=lambda s: str(s["as_of"]), reverse=True):
        d = str(s["as_of"])
        counts = "; ".join(f"{band_title(k, b)}: {len(b.get('candidates', []))}" for k, b in s.get("bands", {}).items())
        entries.append(
            f"<entry><title>Week ending {x(d)}</title><id>urn:agent-code:research-dashboard:{x(d)}</id>"
            f'<link rel="alternate" type="text/html" href="reports/{x(d)}.html"/><updated>{x(stamp(s))}</updated>'
            f"<summary>{x(counts)}. Status {x(str(s.get('status', '?')))}; methodology {x(str(s.get('spec_version', '?')))}. "
            f"Research comparisons only, not advice.</summary></entry>")
    updated = stamp(max(snaps, key=lambda s: str(s["as_of"]))) if snaps else "1970-01-01T00:00:00Z"
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<title>{x(brand())}: weekly reports</title>"
            "<id>urn:agent-code:research-dashboard</id><link rel=\"self\" href=\"feed.xml\"/>"
            '<link rel="alternate" type="text/html" href="history.html"/>'
            f"<updated>{x(updated)}</updated><author><name>agent-code research dashboard</name></author>"
            + "".join(entries) + "</feed>\n")


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
    # a content hash in every asset link, so a browser never pairs new pages with a cached old stylesheet or script
    _SITE["v"] = "?v=" + hashlib.sha256((CSS + assets_research.CSS + JS + assets_research.COMPARE_JS +
                                         assets_research.LAB_JS + assets_bets.CSS + assets_bets.JS).encode("utf-8")).hexdigest()[:10]
    (out / "assets" / "style.css").write_text(CSS + assets_research.CSS + assets_bets.CSS, encoding="utf-8")
    (out / "assets" / "app.js").write_text(JS, encoding="utf-8")
    (out / "assets" / "compare.js").write_text(assets_research.COMPARE_JS, encoding="utf-8")
    (out / "assets" / "lab.js").write_text(assets_research.LAB_JS, encoding="utf-8")
    (out / "assets" / "bets.js").write_text(assets_bets.JS, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    status = store.status()
    if not dates:
        msg = (status or {}).get("message", "no weekly snapshot has been produced yet")
        body = f'<h1>{E(brand())} Dashboard</h1><div class="banner bad"><strong>No research data available</strong>{E(msg)}</div>'
        (out / "index.html").write_text(page("Overview", body, "index.html"), encoding="utf-8")
        for rel, title in (("growth.html", "Growth Stocks"), ("multibaggers.html", "Multibaggers")):
            empty = f'<h1>{title}</h1><p class="scan-empty">No research data available. {E(msg)}</p>'
            (out / rel).write_text(page(title, empty, rel), encoding="utf-8")
        (out / "methodology.html").write_text(page("Methodology", methodology_page(), "methodology.html"), encoding="utf-8")
        (out / "bets.html").write_text(page("Small bets", site_bets.bets_page({}, None), "bets.html"), encoding="utf-8")
        return {"pages": 5, "snapshot": None}
    snap = store.load(dates[-1])
    _SYMBOLS.clear()
    _SYMBOLS.update(symbol_index(snap))
    hits = find_private_keys(snap)
    if hits:
        raise RuntimeError(f"refusing to publish: private-looking fields {hits[:5]}")
    fresh = freshness_banner(snap, status)
    write = lambda rel, title, body, cur, depth=0, fr=fresh, js=(): (out / rel).write_text(  # noqa: E731
        page(title, body, cur, depth, fr, js), encoding="utf-8")
    tracking = store.read_json("tracking.json")
    prev_snap = store.load(dates[-2]) if len(dates) > 1 else None
    daily = site_refresh.load_context(data_dir, snap, out)
    write("index.html", "Overview", overview(snap, status, dates, tracking, prev_snap, daily), "index.html")
    write("ai.html", "AI stocks", ai_page(snap), "ai.html")
    write("growth.html", "Growth Stocks", growth_page(snap, daily), "growth.html")
    write("multibaggers.html", "Multibaggers", multibaggers_page(snap), "multibaggers.html")
    write("options.html", "Options research", options_page(snap, daily), "options.html")
    write("bets.html", "Small-bet options research", site_bets.bets_page(snap, daily), "bets.html", js=("assets/bets.js",))
    write("watchlist.html", "Watchlist 2030", watchlist_page(snap), "watchlist.html")
    write("history.html", "History", history_page(dates, tracking), "history.html")
    write("methodology.html", "Methodology", methodology_page(), "methodology.html", fr="")
    write("audit.html", "Audit trail", audit_page(store, snap, integrity), "audit.html")
    profiles = {k: b.get("profile", "standard") for k, b in snap["bands"].items()}
    write("compare.html", "Compare companies", compare_page(compare.payload(snap, profiles)), "compare.html",
          js=("assets/compare.js",))
    (out / "stock").mkdir()
    (out / "reports").mkdir()
    (out / "downloads").mkdir()
    (out / "data").mkdir(exist_ok=True)
    (out / "symbol").mkdir()
    (out / "fragments").mkdir()
    for rel, text in evidence_fragments(snap["bands"]).items():       # evidence rows load on demand (see assets.JS)
        (out / rel).write_text(text, encoding="utf-8")
    history = [snap if d == dates[-1] else store.load(d) for d in dates]
    for t in _SYMBOLS:
        write(f"symbol/{t}.html", f"{t} · symbol", symbol_page(t, snap, history), "", 1)
    for key, band in snap["bands"].items():
        write(f"excluded-{key}.html", f"Excluded: {band_title(key, band)}", excluded_page(key, band), list_page(key))
    for key, band in snap["bands"].items():
        for c in band["candidates"]:
            write(f"stock/{key}-{c['ticker']}.html", f"{c['ticker']} research", detail(c, snap, history, prev_snap),
                  list_page(key), 1, js=("assets/lab.js",))
    for d in dates:
        s = snap if d == dates[-1] else store.load(d)
        (out / "reports" / f"{d}.html").write_text(page(f"Week ending {d}", weekly_report(s), "history.html", 1, ""),
                                                   encoding="utf-8")
        for key, band in s["bands"].items():
            (out / "downloads" / f"{d}_{key}.csv").write_text(band_csv(band), encoding="utf-8")
        for h in spec.HORIZONS:
            for kind, lst in lists_of((s.get("options") or {}).get(h.key) or {}).items():
                (out / "downloads" / f"{d}_options_{h.key}_{kind}.csv").write_text(
                    options_csv((lst or {}).get("rows", [])), encoding="utf-8")
        if s.get("watchlist"):
            (out / "downloads" / f"{d}_watchlist_2030.csv").write_text(watchlist_csv(s), encoding="utf-8")
    (out / "data" / "latest.json").write_text(json.dumps(snap, default=str), encoding="utf-8")
    for s in history:
        (out / "data" / f"{s['as_of']}.json").write_text(json.dumps(s, default=str), encoding="utf-8")
    from .schema import SCHEMA
    (out / "data" / "schema.json").write_text(json.dumps(SCHEMA, indent=1), encoding="utf-8")
    (out / "feed.xml").write_text(atom_feed(history), encoding="utf-8")
    leaks = scan_for_secrets(out, secret_env)
    if leaks:
        shutil.rmtree(out)
        raise RuntimeError(f"refusing to publish: secret values found in {len(leaks)} file(s)")
    return {"pages": len(list(out.rglob("*.html"))), "snapshot": dates[-1], "integrity_problems": integrity}
