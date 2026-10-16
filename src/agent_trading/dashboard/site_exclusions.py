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


def excluded_summary(key: str, band: dict) -> str:
    n = len(band.get("excluded", []))
    if not n:
        return '<p class="small muted">No stock was excluded.</p>'
    top = "; ".join(f"{E(r)} ({len(t)})" for r, t in group_exclusions(band["excluded"])[:3])
    return (
        f'<p class="small"><a href="excluded-{E(key)}.html">{n:,} excluded or not ranked: see every stock and '
        f'reason →</a><br><span class="muted">Most common: {top}</span></p>'
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
        f"{blocks or '<p class=muted>No stock was excluded.</p>'}"
    )
