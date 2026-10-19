"""Server-rendered Leaders 2030 comparison and linked evidence pages."""

from __future__ import annotations

from collections import defaultdict
from html import escape as E

from . import spec
from .evidence import quality_level
from .fmt import cap, money, num, ok, pct, sval
from .site_list_common import filter_select
from .site_research import quality_badge
from .site_scan import pin_button

MOVEMENTS = {
    "stays_in_top_20": ("•", "stays in top 20", "neutral"),
    "rises_into_top_20": ("↑", "rises into top 20", "positive"),
    "drops_out_of_top_20": ("↓", "drops out of top 20", "negative"),
    "curated_challenger": ("◆", "curated challenger", "neutral"),
    "unavailable": ("—", "unavailable", "neutral"),
}


def cap_range(row: dict) -> str:
    sc = row["scenario_2030"]
    values = [sc[f"{case}_cap"] for case in ("bear", "base", "bull")]
    current = row["current_market_cap_usd"]
    if not all(ok(v) for v in [current, *values]):
        return ""
    lo, hi = min(current, *values), max(current, *values)

    def x(v):
        return 6 + 108 * (v - lo) / (hi - lo) if hi > lo else 60

    label = f"Bear {cap(values[0])}, base {cap(values[1])}, bull {cap(values[2])}; tick is current {cap(current)}. Row scale."
    return (
        f'<svg class="upside-range" viewBox="0 0 120 22" width="120" height="22" role="img" aria-label="{E(label)}"><title>{E(label)}</title>'
        f'<line class="upside-span" x1="{x(values[0]):.2f}" x2="{x(values[2]):.2f}" y1="11" y2="11"/>'
        f'<line class="upside-zero" x1="{x(current):.2f}" x2="{x(current):.2f}" y1="3" y2="19"/>'
        f'<circle class="upside-base" cx="{x(values[1]):.2f}" cy="11" r="4"/></svg>'
    )


def also(row: dict) -> str:
    others = row.get("other_share_classes") or []
    return f" · also listed as {E(', '.join(others))}" if others else ""


def methodology() -> str:
    return (
        f"<section><h2>How these ranks are computed and what they are not</h2><p>{E(spec.LEADERS_RULE)}</p>"
        f"<p>{E(spec.LEADERS_SHARE_RULE)}</p><p>{E(spec.LEADERS_SHARE_CHECKS['rule'])}</p>"
        f"<p>{E(spec.LEADERS_SCENARIO_RULES['growth_basis'])}</p>"
        f"<p>{E(spec.LEADERS_SCENARIO_RULES['method'])}</p><p>Scenario source: Leaders model "
        f"version {E(spec.SPEC_VERSION)}, through 2030-12-31. "
        "Growth drivers are dated reported figures and issuer excerpts. They do not establish future growth.</p></section>"
    )


def detail(row: dict, price_note: str = "") -> str:
    drivers = (
        "".join(f"<li>{E(text)}</li>" for text in row["growth_drivers"]) or "<li>No dated growth evidence stored.</li>"
    )
    gaps = (
        "".join(f"<li>{E(text)}</li>" for text in row["missing_inputs"])
        or "<li>No missing required inputs recorded.</li>"
    )
    source = row.get("assumption_source")
    source_text = f"<p>Owner assumption source: {E(source)} · {E(row['assumption_date'])}.</p>" if source else ""
    scenario_rows = "".join(
        f"<tr><td>{case.title()}</td><td>{money(row['scenario_2030'][case + '_price'])}</td>"
        f"<td>{num(row['scenario_2030'][case + '_shares'], 0)}</td><td>{cap(row['scenario_2030'][case + '_cap'])}</td>"
        f"<td>{pct(row['scenario_2030'][case + '_implied_cagr'], 2) if ok(row['scenario_2030'][case + '_implied_cagr']) else '—'}</td></tr>"
        for case in ("bear", "base", "bull")
    )
    assumptions = []
    for case, values in row["scenario_assumptions"].items():
        path = " → ".join(pct(g, 1) for g in values["growth_path"])
        assumptions.append(
            f"<li><strong>{case.title()}</strong>: {E(values['growth_basis'])} {pct(values['observed_revenue_cagr_3y'], 1)}; "
            f"revenue growth by year {path} (final year prorated); fade {pct(values['fade'], 0)} toward "
            f"{pct(values['terminal_growth'], 0)}. Revenue 2030 {cap(values['revenue_2030'])}; exit EV/Sales "
            f"{num(values['exit_ev_to_sales'], 2)}; net cash {cap(values['net_cash_held'])}; dilution "
            f"{pct(values['annual_dilution'], 1)}/yr. Raw cap {cap(values['unconstrained_cap'])}; "
            f"explicit bear stress reduction {cap(values['bear_stress_adjustment'])}.</li>"
        )
    aggressive = (
        '<p class="warn">Base: aggressive assumption (above 25%/yr implied cap growth).</p>'
        if row["aggressive_assumption"]
        else ""
    )
    return (
        f'<h1>{E(row["company_name"])} · Leaders evidence</h1><p><a href="../leaders.html">Back to Leaders 2030</a></p>'
        + (
            f"<p>Ranked once for the company; other listed classes: {E(', '.join(row['other_share_classes']))}.</p>"
            if row.get("other_share_classes")
            else ""
        )
        + f"<p>{E(row['scenario_basis'])} · snapshot {E(row['snapshot_id'])} · evidence {E(row['evidence_grade'])}.</p>"
        f"<p>Sector: {E(row['sector'])}. {quality_badge(quality_level(row['evidence_grade']), row['evidence_grade'], len(row['missing_inputs']))}</p>"
        f"<p>Price date: {E(row['price_date'] or 'unavailable')}; current cap date: {E(row['market_cap_date'] or 'unavailable')}.</p>"
        f"<p>{E(price_note)}</p>"
        f"<p>{E(row['shares_assumption'])}</p><p>Share basis: {E(row['shares_basis'] or 'not applicable')}; "
        f"{num(row['shares_outstanding'], 0)} shares, dated {E(row['shares_date'] or 'unavailable')}.</p>"
        f"{source_text}<p>{E(row['notes'])}</p><h2>Dated growth evidence</h2><ul>{drivers}</ul>"
        f"<p>Current market cap: {cap(row['current_market_cap_usd'])}. Implied %/yr is market-cap CAGR, "
        "not price return; dilution can make these differ. Curated caps without a current value have no implied rate.</p>"
        f"{aggressive}"
        '<div class="table-wrap"><table><caption>Conditional 2030 scenarios</caption><thead><tr><th>Case</th><th>Price</th><th>Projected shares</th><th>Market cap</th><th>Implied %/yr</th></tr></thead>'
        f"<tbody>{scenario_rows}</tbody></table></div>"
        f"<h2>Scenario inputs and stress constraints</h2><ul>{''.join(assumptions)}</ul>"
        "<p>Bear caps are constrained to at most 90% of today's cap; any reduction above is an explicit downside stress, "
        "not a calibrated outcome. Registered cyclical names start with at least a 20% revenue decline.</p>"
        f"<h2>Missing inputs</h2><ul>{gaps}</ul><p>{E(row['unavailable_reason'] or '')}</p>"
    )


def leaders_page(payload: dict, details: dict[str, str], price_note: str = "") -> str:
    entries = payload["entries"]
    gaps = list(payload["gaps"])
    out = ["<h1>Leaders 2030</h1><p>Current top 20, conditional 2030 entrants and curated challengers.</p>"]
    if not payload["computed_count"]:
        out.append(
            '<p class="banner warn">No S&P 500 2030 scenarios can be computed from this stored snapshot; a future weekly collection must retain the missing inputs.</p>'
        )
    companies = payload.get("company_count", payload["universe_count"])
    classes = payload.get("share_classes") or []
    if payload["partial"]:
        merged = (
            f" ({payload['universe_count']} index tickers; {len(classes)} extra share classes ranked with their company)"
            if classes
            else ""
        )
        out.append(
            f'<p class="small warn">Ranks among {payload["current_cap_count"]} of {companies} companies with data{merged}; '
            f"{payload['computed_count']} have 2030 scenarios. Missing members can change every rank.</p>"
        )
    unranked = defaultdict(list)
    for gap in gaps:
        if not gap.get("ranked", True):
            unranked[gap.get("kind") or "other inputs"].append(gap["ticker"])
    if unranked:
        out.append(
            '<p class="small warn">Not ranked for missing or inconsistent inputs: '
            + "; ".join(f"{E(kind)}: {E(', '.join(tickers))}" for kind, tickers in unranked.items())
            + ". A large company among them would change every rank below it; reasons are listed below the table.</p>"
        )
    sectors = sorted({r["sector"] for r in entries})
    out.append(
        '<div class="controls"><input type="search" data-search="t-leaders" placeholder="Search ticker, name, reason" aria-label="Search Leaders">'
        '<button class="action" type="button" data-reset="t-leaders">Reset filters</button><span class="small muted" data-count="t-leaders" aria-live="polite"></span></div>'
        '<details class="filter-details"><summary>Filter leaders</summary><div class="controls">'
        + filter_select("t-leaders", "sector", "All sectors", [(s, s) for s in sectors])
        + filter_select("t-leaders", "movement", "All movements", [(k, v[1]) for k, v in MOVEMENTS.items()])
        + filter_select("t-leaders", "kind", "Computed and curated", [("computed", "Computed"), ("curated", "Curated")])
        + filter_select("t-leaders", "pinned", "All tickers", [("yes", "Pinned")])
        + "</div></details>"
    )
    out.append(
        '<div class="table-wrap"><table id="t-leaders" data-table><caption>Current and conditional 2030 size ranks within available stored inputs</caption><thead><tr>'
        + "".join(
            f"<th{attrs}>{label}</th>"
            for label, attrs in [
                ("Rank", ' data-sort="num"'),
                ("Ticker / name", ' class="tk" data-sort="text"'),
                ("Current market cap", ' class="num" data-sort="num"'),
                ("2030 bear cap", ' class="num" data-sort="num"'),
                ("Bear implied %/yr", ' class="num" data-sort="num"'),
                ("2030 base cap", ' class="num" data-sort="num"'),
                ("Base implied %/yr", ' class="num" data-sort="num"'),
                ("2030 bull cap", ' class="num" data-sort="num"'),
                ("Bull implied %/yr", ' class="num" data-sort="num"'),
                ("2030 rank", ' data-sort="num"'),
                ("Change", ' data-sort="num"'),
            ]
        )
        + "</tr></thead><tbody>"
    )
    for i, row in enumerate(entries):
        sc = row["scenario_2030"]
        symbol, label, color = MOVEMENTS[row["movement"]]
        curated = row["scenario_basis"] == "curated assumption"
        path = f"leaders/{payload['as_of']}-{i}.html"
        details[path] = detail(row, price_note)
        reason = E(row["unavailable_reason"] or "No value in this stored comparison")
        scenario_cells = []
        for case in ("bear", "base", "bull"):
            value, rate = sc[f"{case}_cap"], sc[f"{case}_implied_cagr"]
            flag = (
                '<div class="small warn">aggressive assumption</div>'
                if case == "base" and row["aggressive_assumption"]
                else ""
            )
            rate_reason = (
                "Market-cap CAGR through 2030-12-31; excludes distributions and differs from price return"
                if ok(rate)
                else "No current cap for this curated assumption"
                if curated
                else reason
            )
            scenario_cells.append(
                f'<td class="num" data-v="{sval(value)}" title="{reason if not ok(value) else "Conditional, not a prediction"}">{cap(value) if ok(value) else "—"}{cap_range(row) if case == "base" else ""}</td>'
                f'<td class="num" data-v="{sval(rate)}" title="{rate_reason}">{pct(rate, 2) if ok(rate) else "—"}{flag}</td>'
            )
        pin = pin_button(row["ticker"]) if row["ticker"] else ""
        delta = f"{row['rank_delta']:+d}" if row["rank_delta"] is not None else "—"
        out.append(
            f'<tr data-ticker="{E(row["ticker"] or "")}" data-sector="{E(row["sector"])}" data-movement="{row["movement"]}" data-kind="{"curated" if curated else "computed"}">'
            f'<td data-v="{sval(row["current_rank"])}">{num(row["current_rank"], 0) if ok(row["current_rank"]) else "—"}</td>'
            f'<td class="tk" data-v="{E(row["ticker"] or row["company_name"])}">{pin}<strong>{E(row["ticker"] or "Private / pre-IPO")}</strong><div class="small muted">{E(row["company_name"])}{also(row)}</div><a class="small" href="{E(path)}">Details</a></td>'
            f'<td class="num" data-v="{sval(row["current_market_cap_usd"])}" title="{reason if not ok(row["current_market_cap_usd"]) else "Dated close × diluted shares; see Details"}">{cap(row["current_market_cap_usd"]) if ok(row["current_market_cap_usd"]) else "—"}</td>'
            f"{''.join(scenario_cells)}"
            f'<td data-v="{sval(row["rank_2030"])}" title="{reason if not ok(row["rank_2030"]) else "Conditional base cap rank"}">{num(row["rank_2030"], 0) if ok(row["rank_2030"]) else "—"}</td>'
            f'<td data-v="{sval(row["rank_delta"])}"><span class="{color}">{delta}</span><div class="small {color}">{symbol} {E(label)}</div></td></tr>'
        )
    out.append(
        '</tbody></table></div><p data-empty="t-leaders" hidden>No rows match these filters.</p><p class="small muted" data-pin-status>Pins are saved only on this device. Private companies without tickers cannot be pinned.</p>'
    )
    grouped = defaultdict(list)
    for gap in gaps:
        grouped[gap["reason"]].append(gap["ticker"])
    if grouped:
        out.append(
            '<details><summary>Members without sufficient stored inputs</summary><ul class="small">'
            + "".join(
                f"<li><strong>{E(', '.join(tickers))}</strong>: {E(reason)}</li>" for reason, tickers in grouped.items()
            )
            + '</ul><p class="small muted">Stale-statement reasons reflect SEC company-facts data as collected; '
            "it can lag a filing that SEC's filing index already lists. Nothing is filled in by hand.</p></details>"
        )
    if classes:
        out.append(
            '<p class="small muted">One row per company: '
            + "; ".join(f"{E(c['ticker'])} is counted with {E(c['ranked_as'])}" for c in classes)
            + " (same SEC registrant; only the most liquid class has a row).</p>"
        )
    out.append(
        f'<p><a class="action" href="downloads/{E(payload["as_of"])}_leaders_2030.csv" download>Download Leaders CSV ↓</a> · '
        f'<a href="data/{E(payload["as_of"])}_leaders_2030.json">Derived data and coverage</a></p>'
    )
    out.append(
        "<details><summary>Coverage, assumptions and methodology</summary>"
        f"<p>Stored snapshot: {E(payload['as_of'])} (methodology {E(payload.get('snapshot_methodology_version') or 'unavailable')}). "
        f"Derived comparison: {E(payload['methodology_version'])}. Original snapshot methodology is preserved. "
        "Ranks cover available stored inputs; full-index top-20 membership is not established while coverage is partial.</p>"
        + ("<p>No curated challengers registered.</p>" if not payload["registered_challengers"] else "")
        + (f"<p>{E('; '.join(payload['omitted_challengers']))}</p>" if payload["omitted_challengers"] else "")
        + "<ul>"
        + "".join(f"<li>{E(label)}: {payload['counts'].get(key, 0)}</li>" for key, (_, label, _) in MOVEMENTS.items())
        + "</ul>"
        + methodology()
        + "</details>"
    )
    return "".join(out)
