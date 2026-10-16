"""Shared page shell, navigation, accessibility headers and server-rendered freshness."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..market_calendar import is_trading_day
from . import (
    spec,
)
from .fmt import (
    sval as sval,
)

_SYMBOLS: dict[str, str] = {}  # ticker -> name, for the header search (set by build_site)


_SITE = {"v": ""}  # asset version for cache busting (set by build_site)


E = html.escape


NAV = [
    ("index.html", "Overview"),
    ("growth.html", "Growth Stocks"),
    ("multibaggers.html", "Multibaggers"),
    ("ai.html", "AI stocks"),
    ("options.html", "Options"),
    ("bets.html", "Small bets"),
    ("watchlist.html", "Watchlist 2030"),
    ("goal.html", "Plan 2030"),
    ("evidence.html", "Evidence"),
    ("compare.html", "Compare"),
    ("history.html", "History & tracking"),
    ("methodology.html", "Methodology"),
    ("audit.html", "Audit trail"),
]


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
    nav = "".join(
        f'<a href="{up}{href}"{" aria-current=page" if href == current else ""}>{E(label)}</a>' for href, label in NAV
    )
    opts = "".join(f'<option value="{E(t)}">{E(n)}</option>' for t, n in _SYMBOLS.items())
    search = (
        f'<form class="symsearch" role="search" data-base="{up}symbol/" onsubmit="return false">'
        f'<label class="sr-only" for="symq">Find a ticker</label><input id="symq" type="search" list="symlist" '
        f'placeholder="Find a ticker" autocomplete="off" aria-describedby="symhint">'
        f'<span id="symhint" class="sr-only">Choose a ticker from the list to open its page</span>'
        f'<datalist id="symlist">{opts}</datalist></form>'
        if _SYMBOLS
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} · {E(brand())}</title>
<link rel="icon" type="image/svg+xml" href="{up}assets/favicon.svg">
<meta name="robots" content="noindex">
<script>try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
<link rel="stylesheet" href="{up}assets/style.css{_SITE["v"]}">
<link rel="alternate" type="application/atom+xml" title="Weekly research reports" href="{up}feed.xml"></head>
<body><a class="skip" href="#main">Skip to content</a><header class="site"><div class="inner"><a class="brand" href="{up}index.html">{E(brand())}</a>
<nav>{nav}</nav>{search}<button class="themebtn" type="button" aria-label="Colour theme: automatic">Theme: auto</button></div></header>
<main id="main" tabindex="-1">{column_headers(freshness + body)}
<footer>{E(spec.DISCLAIMER)} Current registered methodology {E(spec.SPEC_VERSION)}. Sources: SEC EDGAR, Nasdaq Trader,
Wikipedia (CC BY-SA 4.0), Cboe delayed quotes, Alpha Vantage. Built from stored weekly snapshots.</footer></main>
<script src="{up}assets/app.js{_SITE["v"]}"></script>{"".join(f'<script src="{up}{s}{_SITE["v"]}"></script>' for s in scripts)}</body></html>"""


def sessions_after(as_of: str, days: int = spec.FRESHNESS_CALENDAR_DAYS) -> list[str]:
    """NYSE sessions after the as-of session, for the browser to count the data's age (spec FRESHNESS_RULE)."""
    start = date.fromisoformat(str(as_of)[:10])
    return [
        (start + timedelta(days=i)).isoformat() for i in range(1, days + 1) if is_trading_day(start + timedelta(days=i))
    ]


def freshness_banner(snap: dict, status: dict | None, now: datetime | None = None) -> str:
    as_of = snap["as_of"]
    built = (now or datetime.now(ZoneInfo("America/New_York"))).astimezone(ZoneInfo("America/New_York"))
    # Match the browser's registered 16:00 ET completed-session convention.
    end = built.date() if built.hour >= 16 else built.date() - timedelta(days=1)
    start = date.fromisoformat(as_of)
    age = sum(is_trading_day(start + timedelta(days=i)) for i in range(1, max(0, (end - start).days) + 1))
    age_text = "the latest completed session" if age == 0 else f"{age} trading session{'s' if age != 1 else ''} old"
    stale = age > spec.FRESHNESS_STALE_SESSIONS
    parts = [
        f'<div class="banner info" id="freshness" data-asof="{E(as_of)}" '
        f'data-sessions="{E(",".join(sessions_after(as_of)))}" data-stale-after="{spec.FRESHNESS_STALE_SESSIONS}">'
        f'<strong>Data as of the {E(as_of)} close (<span id="age">{age_text}'
        f"</span>).</strong>Age checked at site build {built:%Y-%m-%d %H:%M} ET. Snapshot built {E(str(snap.get('run_finished', '')).replace('+00:00', ''))} UTC. "
        f"Quotes are end-of-session and delayed, never live. Run status: {E(snap.get('status', '?'))}. "
        f"Snapshot methodology: {E(str(snap.get('spec_version') or 'unavailable'))}.</div>"
    ]
    if status and status.get("status") == "failed" and str(status.get("at", "")) >= str(snap.get("run_finished", "")):
        parts.append(
            f'<div class="banner bad"><strong>Stale data: the latest weekly update failed.</strong>'
            f"{E(status.get('message', ''))} (at {E(str(status.get('at')))} UTC). The research below is the "
            f"last successful snapshot, from {E(as_of)}.</div>"
        )
    if snap.get("status") == "partial":
        parts.append(
            '<div class="banner warn"><strong>Partial data.</strong>Some items could not be fetched; '
            "they are listed as excluded with the reason. " + E("; ".join(snap.get("problems", [])[:3])) + "</div>"
        )
    parts.append(
        f'<div class="banner warn" id="stale-client"{"" if stale else " hidden"}><strong>This page may be out of date.</strong>'
        f"More than {spec.FRESHNESS_STALE_SESSIONS} NYSE sessions have passed since the as-of close, so at "
        "least one weekly update did not publish.</div>"
    )
    return "".join(parts)
