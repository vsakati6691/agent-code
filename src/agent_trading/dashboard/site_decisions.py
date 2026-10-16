"""Shared, escaped presentation of the dated growth-research fields."""

from __future__ import annotations

import html
import json

from .decisions import FIELDS, finite
from .fmt import cap, money

E = html.escape
OLD = "Not collected in this snapshot; a new methodology run is required"


def formatted(value, kind: str) -> str:
    if value is None:
        return "n/a"
    if kind == "text":
        return str(value)
    if not finite(value):
        return "n/a"
    if kind == "pct":
        return f"{value:.1%}"
    if kind == "pp":
        return f"{value * 100:+.1f} pp"
    if kind == "money":
        return cap(value) if abs(value) >= 1e6 else money(value)
    if kind == "shares":
        return f"{value:+,.0f} shares"
    return f"{value:,.1f}" + ("×" if kind == "multiple" else "")


def spark(c: dict) -> str:
    values = (c.get("decision_research") or {}).get("spark", [])
    if len(values) < 2:
        return '<span class="small muted">n/a · 1Y price history not collected</span>'
    from .site_overview import sparkline

    sampled = values[:-1:5] + [values[-1]]
    return sparkline(
        list(reversed(sampled)), f"{c['ticker']} one year of closing prices sampled weekly, delayed, not live"
    )


def flattened(c: dict) -> dict:
    research = c.get("decision_research") or {}
    out = {}
    for group, fields in FIELDS.items():
        data = research.get("groups", {}).get(group, {})
        for key, label, kind in fields:
            item = data.get("fields", {}).get(key, {})
            value = item.get("value")
            reason = item.get("reason") or (OLD if not item else "")
            stamp = item.get("as_of") or data.get("as_of") or "n/a"
            peer = item.get("percentile", {})
            peer_text = (
                (
                    f"P{peer['value']:.0f} · {peer.get('n', 0)} in list"
                    if peer.get("value") is not None
                    else "percentile n/a · " + peer.get("reason", "fewer than two available list values")
                )
                if group == "valuation"
                else ""
            )
            value_text = formatted(value, kind)
            arrow = (
                {"accelerating": "↑", "improving": "↑", "stable": "→", "decelerating": "↓", "deteriorating": "↓"}.get(
                    item.get("trend") or value, ""
                )
                if not isinstance(value, list)
                else ""
            )
            out[key] = {
                "v": value,
                "text": f"{arrow} {value_text}".strip(),
                "reason": reason,
                "note": peer_text or item.get("period", ""),
                "as_of": stamp,
                "kind": kind,
                "label": label,
            }
            if group == "valuation":
                out[key + "_percentile"] = {
                    "v": peer.get("value"),
                    "text": formatted(peer.get("value"), "number"),
                    "reason": peer.get("reason", "Percentile not collected") if peer.get("value") is None else "",
                    "note": f"{peer.get('n', 0)} available values in this list; 0–100",
                    "as_of": stamp,
                    "kind": "number",
                    "label": label + " percentile",
                }
    business = research.get("business") or {}
    for key, label in (
        ("description", "Business · 10-K"),
        ("growth", "Why it could keep growing · 10-K"),
        ("risk", "Why it could fail · 10-K"),
    ):
        out["business_" + key] = {
            "v": business.get(key),
            "text": business.get(key) or "n/a",
            "reason": business.get("reason", OLD) if not business.get(key) else "",
            "note": "Issuer excerpt",
            "as_of": business.get("filed") or "n/a",
            "kind": "text",
            "label": label,
        }
    return out


def scanner_payload(snap: dict, keys: list[str]) -> str:
    rows, columns = {}, {}
    for key in keys:
        for c in snap["bands"][key].get("candidates", []):
            flat = flattened(c)
            rows[f"{key}:{c['ticker']}"] = {
                k: [x[n] for n in ("v", "text", "reason", "note", "as_of")] for k, x in flat.items()
            }
            columns.update({k: [x["label"], x["kind"]] for k, x in flat.items()})
    # Inert JSON, with HTML-significant characters escaped even in issuer-provided prose.
    payload = (
        json.dumps({"rows": rows, "columns": columns}, separators=(",", ":"), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("&", "\\u0026")
    )
    return f'<script type="application/json" id="decision-data">{payload}</script>'


def scanner_controls() -> str:
    groups = []
    for group, fields in FIELDS.items():
        options = "".join(f'<option value="{key}">{E(label)}</option>' for key, label, _ in fields)
        groups.append(f'<optgroup label="{group.title()}">{options}</optgroup>')
    groups.append(
        '<optgroup label="Business">'
        + "".join(
            f'<option value="business_{key}">{label}</option>'
            for key, label in (
                ("description", "Business description"),
                ("growth", "Why it could grow"),
                ("risk", "Why it could fail"),
            )
        )
        + "</optgroup>"
    )
    groups.append(
        '<optgroup label="Valuation percentiles">'
        + "".join(
            f'<option value="{key}_percentile">{E(label)} percentile</option>' for key, label, _ in FIELDS["valuation"]
        )
        + "</optgroup>"
    )
    return f"""<div class="decision-controls controls">
<label>Research field<select id="research-field">{"".join(groups)}</select></label>
<label>Minimum<input id="research-min" type="number" step="any" placeholder="No minimum"></label>
<label>Maximum<input id="research-max" type="number" step="any" placeholder="No maximum"></label>
<label>Field contains<input id="research-text" type="search" placeholder="e.g. accelerating"></label>
<label>Field coverage<select id="research-coverage"><option value="">All</option><option value="available">Available</option><option value="missing">n/a only</option></select></label>
</div><p class="small muted" id="research-units">Choose a field to compare. Percent inputs use percentage points (20 means 20%). Missing values sort last.</p>
<div class="pin-sectors card"><strong>Pinned sector concentration</strong><p class="small muted">Equal count of pinned tickers in this scan, not portfolio weights.</p><div id="pin-sector-bar" aria-live="polite">Pin a ticker to see sectors.</div></div>"""


def detail(c: dict) -> str:
    research = c.get("decision_research") or {}
    flat = flattened(c)
    cards = []
    for group, fields in FIELDS.items():
        items = []
        for key, label, _ in fields:
            if key == "insider_net" and flat[key]["v"] is None:
                continue  # the dated Form 4 panel replaces the old unavailable ownership note
            x = flat[key]
            reason = f'<small class="muted">{E(x["reason"])}</small>' if x["reason"] else ""
            items.append(
                f'<div class="research-metric"><dt>{E(label)}</dt><dd>{E(x["text"])}{reason}'
                f'<small class="muted">{E(x["note"])}</small></dd></div>'
            )
        stamp = research.get("groups", {}).get(group, {}).get("as_of") or "n/a · not collected"
        source = research.get("groups", {}).get(group, {}).get("source", "")
        cards.append(
            f'<article class="card"><h3>{group.title()}</h3><p class="small muted">Data as of {E(stamp)} · {E(source)}</p>'
            f"<dl>{''.join(items)}</dl></article>"
        )
    business = research.get("business") or {}
    narrative = "".join(
        f"<div><h3>{label}</h3><p>{E(business.get(key) or 'n/a · ' + business.get('reason', OLD))}</p></div>"
        for key, label in (
            ("description", "Business"),
            ("growth", "Why it could keep growing"),
            ("risk", "Why it could fail"),
        )
    )
    url = business.get("url", "")
    source = (
        f'<a href="{E(url)}">Read the source 10-K</a>'
        if url.startswith("https://www.sec.gov/Archives/edgar/data/")
        else "10-K source n/a"
    )
    return f"""<section class="decision-research"><div class="section-heading"><div><p class="eyebrow">THE DECISION FILE</p><h2>Quality, price &amp; durability</h2></div>{spark(c)}</div>
<p class="small muted">Fundamental quality excludes momentum. Scores are research comparisons, not probabilities.
Valuation percentiles compare available values in this same published list; higher means numerically higher, not better.</p>
<p class="small muted">Prices: {E(research.get("price_as_of") or "n/a")} · delayed, not live. SEC filed through {E(research.get("filing_as_of") or "n/a")}; quarter ended {E(research.get("period_end") or "n/a")}.
Estimates are current observations, not historical forecasts. Margin trends compare TTM with prior TTM.</p>
<p class="small muted">Registered score and scenario panels retain their reported-debt definitions. The decision fields require complete debt inputs and can be n/a when those older inputs are available.</p>
<div class="decision-grid">{"".join(cards)}</div><div class="card business-evidence">{narrative}
<p class="small muted">Issuer excerpts · data as of {E(business.get("filed") or "n/a")} · {source}. These are issuer statements, not independently verified forecasts.</p></div></section>"""
