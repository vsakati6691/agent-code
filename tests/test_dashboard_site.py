"""Presentation and output guards for the built site (review of 2026-10-14)."""
from __future__ import annotations

import pytest

from agent_trading.dashboard import scoring
from agent_trading.dashboard.scenarios import implied_growth_text


# --- item 1: implied growth wording -----------------------------------------------------------

def test_implied_growth_reads_in_one_pass():
    assert implied_growth_text(1.35, 0.49) == "Price implies about 135%/yr revenue growth for 5 years vs 49% trailing"
    neg = implied_growth_text(-0.12, 0.08)
    assert neg.startswith("The price implies shrinking revenue") and "-" not in neg and "12%" in neg
    assert "could not be computed" in implied_growth_text(None, 0.1)
    assert implied_growth_text(0.2, None) == "Price implies about 20%/yr revenue growth for 5 years"


def test_counterargument_uses_the_plain_wording():
    m = {"implied_revenue_cagr": 1.35, "revenue_growth_ttm": 0.49, "implied_growth_gap": -0.86}
    sub = {k: 1.0 for c in scoring.spec.COMPONENTS for k in c.metrics}
    sub["implied_growth_gap"] = 0.0
    text = scoring.counterargument(sub, m, [])
    assert text == "Weakest evidence: Price implies about 135%/yr revenue growth for 5 years vs 49% trailing."
    assert "away from recent results" not in text


def test_bear_case_does_not_repeat_the_implied_growth_sentence():
    from agent_trading.dashboard.scenarios import bear_case
    m = {"implied_revenue_cagr": 1.35, "revenue_growth_ttm": 0.49, "implied_growth_gap": -0.86}
    counter = "Weakest evidence: " + implied_growth_text(1.35, 0.49) + "."
    assert bear_case(m, counter).count("Price implies") == 1
    assert bear_case(m, "Weakest evidence: leverage.").count("Price implies") == 1


# --- item 2 / item 12: output guards over the whole built site ----------------------------------

import re  # noqa: E402

from tests.dashboard_fixtures import demo_site  # noqa: E402

FORBIDDEN = [(r"\d[eE][-+]\d", "scientific notation"), (r"\bnan\b", "nan"), (r"\bNaN\b", "NaN"), (r"\bNone\b", "None"),
             (r"(?<![\w-])-?inf\b", "inf"), (r"\{", "brace")]


def visible_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return html


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    return demo_site(tmp_path_factory.mktemp("demo"))[1]


def test_no_raw_numbers_or_python_values_leak_into_pages_or_csv(site):
    problems = []
    for p in list(site.rglob("*.html")) + list(site.rglob("*.csv")):
        text = p.read_text(encoding="utf-8")
        body = visible_text(text) if p.suffix == ".html" else text
        for pattern, label in FORBIDDEN:
            m = re.search(pattern, body)
            if m:
                problems.append(f"{p.relative_to(site)}: {label}: ...{body[max(0, m.start() - 40):m.end() + 40]!r}")
    assert not problems, "\n".join(problems[:15])


def test_detail_page_inputs_are_rounded_percentages():
    from agent_trading.dashboard.fmt import metric
    assert metric("fcf_margin_change", 8.33e-17) == "+0.0%"
    assert metric("gross_margin", 0.53212) == "53.2%"
    assert metric("net_debt_to_ebitda", 0.123456) == "0.1235x"
    assert metric("fcf_growth_ttm", -1.0) == "not meaningful (negative base)"
    assert metric("log_market_cap", 9.6).endswith("market cap")


def test_net_debt_or_net_cash_never_both():
    from agent_trading.dashboard.fmt import net_position
    assert net_position(1.5e9) == "Net debt $1.5B" and net_position(-1.5e9) == "Net cash $1.5B"
    assert net_position(-2e8, False) == "net cash $200M" and net_position(None) == "Net debt n/a"


def test_pages_never_say_net_debt_net_cash(site):
    for p in site.rglob("*.html"):
        text = p.read_text(encoding="utf-8").lower()
        assert "net debt net cash" not in text and "net cash held -" not in text, p.name


def test_detail_page_keeps_list_title_casing(site):
    page = (site / "stock" / "large-S11.html").read_text(encoding="utf-8")
    assert "in the Large cap (S&amp;P 500 members) list" in page and "s&amp;p 500 members" not in page


def test_chart_ticks_are_round_numbers():
    from agent_trading.dashboard.site import nice_ticks
    assert nice_ticks(22, 1040) == [0, 250, 500, 750, 1000, 1250]
    assert nice_ticks(95, 140) == [90, 100, 110, 120, 130, 140]
    assert nice_ticks(70, 180) == [50, 75, 100, 125, 150, 175, 200]
    t = nice_ticks(22, 5040)
    assert t[0] <= 22 and t[-1] >= 5040 and all(v % 500 == 0 for v in t) and len(t) <= 7


def test_price_chart_axis_labels_are_round(site):
    page = (site / "stock" / "large-S11.html").read_text(encoding="utf-8")
    labels = [int(x) for x in re.findall(r'text-anchor="end" font-size="11" fill="var\(--text-muted\)">(-?\d+)</text>', page)]
    assert labels and all(v % 10 == 0 for v in labels)


@pytest.mark.parametrize("kind, signed, text", [
    ("call", 0.052, "+5.2% (stock must rise)"),
    ("call", -0.031, "already past breakeven (breakeven 3.1% below the stock)"),
    ("put", -0.052, "-5.2% (stock must fall)"),
    ("put", 0.020, "already past breakeven (breakeven 2.0% above the stock)"),
    ("put", 0.0, "already past breakeven (breakeven 0.0% above the stock)"),
])
def test_distance_to_breakeven_wording(kind, signed, text):
    from agent_trading.dashboard.site_options import distance_text
    assert distance_text(kind, signed) == text


def test_options_page_never_says_zero_move(site):
    page = (site / "options.html").read_text(encoding="utf-8")
    assert "0.0% down" not in page and "0.0% up" not in page and "Distance to breakeven" in page


def test_no_backslash_escapes_inside_html_attributes(site):
    for p in site.rglob("*.html"):
        assert "\\'" not in p.read_text(encoding="utf-8"), p.name     # a backslash before a quote


def test_tabs_are_not_silently_restored_and_follow_the_hash():
    from agent_trading.dashboard.assets import CSS, JS
    assert "localStorage.getItem('matrix'" not in JS and "localStorage.getItem('tab:" not in JS
    assert "history.replaceState(null, '', '#' + state.type + '-' + state.hz)" in JS
    assert 'aria-selected="true"] { background: var(--series-1)' in CSS and "underline" in CSS


def test_options_h2_names_the_active_choice(site):
    page = (site / "options.html").read_text(encoding="utf-8")
    assert re.search(r'<section data-hz="3m" data-type="call" hidden><h2>About 3 months · calls', page)


def _header_classes(page: str, table_id: str) -> list[tuple[str, str]]:
    m = re.search(r'<table id="' + re.escape(table_id) + r'".*?<thead><tr>(.*?)</tr></thead>', page, re.S)
    assert m, table_id
    return [(re.sub(r"<[^>]+>", "", label).strip(), cls) for cls, label in
            re.findall(r"<th class=['\"]([^'\"]*)['\"][^>]*>(.*?)</th>", m.group(1))]


def test_phone_width_keeps_only_the_named_columns(site):
    over = _header_classes((site / "index.html").read_text(encoding="utf-8"), "t-large")
    kept = [label for label, cls in over if "hide-sm" not in cls]
    assert kept == ["#", "Ticker / company / sector", "Price", "Score", "1Y", "Main risk / weakest evidence"]
    opt = _header_classes((site / "options.html").read_text(encoding="utf-8"), "o-3m-call")
    kept = [label for label, cls in opt if "hide-sm" not in cls]
    assert kept == ["#", "Underlying", "Expiry", "Strike", "Bid / ask", "Premium*", "Breakeven at expiry", "Research score"]


def test_ticker_column_is_sticky_in_every_wide_table(site):
    for page, tid in (("index.html", "t-large"), ("options.html", "o-3m-call"), ("watchlist.html", "t-watch")):
        assert any("tk" in cls.split() for _, cls in _header_classes((site / page).read_text(encoding="utf-8"), tid)), page


def _outside_details(html: str) -> str:
    return re.sub(r"(?s)<details\b.*?</details>", " ", html)


def test_long_paragraphs_are_folded_except_on_methodology(site):
    from agent_trading.dashboard import spec
    full = [spec.MULTIBAGGER_DEFINITION[:80], spec.PROBABILITY_STATEMENT[:80], spec.SCENARIO_METHOD[:80]]
    pages = [site / "index.html"] + list((site / "stock").glob("*.html"))
    for p in pages:
        text = p.read_text(encoding="utf-8").replace("&#x27;", "'")
        for f in full:
            assert f.replace("'", "'") not in _outside_details(text), (p.name, f[:30])
    meth = (site / "methodology.html").read_text(encoding="utf-8").replace("&#x27;", "'")
    assert all(f in _outside_details(meth) for f in full)


def test_empty_states_say_what_appears_and_when(tmp_path):
    from agent_trading.dashboard.fmt import tracking_schedule
    text = tracking_schedule(["2026-10-09"])
    assert "21 trading sessions after the first snapshot (2026-10-09)" in text and "2026-11-09" in text
    assert "52 weekly snapshots" in text and "1 stored" in text
    assert "first weekly snapshot" in tracking_schedule([])


def test_history_overview_and_audit_explain_empty_states(site):
    hist = (site / "history.html").read_text(encoding="utf-8")
    assert "No tracking yet" not in hist and "trading sessions after the first snapshot" in hist
    over = (site / "index.html").read_text(encoding="utf-8")
    assert "No tracking data yet" not in over and "trading sessions after the first snapshot" in over
    audit = (site / "audit.html").read_text(encoding="utf-8")
    assert re.search(r"<td class=\"small\">(fixture|local build)</td>", audit)


def test_phone_nav_is_one_scrolling_row():
    from agent_trading.dashboard.assets import CSS, JS
    phone = CSS[CSS.index("@media (max-width: 700px)"):]
    assert "nav { display: flex; flex-wrap: nowrap; overflow-x: auto;" in phone and "min-width: 0" in phone
    assert "nav a[aria-current]" in JS


# --- item 12: structural output guards ----------------------------------------------------------

def _pages(site):
    return sorted(site.rglob("*.html"))


def test_every_internal_link_and_source_resolves(site):
    broken = []
    for p in _pages(site):
        for ref in re.findall(r'(?:href|src)="([^"]+)"', p.read_text(encoding="utf-8")):
            if ref.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            target = (p.parent / ref.split("#")[0].split("?")[0]).resolve()
            if not target.exists():
                broken.append(f"{p.relative_to(site)} -> {ref}")
    assert not broken, broken[:10]


def test_every_page_is_under_300_kb(site):
    big = [(p.name, p.stat().st_size) for p in _pages(site) if p.stat().st_size >= 300_000]
    assert not big, big


def test_every_table_has_a_caption_or_label(site):
    missing = []
    for p in _pages(site):
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"<table\b[^>]*>", text):
            if "aria-label=" not in m.group(0) and not text[m.end():m.end() + 40].lstrip().startswith("<caption"):
                missing.append(f"{p.relative_to(site)}: {m.group(0)[:60]}")
    assert not missing, missing[:10]


def test_every_page_has_exactly_one_h1(site):
    wrong = [(p.relative_to(site).as_posix(), len(re.findall(r"<h1\b", p.read_text(encoding="utf-8"))))
             for p in _pages(site)]
    assert all(n == 1 for _, n in wrong), [w for w in wrong if w[1] != 1]


def test_excluded_lists_live_on_their_own_compact_pages(site):
    index = (site / "index.html").read_text(encoding="utf-8")
    assert re.search(r'href="excluded-(mid|small|multibagger).html"', index) and "<th>Reason</th>" not in index
    page = (site / "excluded-small.html").read_text(encoding="utf-8")
    assert page.count("<h1") == 1 and "Excluded from" in page


# --- item 13: per-symbol pages and header search --------------------------------------------

def test_symbol_pages_cover_lists_options_and_watchlist(site):
    import json as _json
    snap = _json.loads((site / "data" / "latest.json").read_text())
    expected = {c["ticker"] for b in snap["bands"].values() for c in b["candidates"]}
    expected |= set(snap["options"]["underlyings"]) | {e["ticker"] for e in snap["watchlist"]["entries"]}
    have = {p.stem for p in (site / "symbol").glob("*.html")}
    assert expected == have
    page = (site / "symbol" / "S04.html").read_text(encoding="utf-8")
    for heading in ("This week's lists", "Option contracts", "Watchlist 2030", "History across snapshots"):
        assert heading in page
    assert page.count("2026-10-02") >= 1 and page.count("2026-10-09") >= 1          # both snapshots in history
    nope = (site / "symbol" / "NOPE.html").read_text(encoding="utf-8")
    assert "Scenario unavailable" in nope and "Not in any of this week" in nope


def test_every_page_has_the_inline_symbol_search(site):
    for p in _pages(site):
        text = p.read_text(encoding="utf-8")
        assert '<datalist id="symlist">' in text and 'value="S04"' in text, p.name


# --- item 15: sparklines and distribution strips ------------------------------------------------

def test_list_rows_have_a_one_year_sparkline_vs_benchmark(site):
    page = (site / "index.html").read_text(encoding="utf-8")
    sparks = re.findall(r'<svg class="spark"[^>]*aria-label="1-year price: ([^"]+)"', page)
    assert len(sparks) >= 10 and all("SPY" in s or "IJH" in s or "IWM" in s for s in sparks)
    assert 'stroke-dasharray="3 2"' in page


def test_lists_show_sector_and_market_cap_mix(site):
    page = (site / "index.html").read_text(encoding="utf-8")
    assert page.count('aria-label="Sector mix"') >= 3 and page.count('aria-label="Market-cap mix"') >= 3
    from agent_trading.dashboard.site_overview import distribution_strip
    strip = distribution_strip([{"sector": "Energy", "market_cap": 5e9}, {"sector": "Energy", "market_cap": 3e11}])
    assert "Energy <strong>2</strong>" in strip and "$2B-$10B <strong>1</strong>" in strip and "$200B+ <strong>1</strong>" in strip


# --- item 14: why a watchlist scenario is unavailable --------------------------------------------

def test_next_filing_estimate_from_cadence_and_fallback():
    from datetime import date
    from agent_trading.dashboard.watchlist import next_filing_estimate
    subs = {"filings": {"recent": {"form": ["10-Q", "8-K", "10-Q", "10-K", "10-Q"],
                                   "filingDate": ["2026-08-07", "2026-08-01", "2026-05-08", "2026-02-20", "2025-11-06"]}}}
    nxt, basis = next_filing_estimate(subs, None, date(2026, 10, 9))
    assert nxt == date(2026, 8, 7) + (date(2026, 8, 7) - date(2026, 5, 8)) and "median gap" in basis
    nxt, basis = next_filing_estimate({"sic": "1"}, "2026-08-10", date(2026, 10, 9))
    assert nxt == date(2026, 11, 9) and "assumed quarterly cadence" in basis
    nxt, basis = next_filing_estimate(None, "2026-01-10", date(2026, 10, 9))
    assert "overdue" in basis


def test_unlock_steps_name_exact_inputs_and_never_invent_methods():
    from datetime import date
    from agent_trading.dashboard.watchlist import unlock_steps
    q = unlock_steps("quarters", quarters=2, next_filing=(date(2026, 11, 15), "the last filing cadence"))
    assert q[0] == "2 of 4 required quarters reported; next 10-Q/10-K expected around 2026-11-15 based on the last filing cadence."
    assert "The spec defines no other ETF method" in " ".join(unlock_steps("etf_class"))
    assert "edit config/research_watchlist.json" in " ".join(unlock_steps("unresolved"))


def test_watchlist_page_lists_what_unlocks_each_unavailable_scenario(site):
    import json as _json
    snap = _json.loads((site / "data" / "latest.json").read_text())
    w = {e["ticker"]: e for e in snap["watchlist"]["entries"]}
    assert w["NEWQ"]["scenarios"] is None and w["NEWQ"]["unlock"][0].startswith("2 of 4 required quarters reported")
    for t in ("NOPE", "ODDF"):
        assert w[t]["scenarios"] is None and w[t]["unlock"], t
    assert all(e["unlock"] for e in w.values() if e["scenarios"] is None)
    page = (site / "watchlist.html").read_text(encoding="utf-8")
    assert "Why unavailable, and what would unlock it" in page


# --- item 16: week-over-week change causes ------------------------------------------------------

def test_rank_changes_carry_score_and_component_moves():
    from agent_trading.dashboard.pipeline import rank_changes
    prev = [{"ticker": "A", "rank": 3, "composite": 60.0, "components": {"growth": 0.5, "valuation": 0.4, "quality": 0.6}}]
    cur = [{"ticker": "A", "rank": 1, "composite": 65.3, "components": {"growth": 0.62, "valuation": 0.385, "quality": 0.6}}]
    (ch,) = rank_changes(cur, prev)
    assert ch["change"] == 2 and ch["score_change"] == pytest.approx(5.3)
    assert ch["component_changes"] == {"growth": 12.0, "valuation": -1.5}


def test_changes_panel_names_the_causes(site):
    from agent_trading.dashboard.site_overview import move_cause
    text = move_cause({"ticker": "S04", "change": 4, "to": 1, "score_change": 5.3,
                       "component_changes": {"growth": 12.0, "valuation": -1.5}}, "Large cap")
    assert text == "S04 up 4 to #1 (Large cap): score +5.3; growth +12.0, valuation -1.5"
    old = move_cause({"ticker": "X", "change": -2, "to": 5, "explanation": "component score changes: growth -3.0"}, "Mid")
    assert old == "X down 2 to #5 (Mid): component score changes: growth -3.0"
    page = (site / "index.html").read_text(encoding="utf-8")
    assert "Biggest moves and why" in page and re.search(r"(up|down) \d+ to #\d+ \(Large cap \(S&amp;P 500 members\)\): score [+-]", page)


def test_move_with_unchanged_own_score_says_others_moved():
    from agent_trading.dashboard.site_overview import move_cause
    t = move_cause({"ticker": "S11", "change": -2, "to": 3, "score_change": 0.0, "component_changes": {}}, "Large cap")
    assert t == "S11 down 2 to #3 (Large cap): its own score was unchanged; other stocks scored higher this week"


# --- item 17: Atom feed -----------------------------------------------------------------------------

def test_atom_feed_lists_every_weekly_report(site):
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring((site / "feed.xml").read_bytes())
    entries = root.findall("a:entry", ns)
    reports = sorted(p.stem for p in (site / "reports").glob("*.html"))
    assert sorted(e.find("a:title", ns).text.replace("Week ending ", "") for e in entries) == reports
    for e in entries:
        href = e.find("a:link", ns).get("href")
        assert (site / href).exists() and e.find("a:updated", ns).text and "not advice" in e.find("a:summary", ns).text
    assert entries[0].find("a:title", ns).text == f"Week ending {reports[-1]}"          # newest first
    assert 'type="application/atom+xml"' in (site / "index.html").read_text(encoding="utf-8")


# --- item 18: documented JSON ----------------------------------------------------------------

def test_per_snapshot_json_schema_and_audit_links(site):
    import json as _json
    from agent_trading.dashboard.store import Store
    store = Store(site.parent / "data")
    for d in store.dates():
        assert _json.loads((site / "data" / f"{d}.json").read_text()) == _json.loads(_json.dumps(store.load(d), default=str))
    schema = _json.loads((site / "data" / "schema.json").read_text())
    latest = _json.loads((site / "data" / "latest.json").read_text())
    assert set(latest) <= set(schema["properties"]), set(latest) - set(schema["properties"])
    cand = schema["properties"]["bands"]["additionalProperties"]["properties"]["candidates"]["items"]["properties"]
    assert {"ticker", "rank", "composite", "scenarios"} <= set(cand)
    audit = (site / "audit.html").read_text(encoding="utf-8")
    assert 'href="data/schema.json"' in audit and all(f'href="data/{d}.json"' in audit for d in store.dates())
