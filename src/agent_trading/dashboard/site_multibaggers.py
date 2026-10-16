"""Speculative multibagger cards and conditional scenario flags."""

from __future__ import annotations

from . import spec
from .fmt import SUMMARIES, cap, money, num, pct, summary_details
from .scenarios import implied_growth_text
from .site_exclusions import excluded_summary
from .site_list_common import E, definition_line
from .site_scan import pin_button


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
    return (
        f"In the bull case revenue grows from {cap(rev0)} to about {cap(y['revenue'])} ({pct(cagr)} a year for "
        f"{last} years), EV/Sales holds at about {num(a.get('exit_ev_to_sales'), 1)}x and dilution stays near "
        f"{pct(a.get('annual_dilution'), 1)} a year. Under those assumptions the bull case {verdict}. All of it "
        "would have to happen together; none of it is forecast."
    )


def scenario_flags_html(c: dict, band: dict | None = None) -> str:
    """Passing the research screen and passing each scenario test are different things; show both, apart."""
    sc = c.get("scenarios") or {}
    fl = sc.get("flags") or {}
    gates = (band or {}).get("gates") or []
    screen = (
        f"passed: ranked #{c.get('rank')} with every eligibility gate met"
        if gates
        else f"passed: ranked #{c.get('rank')} (liquidity, data and tradability rules met)"
    )

    def cell(key, label):
        if key not in fl:
            return f'<li>{E(label)}: <span class="pill muted">not tested</span></li>'
        return f'<li>{E(label)}: <span class="pill {"ok" if fl[key] else "muted"}">{"yes" if fl[key] else "no"}</span></li>'

    tests = (
        cell("bull_doubles_in_5y", "2x in 5 years (bull case)")
        + cell("bull_multibagger_5y", "5x in 5 years (bull case)")
        + cell("bull_5x_in_10y", "5x in 10 years (bull case)")
        + cell("base_2x_in_10y", "2x in 10 years (base case)")
    )
    note = "" if sc else ' <span class="muted">Scenarios were not computed, so every test reads "not tested".</span>'
    return (
        f'<div class="flags small"><p><strong>Research screen:</strong> {E(screen)}. Passing the screen is separate from '
        f"the scenario tests below.</p><p><strong>Scenario tests</strong> (conditional on the stated assumptions; not "
        f'forecasts, targets or probabilities):{note}</p><ul class="tight">{tests}</ul></div>'
    )


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
                rows += (
                    f"<tr><td>{k}</td>"
                    + "".join(
                        f'<td class="num">{money(sc[k]["years"][str(y)]["value_per_share"])}<div class="small muted">'
                        f"{num(sc[k]['years'][str(y)]['multiple_of_price'], 1)}x</div></td>"
                        for y in yrs
                    )
                    + "</tr>"
                )
            scen = f'<div class="table-wrap"><table aria-label="Bear, base and bull values per share"><thead><tr><th>Scenario</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
        else:
            scen = f'<p class="small muted">{E(c.get("scenario_note") or "Scenarios not computed.")}</p>'
        runway = m.get("cash_runway_years")
        cash_txt = (
            f"FCF {cap(m.get('fcf_ttm'))} (margin {pct(m.get('fcf_margin'))})"
            if (m.get("fcf_ttm") or 0) > 0
            else f"cash burn; runway about {num(runway, 1)} years"
            if runway is not None
            else "cash flow n/a"
        )
        inval = "".join(f"<li>{E(x)}</li>" for x in c.get("invalidation", [])[:4])
        cards.append(f"""<article class="card mb"><header><span class="rank">#{c["rank"]}</span>
{pin_button(c["ticker"])}<a href="stock/multibagger-{E(c["ticker"])}.html"><strong>{E(c["ticker"])}</strong></a> {E(c.get("name") or "")}
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
{f'<div class="banner info small">{E(b["shortfall_note"])}</div>' if b.get("shortfall_note") else ""}
<div class="mb-list">{"".join(cards) or '<p class="muted">No stock passed every gate this week.</p>'}</div>
{excluded_summary("multibagger", b)}"""
