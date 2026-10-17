"""Presentation context for AI research; no scoring or registered-rule changes."""

from html import escape as E

from . import spec
from .price_integrity import preclose

UNIVERSE_DESCRIPTION = (
    "A fixed, curated list of US-listed common stocks, grouped by role in the AI supply chain. "
    "Membership is recorded in advance; adding or removing a name requires a new methodology version. "
    "AI exposure is not a measurement of future growth. Foreign filers without US-GAAP XBRL cannot be scored. "
    "Eligible names are ranked within the AI large-cap ($10B+) and mid-cap ($2B–$10B) lists. "
    "The AI lists and Growth Stocks use separate scoring profiles; their weights are not identical."
)


def scoring_note() -> str:
    """Explain the registered profiles without altering the hashed specification text."""
    labels = {
        "growth": "revenue growth",
        "earnings": "earnings",
        "quality": "quality",
        "balance": "balance sheet",
        "valuation": "valuation",
        "momentum": "momentum",
        "relative": "benchmark-relative performance",
    }
    weights = "; ".join(f"{labels[c.key]} {c.weight:.0%}" for c in spec.PROFILES["standard"])
    return (
        f"Current registered AI scoring uses the standard profile: {weights}. "
        "Growth Stocks uses a separate fundamental-growth profile. Compare scores within each list, "
        "rather than treating scores from different profiles as equivalent."
    )


def snapshot_note(snap: dict) -> str:
    basis = "Stored intraday inputs; correction 2026-10-16" if preclose(snap) else "Stored snapshot inputs; delayed"
    return f"Snapshot {snap.get('as_of', 'date unavailable')} · {basis}."


def intro(snap: dict, bands: dict) -> str:
    links = [(key, label) for key, label in (("ai_large", "Large cap"), ("ai_mid", "Mid cap")) if key in bands]
    if any(b.get("candidates") for b in bands.values()):
        links.append(("top20", "Scenario test"))
    links.extend((("universe", "AI universe"), ("private", "Private companies")))
    jumps = "".join(f'<a href="#{key}">{label}</a>' for key, label in links)
    return (
        '<header class="compact-heading"><h1>AI stocks</h1><p>Ranked public companies and conditional size scenarios.</p></header>'
        f'<nav class="section-nav" aria-label="AI page sections">{jumps}</nav>'
    )


def guide(snap: dict, bands: dict) -> str:
    profiles = ", ".join(sorted({str(b.get("profile") or "not recorded") for b in bands.values()}))
    profile_note = f"Stored AI profile: {profiles}. " if bands else ""
    return (
        '<aside class="ai-guide">'
        '<details class="small"><summary>Scoring and scenario limits</summary>'
        f"<p>{E(snapshot_note(snap))}</p><p>{E(profile_note)}{E(scoring_note())}</p><p>{E(spec.AI_PROBABILITY_NOTE)}</p>"
        "<p>This is not a forecast and not advice. Universe membership is a recorded judgement. A high score does not predict that a company will "
        'become one of the largest. <a href="methodology.html#ai">Read the AI methodology</a>.</p></details></aside>'
    )
