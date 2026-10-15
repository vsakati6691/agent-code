"""Spec 2026-10-14.5: data states, research panel, 'what changed', comparison, scenario calculator, freshness.

All external services are mocked (tests/dashboard_fixtures.FakeProviders); nothing touches the network."""
from __future__ import annotations

import copy
import json
import re
from datetime import date, timedelta

import pytest

from agent_trading.dashboard import changes, compare, evidence, lab, research, scenarios, spec
from agent_trading.dashboard.http import FetchError
from agent_trading.dashboard.store import Store
from tests.conftest import make_bars
from tests.dashboard_fixtures import AS_OF, FakeProviders, benchmarks, demo_site


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    data, out = demo_site(tmp_path_factory.mktemp("research"))
    store = Store(data)
    snaps = [store.load(d) for d in store.dates()]
    return {"data": data, "out": out, "snaps": snaps}


def a_candidate(demo, band="large"):
    return copy.deepcopy(demo["snaps"][-1]["bands"][band]["candidates"][0])


# --- rules are registered before use ---------------------------------------------------------------------------

def test_display_rules_are_registered_and_hashed():
    assert spec.SPEC_VERSION >= "2026-10-14.5"          # later versions keep these display rules
    assert any(v == "2026-10-14.5" for v, _ in spec.SPEC_CHANGELOG)
    rules = spec.spec_dict()["display_rules"]
    for key in ("watchlist_price", "freshness", "dataset_states", "forensics", "changes", "compare", "scenario_lab"):
        assert key in rules
    assert set(spec.DATASET_STATES) == {"available", "partial", "stale", "missing", "provider_error"}


# --- dataset states (adapted from ticker-dossier coverage records) -------------------------------------------

def _snap_with(events=None, tradability=None, options=None, universe=None):
    return {"as_of": "2026-10-09", "run_finished": "2026-10-10T15:00:00+00:00", "sources": {}, "problems": [],
            "universe": universe or {"sp500_count": 500, "sp500_price_coverage": 1.0, "broad_eligible": 100,
                                     "broad_exclusion_counts": {}},
            "events": events if events is not None else {"window_days": 45, "items": [], "status": "ok"},
            "tradability": tradability or {"verdicts_stored": 10, "to_check": 0, "oldest_check": "2026-10-01T00:00:00+00:00",
                                           "max_age_days": 35},
            "options": options or {"enabled": False, "status": "disabled in configuration"}, "bands": {}}


def _state(snap, name):
    return next(r for r in evidence.datasets(snap) if r["dataset"] == name)


def test_earnings_unavailable_is_never_reported_as_no_events():
    ok_none = _snap_with()
    assert evidence.earnings_state(ok_none)[0] == "available"
    assert "no listed name has a scheduled report" in evidence.earnings_state(ok_none)[1]
    missing = _snap_with(events={"window_days": 45, "items": [], "status": "unavailable", "state": "missing",
                                 "reason": "data unavailable (Alpha Vantage key not configured (ALPHAVANTAGE_API_KEY))"})
    assert _state(missing, "Earnings calendar")["state"] == "missing"
    failed = _snap_with(events={"window_days": 45, "items": [], "status": "unavailable", "state": "provider_error",
                                "reason": "data unavailable (earnings: HTTP 503 after 3 attempts)"})
    assert _state(failed, "Earnings calendar")["state"] == "provider_error"
    # a snapshot from before 2026-10-14.5 only has the note
    old = _snap_with(events={"window_days": 45, "items": [],
                             "note": "Earnings dates unavailable: data unavailable (Alpha Vantage key not configured (X))"})
    assert evidence.earnings_state(old)[0] == "missing"


def test_dataset_states_cover_partial_stale_missing_and_errors():
    snap = _snap_with(universe={"sp500_count": 500, "sp500_price_coverage": 0.95, "broad_eligible": 100,
                                "broad_exclusion_counts": {"no quote": 100}},
                      tradability={"verdicts_stored": 10, "to_check": 0, "oldest_check": "2026-08-01T00:00:00+00:00",
                                   "max_age_days": 35})
    assert _state(snap, "S&P 500 daily prices")["state"] == "partial"
    assert _state(snap, "Broad-universe quotes")["state"] == "provider_error"
    assert _state(snap, "Robinhood tradability verdicts")["state"] == "stale"
    assert _state(snap, "Option chains")["state"] == "missing"
    assert _state(_snap_with(), "S&P 500 daily prices")["state"] == "available"
    assert _state(_snap_with(tradability={"verdicts_stored": 0, "to_check": 3}), "Robinhood tradability verdicts")["state"] == "missing"
    with pytest.raises(ValueError):
        evidence.record("x", "y", "sample", "")      # no sample/fallback state exists


def test_pipeline_records_why_the_earnings_lookup_failed():
    from agent_trading.dashboard.pipeline import run
    from agent_trading.dashboard.tradability import Tradability

    class NoKey(FakeProviders):
        def earnings_calendar(self):
            raise FetchError("Alpha Vantage key not configured (ALPHAVANTAGE_API_KEY)")

    def snap_for(p):
        benchmarks(p)
        for i in range(4):
            p.add(f"S{i:02d}", 100 + i, growth=0.2 + 0.05 * i)
        t = Tradability.all_tradable(list(p.listed), (AS_OF - timedelta(days=1)).isoformat())
        return run(p, AS_OF, None, options_enabled=False, tradability=t)
    s = snap_for(NoKey())
    assert s["events"]["status"] == "unavailable" and s["events"]["state"] == "missing"
    p = FakeProviders()
    p.fail.add("earnings")
    assert snap_for(p)["events"]["state"] == "provider_error"
    ok = snap_for(FakeProviders())
    assert ok["events"]["status"] == "ok" and ok["events"]["state"] == "available"
    assert ok["tradability"]["oldest_check"] and ok["tradability"]["max_age_days"] == spec.TRADABILITY_MAX_AGE_DAYS


# --- watchlist: price verified independently of history length -----------------------------------------------

def test_short_history_keeps_a_verified_price_and_names_what_is_missing():
    from agent_trading.dashboard.pipeline import run
    from agent_trading.dashboard.tradability import Tradability
    from agent_trading.dashboard.watchlist import WatchlistConfig
    p = FakeProviders()
    benchmarks(p)
    p.add("S00", 100, growth=0.3)
    p.listed["NEWF"] = ("Roundhill Example Semiconductor ETF", "Nasdaq", True)
    p.bars["NEWF"] = make_bars(n=40, start=50, drift=0.001, seed=7, end=AS_OF.isoformat())
    p.listed["BADF"] = ("Broken Example Fund ETF", "Nasdaq", True)
    bad = make_bars(n=40, start=50, drift=0.001, seed=8, end=AS_OF.isoformat())
    bad.iloc[-5:, bad.columns.get_loc("close")] = -1.0                  # an invalid price is still rejected
    p.bars["BADF"] = bad
    t = Tradability.all_tradable(list(p.listed), (AS_OF - timedelta(days=1)).isoformat())
    s = run(p, AS_OF, None, options_enabled=False, tradability=t,
            watchlist=WatchlistConfig(("NEWF", "BADF"), "2026-10-14", "test"))
    new = next(e for e in s["watchlist"]["entries"] if e["ticker"] == "NEWF")
    assert new["price"] is not None and new["price_date"] == AS_OF.isoformat()
    assert new["history_bars"] == 40 and "only 40 daily bars" in new["history_note"]
    assert any("only 40 daily bars" in m for m in new["missing"])
    assert new["returns"]["1m"] is not None and new["returns"]["1y"] is None     # each window needs its own history
    bad_e = next(e for e in s["watchlist"]["entries"] if e["ticker"] == "BADF")
    assert bad_e["price"] is None and "no verified as-of price" in bad_e["unavailable_reason"]


# --- return windows and sparkline labels -------------------------------------------------------------------------

def test_return_windows_store_dates_and_the_chart_includes_their_start():
    close = make_bars(n=1400, start=100, drift=0.001, seed=3, end="2026-10-09")["close"]
    h = scenarios.history_stats(close, close * 1.0)
    one = h["returns"]["1y"]
    assert one["start"] == str(close.index[-253].date()) and one["end"] == "2026-10-09" and one["sessions"] == 252
    ch = scenarios.chart_series(close, close)
    for k in ("1m", "3m", "6m", "1y", "3y", "5y"):
        assert h["returns"][k]["start"] in ch["dates"], k
    assert ch["dates"] == sorted(ch["dates"])
    i = ch["dates"].index(one["start"])
    assert ch["stock"][-1] / ch["stock"][i] - 1 == pytest.approx(one["stock"], abs=0.002)   # chart values are rounded


def test_sparkline_label_uses_the_return_tables_figures(demo):
    from agent_trading.dashboard.site_overview import row_spark
    c = a_candidate(demo)
    c["history"]["returns"]["1y"]["stock"] = 4.25           # what the table shows
    c["history"]["returns"]["1y"]["benchmark"] = 0.19
    html = row_spark(c, "SPY")
    assert "+425%" in html and "SPY +19%" in html


# --- freshness in NYSE sessions ----------------------------------------------------------------------------------

def test_freshness_counts_nyse_sessions_not_calendar_days():
    from agent_trading.dashboard.assets import JS
    from agent_trading.dashboard.site import sessions_after
    s = sessions_after("2026-11-25", 10)          # Thanksgiving 2026-11-26 is closed; weekend skipped
    assert s[0] == "2026-11-27" and "2026-11-26" not in s and "2026-11-28" not in s
    assert "America/New_York" in JS and "hour >= 16" in JS and "T21:00:00Z" not in JS


# --- company research panel (adapted from cc-equity-research templates) ------------------------------------------

def test_forensic_checks_follow_the_registered_thresholds(demo):
    c = a_candidate(demo)
    f = c["fundamentals"]
    f["net_income"] = [100.0] * 8
    c["metrics"]["fcf_ttm"] = 400 * 0.9
    assert research.forensics(c)[0]["verdict"] == "Clean"
    c["metrics"]["fcf_ttm"] = 400 * 0.6
    assert research.forensics(c)[0]["verdict"] == "Concerning"
    f["net_income"] = [-1.0] * 8
    assert research.forensics(c)[0]["verdict"] == "Not meaningful"
    c["metrics"]["sbc_to_revenue"] = 0.12
    assert research.forensics(c)[1]["verdict"] == "Concerning"
    c["metrics"]["sbc_to_revenue"] = 0.07
    assert research.forensics(c)[1]["verdict"] == "Watch"
    c["metrics"]["sbc_to_revenue"] = None
    assert research.forensics(c)[1]["verdict"] == "Not measurable"


def test_trends_are_quarterly_and_labelled_with_direction(demo):
    c = a_candidate(demo)
    c["fundamentals"]["revenue"] = [130.0, 120.0, 110.0, 100.0, 100.0, 100.0, 100.0, 100.0]
    t = research.trends(c)[0]
    assert t["label"].startswith("Revenue growth") and t["values"][0] == pytest.approx(0.30)
    assert t["direction"] == "rising" and t["quarters"] == c["fundamentals"]["quarters"][:4]


def test_invalidation_text_is_unchanged_and_conditions_are_checkable(demo):
    c = a_candidate(demo)
    conds = scenarios.thesis_conditions(c["metrics"], c["scenarios"])
    assert [x["text"] for x in conds] == scenarios.invalidation(c["metrics"], c["scenarios"]) == c["invalidation"]
    m = dict(c["metrics"], revenue_growth_ttm=c["metrics"]["revenue_growth_ttm"] / 3, dilution=0.09)
    status = {x["id"]: scenarios.check_condition(x, m, c["fundamentals"])[0] for x in conds}
    assert status["revenue_growth"] == "breached" and status["dilution"] == "breached"
    assert scenarios.check_condition(conds[0], {}, None)[0] == "not measurable"


def test_thesis_check_uses_the_conditions_from_the_first_appearance(demo):
    first, last = demo["snaps"][0], demo["snaps"][-1]
    c = copy.deepcopy(last["bands"]["large"]["candidates"][0])
    orig = next(x for x in first["bands"]["large"]["candidates"] if x["ticker"] == c["ticker"])
    c["metrics"]["revenue_growth_ttm"] = orig["metrics"]["revenue_growth_ttm"] / 4
    th = research.thesis_check(c, demo["snaps"])
    assert th["since"] == str(first["as_of"]) and not th["first_snapshot"]
    original = scenarios.invalidation(orig["metrics"], orig["scenarios"])[0]
    assert th["rows"][0]["text"] == original.replace("today's ", "the ").replace("%)", f"% on {first['as_of']})")
    assert th["rows"][0]["status"] == "breached" and th["breached"] >= 1
    only = research.thesis_check(copy.deepcopy(first["bands"]["large"]["candidates"][0]), demo["snaps"][:1])
    assert only["first_snapshot"]


def test_panel_lists_events_missing_information_and_sources(demo):
    snap = demo["snaps"][-1]
    c = a_candidate(demo)
    from agent_trading.dashboard.site import profile_of
    p = research.panel(c, snap, demo["snaps"], profile_of(snap["bands"]["large"]))
    statuses = {e["status"] for e in p["events"]}
    assert statuses <= {"verified", "unverified", "estimated", "unknown"} and "estimated" in statuses
    assert any("not collected" in x for x in p["missing"])
    assert any(s["url"] and s["url"].startswith("https://data.sec.gov/api/xbrl/companyfacts/CIK") for s in p["sources"])
    assert all(isinstance(x, str) for x in p["support"] + p["counter"] + p["assumptions"])


# --- what changed since the previous snapshot --------------------------------------------------------------------

def test_what_changed_explains_missing_comparisons(demo):
    snap = demo["snaps"][-1]
    c = a_candidate(demo)
    assert changes.compare(c, snap, None)["status"] == "first_snapshot"
    prev = copy.deepcopy(demo["snaps"][0])
    for b in prev["bands"].values():
        b["candidates"] = [x for x in b["candidates"] if x["ticker"] != c["ticker"]]
    r = changes.compare(c, snap, prev)
    assert r["status"] == "not_listed_before" and "was not on any list" in r["notes"][0]


def test_what_changed_finds_filings_deterioration_dilution_breaches_and_data_gaps(demo):
    snap = demo["snaps"][-1]
    prev = copy.deepcopy(demo["snaps"][0])
    c = a_candidate(demo)
    p = next(x for x in prev["bands"]["large"]["candidates"] if x["ticker"] == c["ticker"])
    p["fundamentals"]["last_filed"] = "2026-05-01"
    c["fundamentals"]["last_filed"], c["fundamentals"]["last_form"] = "2026-08-01", "10-Q"
    p["metrics"]["operating_margin"] = c["metrics"]["operating_margin"] + 0.10
    p["metrics"]["dilution"], c["metrics"]["dilution"] = 0.01, 0.07
    c["metrics"]["revenue_growth_ttm"] = p["metrics"]["revenue_growth_ttm"] / 4
    c["missing"] = ["roic"]
    p["missing"] = []
    prev["spec_version"] = "2026-10-13.1"
    r = changes.compare(c, snap, prev)
    kinds = {i["kind"] for i in r["items"]}
    assert {"filing", "deterioration", "dilution", "thesis", "data"} <= kinds
    filing = next(i for i in r["items"] if i["kind"] == "filing")
    assert filing["source"].startswith("https://www.sec.gov/cgi-bin/browse-edgar") and filing["date"] == "2026-08-01"
    assert any("rules version changed" in n for n in r["notes"])
    assert all(i["date"] for i in r["items"])


# --- comparison (adapted from filingcopilot comparison.py) ---------------------------------------------------------

def _entry(t, q="2026-06-30", profile="standard", bench="SPY", kind="listed", dates=None, values=None):
    return {"ticker": t, "kind": kind, "price_date": "2026-10-09", "profile": profile, "benchmark": bench,
            "period": {"latest_quarter": q}, "chart": {"dates": dates or [], "values": values or []},
            "returns": {"1y": {"start": "2025-10-08"}}}


def test_comparability_flags_mismatched_periods_profiles_and_benchmarks():
    assert compare.comparability([_entry("A")])[0].startswith("Choose 2 to 4")
    assert compare.comparability([_entry(t) for t in "ABCDE"])[0].startswith("Choose 2 to 4")
    assert compare.comparability([_entry("A"), _entry("B", q="2026-07-15")]) == []      # 15 days apart: same period
    flags = compare.comparability([_entry("A"), _entry("B", q="2026-09-03", profile="long_horizon", bench="IWM")])
    assert any("different periods" in f for f in flags)
    assert any("different scoring profiles" in f for f in flags)
    assert any("different benchmarks" in f for f in flags)
    w = compare.comparability([_entry("A"), _entry("W", q=None, profile=None, bench=None, kind="watchlist")])
    assert any("not scored" in f for f in w) and any("cannot be period-matched" in f for f in w)


def test_rebase_uses_only_common_dates_without_interpolation():
    a = _entry("A", dates=["2026-01-02", "2026-01-09", "2026-01-16", "2026-01-23"], values=[100, 110, 120, 130])
    b = _entry("B", dates=["2026-01-09", "2026-01-16", "2026-01-30"], values=[50, 40, 45])
    r = compare.rebase_common([a, b])
    assert r["found"] and r["start"] == "2026-01-09" and r["end"] == "2026-01-16" and r["common_days"] == 2
    sa, sb = r["series"]
    assert sa["points"][0][1] == 100 and sb["points"][-1][1] == pytest.approx(80.0)
    assert sa["omitted"] == 2 and sb["omitted"] == 1
    assert not compare.rebase_common([a, _entry("C", dates=["2027-01-01"], values=[1])])["found"]
    assert compare.window_start([a, b], "1y", "2026-10-09", 1) == "2025-10-08"
    b["returns"]["1y"]["start"] = None
    assert compare.window_start([a, b], "1y", "2026-10-09", 1) == "2025-10-09"


def test_comparison_payload_is_one_entry_per_ticker_with_matching_basis(demo):
    snap = demo["snaps"][-1]
    data = compare.payload(snap, {k: b.get("profile", "standard") for k, b in snap["bands"].items()})
    tickers = [e["ticker"] for e in data["entries"]]
    assert len(tickers) == len(set(tickers)) >= 4
    assert {e["price_date"] for e in data["entries"] if e["kind"] == "listed"} == {str(snap["as_of"])}
    assert all(e["period"]["currency"] == "USD" for e in data["entries"])
    spec_listed = next(e for e in data["entries"] if e["kind"] == "listed")
    assert spec_listed["returns"]["1y"]["sessions"] == 252
    packed = compare.pack(data)
    assert all("dates" not in e["chart"] for e in packed["entries"])
    assert len(packed["date_sets"]) <= len(packed["entries"])
    e0 = packed["entries"][0]
    assert packed["date_sets"][e0["chart"]["dset"]] == data["entries"][0]["chart"]["dates"]


# --- interactive scenarios (published formula on the visitor's inputs) ----------------------------------------------

def test_calculator_reset_reproduces_the_published_base_case(demo):
    n = 0
    for band in demo["snaps"][-1]["bands"].values():
        for c in band["candidates"]:
            inp = lab.inputs(c)
            if not inp:
                continue
            n += 1
            out = lab.run(inp, inp["published"])
            for y in inp["years"]:
                assert out[y]["value_per_share"] == pytest.approx(c["scenarios"]["base"]["years"][str(y)]["value_per_share"],
                                                                rel=1e-12)
    assert n >= 3


def test_calculator_responds_to_inputs_and_keeps_them_in_bounds(demo):
    c = next(c for b in demo["snaps"][-1]["bands"].values() for c in b["candidates"] if lab.inputs(c))
    inp = lab.inputs(c)
    base = lab.run(inp, inp["published"])
    y = inp["years"][-1]
    up = lab.run(inp, dict(inp["published"], starting_revenue_growth=inp["published"]["starting_revenue_growth"] + 0.10))
    assert up[y]["value_per_share"] > base[y]["value_per_share"]
    more_shares = lab.run(inp, dict(inp["published"], annual_dilution=0.05))
    assert more_shares[y]["value_per_share"] < base[y]["value_per_share"] or inp["published"]["annual_dilution"] >= 0.05
    wild = lab.run(inp, dict(inp["published"], exit_ev_to_sales=10_000))
    capped = lab.run(inp, dict(inp["published"], exit_ev_to_sales=inp["bounds"]["exit_ev_to_sales"][1]))
    assert wild[y]["value_per_share"] == capped[y]["value_per_share"]
    for k, (lo, hi) in inp["bounds"].items():
        v = inp["published"].get(k)
        assert v is None or lo <= v <= hi           # bounds always contain the published value
    m = lab.run(inp, dict(inp["published"], fcf_margin=0.2))
    assert m[y]["ev_to_fcf"] == pytest.approx(m[y]["revenue"] * m[y]["ev_to_sales"] / (m[y]["revenue"] * 0.2))
    assert m[y]["value_per_share"] == base[y]["value_per_share"]        # margins never change the EV/Sales value


def test_calculator_script_mirrors_the_reference():
    from agent_trading.dashboard.assets_research import LAB_JS
    for token in ("inp.fade * (inp.terminal - g)", "Math.pow(1 + d, y)", "(rev * mult + inp.net_cash) / sh",
                  "data-shown", "Reset to the published base-case assumptions."):
        assert token in LAB_JS, token
    assert "localStorage" not in LAB_JS and "fetch(" not in LAB_JS and "XMLHttpRequest" not in LAB_JS


# --- the built site ---------------------------------------------------------------------------------------------

def test_site_has_compare_page_research_panels_and_data_status(demo):
    out = demo["out"]
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="compare.html"' in idx and "What changed since the previous snapshot?" in idx
    cmp_page = (out / "compare.html").read_text(encoding="utf-8")
    assert 'id="cmp-data"' in cmp_page and "assets/compare.js" in cmp_page and (out / "assets" / "compare.js").exists()
    data = json.loads(re.search(r'<script type="application/json" id="cmp-data">(.*?)</script>', cmp_page, re.S)[1])
    assert data["rules"]["max_names"] == 4 and data["date_sets"]
    # A newly ranked first name may not have a previous record. Test comparison on a common name.
    common = set.intersection(*({c["ticker"] for c in s["bands"]["large"]["candidates"]} for s in demo["snaps"]))
    assert common
    stock = (out / "stock" / f"large-{sorted(common)[0]}.html").read_text(encoding="utf-8")
    for text in ("Company research panel", "Earnings-quality checks", "Thesis conditions", "Missing information",
                 "Sources and dates", "Evidence quality", "Try your own assumptions", "Your experiment",
                 "What changed since the previous snapshot?", "Compared with the snapshot of", "assets/lab.js"):
        assert text in stock, text
    audit = (out / "audit.html").read_text(encoding="utf-8")
    assert 'id="data-status"' in audit and "Earnings calendar" in audit and "Option chains" in audit
    assert "sample" not in re.sub(r"(?s)<[^>]+>", " ", audit).lower().replace("sample or", "")


def test_lab_json_in_pages_contains_no_account_fields(demo):
    for p in (demo["out"] / "stock").glob("*.html"):
        m = re.search(r"data-lab='([^']*)'", p.read_text(encoding="utf-8"))
        if m:
            blob = m[1].lower()
            for word in ("account", "position", "quantity", "cost_basis", "balance"):
                assert word not in blob, (p.name, word)


def test_events_say_whether_the_calendar_lookup_worked(demo):
    c = a_candidate(demo)
    c["next_earnings"] = None
    snap = demo["snaps"][-1]
    ok_note = research.events(c, str(snap["as_of"]), snap)[0]["note"]
    assert "lookup succeeded but lists no date" in ok_note
    failed = dict(snap, events={"window_days": 45, "items": [], "status": "unavailable", "state": "provider_error",
                                "reason": "HTTP 503"})
    assert "lookup was unavailable" in research.events(c, str(snap["as_of"]), failed)[0]["note"]


def test_empty_and_unavailable_states_render_honestly():
    from agent_trading.dashboard.site_compare import compare_page
    from agent_trading.dashboard.site_research import lab_section
    page = compare_page({"as_of": "2026-10-09", "entries": [], "groups": [], "returns": [], "rules": spec.COMPARE_RULES})
    assert "Not enough companies" in page and 'id="cmp-pick"' not in page
    assert "Not available: no published scenario" in lab_section(None)
    from agent_trading.dashboard.site_overview import panels
    snap = {"bands": {}, "as_of": "2026-10-13", "universe": {}, "sources": {}, "events": {
        "window_days": 45, "items": [], "status": "unavailable", "state": "missing", "reason": "key not configured",
        "note": "Earnings dates unavailable: key not configured"}}
    html = panels(snap, None, ["2026-10-13"])
    assert "could not be collected" in html and "No earnings scheduled" not in html
    assert "No earlier snapshot is stored" in html


def test_original_conditions_are_dated_not_called_today(demo):
    first, last = demo["snaps"][0], demo["snaps"][-1]
    c = copy.deepcopy(last["bands"]["large"]["candidates"][0])
    rows = research.thesis_check(c, demo["snaps"])["rows"]
    assert all("today's" not in r["text"] for r in rows)
    assert any(f"on {first['as_of']}" in r["text"] for r in rows)
