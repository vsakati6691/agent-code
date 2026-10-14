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
    assert re.search(r'<section data-hz="3m" data-type="call"[^>]* hidden><h2>About 3 months · calls', page)


def _header_classes(page: str, table_id: str) -> list[tuple[str, str]]:
    """[(header label, class attribute)] for a table's column headers, whatever the attribute order."""
    m = re.search(r'<table id="' + re.escape(table_id) + r'".*?<thead><tr>(.*?)</tr></thead>', page, re.S)
    assert m, table_id
    out = []
    for attrs, label in re.findall(r"<th\b([^>]*)>(.*?)</th>", m.group(1)):
        cls = re.search(r"class=['\"]([^'\"]*)['\"]", attrs)
        out.append((re.sub(r"<[^>]+>", "", label).strip(), cls.group(1) if cls else ""))
    return out


def test_phone_width_keeps_only_the_named_columns(site):
    over = _header_classes((site / "growth.html").read_text(encoding="utf-8"), "t-large")
    kept = [label for label, cls in over if "hide-sm" not in cls]
    assert kept == ["#", "Ticker / company / sector", "Price", "Score", "1Y", "Main risk / weakest evidence"]
    opt = _header_classes((site / "options.html").read_text(encoding="utf-8"), "o-3m-call")
    kept = [label for label, cls in opt if "hide-sm" not in cls]
    # 2026-10-14.6: maximum loss stays visible on phones; bid/ask moves to the expandable facts
    assert kept == ["#", "Underlying", "Expiry", "Strike", "Premium*", "Breakeven at expiry", "Max loss", "Research score"]


def test_ticker_column_is_sticky_in_every_wide_table(site):
    for page, tid in (("growth.html", "t-large"), ("options.html", "o-3m-call"), ("watchlist.html", "t-watch")):
        assert any("tk" in cls.split() for _, cls in _header_classes((site / page).read_text(encoding="utf-8"), tid)), page


def _outside_details(html: str) -> str:
    return re.sub(r"(?s)<details\b.*?</details>", " ", html)


def test_long_paragraphs_are_folded_except_on_methodology(site):
    from agent_trading.dashboard import spec
    full = [spec.MULTIBAGGER_DEFINITION[:80], spec.PROBABILITY_STATEMENT[:80], spec.SCENARIO_METHOD[:80]]
    pages = [site / "index.html", site / "growth.html", site / "multibaggers.html"] + list((site / "stock").glob("*.html"))
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
    index = (site / "growth.html").read_text(encoding="utf-8")
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
    page = (site / "growth.html").read_text(encoding="utf-8")
    sparks = re.findall(r'<svg class="spark"[^>]*aria-label="1-year price: ([^"]+)"', page)
    assert len(sparks) >= 10 and all("SPY" in s or "IJH" in s or "IWM" in s for s in sparks)
    assert 'stroke-dasharray="3 2"' in page


def test_lists_show_sector_and_market_cap_mix(site):
    page = (site / "growth.html").read_text(encoding="utf-8")
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


# --- item 19: theme toggle and print stylesheet ------------------------------------------------

def test_theme_toggle_overrides_system_and_is_applied_before_paint(site):
    from agent_trading.dashboard.assets import CSS, JS
    page = (site / "index.html").read_text(encoding="utf-8")
    head = page[:page.index("</head>")]
    assert 'localStorage.getItem("theme")' in head and head.index("<script>") < head.index("style.css")
    assert 'class="themebtn"' in page
    assert "var order = ['auto', 'light', 'dark'];" in JS
    assert ':root[data-theme="dark"]' in CSS and ':root:where(:not([data-theme="light"]))' in CSS


def test_print_stylesheet_hides_controls_and_expands_details():
    from agent_trading.dashboard.assets import CSS, JS
    pr = CSS[CSS.index("@media print"):]
    assert "header.site" in pr and ".tabs" in pr and "display: none" in pr and "background: #fff" in pr
    assert "beforeprint" in JS and "setAttribute('open'" in JS


# --- item 20: verified earnings dates (SEC 8-K item 2.02) ---------------------------------------

SUBS = {"filings": {"recent": {"form": ["8-K", "10-Q", "8-K", "8-K", "8-K/A", "8-K"],
                                "filingDate": ["2026-07-30", "2026-07-31", "2026-06-02", "2026-04-29", "2026-02-01", "2026-01-28"],
                                "items": ["2.02,9.01", "", "5.07", "2.02", "2.02", "9.01"]}}}


def test_parse_earnings_8k_keeps_only_item_2_02():
    from agent_trading.dashboard.providers import parse_earnings_8k
    assert parse_earnings_8k(SUBS) == ["2026-07-30", "2026-04-29", "2026-02-01"]
    assert parse_earnings_8k({"sic": "1"}) == [] and parse_earnings_8k(None) == []


class _Http:
    def __init__(self, left):
        self.left = left

    def budget_left(self, provider):
        return self.left


class _Prov:
    def __init__(self, left, subs):
        self.http, self._subs, self.calls = _Http(left), subs, 0

    def submissions(self, cik):
        self.calls += 1
        return self._subs


def test_verify_earnings_labels_cadence_and_respects_the_budget():
    from datetime import date
    from agent_trading.dashboard.pipeline import Context, verify_earnings
    ok = verify_earnings(Context(date(2026, 10, 9), _Prov(500, SUBS)), 1, "2026-10-29")
    assert ok["last_results"] == "2026-07-30" and ok["last_results_status"] == "verified (8-K)"
    assert ok["next_status"] == "scheduled (Alpha Vantage, unverified)" and ok["cadence_check"].startswith("consistent")
    far = verify_earnings(Context(date(2026, 10, 9), _Prov(500, SUBS)), 1, "2027-01-30")
    assert far["cadence_check"].startswith("differs by")
    prov = _Prov(5, SUBS)
    low = verify_earnings(Context(date(2026, 10, 9), prov), 1, "2026-10-29")
    assert prov.calls == 0 and "budget" in low["last_results_status"] and low["next_status"].endswith("unverified)")
    none = verify_earnings(Context(date(2026, 10, 9), _Prov(500, {"sic": "1"})), 1, None)
    assert none["last_results"] is None and "no 8-K item 2.02" in none["last_results_status"]


def test_8k_results_and_filing_cadence_are_point_in_time():
    """The SEC submissions file is a current view: filings after the as-of date must not become 'last results'
    (a rerun for an earlier week, or a Saturday run after a holiday Friday when EDGAR was open)."""
    from datetime import date
    from agent_trading.dashboard.pipeline import Context, verify_earnings
    from agent_trading.dashboard.providers import parse_earnings_8k
    from agent_trading.dashboard.watchlist import next_filing_estimate
    assert parse_earnings_8k(SUBS, date(2026, 7, 1)) == ["2026-04-29", "2026-02-01"]
    assert parse_earnings_8k(SUBS, date(2026, 7, 30)) == ["2026-07-30", "2026-04-29", "2026-02-01"]   # same day counts
    assert parse_earnings_8k(SUBS, date(2026, 1, 1)) == []
    earlier = verify_earnings(Context(date(2026, 7, 1), _Prov(500, SUBS)), 1, "2026-07-29")
    assert earlier["last_results"] == "2026-04-29" and earlier["last_results_status"] == "verified (8-K)"
    assert "2026-07-30" not in str(earlier)
    subs = {"filings": {"recent": {"form": ["10-Q", "10-Q", "10-K", "10-Q"],
                                   "filingDate": ["2026-11-06", "2026-08-07", "2026-02-20", "2025-11-06"]}}}
    nxt, basis = next_filing_estimate(subs, None, date(2026, 10, 9))
    assert nxt == date(2026, 8, 7) + (date(2026, 8, 7) - date(2026, 2, 20)) and "last 3" in basis   # 2026-11-06 ignored


def test_site_shows_verified_8k_dates(site):
    page = (site / "stock" / "large-S04.html").read_text(encoding="utf-8")
    assert "verified (8-K)" in page and "last results 2026-07-30" in page and "unverified" in page
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "S04</strong> 2026-10-30" in index and "verified (8-K)" in index


# --- review of the live site (2026-10-14): readable reasons, options-off naming, phone order -----------

def test_exclusion_groups_keep_the_rule_and_drop_each_stocks_value():
    from agent_trading.dashboard.site_overview import NOT_CHECKED, group_exclusions, reason_group
    assert reason_group("gate failed: TTM revenue growth 6% (needs >= 15%)") == \
        ("gate failed: TTM revenue growth below 15%", "6%")
    assert reason_group("gate failed: dilution 9% (needs <= 8%)") == ("gate failed: dilution above 8%", "9%")
    assert reason_group("illiquid: 20-day median dollar volume $1.5M < $5M") == \
        ("illiquid: 20-day median dollar volume below $5M", "$1.5M")
    assert reason_group("market cap $0.83B outside the band") == ("market cap outside the band", "$0.83B")
    assert reason_group("too little evidence: 5 of 21 sub-metrics missing") == \
        ("too little evidence (too many sub-metrics missing)", "5 of 21")
    assert reason_group("price 1.20 below 2") == ("price below $2", "$1.20")
    assert reason_group("Robinhood tradability not yet verified") == (NOT_CHECKED, "")
    assert reason_group("no CIK for this S&P 500 member") == ("no CIK for this S&P 500 member", "")
    assert reason_group("gate input unavailable: 3-year revenue growth")[0] == "gate input unavailable: 3-year revenue growth"
    assert reason_group("price data rejected: ADIG: only 41 bars, need 60") == \
        ("price data rejected: too little price history (needs 60 daily bars)", "41 bars")
    assert reason_group("price data rejected: KOD: recent data anomaly (unadjusted split on 2026-09-30); "
                        "feed unreliable") == \
        ("price data rejected: recent data anomaly (unadjusted split); feed unreliable", "2026-09-30")
    assert reason_group("price data rejected: PPIH: negative volume") == ("price data rejected: negative volume", "")
    groups = group_exclusions([{"ticker": "A", "reason": "gate failed: TTM revenue growth 6% (needs >= 15%)"},
                               {"ticker": "B", "reason": "gate failed: TTM revenue growth 4% (needs >= 15%)"}])
    assert groups == [("gate failed: TTM revenue growth below 15%", [("A", "6%"), ("B", "4%")])]


def test_excluded_summaries_on_the_site_have_no_placeholder_dots(site):
    page = (site / "growth.html").read_text(encoding="utf-8")
    for summary in re.findall(r"Most common: (.*?)</span>", page):
        assert "…" not in summary, summary


def test_missing_earnings_calendar_is_not_reported_as_no_earnings():
    from agent_trading.dashboard.site_overview import panels
    snap = {"bands": {}, "as_of": "2026-10-13", "universe": {}, "events": {
        "window_days": 45, "items": [], "note": "Earnings dates unavailable: data unavailable (key not configured)"}}
    html = panels(snap, None, ["2026-10-13"])
    assert "No earnings scheduled" not in html and "could not be collected" in html
    snap["events"]["note"] = "Scheduled earnings dates from Alpha Vantage's calendar."
    assert "No earnings scheduled in the next 45 days" in panels(snap, None, ["2026-10-13"])


def test_flags_shared_by_most_names_collapse_to_a_count():
    from agent_trading.dashboard.site_overview import FLAG_LIST_MAX, _flag_item
    short = _flag_item("Negative free cash flow", ["A", "B"], 35)
    assert "<details>" not in short and "A, B" in short
    many = [f"T{i}" for i in range(FLAG_LIST_MAX + 1)]
    long = _flag_item("5-year drawdown worse than -50%", many, 35)
    assert "<details>" in long and f"{FLAG_LIST_MAX + 1} of 35 listed names" in long


def test_tikasa_brand_and_options_link_stay_consistent_when_options_are_disabled(tmp_path):
    """Dataset availability does not change the brand or hide the explanatory options page."""
    from agent_trading.dashboard.site import build_site
    from agent_trading.dashboard.store import Store
    data, out = demo_site(tmp_path / "a", two_weeks=False)
    on = (out / "index.html").read_text(encoding="utf-8")
    assert "Tikasa Stock Research" in on and 'href="options.html"' in on
    snap = Store(data).load(Store(data).dates()[-1])
    snap["options"] = {"enabled": False, "status": "disabled in configuration"}
    off_data, off_out = tmp_path / "off-data", tmp_path / "off-site"
    Store(off_data).write_snapshot(snap, "test")
    build_site(off_data, off_out)
    for name in ("index.html", "watchlist.html", "methodology.html"):
        page = (off_out / name).read_text(encoding="utf-8")
        assert "Tikasa Stock Research" in page and "Growth Research" not in page, name
        assert re.search(r'<nav>.*href="options\.html"', page), name
    index = (off_out / "index.html").read_text(encoding="utf-8")
    assert 'id="options-watchlist"' in index and "not collected" in index
    assert "<title>Tikasa Stock Research: weekly reports</title>" in (off_out / "feed.xml").read_text(encoding="utf-8")


def test_every_page_uses_the_tikasa_name_in_header_and_title(site):
    for p in _pages(site):
        page = p.read_text(encoding="utf-8")
        assert re.search(r'<a class="brand"[^>]+>Tikasa Stock Research</a>', page), p.name
        assert re.search(r'<title>[^<]*Tikasa Stock Research</title>', page), p.name


def test_overview_and_research_lists_have_separate_pages(site):
    overview = (site / "index.html").read_text(encoding="utf-8")
    growth = (site / "growth.html").read_text(encoding="utf-8")
    multibaggers = (site / "multibaggers.html").read_text(encoding="utf-8")
    assert "Market context" in overview and 'id="research-briefing"' in overview
    assert 'id="t-scan"' not in overview and 'id="t-large"' not in overview and 'class="mb-list"' not in overview
    assert 'id="t-scan"' in growth and 'id="t-large"' in growth and 'id="t-small"' in growth
    assert 'data-list="multibagger"' not in growth and 'class="mb-list"' not in growth
    assert 'class="mb-list"' in multibaggers and 'id="t-large"' not in multibaggers
    assert "What must happen for a multibagger outcome" in multibaggers


@pytest.mark.parametrize("name,label", [("index.html", "Overview"), ("growth.html", "Growth Stocks"),
                                       ("multibaggers.html", "Multibaggers")])
def test_primary_research_navigation_marks_only_the_active_page(site, name, label):
    page = (site / name).read_text(encoding="utf-8")
    nav = re.search(r"<nav>(.*?)</nav>", page, re.S)[1]
    assert nav.count("aria-current=page") == 1
    assert f'<a href="{name}" aria-current=page>{label}</a>' in nav
    for route in ("index.html", "growth.html", "multibaggers.html"):
        assert f'href="{route}"' in nav


def test_research_backlinks_return_to_the_matching_list_page(site):
    for p in (site / "stock").glob("*.html"):
        band = p.stem.split("-", 1)[0]
        target = "ai.html" if band.startswith("ai_") else "multibaggers.html" if band == "multibagger" else "growth.html"
        page = p.read_text(encoding="utf-8")
        assert f'href="../{target}#{band}"' in page
        assert f'href="../{target}" aria-current=page' in page
    for p in site.glob("excluded-*.html"):
        band = p.stem.removeprefix("excluded-")
        target = "ai.html" if band.startswith("ai_") else "multibaggers.html" if band == "multibagger" else "growth.html"
        assert f'href="{target}#{band}"' in p.read_text(encoding="utf-8")


def test_watchlist_fund_type_label_is_plain():
    from agent_trading.dashboard.site_watchlist import tidy
    old = "other security (not common stock (warrant, right, unit, preferred, note, fund or blank-check))"
    assert tidy(old) == "other security (not common stock)"
    assert tidy(f"no scenario method for this security type ({old})") == \
        "no scenario method for this security type (other security (not common stock))"
    assert tidy(None) == ""


def test_listed_fund_shares_resolve_as_a_fund_not_a_nested_label():
    import pandas as pd
    from agent_trading.dashboard.watchlist import resolve
    dirs = pd.DataFrame([{"ticker": "RVX", "name": "Example Ventures Fund I Common Shares of Beneficial Interest",
                          "exchange": "NYSE", "test_issue": False, "etf": False, "financial_status": ""},
                         {"ticker": "WTX", "name": "Example Corp Warrants", "exchange": "Nasdaq", "test_issue": False,
                          "etf": False, "financial_status": ""}]).set_index("ticker")
    sec = pd.DataFrame(columns=["cik", "name", "exchange"])
    assert resolve("RVX", dirs, sec)["asset_type"] == "fund or trust (not an operating company)"
    assert resolve("WTX", dirs, sec)["asset_type"].startswith("other security: ")


def test_earnings_panel_shows_five_dates_and_folds_the_rest():
    from agent_trading.dashboard.site_overview import EARNINGS_SHOWN, panels
    items = [{"ticker": f"T{i}", "date": f"2026-10-{15 + i}", "list": "large"} for i in range(9)]
    snap = {"bands": {}, "as_of": "2026-10-13", "universe": {}, "events": {"window_days": 45, "items": items, "note": ""}}
    html = panels(snap, None, ["2026-10-13"])
    shown, folded = html.split("<details", 1)
    assert all(f"<strong>T{i}</strong>" in shown for i in range(EARNINGS_SHOWN))
    assert f"{9 - EARNINGS_SHOWN} more" in folded and "<strong>T8</strong>" in folded


# --- accessibility (2026-10-14 cycle): column headers, tab wiring, skip link ----------------------------------

def test_every_column_header_declares_its_scope(site):
    missing = []
    for p in _pages(site):
        for m in re.finditer(r"<th\b[^>]*>", p.read_text(encoding="utf-8")):
            if 'scope="col"' not in m.group(0):
                missing.append(f"{p.relative_to(site)}: {m.group(0)[:60]}")
    assert not missing, missing[:10]
    from agent_trading.dashboard.site import column_headers
    assert column_headers("<thead><tr><th class='num'>A</th><th>B</th></tr></thead>") ==         "<thead><tr><th scope=\"col\" class='num'>A</th><th scope=\"col\">B</th></tr></thead>"
    assert column_headers('<th scope="row">x</th>') == '<th scope="row">x</th>'           # an explicit scope is kept
    from agent_trading.dashboard.assets_research import COMPARE_JS
    assert COMPARE_JS.count("scope = 'col'") == 2                                        # the browser-built table too


def _ids(page: str) -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', page))


def test_tab_lists_name_their_panels_and_panels_name_their_tabs(site):
    for name in ("growth.html", "options.html"):
        page = (site / name).read_text(encoding="utf-8")
        ids = _ids(page)
        tabs = re.findall(r'<button role="tab"[^>]*>', page)
        assert tabs, name
        for tab in tabs:
            tid = re.search(r'\bid="([^"]+)"', tab)
            controls = re.search(r'aria-controls="([^"]+)"', tab)
            assert tid and controls, tab
            for pid in controls.group(1).split():
                assert pid in ids, (name, pid)
                panel = re.search(r'<section[^>]*\bid="' + re.escape(pid) + r'"[^>]*>', page).group(0)
                assert 'role="tabpanel"' in panel and tid.group(1) in re.search(r'aria-labelledby="([^"]+)"', panel).group(1).split()
    options = (site / "options.html").read_text(encoding="utf-8")
    assert options.count('role="tabpanel"') == 6
    assert 'id="opanel-put-6m" role="tabpanel" aria-labelledby="otab-type-put otab-hz-6m"' in options
    assert 'aria-controls="opanel-put-3m opanel-put-6m opanel-put-12m"' in options     # the Puts tab controls three panels
    assert not re.search(r'\bid="(call|put)-(3m|6m|12m)"', options)                   # view hashes stay free of elements


def test_every_page_has_a_skip_link_to_a_focusable_main(site):
    from agent_trading.dashboard.assets import CSS
    for p in _pages(site):
        text = p.read_text(encoding="utf-8")
        assert '<a class="skip" href="#main">Skip to content</a>' in text and '<main id="main" tabindex="-1">' in text, p.name
        assert text.index('class="skip"') < text.index("<header"), p.name              # first in the Tab order
    assert ".skip:focus { left: 16px; }" in CSS
