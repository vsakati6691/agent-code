"""Group and display the recorded reasons candidates were excluded."""

from __future__ import annotations

import re

from .site_list_common import E, band_title, list_page

NUMBER = re.compile(r"\$?-?\d+(?:[,.]\d+)*(?:[%BMKx](?![A-Za-z]))?")


NOT_CHECKED = "not checked for Robinhood tradability (only stocks that would make the list are checked)"


REASON_RULES = (
    (re.compile(r"^Robinhood tradability not yet verified$"), lambda m: (NOT_CHECKED, "")),
    (
        re.compile(r"^too little evidence: (\d+ of \d+) sub-metrics missing$"),
        lambda m: ("too little evidence (too many sub-metrics missing)", m[1]),
    ),
    (
        re.compile(r"^gate failed: (.+?) (\S+) \(needs (>=|<=) (.+)\)$"),
        lambda m: (f"gate failed: {m[1]} {'below' if m[3] == '>=' else 'above'} {m[4]}", m[2]),
    ),
    (
        re.compile(r"^illiquid: (20-day median dollar volume) (\S+) < (\S+)$"),
        lambda m: (f"illiquid: {m[1]} below {m[3]}", m[2]),
    ),
    (re.compile(r"^market cap (\S+) outside the band$"), lambda m: ("market cap outside the band", m[1])),
    (re.compile(r"^price (\S+) below (\S+)$"), lambda m: (f"price below ${m[2]}", f"${m[1]}")),
    (re.compile(r"^revenue growth (\S+) below the (.+)$"), lambda m: (f"revenue growth below the {m[2]}", m[1])),
    (
        re.compile(r"^price data rejected: [^:]+: only (\d+) bars, need (\d+)$"),
        lambda m: (f"price data rejected: too little price history (needs {m[2]} daily bars)", f"{m[1]} bars"),
    ),
    (
        re.compile(
            r"^price data rejected: [^:]+: recent data anomaly \(frozen bars (\S+) to (\S+)\); feed unreliable$"
        ),
        lambda m: ("price data rejected: recent data anomaly (frozen bars); feed unreliable", f"{m[1]} to {m[2]}"),
    ),
    (
        re.compile(r"^price data rejected: [^:]+: recent data anomaly \((.+) on (\S+)\); feed unreliable$"),
        lambda m: (f"price data rejected: recent data anomaly ({m[1]}); feed unreliable", m[2]),
    ),
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


TRADABILITY = re.compile(r"tradab", re.I)  # the fail-closed tradability gate, applied to scored stocks only


def funnel(band: dict) -> dict:
    """Stored screening counts for one list: evaluated, ranked, published and the tradability gate's share.

    The gate runs after scoring (pipeline_score.tradable_only), so ranked + gate exclusions is the pool that passed
    every other rule. Older snapshots without the counts return None for them."""
    excluded = band.get("excluded", [])
    gate = sum(1 for x in excluded if TRADABILITY.search(str(x.get("reason", ""))))
    ranked = band.get("ranked")
    return {
        "evaluated": band.get("evaluated"),
        "ranked": ranked,
        "published": len(band.get("candidates", [])),
        "max_results": band.get("max_results"),
        "excluded": len(excluded),
        "tradability_excluded": gate,
        "passed_other_rules": ranked + gate if isinstance(ranked, int) else None,
    }


def _funnel_line(band: dict) -> str:
    f = funnel(band)
    if f["evaluated"] is None or f["ranked"] is None:
        return ""
    text = (
        f"Screening funnel: {f['evaluated']:,} evaluated → {f['ranked']:,} ranked → {f['published']} published"
        + (f" (up to {f['max_results']})" if f["max_results"] else "")
        + "."
    )
    if f["tradability_excluded"] and f["passed_other_rules"]:
        share = f["tradability_excluded"] / f["passed_other_rules"]
        text += (
            f" Tradability check: {f['tradability_excluded']:,} of the {f['passed_other_rules']:,} scored stocks that "
            f"passed every other rule ({share:.0%}) were left out (unverified, stale or not tradable), so only "
            f"{f['ranked']:,} could be ranked."
        )
    return f'<span class="funnel">{E(text)}</span><br>'


def score_breakdown(band: dict) -> str:
    """Raw score, sector deduction and final score for each published pick, when the snapshot recorded them."""
    rows = band.get("candidates", [])
    if not rows or not all(c.get("raw_composite") is not None and "sector_penalty" in c for c in rows):
        return ""
    if not any((c.get("sector_penalty") or 0) > 0 for c in rows):
        return '<p class="small muted">No published pick received a sector deduction; ranks follow the raw score.</p>'
    body = "".join(
        f'<tr><td class="num">{c["rank"]}</td><td>{E(c["ticker"])}</td><td>{E(c.get("sector") or "Unknown")}</td>'
        f'<td class="num">{c["raw_composite"]:.1f}</td><td class="num">{-(c["sector_penalty"] or 0):.1f}</td>'
        f'<td class="num">{(c.get("composite") or 0):.1f}</td></tr>'
        for c in rows
    )
    return (
        '<details class="small"><summary>Why the order changed: raw score, sector deduction, final score</summary>'
        '<div class="table-wrap"><table aria-label="Score breakdown"><thead><tr><th class="num">#</th><th>Ticker</th>'
        '<th>Sector</th><th class="num">Raw</th><th class="num">Sector deduction</th><th class="num">Final</th></tr>'
        f"</thead><tbody>{body}</tbody></table></div><p>Ranks follow the final score. The registered sector deduction "
        "applies before selection; see the methodology page.</p></details>"
    )


def excluded_summary(key: str, band: dict) -> str:
    n = len(band.get("excluded", []))
    breakdown = score_breakdown(band)
    if not n:
        return f'<p class="small">{_funnel_line(band)}<span class="muted">No stock was excluded.</span></p>{breakdown}'
    top = "; ".join(f"{E(r)} ({len(t)})" for r, t in group_exclusions(band["excluded"])[:3])
    return (
        f'<p class="small">{_funnel_line(band)}<a href="excluded-{E(key)}.html">{n:,} excluded or not ranked: see '
        f'every stock and reason →</a><br><span class="muted">Most common: {top}</span></p>{breakdown}'
    )


def excluded_page(key: str, band: dict) -> str:
    groups = group_exclusions(band.get("excluded", []))
    blocks = "".join(
        f'<details><summary>{E(reason)} <span class="muted">({len(items):,})</span></summary><p class="small">'
        + ", ".join(f"{E(t)}" + (f" ({E(d)})" if d else "") for t, d in items)
        + "</p></details>"
        for reason, items in groups
    )
    return (
        f'<p class="small"><a href="{list_page(key)}#{E(key)}">&larr; back to the list</a></p>'
        f"<h1>Excluded from: {E(band_title(key, band))}</h1>"
        f'<p class="lede">Every stock that was considered for this list but not ranked or not shown, grouped by '
        f"reason. Numbers in brackets are the values that failed the rule.</p>"
        f'<p class="small">{_funnel_line(band)}</p>'
        f"{blocks or '<p class=muted>No stock was excluded.</p>'}"
    )
