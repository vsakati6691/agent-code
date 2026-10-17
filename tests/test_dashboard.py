"""Research dashboard: ranking, missing/stale data, scenarios, options, snapshots, automation failures, site build."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, date, timedelta

import numpy as np
import pandas as pd
import pytest

from agent_trading.dashboard import options as opt
from agent_trading.dashboard import scenarios, scoring, spec, tracking
from agent_trading.dashboard.__main__ import main as cli
from agent_trading.dashboard.fundamentals import build, growth, ttm
from agent_trading.dashboard.pipeline import RunFailed, as_of_for, rank_changes, run
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.store import IntegrityError, SnapshotExists, Store
from agent_trading.dashboard.tradability import Tradability, TradabilityError, parse_results
from tests.conftest import make_bars
from tests.dashboard_fixtures import AS_OF, FakeProviders, benchmarks, make_facts, option_row

# --- spec ------------------------------------------------------------------------------------------


def test_spec_is_complete_and_hash_is_stable():
    assert abs(sum(c.weight for c in spec.COMPONENTS) - 1) < 1e-12
    assert spec.spec_hash() == spec.spec_hash()
    assert {m for c in spec.COMPONENTS for m in c.metrics} <= set(spec.METRIC_NOTES)
    assert any(c.key == "momentum" for c in spec.COMPONENTS) and any(c.key == "relative" for c in spec.COMPONENTS)
    assert "upside" not in json.dumps(spec.OPTION_RANKING).lower().replace("is deliberately not", "")


def test_scale_bounds_reverse_and_missing():
    s = spec.Scale(0.0, 0.4)
    assert scoring.scale(0.2, s) == pytest.approx(0.5)
    assert scoring.scale(-1, s) == 0 and scoring.scale(9, s) == 1
    assert scoring.scale(None, s) == 0 and scoring.scale(float("inf"), s) == 0
    r = spec.Scale(0.0, 4.0, reverse=True)
    assert scoring.scale(0.0, r) == 1 and scoring.scale(4.0, r) == 0 and scoring.scale(float("inf"), r) == 0


# --- fundamentals -------------------------------------------------------------------------------------


def test_fundamentals_are_point_in_time():
    facts = make_facts(filed_lag=40)  # newest quarter ends 2026-06-30, filed 2026-08-09
    before = build(facts, date(2026, 8, 1))
    after = build(facts, date(2026, 8, 10))
    assert after.quarters[0] == "2026-06-30"
    assert before.quarters[0] == "2026-03-31"  # the June quarter was not yet filed
    assert before.last_filed < "2026-08-01"


def test_fourth_quarter_is_derived_from_annual_facts():
    facts = make_facts(quarters=4, last=date(2025, 9, 30))
    rev = facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    q4 = [f for f in rev if f["end"] == "2024-12-31"][0]
    q1to3 = sum(f["val"] for f in rev if f["end"] in ("2024-03-31", "2024-06-30", "2024-09-30"))
    # replace the discrete Q4 2024 with a fiscal-year 10-K fact (as most companies report it)
    rev.remove(q4)
    rev.append(
        {"start": "2024-01-01", "end": "2024-12-31", "val": q4["val"] + q1to3, "form": "10-K", "filed": "2025-02-15"}
    )
    for e, s in (("2024-03-31", "2024-01-01"), ("2024-06-30", "2024-01-01"), ("2024-09-30", "2024-01-01")):
        rev.append(
            {
                "start": s,
                "end": e,
                "val": sum(
                    f["val"]
                    for f in rev
                    if f.get("end") in [x for x in ("2024-03-31", "2024-06-30", "2024-09-30") if x <= e]
                    and f["form"] == "10-Q"
                    and (date.fromisoformat(f["end"]) - date.fromisoformat(f["start"])).days < 100
                ),
                "form": "10-Q",
                "filed": "2024-11-01",
            }
        )
    f = build(facts, date(2025, 12, 1))
    i = f.quarters.index("2024-12-31")
    assert f.flows["revenue"][i] == pytest.approx(q4["val"]) and f.derived["revenue"][i]


def test_ttm_and_growth_on_non_positive_base():
    assert ttm([1, 2, 3, 4, 5]) == 10 and ttm([1, None, 3, 4]) is None and ttm([1, 2]) is None
    assert growth(110, 100) == pytest.approx(0.1)
    assert growth(5, 0) is None and growth(5, -3) is None


# --- scoring --------------------------------------------------------------------------------------------


def _metrics(**over):
    f = build(make_facts(), AS_OF)
    close = make_bars(n=600, drift=0.001, seed=1, end=AS_OF.isoformat())["close"]
    bench = make_bars(n=600, drift=0.0003, seed=2, end=AS_OF.isoformat())["close"]
    m = scoring.compute_metrics(f, close, bench, 1e10)
    m.update(over)
    return m, f


def test_dilution_falls_back_one_quarter_when_the_latest_is_a_fiscal_q4():
    """Spec 2026-10-14.4: a fiscal Q4 has only a full-year diluted share count (MU, STX, WDC in October 2026)."""
    close = make_bars(n=600, drift=0.001, seed=1, end=AS_OF.isoformat())["close"]
    bench = make_bars(n=600, drift=0.0003, seed=2, end=AS_OF.isoformat())["close"]
    f = build(make_facts(), AS_OF)
    full = scoring.compute_metrics(f, close, bench, 1e10)["dilution"]
    assert full == pytest.approx(f.diluted_shares[0] / f.diluted_shares[4] - 1)
    q4 = replace(f, diluted_shares=[None] + f.diluted_shares[1:4] + [None] + f.diluted_shares[5:])
    assert scoring.compute_metrics(q4, close, bench, 1e10)["dilution"] == pytest.approx(
        f.diluted_shares[1] / f.diluted_shares[5] - 1
    )
    two_back = replace(f, diluted_shares=[None, None] + f.diluted_shares[2:])
    assert scoring.compute_metrics(two_back, close, bench, 1e10)["dilution"] is None  # at most one quarter back
    assert spec.DILUTION_LOOKBACK_QUARTERS == 1 and spec.spec_dict()["dilution_lookback_quarters"] == 1


def test_missing_input_scores_zero_without_reweighting():
    m, f = _metrics()
    full = scoring.score_one("X", m, f, [])
    m2 = dict(m, sbc_to_revenue=None)
    part = scoring.score_one("X", m2, f, [])
    assert "sbc_to_revenue" in part.missing and part.sub_scores["sbc_to_revenue"] == 0
    weight = spec.COMPONENTS[3].weight / len(spec.COMPONENTS[3].metrics)
    assert part.composite == pytest.approx(full.composite - 100 * weight * full.sub_scores["sbc_to_revenue"], abs=0.01)
    assert part.confidence < full.confidence


def test_critical_component_missing_or_thin_evidence_is_not_ranked():
    m, f = _metrics()
    s = scoring.score_one("X", dict(m, return_12_1=None), f, [])
    assert s.composite is None and "Price momentum" in s.excluded_reason and "missing" in s.counterargument.lower()
    thin = {k: None for k in ("revenue_cagr_3y", "growth_consistency", "fcf_growth_ttm", "roic", "accruals")}
    s = scoring.score_one("X", dict(m, **thin), f, [])
    assert s.composite is None and "too little evidence" in s.excluded_reason


def test_ranking_is_deterministic_monotonic_and_order_independent():
    m, f = _metrics()
    a = scoring.score_one("AAA", m, f, [])
    b = scoring.score_one("BBB", m, f, [])  # identical evidence -> tie broken by ticker
    better = scoring.score_one("CCC", dict(m, revenue_growth_ttm=m["revenue_growth_ttm"] + 0.1), f, [])
    assert better.composite >= a.composite
    r1 = [s.ticker for s in scoring.rank([b, better, a])]
    r2 = [s.ticker for s in scoring.rank([a, b, better])]
    assert r1 == r2 and r1.index("AAA") < r1.index("BBB")
    assert [s.rank for s in scoring.rank([a, b, better])] == [1, 2, 3]


def test_counterargument_names_the_weakest_weighted_input():
    m, f = _metrics(fcf_yield=-0.5)
    s = scoring.score_one("X", m, f, [])
    assert s.counterargument


def test_implied_growth():
    g = scoring.implied_revenue_cagr(ev=3e9 * 1.09**-5 * 1.0, revenue=1e9)
    assert g == pytest.approx(0.0, abs=1e-9)  # EV that only needs flat revenue at 3x exit
    assert scoring.implied_revenue_cagr(None, 1e9) is None and scoring.implied_revenue_cagr(1e9, 0) is None


# --- scenarios ----------------------------------------------------------------------------------------


def test_scenario_math_matches_hand_calculation():
    sc = scenarios.scenario_table(
        price=10.0,
        shares=100.0,
        revenue_ttm=100.0,
        revenue_growth=0.30,
        ev_to_sales=10.0,
        net_cash=0.0,
        fcf_margin=0.1,
        dilution=0.0,
    )
    path = scenarios.growth_path(0.30, 5)
    rev1 = 100 * (1 + path[0])
    exit_mult = 10 * 0.75
    mult1 = 10 + (exit_mult - 10) / 5
    assert sc["base"]["years"][1]["value_per_share"] == pytest.approx(rev1 * mult1 / 100)
    for y in spec.SCENARIO_YEARS:
        assert (
            sc["bear"]["years"][y]["value_per_share"]
            <= sc["base"]["years"][y]["value_per_share"]
            <= sc["bull"]["years"][y]["value_per_share"]
        )
    assert sc["bear"]["assumptions"]["exit_ev_to_sales"] == pytest.approx(5.0)
    assert set(sc["flags"]) == {"bull_doubles_in_5y", "bull_multibagger_5y"}


def test_scenario_growth_is_capped_and_inputs_validated():
    sc = scenarios.scenario_table(10, 100, 100, 3.0, 5, 0, None, None)
    assert sc["base"]["assumptions"]["starting_revenue_growth"] == spec.SCENARIO_GROWTH_CAP
    with pytest.raises(ValueError):
        scenarios.scenario_table(0, 100, 100, 0.1, 5, 0, None, None)
    with pytest.raises(ValueError):
        scenarios.scenario_table(10, 100, float("nan"), 0.1, 5, 0, None, None)


def test_multibagger_flag_needs_five_x():
    sc = scenarios.scenario_table(1.0, 1.0, 1.0, 0.60, 20.0, 0.0, None, 0.0)
    bull5 = sc["bull"]["years"][5]["multiple_of_price"]
    assert sc["flags"]["bull_multibagger_5y"] == (bull5 >= 5) and sc["flags"]["bull_doubles_in_5y"] == (bull5 >= 2)


def test_history_stats_and_drawdown():
    close = pd.Series([100, 120, 60, 90, 150.0], index=pd.bdate_range("2026-01-01", periods=5))
    dd, peak, trough = scenarios.max_drawdown(close)
    assert dd == pytest.approx(-0.5) and peak == "2026-01-02" and trough == "2026-01-05"


# --- options ----------------------------------------------------------------------------------------------


def test_payoff_breakeven_and_max_loss():
    assert opt.payoff_at_expiry(120, 100, 5) == 15 and opt.payoff_at_expiry(90, 100, 5) == -5
    row = option_row("ABC", AS_OF + timedelta(days=90), 100, 4.9, 5.1)
    r = opt.research_row(row, 100.0, AS_OF, "ABC", [])
    assert r["breakeven"] == pytest.approx(105.1) and r["max_loss_per_contract"] == pytest.approx(510)
    worst = min(p["pl_per_contract"] for p in r["payoffs"])
    assert worst == pytest.approx(-510)  # a long call can lose at most the premium
    assert r["premium_per_contract_ask"] == pytest.approx(510) and r["multiplier"] == 100


def test_black_scholes_reference_value():
    assert opt.bs_call(100, 100, 1.0, 0.2, 0.04) == pytest.approx(9.925, abs=0.01)
    assert opt.bs_call(120, 100, 0, 0.2) == 20


@pytest.mark.parametrize(
    "over, why",
    [
        ({"bid": 4.0, "ask": 6.0}, "spread too wide"),
        ({"oi": 100}, "open interest too low"),
        ({"vol": 0}, "volume too low"),
        ({"delta": 0.9}, "delta outside"),
        ({"root": "ABC1"}, "adjusted"),
        ({"bid": 0.0, "ask": 0.1}, "no two-sided"),
    ],
)
def test_option_eligibility_rules(over, why):
    kw = {"bid": 4.9, "ask": 5.1}
    kw.update(over)
    ok, reason = opt.eligible(option_row("ABC", AS_OF + timedelta(days=90), 100, **kw), "ABC", AS_OF)
    assert not ok and why in reason


def test_horizons_rank_without_upside_and_cap_per_underlying():
    exp = AS_OF + timedelta(days=90)
    rows = [
        option_row("ABC", exp, k, b, b + 0.1, delta=d)
        for k, b, d in ((95, 8.0, 0.65), (100, 5.0, 0.55), (105, 3.0, 0.45), (110, 1.6, 0.32))
    ]
    chains = {"ABC": ({"symbol": "ABC", "close": 100.0, "last_trade_time": f"{AS_OF}T16:00:00"}, rows)}
    out = opt.build_horizons(chains, AS_OF, {})
    got = out["3m"]["calls"]["rows"]
    assert len(got) == spec.OPTION_RULES["max_per_underlying_per_horizon"]
    assert all({"liquidity", "breakeven", "time_decay", "total"} <= set(x["rank_components"]) for x in got)
    assert not any("upside" in k for x in got for k in x["rank_components"])
    assert out["6m"]["calls"]["status"].startswith("no call") and out["6m"]["calls"]["rows"] == []


def test_stale_or_missing_chain_shows_unavailable_not_invented():
    exp = AS_OF + timedelta(days=90)
    stale = {"symbol": "ABC", "close": 100.0, "last_trade_time": f"{AS_OF - timedelta(days=3)}T16:00:00"}
    out = opt.build_horizons({"ABC": (stale, [option_row("ABC", exp, 100, 4.9, 5.1)]), "XYZ": "HTTP 403"}, AS_OF, {})
    assert out["3m"]["calls"]["rows"] == [] and out["3m"]["calls"]["status"].startswith("unavailable")
    assert out["3m"]["puts"]["rows"] == [] and out["3m"]["puts"]["status"].startswith("unavailable")
    assert "stale chain" in out["chain_problems"]["ABC"] and out["chain_problems"]["XYZ"] == "HTTP 403"


def test_events_before_expiry_and_flags():
    row = option_row("ABC", AS_OF + timedelta(days=90), 100, 4.9, 5.1)
    ev = [
        {"date": AS_OF + timedelta(days=20), "event": "earnings"},
        {"date": AS_OF + timedelta(days=200), "event": "x"},
    ]
    r = opt.research_row(row, 100.0, AS_OF, "ABC", ev)
    assert [e["event"] for e in r["events_before_expiry"]] == ["earnings"]
    assert any("delayed" in f for f in r["flags"])
    assert "not a calibrated probability" in spec.DELTA_STATEMENT.lower().replace("not a\ncalibrated", "")


# --- snapshots ---------------------------------------------------------------------------------------------


def test_snapshot_is_write_once_and_tamper_evident(tmp_path):
    st = Store(tmp_path)
    st.write_snapshot({"as_of": "2026-10-09", "status": "ok", "bands": {}})
    with pytest.raises(SnapshotExists):
        st.write_snapshot({"as_of": "2026-10-09", "status": "ok", "bands": {"x": 1}})
    p = tmp_path / "snapshots" / "2026-10-09" / "snapshot.json"
    p.write_text(p.read_text().replace("ok", "OK"))
    with pytest.raises(IntegrityError):
        st.load("2026-10-09")
    assert st.verify_all() and [e["event"] for e in st.audit_log()] == ["snapshot_written"]


@pytest.mark.parametrize("bad", [{"account_number": "x"}, {"bands": {"large": {"positions": []}}}, {"apikey": "k"}])
def test_snapshot_refuses_private_fields(tmp_path, bad):
    with pytest.raises(IntegrityError):
        Store(tmp_path).write_snapshot({"as_of": "2026-10-09", **bad})


def test_audit_log_is_append_only(tmp_path):
    st = Store(tmp_path)
    st.audit("a")
    st.audit("b", x=1)
    first = (tmp_path / "audit.jsonl").read_text()
    st.audit("c")
    assert (tmp_path / "audit.jsonl").read_text().startswith(first)


# --- tracking -------------------------------------------------------------------------------------------------


def test_forward_returns_never_look_ahead_and_report_delisting():
    idx = pd.bdate_range("2026-01-01", periods=60)
    up = pd.Series(range(100, 160), index=idx, dtype=float)
    r, status = tracking.forward_return(up, idx[0].date(), 21, idx[-1].date())
    assert status == "ok" and r == pytest.approx(up.iloc[21] / up.iloc[0] - 1)
    r, status = tracking.forward_return(up, idx[50].date(), 21, idx[-1].date())
    assert r is None and status == "pending"  # future prices are not available yet
    gone = up.iloc[:10]
    r, status = tracking.forward_return(gone, idx[0].date(), 21, idx[-1].date())
    assert r is None and "delisting" in status


def test_forward_return_counts_nyse_sessions_not_weekdays():
    """Regression (2026-10-14): 2026-01-19 (MLK Day) has no bar. Twenty-one weekdays after 2026-01-02 is only 20
    sessions, and weekday counting reported every complete series as a possible delisting on that day."""
    from agent_trading.market_calendar import is_trading_day

    days = [d for d in pd.bdate_range("2026-01-02", "2026-03-31") if is_trading_day(d.date())]
    assert pd.Timestamp("2026-01-19") not in days
    close = pd.Series(range(100, 100 + len(days)), index=pd.DatetimeIndex(days), dtype=float)
    start = date(2026, 1, 2)
    assert (
        tracking.sessions_elapsed(start, date(2026, 2, 2)) == 20 and int(np.busday_count(start, date(2026, 2, 2))) == 21
    )
    assert tracking.forward_return(close[close.index <= "2026-02-02"], start, 21, date(2026, 2, 2)) == (None, "pending")
    r, status = tracking.forward_return(close[close.index <= "2026-02-03"], start, 21, date(2026, 2, 3))
    assert status == "ok" and r == pytest.approx(close.iloc[21] / close.iloc[0] - 1)
    # a series that really stops before the as-of session is still reported as a possible delisting
    r, status = tracking.forward_return(close.iloc[:10], start, 21, date(2026, 3, 31))
    assert r is None and status.startswith("prices stop on 2026-01-15") and "delisting" in status
    # a vendor gap (a session without a bar) is named as such, never bridged or called a delisting
    gap = close[close.index <= "2026-02-03"].drop(pd.Timestamp("2026-01-27"))
    r, status = tracking.forward_return(gap, start, 21, date(2026, 2, 3))
    assert r is None and status == "missing bars: only 20 of 21 sessions after 2026-01-02 have a close"
    # the tracking schedule shown on the site uses the same calendar: results appear when the sessions have passed
    from agent_trading.dashboard.fmt import tracking_schedule

    assert "1-month results from about 2026-02-03" in tracking_schedule(["2026-01-02"])


def test_tracking_applies_friction_turnover_and_never_claims_edge():
    idx = pd.bdate_range("2026-01-01", periods=80)
    prices = {t: pd.Series([100 * (1.001**i) for i in range(80)], index=idx) for t in ("A", "B", "C", "SPY")}
    snaps = [
        {
            "as_of": str(idx[0].date()),
            "spec_version": "v",
            "bands": {"large": {"candidates": [{"ticker": "A"}, {"ticker": "B"}]}},
        },
        {
            "as_of": str(idx[5].date()),
            "spec_version": "v",
            "bands": {"large": {"candidates": [{"ticker": "A"}, {"ticker": "C"}]}},
        },
    ]
    out = tracking.track(snaps, prices, idx[-1].date())
    h = out["by_snapshot"][0]["horizons"]["1m"]
    assert h["status"] == "ok" and h["net"] == pytest.approx(h["gross"] - 2 * 15 / 1e4)
    assert out["turnover"]["large"][0]["turnover"] == pytest.approx(0.5)
    assert "No edge is claimed" in out["evidence_note"]


# --- pipeline with fake providers -------------------------------------------------------------------------------


def ok_all(p: FakeProviders) -> Tradability:
    return Tradability.all_tradable(list(p.listed), "2026-10-08")


@pytest.fixture
def prov():
    p = FakeProviders()
    benchmarks(p)
    for i in range(12):  # S&P 500 members, varied growth
        p.add(f"S{i:02d}", 100 + i, growth=0.05 + 0.04 * i, drift=0.0004 + 0.0001 * i, shares=5e8)
    p.add("MIDA", 300, sp=False, shares=4e7, drift=0.0003, growth=0.25)  # ~$5B
    p.add("SPEC", 301, sp=False, shares=8e6, drift=0.0003, growth=0.50)  # ~$1B
    p.add("SLOW", 302, sp=False, shares=8e6, drift=0.0003, growth=0.05)  # ~$1B, slow growth
    p.listed["WARR"] = ("Foo Corp Warrants", "Nasdaq", False)
    p.listed["FUND"] = ("Some ETF", "NYSE Arca", True)
    return p


def test_run_builds_ranked_lists_with_reasons(prov):
    snap = run(prov, AS_OF, options_enabled=False, tradability=ok_all(prov))
    large = snap["bands"]["large"]
    assert len(large["candidates"]) == 10 and [c["rank"] for c in large["candidates"]] == list(range(1, 11))
    assert snap["status"] == "ok" and snap["spec_hash"] == spec.spec_hash()
    small = [c["ticker"] for c in snap["bands"]["small"]["candidates"]]
    assert small[0] == "SPEC" and "SLOW" in small  # small cap has no growth gate (spec .2)
    assert snap["bands"]["small"]["shortfall_note"]  # fewer than 10 are not padded
    assert len(snap["bands"]["multibagger"]["candidates"]) <= 5
    counts = snap["universe"]["broad_exclusion_counts"]
    assert counts.get("ETF or fund") == 1 and any("warrant" in k for k in counts)
    c = large["candidates"][0]
    for key in ("thesis", "bear_case", "risks", "invalidation", "scenarios", "history", "counterargument"):
        assert c[key]
    assert c["probability"] == spec.PROBABILITY_STATEMENT
    blob = json.dumps(snap)
    assert "account_number" not in blob and not re.search(r"(?<![\d.])1234(?!\d)", blob)


def test_stale_price_and_missing_fundamentals_are_excluded_with_reasons(prov):
    prov.bars["S01"] = prov.bars["S01"].iloc[:-3]  # no bar for the as-of session
    prov.bars["S01"].index = prov.bars["S01"].index  # history and quote both stale
    del prov.facts[102]
    snap = run(prov, AS_OF, options_enabled=False, tradability=ok_all(prov))
    ex = {x["ticker"]: x["reason"] for x in snap["bands"]["large"]["excluded"]}
    assert "stale" in ex["S01"] and "unavailable" in ex["S02"]
    assert "S01" not in [c["ticker"] for c in snap["bands"]["large"]["candidates"]]


def test_missing_benchmark_or_reference_data_fails_the_run(prov):
    del prov.bars["SPY"]
    with pytest.raises(RunFailed, match="benchmark SPY"):
        run(prov, AS_OF, options_enabled=False, tradability=ok_all(prov))
    p2 = FakeProviders()
    p2.fail.add("sp500")
    with pytest.raises(RunFailed, match="reference data"):
        run(p2, AS_OF)


def test_low_sp500_coverage_fails_instead_of_publishing_partial_ranking(prov):
    for t in [f"S{i:02d}" for i in range(3)]:
        del prov.bars[t]
    with pytest.raises(RunFailed, match="S&P 500"):
        run(prov, AS_OF, options_enabled=False, tradability=ok_all(prov))


def test_holiday_as_of_is_refused_and_as_of_rule():
    with pytest.raises(RunFailed, match="not an NYSE trading day"):
        run(FakeProviders(), date(2026, 12, 25))
    from datetime import datetime

    assert as_of_for(datetime(2026, 10, 10, 14, 17, tzinfo=UTC)) == date(2026, 10, 9)  # Saturday run
    assert as_of_for(datetime(2026, 4, 4, 14, 17, tzinfo=UTC)) == date(2026, 4, 2)  # Good Friday


def test_one_share_class_per_company(prov):
    prov.add("S00B", 100, name="S00 Class B Common Stock", volume=100_000, shares=5e8)
    prov.facts[100] = make_facts(100, shares=5e8, growth=0.05)
    snap = run(prov, AS_OF, options_enabled=False, tradability=ok_all(prov))
    ex = {x["ticker"]: x["reason"] for x in snap["bands"]["large"]["excluded"]}
    assert "another share class" in ex["S00B"]


def test_options_section_uses_only_valid_chains(prov):
    exp = AS_OF + timedelta(days=95)
    snap0 = run(prov, AS_OF, options_enabled=False, tradability=ok_all(prov))
    top = snap0["bands"]["large"]["candidates"][0]["ticker"]
    spot = prov.bars[top]["close"].iloc[-1]
    prov.chains[top] = (
        {"symbol": top, "close": spot, "last_trade_time": f"{AS_OF}T16:00:00"},
        [option_row(top, exp, round(spot), spot * 0.05, spot * 0.051)],
    )
    snap = run(prov, AS_OF, options_enabled=True, tradability=ok_all(prov))
    o = snap["options"]
    assert o["status"] == "ok" and o["3m"]["calls"]["rows"][0]["underlying"] == top
    assert len(o["chain_problems"]) == 9  # the other candidates have no chain
    assert o["12m"]["calls"]["rows"] == [] and o["3m"]["puts"]["rows"] == []


def test_rank_changes_explained():
    prev = [
        {"ticker": "A", "rank": 1, "components": {"growth": 0.9}},
        {"ticker": "B", "rank": 2, "components": {"growth": 0.5}},
    ]
    cur = [
        {"ticker": "B", "rank": 1, "components": {"growth": 0.8}},
        {"ticker": "C", "rank": 2, "components": {"growth": 0.7}},
    ]
    ch = {c["ticker"]: c for c in rank_changes(cur, prev)}
    assert ch["B"]["change"] == 1 and "growth +30.0" in ch["B"]["explanation"]
    assert ch["C"]["change"] == "new" and ch["A"]["change"] == "dropped"


# --- CLI, automation failures and site build ---------------------------------------------------------------------


@pytest.fixture
def cli_env(monkeypatch, prov):
    monkeypatch.setenv("SEC_USER_AGENT", "test research test@example.com")
    monkeypatch.setattr("agent_trading.dashboard.__main__._providers", lambda cache: prov)
    monkeypatch.setattr("agent_trading.dashboard.__main__.Tradability.load", lambda root: ok_all(prov))
    return prov


def test_cli_failed_run_keeps_last_snapshot_and_site_shows_stale_banner(tmp_path, cli_env):
    data, out = tmp_path / "data", tmp_path / "site"
    assert cli(["run", "--data", str(data), "--as-of", "2026-10-09", "--no-options"]) == 0
    assert cli(["run", "--data", str(data), "--as-of", "2026-10-09"]) == 0  # rerun: kept, not overwritten
    del cli_env.bars["SPY"]
    assert cli(["run", "--data", str(data), "--as-of", "2026-10-16", "--no-options"]) == 2
    st = Store(data)
    assert st.dates() == ["2026-10-09"] and st.status()["status"] == "failed"
    events = [e["event"] for e in st.audit_log()]
    assert "run_failed" in events and "run_skipped" in events
    assert cli(["build", "--data", str(data), "--out", str(out)]) == 0
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "latest weekly update failed" in index and "2026-10-09" in index
    assert (out / "options.html").exists() and "Options data unavailable" in (out / "options.html").read_text(
        encoding="utf-8"
    )


def test_cli_keeps_the_snapshot_when_the_tracking_update_fails(tmp_path, cli_env, monkeypatch):
    """A failure after the snapshot is written must not discard the week: the workflow commits the data branch
    only on exit 0 or 2, so the run records the failure, writes status.json and still exits 0."""
    monkeypatch.setattr("agent_trading.dashboard.__main__.tracking.track", lambda *a, **k: 1 / 0)
    data = tmp_path / "data"
    assert cli(["run", "--data", str(data), "--as-of", "2026-10-09", "--no-options"]) == 0
    store = Store(data)
    assert store.dates() == ["2026-10-09"] and store.verify_all() == []
    assert store.read_json("tracking.json") is None  # not written: nothing stale or invented
    events = [e["event"] for e in store.audit_log()]
    assert events[-3:] == ["snapshot_written", "tracking_failed", "run_finished"]
    failed = next(e for e in store.audit_log() if e["event"] == "tracking_failed")
    assert failed["error"].startswith("ZeroDivisionError")
    status = store.status()
    assert status["status"] == "partial" and status["as_of"] == "2026-10-09"
    assert any("tracking not updated (ZeroDivisionError)" in p for p in status["problems"])
    assert cli(["verify", "--data", str(data)]) == 0
    out = tmp_path / "site"
    assert cli(["build", "--data", str(data), "--out", str(out)]) == 0  # the site still builds from the snapshot
    assert "Stale data" not in (out / "index.html").read_text(encoding="utf-8")


def test_cli_crash_is_recorded_not_raised(tmp_path, cli_env, monkeypatch):
    monkeypatch.setattr("agent_trading.dashboard.__main__.run", lambda *a, **k: 1 / 0)
    assert cli(["run", "--data", str(tmp_path), "--as-of", "2026-10-09"]) == 2
    assert "ZeroDivisionError" in Store(tmp_path).status()["message"]


def test_site_build_pages_downloads_and_privacy(tmp_path, cli_env, monkeypatch):
    data, out = tmp_path / "data", tmp_path / "site"
    assert cli(["run", "--data", str(data), "--as-of", "2026-10-09", "--no-options"]) == 0
    info = build_site(data, out)
    assert info["snapshot"] == "2026-10-09"
    assert info["pages"] == len(list(out.rglob("*.html")))
    for page in (
        "index.html",
        "growth.html",
        "multibaggers.html",
        "options.html",
        "history.html",
        "methodology.html",
        "audit.html",
        ".nojekyll",
        "downloads/2026-10-09_large.csv",
        "reports/2026-10-09.html",
        "data/latest.json",
    ):
        assert (out / page).exists(), page
    top = json.loads((out / "data" / "latest.json").read_text())["bands"]["large"]["candidates"][0]["ticker"]
    detail = (out / "stock" / f"large-{top}.html").read_text(encoding="utf-8")
    for text in (
        "Strongest bear case",
        "Bear / base / bull",
        "What would invalidate",
        "Probability not established",
        "Price vs benchmark",
    ):
        assert text in detail
    text = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in out.rglob("*") if p.is_file())
    assert not re.search(r"(?<![\d.])1234(?!\d)", text)  # the account's last four digits
    assert "account_number" not in text and "test@example.com" not in text
    # a secret value that leaks into the output blocks publication
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "LEAKYKEY1234")
    st = Store(data)
    st.audit("note", text="LEAKYKEY1234")
    with pytest.raises(RuntimeError, match="secret values"):
        build_site(data, out, ("ALPHAVANTAGE_API_KEY",))
    assert not out.exists()


def test_site_without_any_snapshot_shows_unavailable(tmp_path):
    Store(tmp_path / "d").write_status("failed", "first run failed: SEC unavailable")
    build_site(tmp_path / "d", tmp_path / "s")
    for name in ("index.html", "growth.html", "multibaggers.html"):
        assert "No research data available" in (tmp_path / "s" / name).read_text(encoding="utf-8")


# --- Robinhood tradability (spec 2026-10-14.1) ---------------------------------------------------------------

RESULT = {
    "symbol": "AAA",
    "tradeable": True,
    "state": "active",
    "account_type_tradabilities": [{"account_type": "individual", "account_type_tradability": "tradable"}],
}


@pytest.mark.parametrize(
    "row, ok",
    [
        (RESULT, True),
        (dict(RESULT, tradeable=False), False),
        (dict(RESULT, state="inactive"), False),
        (
            dict(
                RESULT,
                account_type_tradabilities=[{"account_type": "individual", "account_type_tradability": "untradable"}],
            ),
            False,
        ),
        (dict(RESULT, account_type_tradabilities=[]), False),
    ],
)
def test_tradability_rule(row, ok):
    v = parse_results({"data": {"results": [row], "not_found": ["ZZZ"]}}, "2026-10-08")
    assert v["AAA"]["tradable"] is ok and v["ZZZ"]["tradable"] is False and "not found" in v["ZZZ"]["reason"]


def test_tradability_payload_with_account_fields_is_rejected_and_never_stored(tmp_path):
    with pytest.raises(TradabilityError):
        parse_results({"account_number": "123456789", "data": {"results": [RESULT]}}, "2026-10-08")
    t = Tradability()
    t.merge(parse_results({"data": {"results": [RESULT]}}, "2026-10-08"))
    text = t.save(tmp_path).read_text()
    assert "account_number" not in text and not re.search(r"\d{9}", text)


def test_tradability_staleness_and_unknown_symbols():
    t = Tradability.all_tradable(["AAA"], "2026-09-01")
    assert t.check("AAA", date(2026, 10, 5)) == (True, "")
    ok, why = t.check("AAA", date(2026, 10, 9))  # 38 days old
    assert ok is None and "days old" in why
    ok, why = t.check("BBB", date(2026, 10, 9))
    assert ok is None and "not yet verified" in why


def test_untradable_or_unverified_stocks_are_excluded_without_reordering_the_rest(prov):
    full = run(prov, AS_OF, options_enabled=False, tradability=ok_all(prov))["bands"]["large"]["candidates"]
    order = [c["ticker"] for c in full]
    t = ok_all(prov)
    t.symbols[order[0]] = {"tradable": False, "reason": "Robinhood: not tradeable", "checked_at": "2026-10-08"}
    del t.symbols[order[1]]
    todo = []
    snap = run(prov, AS_OF, options_enabled=False, tradability=t, todo_out=todo)
    got = [c["ticker"] for c in snap["bands"]["large"]["candidates"]]
    assert got[: len(order) - 2] == order[2:]  # the others keep their order
    ex = {x["ticker"]: x["reason"] for x in snap["bands"]["large"]["excluded"]}
    assert "not tradeable" in ex[order[0]] and "not yet verified" in ex[order[1]]
    assert order[1] in [x["ticker"] for x in todo] and order[0] not in [x["ticker"] for x in todo]
    assert [c["rank"] for c in snap["bands"]["large"]["candidates"]] == list(range(1, len(got) + 1))


def test_no_stored_verdicts_fails_the_run_but_lists_what_to_check(prov):
    todo = []
    with pytest.raises(RunFailed, match="no Robinhood tradability verdicts"):
        run(prov, AS_OF, options_enabled=False, todo_out=todo)
    assert len(todo) > 0


def test_cli_tradability_import_and_todo(tmp_path, capsys):
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"data": {"results": [RESULT], "not_found": ["ZZZ"]}}))
    assert cli(["tradability", "import", "--data", str(tmp_path), "--checked-at", "2026-10-08", str(f)]) == 0
    t = Tradability.load(tmp_path)
    assert t.symbols["AAA"]["tradable"] and not t.symbols["ZZZ"]["tradable"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"account_number": "1", "data": {"results": []}}))
    assert cli(["tradability", "import", "--data", str(tmp_path), str(bad)]) == 1
    (tmp_path / "robinhood_tradability_todo.json").write_text(
        json.dumps({"symbols": [{"ticker": f"T{i}"} for i in range(12)]})
    )
    capsys.readouterr()
    assert cli(["tradability", "todo", "--data", str(tmp_path)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2 and len(lines[0].split()) == 10 and len(lines[1].split()) == 2


# --- long-horizon multibagger list ---------------------------------------------------------------------------


def test_long_horizon_profile_and_gates_are_well_formed():
    band = {b.key: b for b in spec.BANDS}["multibagger"]
    assert band.universe == "all" and band.min_cap == 500e6 and band.max_cap == 50e9 and 10 in band.scenario_years
    comps = spec.PROFILES[band.profile]
    assert abs(sum(c.weight for c in comps) - 1) < 1e-12 and any(c.key == "runway" for c in comps)
    assert {g[0] for g in band.gates} >= {"revenue_growth_ttm", "revenue_cagr_3y", "gross_margin", "survival"}


def test_multibagger_list_applies_gates_and_long_horizon_scenarios(prov):
    prov.add("LOWGM", 400, sp=False, shares=4e7, drift=0.0003, growth=0.40, gross=0.2)  # fails the margin gate
    snap = run(prov, AS_OF, options_enabled=False, tradability=ok_all(prov))
    mb = snap["bands"]["multibagger"]
    tickers = [c["ticker"] for c in mb["candidates"]]
    assert "MIDA" in tickers and "SPEC" in tickers
    ex = {x["ticker"]: x["reason"] for x in mb["excluded"]}
    assert "gross margin" in ex["LOWGM"] and ex["SLOW"].startswith("gate failed: TTM revenue growth")
    c = next(x for x in mb["candidates"] if x["ticker"] == "MIDA")
    assert "runway" in c["components"] and set(c["scenarios"]["base"]["years"]) == {"1", "3", "5", "10"}
    assert {"bull_5x_in_10y", "base_2x_in_10y"} <= set(c["scenarios"]["flags"])
    assert mb["profile"] == "long_horizon" and "runway" in mb["components"]
    spec_c = next(x for x in mb["candidates"] if x["ticker"] == "SPEC")  # net cash > market cap: EV <= 0
    assert spec_c["scenarios"] is None and "enterprise value" in spec_c["scenario_note"]
    assert "runway" not in snap["bands"]["large"]["candidates"][0]["components"]  # other lists unchanged


def test_survival_and_other_gates():
    from agent_trading.dashboard.pipeline import failed_gate

    band = {b.key: b for b in spec.BANDS}["multibagger"]
    good = {
        "revenue_growth_ttm": 0.3,
        "revenue_cagr_3y": 0.3,
        "gross_margin": 0.6,
        "reported_quarters": 16.0,
        "dilution": 0.02,
        "survival": 1.0,
    }
    assert failed_gate(band, good) is None
    assert "survival" in failed_gate(band, dict(good, survival=0.0))
    assert "unavailable" in failed_gate(band, dict(good, survival=None))
    assert "dilution" in failed_gate(band, dict(good, dilution=0.12))
