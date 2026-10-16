"""Build the static public site from verified stored snapshots; public renderer imports remain compatible."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from . import (
    assets_bets,
    assets_goal,
    assets_research,
    compare,
    leaders,
    site_basics,
    site_bets,
    site_build,
    site_evidence,
    site_goal,
    site_leaders,
    site_methodology,
    site_performance,
    site_refresh,
    spec,
)
from .assets import CSS, JS
from .fmt import (
    sval as sval,
)
from .site_ai import ai_page
from .site_audit import _readable as _readable
from .site_audit import audit_page as audit_page
from .site_company import COMP_SHORT as COMP_SHORT
from .site_company import NICE_STEPS as NICE_STEPS
from .site_company import _earnings_check as _earnings_check
from .site_company import detail as detail
from .site_company import line_chart as line_chart
from .site_company import nice_ticks as nice_ticks
from .site_company import profile_of as profile_of
from .site_company import window_text as window_text
from .site_compare import compare_page
from .site_downloads import band_csv as band_csv
from .site_downloads import leaders_csv
from .site_downloads import options_csv as options_csv
from .site_history import atom_feed as atom_feed
from .site_history import history_page as history_page
from .site_history import weekly_report as weekly_report
from .site_layout import _SITE as _SITE
from .site_layout import _SYMBOLS as _SYMBOLS
from .site_layout import NAV as NAV
from .site_layout import TH_WITHOUT_SCOPE as TH_WITHOUT_SCOPE
from .site_layout import E as E
from .site_layout import brand as brand
from .site_layout import column_headers as column_headers
from .site_layout import freshness_banner as freshness_banner
from .site_layout import page as page
from .site_layout import sessions_after as sessions_after
from .site_lists import growth_page, multibaggers_page
from .site_methodology_page import _R as _R
from .site_methodology_page import OPTION_RULES_TEXT as OPTION_RULES_TEXT
from .site_methodology_page import _component_rows as _component_rows
from .site_methodology_page import methodology_page as methodology_page
from .site_options import lists_of, options_page
from .site_overview import band_title, evidence_fragments, excluded_page, list_page, overview
from .site_symbol import symbol_index, symbol_page
from .site_watchlist import watchlist_csv, watchlist_page
from .store import Store, find_private_keys


def scan_for_secrets(out: Path, env_names: tuple[str, ...]) -> list[str]:
    """Files containing the value of any named environment variable (values are never printed)."""
    values = [os.environ[n] for n in env_names if len(os.environ.get(n, "")) >= 8]
    hits = []
    for p in out.rglob("*"):
        if p.is_file():
            text = p.read_text(encoding="utf-8", errors="ignore")
            if any(v in text for v in values):
                hits.append(str(p.relative_to(out)))
    return hits


def build_site(
    data_dir: Path, out: Path, secret_env: tuple[str, ...] = (), *, code_commit: str = "", data_commit: str = ""
) -> dict:
    store = Store(data_dir)
    challengers = leaders.load_challengers()
    integrity = store.verify_all()
    bad = {p.split()[1] for p in integrity if p.startswith("snapshot ")}
    dates = [d for d in store.dates() if d not in bad]
    snap = store.load(dates[-1]) if dates else None
    build_info = site_build.metadata(code_commit, data_commit, snap)
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    (out / "build.json").write_text(json.dumps(build_info, indent=2) + "\n", encoding="utf-8")
    _SYMBOLS.clear()
    (out / "assets" / "favicon.svg").write_text(site_basics.FAVICON_SVG, encoding="utf-8")
    # a content hash in every asset link, so a browser never pairs new pages with a cached old stylesheet or script
    _SITE["v"] = (
        "?v="
        + hashlib.sha256(
            (
                CSS
                + assets_research.CSS
                + JS
                + assets_research.COMPARE_JS
                + assets_research.LAB_JS
                + assets_bets.CSS
                + assets_bets.JS
                + assets_goal.JS
            ).encode("utf-8")
        ).hexdigest()[:10]
    )
    (out / "assets" / "style.css").write_text(CSS + assets_research.CSS + assets_bets.CSS, encoding="utf-8")
    (out / "assets" / "app.js").write_text(JS, encoding="utf-8")
    (out / "assets" / "compare.js").write_text(assets_research.COMPARE_JS, encoding="utf-8")
    (out / "assets" / "lab.js").write_text(assets_research.LAB_JS, encoding="utf-8")
    (out / "assets" / "bets.js").write_text(assets_bets.JS, encoding="utf-8")
    (out / "assets" / "goal.js").write_text(assets_goal.JS, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    def write_fallback():
        fallback = page("Page not found", site_basics.NOT_FOUND, "")
        fallback = fallback.replace("<head>", f'<head><base href="{site_basics.PAGES_BASE}">', 1)
        (out / "404.html").write_text(fallback, encoding="utf-8")

    status = store.status()
    if not dates:
        msg = (status or {}).get("message", "no weekly snapshot has been produced yet")
        body = f'<h1>{E(brand())} Dashboard</h1><div class="banner bad"><strong>No research data available</strong>{E(msg)}</div>'
        (out / "index.html").write_text(page("Overview", body, "index.html"), encoding="utf-8")
        for rel, title in (("growth.html", "Growth Stocks"), ("multibaggers.html", "Multibaggers")):
            empty = f'<h1>{title}</h1><p class="scan-empty">No research data available. {E(msg)}</p>'
            (out / rel).write_text(page(title, empty, rel), encoding="utf-8")
        (out / "methodology.html").write_text(
            page("Methodology", methodology_page(), "methodology.html"), encoding="utf-8"
        )
        (out / "bets.html").write_text(page("Small bets", site_bets.bets_page({}, None), "bets.html"), encoding="utf-8")
        for rel, title in NAV:
            if not (out / rel).exists():
                empty = f"<h1>{E(title)}</h1><p>No research data available. {E(msg)}</p>"
                if rel == "leaders.html" and not challengers:
                    empty += "<p>No curated challengers registered.</p>"
                (out / rel).write_text(page(title, empty, rel), encoding="utf-8")
        (out / "feed.xml").write_text(atom_feed([]), encoding="utf-8")
        write_fallback()
        return {"pages": len(list(out.rglob("*.html"))), "snapshot": None}
    _SYMBOLS.clear()
    _SYMBOLS.update(symbol_index(snap))
    write_fallback()
    hits = find_private_keys(snap)
    if hits:
        raise RuntimeError(f"refusing to publish: private-looking fields {hits[:5]}")
    fresh = freshness_banner(snap, status)
    browser_files: dict[str, str] = {}
    option_fragments: dict[str, str] = {}
    write = lambda rel, title, body, cur, depth=0, fr=fresh, js=(): (out / rel).write_text(  # noqa: E731
        page(
            title,
            site_performance.external_json(body, Path(rel).stem, browser_files) if depth == 0 else body,
            cur,
            depth,
            fr,
            js,
        ),
        encoding="utf-8",
    )
    tracking = store.read_json("tracking.json")
    prev_snap = store.load(dates[-2]) if len(dates) > 1 else None
    history = [snap if d == dates[-1] else store.load(d) for d in dates]
    daily = site_refresh.load_context(data_dir, snap, out)
    research_evidence = site_evidence.read_evidence()
    write(
        "index.html",
        "Overview",
        overview(snap, status, dates, tracking, prev_snap, daily)
        + site_methodology.progress(history)
        + site_evidence.summary(research_evidence),
        "index.html",
    )
    write("ai.html", "AI stocks", ai_page(snap), "ai.html")
    write("growth.html", "Growth Stocks", growth_page(snap, daily), "growth.html")
    write("multibaggers.html", "Multibaggers", multibaggers_page(snap), "multibaggers.html")
    option_body = options_page(snap, daily, option_fragments)
    if (
        len(page("Options research", option_body, "options.html", freshness=fresh).encode("utf-8"))
        > site_performance.HTML_BUDGET
    ):
        for h in spec.HORIZONS:
            body = options_page(snap, daily, option_fragments, horizon=h.key)
            write(f"options-{h.key}.html", f"Options research · {h.title}", body, "options.html")
        option_body = options_page(snap, daily, option_fragments, horizon=spec.HORIZONS[0].key)
    write("options.html", "Options research", option_body, "options.html")
    write(
        "bets.html", "Small-bet options research", site_bets.bets_page(snap, daily), "bets.html", js=("assets/bets.js",)
    )
    write("watchlist.html", "Watchlist 2030", watchlist_page(snap), "watchlist.html")
    leader_payload = leaders.build(snap, challengers)
    leader_details: dict[str, str] = {}
    write("leaders.html", "Leaders 2030", site_leaders.leaders_page(leader_payload, leader_details), "leaders.html")
    write("goal.html", "Plan 2030", site_goal.goal_page(snap), "goal.html", js=("assets/goal.js",))
    write("evidence.html", "Evidence", site_evidence.evidence_page(research_evidence), "evidence.html")
    write("history.html", "History", history_page(dates, tracking, history), "history.html")
    write("methodology.html", "Methodology", methodology_page(), "methodology.html", fr="")
    write(
        "audit.html", "Audit trail", audit_page(store, snap, integrity) + site_build.section(build_info), "audit.html"
    )
    profiles = {k: b.get("profile", "standard") for k, b in snap["bands"].items()}
    write(
        "compare.html",
        "Compare companies",
        compare_page(compare.payload(snap, profiles)),
        "compare.html",
        js=("assets/compare.js",),
    )
    (out / "stock").mkdir()
    (out / "reports").mkdir()
    (out / "downloads").mkdir()
    (out / "data").mkdir(exist_ok=True)
    (out / "symbol").mkdir()
    (out / "fragments").mkdir()
    (out / "option").mkdir()
    (out / "leaders").mkdir()
    for rel, markup in leader_details.items():
        write(rel, "Leaders evidence", markup, "leaders.html", 1)
    (out / "downloads" / f"{snap['as_of']}_leaders_2030.csv").write_text(leaders_csv(leader_payload), encoding="utf-8")
    (out / "data" / f"{snap['as_of']}_leaders_2030.json").write_text(
        json.dumps(leader_payload, ensure_ascii=False), encoding="utf-8"
    )
    for rel, text in browser_files.items():
        (out / rel).write_text(text, encoding="utf-8")
    for rid, markup in option_fragments.items():
        (out / "fragments" / f"{rid}.json").write_text(json.dumps({"html": column_headers(markup)}), encoding="utf-8")
        body = (
            '<h1>Contract research</h1><p><a href="../options.html">Back to the options watchlist</a></p>'
            + markup.replace('href="methodology.html', 'href="../methodology.html')
        )
        write(f"option/{rid}.html", "Contract research", body, "options.html", 1)
    for rel, text in evidence_fragments(snap["bands"]).items():  # evidence rows load on demand (see assets.JS)
        (out / rel).write_text(text, encoding="utf-8")
    for t in _SYMBOLS:
        write(f"symbol/{t}.html", f"{t} · symbol", symbol_page(t, snap, history), "", 1)
    for key, band in snap["bands"].items():
        write(f"excluded-{key}.html", f"Excluded: {band_title(key, band)}", excluded_page(key, band), list_page(key))
    for key, band in snap["bands"].items():
        for c in band["candidates"]:
            write(
                f"stock/{key}-{c['ticker']}.html",
                f"{c['ticker']} research",
                detail(c, snap, history, prev_snap),
                list_page(key),
                1,
                js=("assets/lab.js",),
            )
    for d in dates:
        s = snap if d == dates[-1] else store.load(d)
        (out / "reports" / f"{d}.html").write_text(
            page(f"Week ending {d}", weekly_report(s), "history.html", 1, ""), encoding="utf-8"
        )
        for key, band in s["bands"].items():
            (out / "downloads" / f"{d}_{key}.csv").write_text(band_csv(band), encoding="utf-8")
        for h in spec.HORIZONS:
            for kind, lst in lists_of((s.get("options") or {}).get(h.key) or {}).items():
                (out / "downloads" / f"{d}_options_{h.key}_{kind}.csv").write_text(
                    options_csv((lst or {}).get("rows", [])), encoding="utf-8"
                )
        if s.get("watchlist"):
            (out / "downloads" / f"{d}_watchlist_2030.csv").write_text(watchlist_csv(s), encoding="utf-8")
    (out / "data" / "latest.json").write_text(json.dumps(snap, default=str), encoding="utf-8")
    for s in history:
        (out / "data" / f"{s['as_of']}.json").write_text(json.dumps(s, default=str), encoding="utf-8")
    from .schema import SCHEMA

    (out / "data" / "schema.json").write_text(json.dumps(SCHEMA, indent=1), encoding="utf-8")
    (out / "feed.xml").write_text(atom_feed(history), encoding="utf-8")
    leaks = scan_for_secrets(out, secret_env)
    if leaks:
        shutil.rmtree(out)
        raise RuntimeError(f"refusing to publish: secret values found in {len(leaks)} file(s)")
    if problems := site_performance.budget_problems(out):
        raise RuntimeError("HTML page budget exceeded: " + "; ".join(problems))
    return {"pages": len(list(out.rglob("*.html"))), "snapshot": dates[-1], "integrity_problems": integrity}
