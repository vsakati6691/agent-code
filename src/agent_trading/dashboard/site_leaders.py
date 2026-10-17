"""Server-rendered Leaders 2030 comparison and linked evidence pages."""

from __future__ import annotations

from collections import defaultdict
from html import escape as E

from . import spec
from .evidence import quality_level
from .fmt import cap, money, num, ok, sval
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


def methodology() -> str:
    return (
        f"<section><h2>How these ranks are computed and what they are not</h2><p>{E(spec.LEADERS_RULE)}</p>"
        f"<p>{E(spec.LEADERS_SHARE_RULE)}</p><p>Scenario source: registered revenue × EV/Sales company model, "
        f"version {E(spec.SPEC_VERSION)}, through 2030-12-31. Existing scenario math is unchanged. "
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
        f"<td>{num(row['scenario_2030'][case + '_shares'], 0)}</td><td>{cap(row['scenario_2030'][case + '_cap'])}</td></tr>"
        for case in ("bear", "base", "bull")
    )
    return (
        f'<h1>{E(row["company_name"])} · Leaders evidence</h1><p><a href="../leaders.html">Back to Leaders 2030</a></p>'
        f"<p>{E(row['scenario_basis'])} · snapshot {E(row['snapshot_id'])} · evidence {E(row['evidence_grade'])}.</p>"
        f"<p>Sector: {E(row['sector'])}. {quality_badge(quality_level(row['evidence_grade']), row['evidence_grade'], len(row['missing_inputs']))}</p>"
        f"<p>Price date: {E(row['price_date'] or 'unavailable')}; current cap date: {E(row['market_cap_date'] or 'unavailable')}.</p>"
        f"<p>{E(price_note)}</p>"
        f"<p>{E(row['shares_assumption'])}</p><p>Share basis: {E(row['shares_basis'] or 'not applicable')}; "
        f"{num(row['shares_outstanding'], 0)} shares, dated {E(row['shares_date'] or 'unavailable')}.</p>"
        f"{source_text}<p>{E(row['notes'])}</p><h2>Dated growth evidence</h2><ul>{drivers}</ul>"
        '<div class="table-wrap"><table><caption>Conditional 2030 scenarios</caption><thead><tr><th>Case</th><th>Price</th><th>Projected shares</th><th>Market cap</th></tr></thead>'
        f"<tbody>{scenario_rows}</tbody></table></div>"
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
    if payload["partial"]:
        out.append(
            f'<p class="small warn">Ranks among {payload["current_cap_count"]} of {payload["universe_count"]} members with data; '
            f"{payload['computed_count']} have 2030 scenarios. Missing members can change every rank.</p>"
        )
    sectors = sorted({r["sector"] for r in entries})
    out.append(
        '<div class="controls"><input type="search" data-search="t-leaders" placeholder="Search ticker, name, reason" aria-label="Search Leaders">'
        + filter_select("t-leaders", "sector", "All sectors", [(s, s) for s in sectors])
        + filter_select("t-leaders", "movement", "All movements", [(k, v[1]) for k, v in MOVEMENTS.items()])
        + filter_select("t-leaders", "kind", "Computed and curated", [("computed", "Computed"), ("curated", "Curated")])
        + filter_select("t-leaders", "pinned", "All tickers", [("yes", "Pinned")])
        + '<button class="action" type="button" data-reset="t-leaders">Reset filters</button><span class="small muted" data-count="t-leaders" aria-live="polite"></span></div>'
    )
    out.append(
        '<div class="table-wrap"><table id="t-leaders" data-table><caption>Current and conditional 2030 size ranks within available stored inputs</caption><thead><tr>'
        + "".join(
            f"<th{attrs}>{label}</th>"
            for label, attrs in [
                ("Rank", ' data-sort="num"'),
                ("Ticker / name", ' class="tk" data-sort="text"'),
                ("Current market cap", ' class="num" data-sort="num"'),
                ("2030 base cap (bear–bull)", ' class="num" data-sort="num"'),
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
        span = (
            f'<div class="small muted">{cap(sc["bear_cap"])} – {cap(sc["bull_cap"])}</div>'
            if not curated and ok(sc["base_cap"])
            else ""
        )
        reason = E(row["unavailable_reason"] or "No value in this stored comparison")
        pin = pin_button(row["ticker"]) if row["ticker"] else ""
        delta = f"{row['rank_delta']:+d}" if row["rank_delta"] is not None else "—"
        out.append(
            f'<tr data-ticker="{E(row["ticker"] or "")}" data-sector="{E(row["sector"])}" data-movement="{row["movement"]}" data-kind="{"curated" if curated else "computed"}">'
            f'<td data-v="{sval(row["current_rank"])}">{num(row["current_rank"], 0) if ok(row["current_rank"]) else "—"}</td>'
            f'<td class="tk" data-v="{E(row["ticker"] or row["company_name"])}">{pin}<strong>{E(row["ticker"] or "Private / pre-IPO")}</strong><div class="small muted">{E(row["company_name"])}</div><a class="small" href="{E(path)}">Details</a></td>'
            f'<td class="num" data-v="{sval(row["current_market_cap_usd"])}" title="{reason if not ok(row["current_market_cap_usd"]) else "Dated close × diluted shares; see Details"}">{cap(row["current_market_cap_usd"]) if ok(row["current_market_cap_usd"]) else "—"}</td>'
            f'<td class="num" data-v="{sval(sc["base_cap"])}" title="{reason if not ok(sc["base_cap"]) else "Conditional, not a prediction"}">{cap(sc["base_cap"]) if ok(sc["base_cap"]) else "—"}{span}</td>'
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
            + "</ul></details>"
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
