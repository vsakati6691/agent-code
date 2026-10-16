"""Shared list titles, ordering and explanatory definitions."""

from __future__ import annotations

import html

from . import spec
from .fmt import cap

E = html.escape


GROWTH_KEYS = ("large", "mid", "small")


ORDER = ("large", "mid", "small", "multibagger", "ai_large", "ai_mid")


def ordered(bands: dict) -> list[str]:
    """Display order: the growth lists, the multibagger list, then any retired list from an old snapshot."""
    return [k for k in ORDER if k in bands] + sorted(k for k in bands if k not in ORDER)


TIME_GUIDE = (
    "Four different time frames appear on this site and are never mixed: trailing historical returns (what "
    "already happened), conditional forward scenarios (1-10 years, or to 2030 for the watchlist), option expiry "
    "horizons (3, 6 and 12 months), and tracking periods (1-12 months after each weekly snapshot)."
)


def band_title(key: str, band: dict) -> str:
    return (
        band.get("short_title")
        or spec.BAND_TITLES_SHORT.get(key)
        or spec.LEGACY_BANDS.get(key, {}).get("title")
        or band.get("title", key)
    )


def list_page(key: str) -> str:
    if key.startswith("ai_"):
        return "ai.html"
    return "multibaggers.html" if key == "multibagger" else "growth.html"


def definition_line(key: str, band: dict) -> str:
    d = band.get("definition") or {}
    if key == "large" or d.get("universe") == "sp500":
        return (
            "Universe: current S&P 500 members only. This is not the whole large-cap market; large companies "
            "outside the index are not screened here."
        )
    lo, hi = d.get("min_cap"), d.get("max_cap")
    rng = f"{cap(lo) if lo else 'any'} to {cap(hi) if hi else 'any'}"
    uni = (
        "S&P 500 plus the broad US-listed universe"
        if d.get("universe") == "all"
        else "US-listed common stocks on NYSE, Nasdaq, NYSE American, NYSE Arca and Cboe BZX (excluding OTC)"
    )
    extra = (
        f"; price ≥ ${d['min_price']:g}; 20-day median dollar volume ≥ {cap(d['min_dollar_volume'])}"
        if d.get("min_price")
        else ""
    )
    return f"Universe: {uni}; market cap {rng}{extra}. Market cap = as-of close x SEC cover-page shares."
