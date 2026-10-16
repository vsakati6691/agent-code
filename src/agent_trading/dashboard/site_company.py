"""Company research pages, stored return windows and price charts."""

from __future__ import annotations

import json

from . import (
    changes,
    evidence,
    lab,
    research,
    spec,
)
from .fmt import (
    SUMMARIES,
    cap,
    metric,
    money,
    net_position,
    num,
    pct,
    summary_details,
)
from .fmt import ok as _ok
from .fmt import (
    sval as sval,
)
from .scenarios import RETURN_WINDOWS, implied_growth_text
from .site_ai import top20_block
from .site_layout import E
from .site_overview import band_title, list_page, scenario_flags_html
from .site_research import changes_section, lab_section, quality_block, research_section

COMP_SHORT = {
    "growth": "Growth",
    "earnings": "Earn/FCF",
    "quality": "Quality",
    "balance": "Balance",
    "runway": "Runway",
    "valuation": "Value",
    "momentum": "Mom.",
    "relative": "Rel.",
}


def window_text(key: str, r: dict, as_of: str) -> str:
    """The sessions a stored return covers; snapshots before spec 2026-10-14.5 stored no start date."""
    n = r.get("sessions") or dict(RETURN_WINDOWS).get(key)
    if r.get("start"):
        return f"{r['start']} to {r['end']} ({n} sessions)"
    return f"{n} trading sessions to {as_of}"


def profile_of(band: dict) -> tuple:
    return spec.PROFILES.get(band.get("profile", "standard"), spec.COMPONENTS)


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
        return " ".join(
            f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}"
            for i, (x, y) in enumerate(xy(i, v) for i, v in enumerate(series))
        )

    ticks = []
    for v in tick_values:
        _, y = xy(0, v)
        ticks.append(
            f'<line x1="{L}" x2="{R}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--border)" stroke-width="1"/>'
            f'<text x="{L - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="var(--text-muted)">{v:.0f}</text>'
        )
    xt = []
    for i in (0, n // 2, n - 1):
        x, _ = xy(i, lo)
        xt.append(
            f'<text x="{x:.1f}" y="{B + 18}" text-anchor="middle" font-size="11" fill="var(--text-muted)">'
            f"{E(chart['dates'][i][:7])}</text>"
        )
    bpath = (
        f'<path d="{path(chart["benchmark"])}" fill="none" stroke="var(--reference)" stroke-width="2" stroke-dasharray="5 4"/>'
        if chart.get("benchmark")
        else ""
    )
    ex, ey = xy(n - 1, chart["stock"][-1])
    end = f'<text x="{ex + 6:.1f}" y="{ey + 4:.1f}" font-size="12" fill="var(--text-primary)">{E(ticker)} {chart["stock"][-1]:.0f}</text>'
    if chart.get("benchmark"):
        bx, by = xy(n - 1, chart["benchmark"][-1])
        if abs(by - ey) < 12:
            by += 12 if by >= ey else -12
        end += f'<text x="{bx + 6:.1f}" y="{by + 4:.1f}" font-size="12" fill="var(--text-secondary)">{E(bench)} {chart["benchmark"][-1]:.0f}</text>'
    data = json.dumps({**chart, "label": ticker, "benchLabel": bench})
    return f"""<div class="legend"><span><i></i>{E(ticker)}</span>{f'<span><i class="ref"></i>{E(bench)}</span>' if chart.get("benchmark") else ""}
<span class="muted">rebased to 100, price return, weekly points</span></div>
<div class="chart" data-series='{E(data)}' data-left="{L}" data-right="{R}"><svg viewBox="0 0 {W} {H}" role="img"
aria-label="{E(ticker)} price versus {E(bench)}, rebased to 100">{"".join(ticks)}{"".join(xt)}{bpath}
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
        f'<td class="num">{pct(v["excess"], 1, True)}</td></tr>'
        if v
        else f'<tr><td>{k}</td><td class="num muted" colspan=3>not enough history</td></tr>'
        for k, v in ((k, h["returns"].get(k)) for k in ("1m", "3m", "6m", "1y", "3y", "5y"))
    )
    dd = h["drawdowns"]
    comp_rows = "".join(
        f'<tr><td>{E(cp.title)}{" (critical)" if cp.critical else ""}</td><td class="num">{cp.weight:.0%}</td>'
        f'<td class="num">{"missing" if c["components"].get(cp.key) is None else round(c["components"][cp.key] * 100)}</td>'
        f'<td><div class="bar"><span style="width:{(c["components"].get(cp.key) or 0) * 100:.0f}%"></span></div></td>'
        f'<td class="small">'
        + "; ".join(
            f'<abbr title="{E(spec.METRIC_NOTES.get(mk, ""))}">{E(mk.replace("_", " "))}</abbr> = {E(metric(mk, m.get(mk)))}'
            f"{' (missing, scored 0)' if mk in c['missing'] else ''}"
            for mk in cp.metrics
        )
        + "</td></tr>"
        for cp in profile_of(snap["bands"][c["band"]])
    )
    fund = c["fundamentals"]

    def frow(label, key):
        return (
            f"<tr><td>{label}</td>"
            + "".join(  # noqa: E731
                f'<td class="num">{num((v or 0) / 1e6, 0) if v is not None else "n/a"}</td>' for v in fund[key]
            )
            + "</tr>"
        )

    fhead = "".join(
        f'<th class="num">{E(q)}{"*" if d else ""}</th>'
        for q, d in zip(fund["quarters"], fund["derived_revenue"], strict=False)
    )
    scen_html = f'<p class="muted">{E(c.get("scenario_note") or "")}</p>'
    if c.get("scenarios"):
        sc = c["scenarios"]
        years = sorted(int(y) for y in sc["base"]["years"])
        rows = ""
        for key in ("bear", "base", "bull"):
            s = sc[key]
            a = s["assumptions"]
            cells = "".join(
                f'<td class="num">{money(s["years"][str(y)]["value_per_share"])}<div class="small muted">'
                f"{num(s['years'][str(y)]['multiple_of_price'], 2)}x · {pct(s['years'][str(y)]['annualized'], 0, True)}/yr</div></td>"
                for y in years
            )
            rows += (
                f'<tr><td><strong>{key}</strong></td>{cells}<td class="small">start growth {pct(a["starting_revenue_growth"])}'
                f", fading to {pct(spec.SCENARIO_TERMINAL_GROWTH)}; exit EV/Sales {num(a['exit_ev_to_sales'], 1)}x; "
                f"dilution {pct(a['annual_dilution'], 1)}/yr; FCF margin {pct(a['fcf_margin_start'])} &rarr; "
                f"{pct(a.get('fcf_margin_end', a.get('fcf_margin_year5')))} by year {years[-1]}; {net_position(-a['net_cash_held'] if _ok(a.get('net_cash_held')) else None, False)} held flat</td></tr>"
            )
        yh = "".join(f'<th class="num">{y} year{"s" if y > 1 else ""}</th>' for y in years)
        scen_html = f"""<div class="table-wrap"><table aria-label="Bear, base and bull scenario values"><thead><tr><th>Scenario</th>{yh}<th>Assumptions</th></tr></thead>
<tbody>{rows}</tbody></table></div>
{scenario_flags_html(c, snap["bands"][c["band"]])}
{summary_details(SUMMARIES["multibagger"], spec.MULTIBAGGER_DEFINITION)}
{summary_details(SUMMARIES["scenario_method"], spec.SCENARIO_METHOD, "How the scenarios are built")}"""
    earn = c.get("next_earnings")
    flags = "".join(f'<span class="pill">{E(f)}</span>' for f in c["flags"]) or '<span class="muted">none</span>'
    ns = "".join(f"<li><strong>{E(k.replace('_', ' '))}:</strong> {E(v)}</li>" for k, v in c["not_scored"].items())
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
<h2>Key business risks</h2><ul class="tight">{"".join(f"<li>{E(r)}</li>" for r in c["risks"])}</ul>
<h2>What would invalidate the thesis</h2><ul class="tight">{"".join(f"<li>{E(r)}</li>" for r in c["invalidation"])}</ul>"""


def _earnings_check(c: dict) -> str:
    ec = c.get("earnings_check") or {}
    if ec.get("last_results"):
        tail = f" · {E(ec['cadence_check'])}" if ec.get("cadence_check") else ""
        return f'<div class="small">last results {E(ec["last_results"])}: <strong>verified (8-K)</strong>{tail}</div>'
    if ec.get("last_results_status"):
        return f'<div class="small muted">{E(ec["last_results_status"])}</div>'
    return ""
