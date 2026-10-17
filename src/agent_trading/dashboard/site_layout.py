"""Shared page shell, navigation, accessibility headers and server-rendered freshness."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..market_calendar import is_trading_day
from . import (
    site_command,
    site_tables,
    spec,
)
from .fmt import (
    sval as sval,
)
from .render_context import CURRENT_RENDER

_SYMBOLS: dict[str, str] = {}  # legacy standalone page() callers; build_site uses its isolated RenderContext


_SITE = {"v": ""}  # legacy standalone asset version; never mutated by build_site


E = html.escape


NAV = [
    ("index.html", "Overview"),
    ("growth.html", "Growth Stocks"),
    ("multibaggers.html", "Multibaggers"),
    ("ai.html", "AI stocks"),
    ("options.html", "Options"),
    ("bets.html", "Small bets"),
    ("watchlist.html", "Watchlist 2030"),
    ("leaders.html", "Leaders 2030"),
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
    context = CURRENT_RENDER.get()
    symbols = context.symbols if context is not None else _SYMBOLS
    asset_version = context.asset_version if context is not None else _SITE["v"]
    private = context is not None and context.private
    if private:
        freshness = (
            '<div class="banner">Private personal research · local access only · do not publish</div>' + freshness
        )
    extra_source = " Massive daily aggregates (private personal use);" if private else ""
    up = "../" * depth
    freshness = freshness.replace('href="audit.html', f'href="{up}audit.html')
    # the options page is always listed: it explains its own state when nothing was collected (2026-10-14.6)
    nav = "".join(
        f'<a href="{up}{href}"{" aria-current=page" if href == current else ""}>{E(label)}</a>' for href, label in NAV
    )
    search = site_command.search(symbols, up + "symbol/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} · {E(brand())}</title>
<link rel="icon" type="image/svg+xml" href="{up}assets/favicon.svg">
<meta name="robots" content="noindex">
<script>try{{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t;}}catch(e){{}}</script>
<link rel="stylesheet" href="{up}assets/style.css{asset_version}">
<noscript><style>[role=tabpanel][hidden],[data-panel][hidden]{{display:block!important}}tr.detail[hidden]{{display:table-row!important}}</style></noscript>
<link rel="alternate" type="application/atom+xml" title="Weekly research reports" href="{up}feed.xml"></head>
<body><a class="skip" href="#main">Skip to content</a><header class="site"><div class="inner"><a class="brand" href="{up}index.html">{E(brand())}</a>
<nav aria-label="Research sections">{nav}</nav>{search}<button class="themebtn" type="button" aria-label="Colour theme: automatic">Theme: auto</button></div></header>
<main id="main" tabindex="-1">{site_tables.enhance(column_headers(freshness + body))}
<footer><details><summary>Research, not advice; scenarios are conditional, with no established probability.</summary>
<p>{E(spec.DISCLAIMER)}</p><p>{E(spec.PROBABILITY_STATEMENT)}</p><p>Quotes are delayed, never live.
Sources:{extra_source} SEC EDGAR, Nasdaq Trader, Wikipedia (CC BY-SA 4.0), Cboe delayed quotes, Alpha Vantage.
Built from stored weekly snapshots. <a href="{up}audit.html">Data sources and run details</a>.</p></details></footer></main>{site_command.dialog() if symbols else ""}
<script src="{up}assets/app.js{asset_version}"></script><script src="{up}assets/command.js{asset_version}"></script>{"".join(f'<script src="{up}{s}{asset_version}"></script>' for s in scripts)}</body></html>"""


def sessions_after(as_of: str, days: int = spec.FRESHNESS_CALENDAR_DAYS) -> list[str]:
    """NYSE sessions after the as-of session, for the browser to count the data's age (spec FRESHNESS_RULE)."""
    start = date.fromisoformat(str(as_of)[:10])
    return [
        (start + timedelta(days=i)).isoformat() for i in range(1, days + 1) if is_trading_day(start + timedelta(days=i))
    ]


def freshness_banner(snap: dict, status: dict | None, now: datetime | None = None) -> str:
    from .price_integrity import correction, preclose

    as_of = snap["as_of"]
    built = (now or datetime.now(ZoneInfo("America/New_York"))).astimezone(ZoneInfo("America/New_York"))
    # Match the browser's registered 16:00 ET completed-session convention.
    end = built.date() if built.hour >= 16 else built.date() - timedelta(days=1)
    start = date.fromisoformat(as_of)
    age = sum(is_trading_day(start + timedelta(days=i)) for i in range(1, max(0, (end - start).days) + 1))
    age_text = "latest session" if age == 0 else f"{age} session{'s' if age != 1 else ''} old"
    stale = age > spec.FRESHNESS_STALE_SESSIONS
    price_basis = "intraday inputs · delayed" if preclose(snap) else "delayed close"
    quote_note = correction(snap) or "Quotes are end-of-session and delayed, never live."
    parts = [
        f'<div class="banner info freshness-line" id="freshness" data-asof="{E(as_of)}" '
        f'data-sessions="{E(",".join(sessions_after(as_of)))}" data-stale-after="{spec.FRESHNESS_STALE_SESSIONS}">'
        f'<span>Data: {start:%d %b %Y} · <span id="age">{age_text}</span> · {price_basis}</span>'
        f"<details><summary>Details</summary><p>{E(quote_note)} Age checked at site build {built:%Y-%m-%d %H:%M} ET. "
        "Session age counts completed NYSE sessions, using the registered 16:00 ET convention.</p></details>"
        '<a href="audit.html#latest-run">Run details</a></div>'
    ]
    if status and status.get("status") == "failed" and str(status.get("at", "")) >= str(snap.get("run_finished", "")):
        parts.append(
            '<div class="banner bad"><strong>Stale data: the latest weekly update failed.</strong>'
            f'Displaying {E(as_of)}. <a href="audit.html#latest-run">Failure details</a>.</div>'
        )
    if snap.get("status") == "partial":
        parts.append(
            '<p class="small warn">Partial data · <a href="audit.html#latest-run">Missing inputs and run details</a>.</p>'
        )
    parts.append(
        f'<div class="banner warn" id="stale-client"{"" if stale else " hidden"}><strong>This page may be out of date.</strong>'
        f"More than {spec.FRESHNESS_STALE_SESSIONS} NYSE sessions have passed since the as-of close, so at "
        "least one weekly update did not publish.</div>"
    )
    return "".join(parts)
