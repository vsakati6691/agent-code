"""Spec 2026-10-14.6: options watchlist (six lists of up to 5), the theta / earnings / quote-freshness fixes,
the probability gate, the always-linked options page, phone-visible maximum loss and older-snapshot compatibility."""

from __future__ import annotations

import csv
import io
import re
from datetime import timedelta
from pathlib import Path

import pytest

from agent_trading.dashboard import evidence, probability, spec
from agent_trading.dashboard import options as opt
from agent_trading.dashboard.pipeline import run
from agent_trading.dashboard.site import build_site, options_csv
from agent_trading.dashboard.site_options import (
    events_status,
    list_limit,
    lists_of,
    probability_text,
    status_block,
    watchlist_cards,
)
from agent_trading.dashboard.store import Store
from agent_trading.dashboard.tradability import Tradability
from tests.dashboard_fixtures import AS_OF, FakeProviders, benchmarks, demo_site, option_row
from tests.spec_history import historical_reason
from tests.test_dashboard_site import _header_classes, visible_text
from tests.test_dashboard_v2 import EXP, chains_for, put_row

ROOT = Path(__file__).resolve().parents[1]
UNDER = {"symbol": "ABC", "close": 100.0, "last_trade_time": f"{AS_OF}T16:00:00"}


# --- registration: the top-five change is a new, dated spec version with the other rules untouched -------------


def test_top_five_is_registered_as_a_new_spec_version_with_eligibility_rules_unchanged():
    # the .6 entry stays in the version history; a later version (2026-10-14.7 added the AI lists) does not undo it
    entry = historical_reason("2026-10-14.6")
    assert "5 contracts instead of 10" in entry and "theta" in entry and "registered before any snapshot" in entry
    assert spec.SPEC_VERSION >= "2026-10-14.6" and [v for v, _ in spec.SPEC_CHANGELOG] == sorted(
        v for v, _ in spec.SPEC_CHANGELOG
    )
    r = spec.OPTION_RULES
    assert r["max_per_type_per_horizon"] == 5 and r["max_per_underlying_per_horizon"] == 2 and r["require_theta"]
    assert (
        r["min_open_interest"],
        r["min_volume"],
        r["max_spread_pct"],
        r["min_delta"],
        r["max_delta"],
        r["standard_multiplier"],
    ) == (500, 10, 0.10, 0.30, 0.70, 100)
    assert {k: v[0] for k, v in spec.OPTION_RANKING.items()} == {
        "liquidity": 0.45,
        "breakeven": 0.35,
        "time_decay": 0.20,
    }
    assert [(h.min_dte, h.max_dte) for h in spec.HORIZONS] == [(70, 110), (150, 210), (300, 430)]
    assert spec.option_list_limit("2026-10-13.2") == 5 and spec.option_list_limit("2026-10-14.5") == 10
    assert spec.option_list_limit(spec.SPEC_VERSION) == 5 and spec.option_list_limit(None) == 5


# --- six independently ranked lists, never padded ---------------------------------------------------------------


def test_six_lists_hold_at_most_five_contracts_each_and_rank_independently():
    out = opt.build_horizons(chains_for(8), AS_OF, {})
    assert out["rules"]["max_per_type_per_horizon"] == 5 and out["spec_version"] == spec.SPEC_VERSION
    for h in spec.HORIZONS:
        for kind in ("calls", "puts"):
            lst = out[h.key][kind]
            rows = lst["rows"]
            assert lst["limit"] == 5 and lst["count"] == len(rows) == 5 and lst["shortfall"] is None
            assert [x["rank"] for x in rows] == [1, 2, 3, 4, 5] and all(x["type"] == kind[:-1] for x in rows)
            scores = [x["rank_components"]["total"] for x in rows]
            assert scores == sorted(scores, reverse=True)
            assert all(h.min_dte <= x["dte"] <= h.max_dte and x["horizon"] == h.key for x in rows)
            assert max(sum(1 for x in rows if x["underlying"] == u) for u in {x["underlying"] for x in rows}) <= 2
            assert all(x["expiration"] > str(AS_OF) and x["dte"] == (EXP[h.key] - AS_OF).days for x in rows)
    calls = [x["option"] for x in out["3m"]["calls"]["rows"]]
    puts = [x["option"] for x in out["3m"]["puts"]["rows"]]
    assert not set(calls) & set(puts)  # separate lists, separate contracts


def test_fewer_than_five_explains_why_and_never_pads():
    out = opt.build_horizons(chains_for(1, per_side=4), AS_OF, {})  # one underlying -> at most 2 per list
    lst = out["3m"]["calls"]
    assert lst["count"] == 2 and "Only 2 of up to 5" in lst["shortfall"]
    assert "left out by the per-underlying limit" in lst["shortfall"] and "not padded" in lst["shortfall"]
    nothing = opt.build_horizons({"X": "HTTP 403"}, AS_OF, {})
    assert nothing["3m"]["puts"]["rows"] == [] and "No option chain passed" in nothing["3m"]["puts"]["shortfall"]
    far = opt.build_horizons(
        {"ABC": (UNDER, [option_row("ABC", AS_OF + timedelta(days=20), 100, 4.9, 5.1)])}, AS_OF, {}
    )
    assert "No call on any usable chain expires 70-110 days" in far["3m"]["calls"]["shortfall"]


# --- correctness: missing theta ------------------------------------------------------------------------------


@pytest.mark.parametrize("theta", [None, 0.0])
def test_missing_theta_is_ineligible_and_never_becomes_the_best_decay_score(theta):
    row = option_row("ABC", EXP["3m"], 100, 4.9, 5.1, theta=theta)
    ok, why = opt.eligible(row, "ABC", AS_OF)
    assert not ok and why == "theta unavailable (time decay not measurable)"
    r = opt.research_row(row, 100.0, AS_OF, "ABC", [])
    assert r["theta"] is None and r["theta_share_per_day"] is None and r["theta_available"] is False
    assert "theta unavailable (time decay not measurable)" in r["flags"]
    rc = opt.rank_score(r)
    assert rc["time_decay"] is None and rc["time_decay_missing"]
    measured = opt.rank_score(
        opt.research_row(option_row("ABC", EXP["3m"], 100, 4.9, 5.1, theta=-0.0001), 100.0, AS_OF, "ABC", [])
    )
    assert rc["total"] < measured["total"]  # before the fix a missing theta scored 1.0 on decay


def test_contract_without_theta_is_rejected_with_the_reason_and_the_rest_still_rank():
    rows = [
        option_row("ABC", EXP["3m"], 100, 4.9, 5.1),
        option_row("ABC", EXP["3m"], 105, 3.0, 3.1, delta=0.45, theta=None),
    ]
    out = opt.build_horizons({"ABC": (UNDER, rows)}, AS_OF, {})
    calls = out["3m"]["calls"]
    assert calls["count"] == 1 and calls["rows"][0]["strike"] == 100
    assert calls["rejections"] == {"theta unavailable (time decay not measurable)": 1}
    assert "1 failed: theta unavailable" in calls["shortfall"]


# --- correctness: earnings status is 'unknown' when the calendar was not collected -----------------------------


def test_missing_earnings_calendar_reads_unknown_never_none_scheduled():
    row = option_row("ABC", EXP["3m"], 100, 4.9, 5.1)
    unknown = opt.research_row(row, 100.0, AS_OF, "ABC", [], events_known=False)
    assert unknown["events_status"] == "unknown" and unknown["risks"]["event"].startswith("Unknown")
    assert "none scheduled" not in unknown["risks"]["event"].lower()
    known = opt.research_row(row, 100.0, AS_OF, "ABC", [])
    assert known["events_status"] == "none scheduled"
    sched = opt.research_row(row, 100.0, AS_OF, "ABC", [{"date": AS_OF + timedelta(days=30), "event": "earnings"}])
    assert sched["events_status"] == "scheduled" and "scheduled before expiry" in sched["risks"]["event"]
    # the renderer: an older snapshot has no status; the unavailability note still makes it 'unknown'
    old = {"option": "x", "events_before_expiry": []}
    assert events_status(old, {"earnings_note": "Earnings dates unavailable: key not configured"})[0] == "unknown"
    assert events_status(old, {"events_known": False})[0] == "unknown"
    assert events_status(old, {})[0] == "none scheduled"
    assert events_status({"option": "x", "events_before_expiry": [{"date": "2026-11-01"}]}, {})[1].startswith(
        "scheduled 2026-11-01"
    )


def test_pipeline_marks_every_contract_unknown_when_the_calendar_lookup_fails():
    p = FakeProviders()
    benchmarks(p)
    for i in range(12):
        p.add(f"S{i:02d}", 100 + i, growth=0.05 + 0.04 * i, drift=0.0004 + 0.0001 * i, shares=5e8)
    trad = Tradability.all_tradable(list(p.listed), "2026-10-08")
    top = run(p, AS_OF, options_enabled=False, tradability=trad)["bands"]["large"]["candidates"][0]["ticker"]
    spot = float(p.bars[top]["close"].iloc[-1])
    p.chains[top] = (
        {
            "symbol": top,
            "close": spot,
            "last_trade_time": f"{AS_OF}T16:00:00",
            "timestamp": f"{AS_OF + timedelta(days=1)} 14:00:00",
        },
        [option_row(top, AS_OF + timedelta(days=95), round(spot), spot * 0.05, spot * 0.051)],
    )
    p.fail.add("earnings")
    snap = run(p, AS_OF, options_enabled=True, tradability=trad)
    o = snap["options"]
    assert o["events_known"] is False and o["earnings_note"].startswith("Earnings dates unavailable")
    x = o["3m"]["calls"]["rows"][0]
    assert x["events_status"] == "unknown" and x["quote_date_ny"] == (AS_OF + timedelta(days=1)).isoformat()
    assert o["rules"]["max_per_type_per_horizon"] == 5 and o["collected_at"] and o["quotes"][top]["quote_time_utc"]
    assert x["probability"]["status"] == "not_established" and x["probability"]["probability_of_profit"] is None
    assert evidence.options_state(snap) == (
        "partial",
        "1 of 10 chains usable; 9 rejected (stale, failed or unreadable)",
    )


# --- correctness: quote freshness vs a contract's last trade ------------------------------------------------------


def test_quote_snapshot_time_is_validated_and_kept_apart_from_the_contract_last_trade():
    under = dict(UNDER, timestamp=f"{AS_OF + timedelta(days=1)} 14:05:00")  # Saturday run: fine
    q = opt.quote_info(under, AS_OF)
    assert q["quote_date_ny"] == (AS_OF + timedelta(days=1)).isoformat() and not q["quote_stale"]
    assert "after the as-of session" in q["quote_status"] and opt.chain_status(under, AS_OF) is None
    assert opt.parse_quote_time("2026-10-10 02:30:00")[1].isoformat() == "2026-10-09"  # UTC -> New York date
    assert opt.quote_info(dict(UNDER, timestamp=f"{AS_OF} 21:30:00"), AS_OF)["quote_status"].startswith(
        "snapshot taken in the as-of session"
    )
    stale = dict(UNDER, timestamp=f"{AS_OF - timedelta(days=1)} 20:00:00")
    assert opt.chain_status(stale, AS_OF).startswith("stale chain: quote snapshot taken")
    assert opt.quote_info(UNDER, AS_OF)["quote_status"].startswith("unknown")  # no timestamp: judged by last trade
    assert opt.chain_status(UNDER, AS_OF) is None
    # a contract that last traded days ago is still quoted: flagged, eligible, and its quote time is the snapshot's
    row = option_row("ABC", EXP["3m"], 100, 4.9, 5.1)
    row["last_trade_time"] = f"{AS_OF - timedelta(days=5)}T15:00:00"
    assert opt.eligible(row, "ABC", AS_OF)[0]
    r = opt.research_row(row, 100.0, AS_OF, "ABC", [], quote=q)
    assert r["quote_time_utc"] == q["quote_time_utc"] and r["contract_last_trade"] == row["last_trade_time"]
    assert r["contract_last_trade"] != r["quote_time_utc"] and any("contract last traded" in f for f in r["flags"])
    never = option_row("ABC", EXP["3m"], 100, 4.9, 5.1)
    never["last_trade_time"] = None
    assert any("last trade time unknown" in f for f in opt.contract_flags(never, "ABC", AS_OF))
    out = opt.build_horizons({"ABC": (under, [row]), "OLD": (stale, [row])}, AS_OF, {})
    assert out["underlyings"] == ["ABC"] and "stale chain: quote snapshot" in out["chain_problems"]["OLD"]
    assert out["quotes"]["ABC"]["quote_status"] == q["quote_status"] and out["quote_source"].startswith("Cboe delayed")


# --- payoff, breakeven and maximum loss, before fees ------------------------------------------------------------


def test_payoff_breakeven_and_max_loss_math_for_calls_and_puts_before_fees():
    call = opt.research_row(option_row("ABC", EXP["6m"], 100, 4.9, 5.1), 102.0, AS_OF, "ABC", [])
    assert call["breakeven"] == pytest.approx(105.1) and call["required_move"] == pytest.approx(105.1 / 102 - 1)
    assert call["premium_per_share_ask"] == 5.1 and call["premium_per_contract_ask"] == call[
        "max_loss_per_contract"
    ] == pytest.approx(510)
    pays = {round(p["move"], 2): p["pl_per_contract"] for p in call["payoffs"]}
    assert pays[-0.5] == pytest.approx(-510) and pays[0.5] == pytest.approx((153 - 100 - 5.1) * 100)
    assert min(pays.values()) == pytest.approx(-510) and max(pays.values()) > 0
    put = opt.research_row(put_row("ABC", EXP["6m"], 100, 4.9, 5.1), 102.0, AS_OF, "ABC", [])
    pp = {round(p["move"], 2): p["pl_per_contract"] for p in put["payoffs"]}
    assert put["breakeven"] == pytest.approx(94.9) and pp[0.5] == pytest.approx(-510)
    assert pp[-0.5] == pytest.approx((100 - 51 - 5.1) * 100) and put["required_move"] == pytest.approx(1 - 94.9 / 102)
    assert (
        "before fees" in call["payoff_note"] and call["fees"] == spec.FEE_TREATMENT and "No commissions" in call["fees"]
    )
    assert call["sensitivity"]["days_forward"] == 30 and "Black-Scholes" not in call["payoff_note"]
    assert "before fees" in call["sensitivity"]["assumptions"] and "4% risk-free" in call["sensitivity"]["assumptions"]
    assert call["risks"]["max_loss"].startswith("A long call can lose the entire premium, $510")
    assert set(call["risks"]) == {"liquidity", "time_decay", "volatility", "event", "max_loss"}


# --- probability: definition, gate, suppression --------------------------------------------------------------------


def _record(**over):
    base = dict(
        model_version="m1",
        option_type="call",
        horizon="3m",
        evaluation_start="2027-01-01",
        evaluation_end="2028-01-15",
        sample_size=250,
        out_of_sample=True,
        holdout_consumed=False,
        calibration_error=0.03,
        brier_score=0.21,
        uncertainty={"method": "bootstrap", "level": 0.95, "ci_width": 0.08},
        data_source="synthetic gate test, not a model",
    )
    return probability.CalibrationRecord(**{**base, **over})


def test_probability_is_not_established_for_every_list_and_estimates_are_dropped_without_a_record():
    assert all(v is None for v in probability.REGISTRY.values()) and not probability.status_summary()["any_calibrated"]
    for kind in spec.OPTION_TYPES:
        for h in spec.HORIZONS:
            d = probability.display(kind, h.key, pop=0.62, itm=0.7)  # passed-in numbers never leak through
            assert (
                d["status"] == "not_established" and d["probability_of_profit"] is None and d["probability_itm"] is None
            )
            assert (
                d["statement"]
                == spec.PROBABILITY_NOT_ESTABLISHED
                == "Probability not established — insufficient validated evidence."
            )
            assert d["why"] == ["no calibration record exists"] and len(d["missing_data"]) == len(
                spec.PROBABILITY_MISSING_DATA
            )
    assert "NOT the probability of finishing in the money" in spec.PROBABILITY_OF_PROFIT_DEFINITION
    assert spec.PROBABILITY_NEVER_SUBSTITUTED.startswith("Delta, the research score, the scenario weights")


@pytest.mark.parametrize(
    "over, why",
    [
        ({"sample_size": 199}, "sample size 199 below"),
        ({"evaluation_end": "2027-06-01"}, "shorter than 365 days"),
        ({"out_of_sample": False}, "not recorded out of sample"),
        ({"holdout_consumed": True}, "already consumed"),
        ({"calibration_error": 0.06}, "calibration error 0.060 above"),
        ({"uncertainty": {"method": "none"}}, "no uncertainty interval"),
        ({"option_type": "put"}, "record is for puts, not calls"),
        ({"horizon": "6m"}, "record is for the 6m horizon, not 3m"),
        ({"model_version": ""}, "missing field: model_version"),
    ],
)
def test_probability_gate_rejects_incomplete_or_weak_calibration(over, why):
    rec = _record(**over)
    problems = probability.validate(rec, "call", "3m")
    assert problems and any(why in p for p in problems), problems
    d = probability.display("call", "3m", record=rec, pop=0.6)
    assert (
        d["status"] == "not_established"
        and d["probability_of_profit"] is None
        and d["statement"] == spec.PROBABILITY_NOT_ESTABLISHED
    )


def test_probability_gate_lets_a_complete_record_through_with_its_provenance():
    rec = _record()
    assert probability.validate(rec, "call", "3m") == []
    d = probability.display("call", "3m", record=rec, pop=0.61, itm=0.7)
    assert d["status"] == "calibrated" and d["probability_of_profit"] == 0.61 and d["probability_itm"] == 0.7
    assert (
        d["model_version"] == "m1"
        and d["sample_size"] == 250
        and d["evaluation_period"] == ["2027-01-01", "2028-01-15"]
    )
    assert d["calibration_error"] == 0.03 and d["uncertainty"]["ci_width"] == 0.08
    for part in ("61%", "m1", "250", "2027-01-01", "0.030", "±4%"):
        assert part in d["statement"], part
    assert probability.display("call", "3m", record=rec)["status"] == "not_established"  # no estimate: no number
    assert (
        len(probability.DATA_CONTRACT["record_fields"]) >= 15
        and "append-only" in probability.DATA_CONTRACT["storage"].lower()
    )


def test_engine_never_passes_an_estimate_into_the_probability_display():
    src = (ROOT / "src" / "agent_trading" / "dashboard" / "options.py").read_text(encoding="utf-8")
    assert "probability.display(kind, hz)" in src and "pop=" not in src and "itm=" not in src
    page_src = (ROOT / "src" / "agent_trading" / "dashboard" / "site_options.py").read_text(encoding="utf-8")
    assert "delta" not in page_src.split("def probability_text")[1].split("def ")[0]


# --- the built site ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return demo_site(tmp_path_factory.mktemp("v3"))


def test_options_page_is_linked_and_explains_every_unavailable_state(tmp_path):
    data, out = demo_site(tmp_path / "a", two_weeks=False)
    snap = Store(data).load(Store(data).dates()[-1])
    empty = {
        h.key: {"calls": {"rows": [], "status": "unavailable"}, "puts": {"rows": [], "status": "unavailable"}}
        for h in spec.HORIZONS
    }
    cases = (
        ({"enabled": False, "status": "disabled in configuration"}, "missing", "not collected for this snapshot"),
        ({"enabled": True, "status": "cboe: HTTP 503 after 3 attempts"}, "provider_error", "produced no usable chain"),
        (
            {
                "enabled": True,
                "status": "ok",
                "underlyings": [],
                **empty,
                "chain_problems": {
                    "S00": "stale chain: underlying last traded 2026-10-08, as-of session is 2026-10-09"
                },
            },
            "stale",
            "rejected as stale",
        ),
    )
    for options, state, phrase in cases:
        d, o = tmp_path / f"d-{state}", tmp_path / f"s-{state}"
        Store(d).write_snapshot(dict(snap, options=options), "test")
        build_site(d, o)
        page = (o / "options.html").read_text(encoding="utf-8")
        assert f'data-state="{state}"' in page and phrase in page and "Options data unavailable" in page, state
        assert "Snapshot methodology" in page and "page renderer" in page and "data-hz=" not in page
        assert evidence.options_state(dict(snap, options=options))[0] == state
        for name in ("index.html", "watchlist.html", "methodology.html", "history.html", "audit.html"):
            assert re.search(r'<nav>.*href="options\.html"', (o / name).read_text(encoding="utf-8")), (state, name)
        index = (o / "index.html").read_text(encoding="utf-8")
        assert 'id="options-watchlist"' in index and f'data-state="{state}"' in index
    assert "DASHBOARD_OPTIONS" in (tmp_path / "s-missing" / "options.html").read_text(encoding="utf-8")


def test_partial_state_names_the_unusable_chains():
    snap = {
        "as_of": "2026-10-09",
        "options": {"enabled": True, "status": "ok", "underlyings": ["A", "B"], "chain_problems": {"C": "HTTP 403"}},
    }
    assert evidence.options_state(snap) == ("partial", "2 of 3 chains usable; 1 rejected (stale, failed or unreadable)")
    s = status_block(snap)
    assert s["state"] == "partial" and s["headline"].startswith("Options collected with gaps")


def test_max_loss_and_critical_warning_stay_visible_on_phones(built):
    page = (built[1] / "options.html").read_text(encoding="utf-8")
    kept = [label for label, cls in _header_classes(page, "o-12m-put") if "hide-sm" not in cls]
    assert "Max loss" in kept and kept == [
        "#",
        "Underlying",
        "Expiry",
        "Strike",
        "Premium*",
        "Breakeven at expiry",
        "Max loss",
        "Research score",
    ]
    head = page[page.index('id="options-critical"') - 40 : page.index('id="options-critical"') + 400]
    assert "hide-sm" not in head and "lose the entire premium" in head
    assert page.count("entire premium") >= 30  # every row's max-loss cell and detail


def test_no_contract_is_described_as_safe(built):
    text = visible_text(
        (built[1] / "options.html").read_text(encoding="utf-8") + (built[1] / "index.html").read_text(encoding="utf-8")
    )
    assert not re.search(r"\b(safe|safely|guaranteed|risk-free trade|no risk|cannot lose)\b", text, re.I)


def test_facts_assumptions_missing_data_and_scores_are_shown_apart(built):
    page = (built[1] / "options.html").read_text(encoding="utf-8")
    page += "".join(p.read_text(encoding="utf-8") for p in (built[1] / "option").glob("*.html"))
    for h in (
        "Observed (delayed quote)",
        "Assumptions",
        "Unknown or missing",
        "Research score",
        "Risks in plain language",
        "not when it was quoted",
        "UTC",
        "Snapshot methodology",
        "page renderer",
        "What these lists are",
        "Earnings before expiry",
        "none scheduled (collected calendar, unverified)",
        "5 of up to 5",
        "Distance to breakeven",
    ):
        assert h in page, h
    assert page.count("data-hz=") == 6 and page.count('role="tablist"') == 2
    assert re.search(
        r'<section data-hz="6m" data-type="put"[^>]* hidden><h2>About 6 months · puts · 150-210 days', page
    )


def test_short_lists_say_why_on_the_page(tmp_path):
    data, _ = demo_site(tmp_path / "a", two_weeks=False)
    snap = Store(data).load(Store(data).dates()[-1])
    snap["options"] = {"enabled": True, "status": "ok", **opt.build_horizons(chains_for(2), AS_OF, {})}
    d, o = tmp_path / "short-data", tmp_path / "short-site"
    Store(d).write_snapshot(snap, "test")
    build_site(d, o)
    page = (o / "options.html").read_text(encoding="utf-8")
    assert "4 of up to 5" in page and "Fewer than 5" in page and "Only 4 of up to 5 calls met every rule" in page
    assert "left out by the per-underlying limit" in page and "not padded" in page
    index = (o / "index.html").read_text(encoding="utf-8")
    assert "4 of up to 5:" in index and "Lists with fewer than the limit" in index


def test_percentages_never_follow_the_probability_label(built):
    page = (built[1] / "options.html").read_text(encoding="utf-8")
    page += "".join(p.read_text(encoding="utf-8") for p in (built[1] / "option").glob("*.html"))
    segments = page.split("Probability of profit:")[1:]
    assert len(segments) >= 31  # header note + one per contract
    for seg in segments:
        head = seg[:160]
        assert "Probability not established" in head, head
        assert not re.search(r"\d+(\.\d+)?%", head), head
    assert (
        probability_text({"probability": {"status": "calibrated", "probability_of_profit": None}})
        == spec.PROBABILITY_NOT_ESTABLISHED
    )


def test_options_csv_carries_quote_time_event_status_score_parts_and_probability_status(built):
    table = list(
        csv.DictReader(
            io.StringIO((built[1] / "downloads" / f"{AS_OF}_options_3m_calls.csv").read_text(encoding="utf-8"))
        )
    )
    assert len(table) == 5
    for col in (
        "quote_status",
        "quote_source",
        "events_status",
        "score_liquidity",
        "score_breakeven",
        "score_time_decay",
        "probability_status",
        "probability_of_profit",
        "fees",
        "contract_last_trade",
        "theta_available",
        "horizon",
    ):
        assert col in table[0], col
    for r in table:
        assert r["probability_status"] == "not_established" and r["probability_of_profit"] == ""
        assert r["events_status"] in ("scheduled", "none scheduled", "unknown") and r["horizon"] == "3m"
        assert float(r["max_loss_per_contract"]) == float(r["premium_per_contract_ask"]) and r["fees"].startswith(
            "before fees"
        )
    rows = opt.build_horizons(chains_for(2), AS_OF, {})["6m"]["puts"]["rows"]
    assert len(list(csv.DictReader(io.StringIO(options_csv(rows))))) == len(rows)


def test_overview_watchlist_shows_six_compact_lists_with_max_loss(built):
    index = (built[1] / "index.html").read_text(encoding="utf-8")
    assert 'id="options-watchlist"' in index and index.count("<h3>Calls ·") == 3 and index.count("<h3>Puts ·") == 3
    assert (
        index.count("max loss") >= 30
        and 'href="options.html#put-12m"' in index
        and 'href="options.html#call-3m"' in index
    )
    assert 'id="growth"' not in index
    cards = watchlist_cards(
        {"as_of": "2026-10-09", "options": {"enabled": False, "status": "disabled in configuration"}}
    )
    assert 'id="options-watchlist"' in cards and 'data-state="missing"' in cards and "ow-grid" not in cards


def test_scenario_flags_are_separate_from_passing_the_research_screen(built):
    index = (built[1] / "multibaggers.html").read_text(encoding="utf-8")
    assert "Research screen:" in index and "Passing the screen is separate from" in index
    for label in (
        "2x in 5 years (bull case)",
        "5x in 5 years (bull case)",
        "5x in 10 years (bull case)",
        "2x in 10 years (base case)",
    ):
        assert label in index, label
    detail = next((built[1] / "stock").glob("large-*.html")).read_text(encoding="utf-8")
    assert "Research screen:" in detail and '5x in 10 years (bull case): <span class="pill muted">not tested' in detail


def test_tab_lists_have_keyboard_support_and_follow_in_page_links():
    from agent_trading.dashboard.assets import JS

    for s in ("ArrowRight", "ArrowLeft", "'Home'", "'End'", "roving", "hashchange", 'button[role="tab"]'):
        assert s in JS, s


def test_audit_page_shows_the_option_dataset_state(built):
    audit = (built[1] / "audit.html").read_text(encoding="utf-8")
    assert "Option chains" in audit and "6 of 6 chains" in audit


def test_older_ten_contract_snapshot_renders_with_its_own_limit_and_without_new_fields(tmp_path, monkeypatch):
    data, _ = demo_site(tmp_path / "a", two_weeks=False)
    snap = Store(data).load(Store(data).dates()[-1])
    monkeypatch.setitem(spec.OPTION_RULES, "max_per_type_per_horizon", 10)
    old = opt.build_horizons(chains_for(8), AS_OF, {})
    monkeypatch.undo()
    for h in spec.HORIZONS:
        for kind in ("calls", "puts"):
            lst = old[h.key][kind]
            lst.pop("limit", None)
            lst.pop("shortfall", None)
            for x in lst["rows"]:
                for k in (
                    "probability",
                    "risks",
                    "events_status",
                    "events_note",
                    "quote_time_utc",
                    "quote_status",
                    "quote_source",
                    "contract_last_trade",
                    "horizon",
                    "theta_available",
                    "fees",
                    "payoff_note",
                ):
                    x.pop(k, None)
            assert len(lst["rows"]) == 10
    for k in ("rules", "quotes", "events_known", "probability", "spec_version", "quote_source"):
        old.pop(k, None)
    snap["options"] = {"enabled": True, "status": "ok", **old}
    snap["spec_version"] = "2026-10-14.5"
    d, o = tmp_path / "old-data", tmp_path / "old-site"
    Store(d).write_snapshot(snap, "test")
    build_site(d, o)
    page = (o / "options.html").read_text(encoding="utf-8")
    assert "10 of up to 10" in page and "Snapshot methodology <strong>2026-10-14.5" in page
    assert f"page renderer <strong>{spec.SPEC_VERSION}" in page and "never re-ranks" in page
    assert len(list(o.glob("options-*.html"))) == 3
    assert len(list((o / "option").glob("*.html"))) == 60
    assert all(p.stat().st_size <= 150_000 for p in o.rglob("*.html"))
    page += "".join(p.read_text(encoding="utf-8") for p in (o / "option").glob("*.html"))
    assert page.count("Probability not established") >= 61 and "risk notes were not stored" in page
    assert list_limit(snap, lists_of(snap["options"]["3m"])["calls"]) == 10
    index = (o / "index.html").read_text(encoding="utf-8")
    assert (
        index.count("<h3>Calls ·") == 3 and index.count('<li><a href="symbol/') == 60
    )  # the stored lists, as published
