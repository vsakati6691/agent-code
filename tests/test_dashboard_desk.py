"""Buy/Sell desk (spec 2026-10-17.4): fixed-rule analysts, debate, trader, risk team, manager, page and tracking."""

import csv
import io
import json
import math
from datetime import date, timedelta

import pandas as pd
import pytest

from agent_trading.dashboard import desk, site_desk, spec, tracking
from agent_trading.dashboard.store import Store, find_private_keys
from tests.spec_history import historical_reason

AS_OF = date(2026, 10, 9)


def rising(n=253, start=100.0, step=0.004):
    return [start * (1 + step) ** i for i in range(n)]


def falling(n=253, flat=193):
    """Flat, then an accelerating fall: below both averages with MACD under its signal, though oversold."""
    return [100.0] * flat + [100.0 * (1 - 0.00004 * k * k) for k in range(1, n - flat + 1)]


def field(value=None, reason="missing", **meta):
    return {"value": value, "reason": None if value is not None else reason, **meta}


def cand(
    ticker="AAA",
    quality=70.0,
    spark=None,
    trend="stable",
    op=("stable", 0.0),
    fcf=("stable", 0.0),
    extended="not extended",
    target=None,
    insider_av=None,
    external=None,
    components=None,
    confidence="high",
    next_earnings=None,
    price=100.0,
):
    groups = {
        "quality": {"fields": {"quality": field(quality)}},
        "growth": {
            "fields": {
                "growth_trend": field(trend),
                "operating_margin_change": field(op[1], trend=op[0]) if op else field(),
                "fcf_margin_change": field(fcf[1], trend=fcf[0]) if fcf else field(),
            }
        },
        "timing": {"fields": {"extended": field(extended)}},
        "ownership": {"fields": {"analyst_target": field(target), "insider_net": field(insider_av)}},
    }
    return {
        "ticker": ticker,
        "name": f"{ticker} Inc.",
        "sector": "Industrials",
        "price": price,
        "components": components or {"growth": 0.8, "earnings": 0.6, "quality": 0.7, "balance": 0.9, "valuation": 0.3},
        "confidence_label": confidence,
        "next_earnings": next_earnings,
        "counterargument": "Weakest evidence: valuation.",
        "external": external,
        "decision_research": {
            "groups": groups,
            "spark": rising() if spark is None else spark,
            "filing_as_of": "2026-08-01",
        },
    }


def test_registered_before_any_rating_and_additive():
    assert spec.SPEC_VERSION == "2026-10-17.4"
    reason = historical_reason("2026-10-17.4")
    assert "written before any rating was computed" in reason
    assert "No existing scale, weight, gate, list" in reason
    assert spec.DESK_RATINGS == ("Sell", "Underweight", "Hold", "Overweight", "Buy")
    assert spec.spec_dict()["decision_desk"]["rules"] == spec.DESK_RULES


def test_indicators_match_their_textbook_definitions():
    px = [100 + math.sin(i / 5) * 10 + i * 0.1 for i in range(260)]
    s = pd.Series(px)
    assert desk.sma(px, 50) == pytest.approx(s.iloc[-50:].mean())
    assert desk.ema(px, 12)[-1] == pytest.approx(s.ewm(span=12, adjust=False).mean().iloc[-1])
    line = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
    m, sig = desk.macd(px, 12, 26, 9)
    assert m == pytest.approx(line.iloc[-1]) and sig == pytest.approx(line.ewm(span=9, adjust=False).mean().iloc[-1])
    assert desk.rsi(rising(30), 14) == 100.0
    assert desk.rsi(list(reversed(rising(30))), 14) == pytest.approx(0.0)
    flat_vol = desk.volatility([100.0 * (1.01 if i % 2 else 1.0) for i in range(253)], 252)
    assert flat_vol == pytest.approx(
        pd.Series([math.log(1.01 if i % 2 else 1 / 1.01) for i in range(1, 253)]).std() * math.sqrt(252)
    )
    assert desk.volatility(rising(100), 252) is None


@pytest.mark.parametrize("quality,vote", [(60.0, 1), (59.99, 0), (40.0, 0), (39.99, -1)])
def test_fundamentals_thresholds(quality, vote):
    a = desk.fundamentals_analyst(cand(quality=quality))
    assert a["vote"] == vote
    assert {p["side"] for p in a["points"][1:]} == {"neutral"}  # strongest/weakest parts are context only


def test_missing_inputs_abstain_and_never_count_as_zero():
    c = cand(quality=None, spark=[], trend=None, op=None, fcf=None)
    for a in (
        desk.fundamentals_analyst(c),
        desk.technical_analyst(c),
        desk.positioning_analyst(c),
        desk.events_analyst(c),
    ):
        assert a["vote"] is None and a["stance"] == "abstains" and a["reason"]
    out = desk.assess(c, AS_OF)
    assert out["rating"] is None and out["summary"].startswith("Not rated: only 0 of 4")


def test_technical_trend_and_momentum():
    up = desk.technical_analyst(cand(spark=rising()))
    assert up["inputs"]["rsi_14"] > 70  # a straight rise is overbought: -1, still +2 overall
    assert up["score"] == 2 and up["vote"] == 1
    down = desk.technical_analyst(cand(spark=falling()))
    assert down["inputs"]["rsi_14"] < 30  # oversold: +1, still -2 overall
    assert down["score"] == -2 and down["vote"] == -1
    short = desk.technical_analyst(cand(spark=rising(150)))
    assert short["vote"] is None and "Needs 200" in short["reason"]


def test_positioning_reads_filings_not_social_media():
    sec = {
        "insiders": {"windows": {"90d": {"net_shares": 5000}}},
        "short_interest": {"percent_of_diluted_shares": 0.12},
    }
    a = desk.positioning_analyst(cand(external=sec, target=120.0))
    assert [p["vote"] for p in a["points"]] == [1, -1, 1] and a["vote"] == 1
    sells = desk.positioning_analyst(cand(external={"insiders": {"windows": {"90d": {"net_shares": -9000}}}}))
    assert sells["points"][0]["vote"] == 0 and sells["points"][0]["side"] == "bear" and sells["vote"] == 0
    fallback = desk.positioning_analyst(cand(insider_av=100.0, target=99.0))
    assert "Alpha Vantage" in fallback["points"][0]["text"] and fallback["score"] == 0
    assert desk.positioning_analyst(cand(target=100.0))["vote"] == -1  # price at the target


def test_events_from_the_latest_filing():
    a = desk.events_analyst(cand(trend="accelerating", op=("improving", 0.03), fcf=("deteriorating", -0.02)))
    assert a["score"] == 1 and a["vote"] == 1
    assert "no news headlines" in a["points"][-1]["text"]


@pytest.mark.parametrize(
    "net,rating",
    [
        (4, "Buy"),
        (3, "Buy"),
        (2, "Overweight"),
        (1, "Hold"),
        (0, "Hold"),
        (-1, "Hold"),
        (-2, "Underweight"),
        (-3, "Sell"),
        (-4, "Sell"),
    ],
)
def test_trader_mapping(net, rating):
    assert desk.trader(net) == rating


def test_risk_reviewers_step_down_positive_calls_only_and_stop_at_hold():
    rv = spec.DESK_RULES["reviewers"]
    assert [desk.review("Buy", 1, rv[k]) for k in ("aggressive", "neutral", "conservative")] == [
        "Buy",
        "Buy",
        "Overweight",
    ]
    assert [desk.review("Buy", 3, rv[k]) for k in ("aggressive", "neutral", "conservative")] == [
        "Overweight",
        "Overweight",
        "Hold",
    ]
    assert desk.review("Overweight", 4, rv["conservative"]) == "Hold"
    assert desk.review("Sell", 4, rv["conservative"]) == "Sell"
    assert desk.review("Hold", 4, rv["conservative"]) == "Hold"


def test_risk_flags():
    noisy = [100.0 * (1.06 if i % 2 else 1.0) for i in range(253)]
    c = cand(
        spark=noisy,
        extended="extended",
        next_earnings=str(AS_OF + timedelta(days=10)),
        components={"balance": 0.2, "growth": 0.5},
    )
    flags, unchecked = desk.risk_flags(c, AS_OF)
    assert [f["key"] for f in flags] == ["earnings", "extended", "volatility", "balance"] and not unchecked
    flags, unchecked = desk.risk_flags(cand(next_earnings=str(AS_OF + timedelta(days=11))), AS_OF)
    assert not flags and not unchecked
    assert "Next earnings date unknown" in desk.risk_flags(cand(), AS_OF)[1]


def test_full_desk_buy_downgrade_and_low_confidence_cap():
    strong = cand(trend="accelerating", op=("improving", 0.02), fcf=("improving", 0.02))
    out = desk.assess(strong, AS_OF)
    assert out["debate"]["net"] == 3 and out["trader"] == "Buy" and out["rating"] == "Buy"
    assert out["debate"]["verdict"] == "Bull case stronger" and out["debate"]["bear"][-1].startswith("Stored research")
    risky = cand(
        trend="accelerating",
        op=("improving", 0.02),
        fcf=("improving", 0.02),
        extended="extended",
        next_earnings=str(AS_OF + timedelta(days=3)),
    )
    out = desk.assess(risky, AS_OF)
    assert out["risk"]["reviews"] == {"aggressive": "Buy", "neutral": "Overweight", "conservative": "Overweight"}
    assert out["rating"] == "Overweight" and out["manager"]["median"] == "Overweight"
    low = desk.assess({**strong, "confidence_label": "low"}, AS_OF)
    assert low["rating"] == "Hold" and low["manager"]["capped"] and "capped it at Hold" in low["summary"]
    weak = cand(quality=20.0, spark=falling(), trend="decelerating", op=("deteriorating", -0.02))
    assert desk.assess(weak, AS_OF)["rating"] == "Sell"


def test_build_rates_each_ticker_once_in_list_order_and_is_reproducible():
    bands = {
        "mid": {"candidates": [cand("BBB")]},
        "large": {"candidates": [cand("AAA", trend="accelerating"), cand("BBB")]},
        "ai_large": {"candidates": [cand("AAA")]},
    }
    out = desk.build(bands, str(AS_OF))
    assert [e["ticker"] for e in out["entries"]] == ["AAA", "BBB"]
    assert out["entries"][1]["lists"] == ["large", "mid"] and out["entries"][1]["benchmark"] == "SPY"
    assert sum(out["counts"].values()) == 2
    again = desk.build(json.loads(json.dumps(bands)), AS_OF)
    assert json.dumps(again, sort_keys=True) == json.dumps(out, sort_keys=True)
    assert not find_private_keys(out)
    assert "NaN" not in json.dumps(out) and "Infinity" not in json.dumps(out)


def test_track_desk_uses_only_stored_ratings():
    idx = pd.bdate_range("2026-01-02", periods=80)
    prices = {
        "AAA": pd.Series([100.0 * 1.01**i for i in range(80)], index=idx),
        "SPY": pd.Series([100.0] * 80, index=idx),
    }
    start = idx[5].date()
    entry = {"ticker": "AAA", "rating": "Buy", "benchmark": "SPY"}
    snaps = [
        {"as_of": str(start), "decision_desk": {"entries": [entry]}},
        {"as_of": str(idx[6].date()), "bands": {}},
    ]  # an older-style snapshot: never tracked
    out = tracking.track_desk(snaps, prices, idx[-1].date())
    assert out["snapshots_with_ratings"] == 1 and out["first_rated"] == str(start)
    one = out["by_rating"]["Buy"]["1m"]
    assert one["measured"] == 1 and one["mean_excess"] == pytest.approx(1.01**21 - 1)
    assert out["by_rating"]["Buy"]["12m"]["pending"] == 1
    assert "No edge is claimed" in out["evidence_note"]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    from tests.dashboard_clock import frozen_dashboard_clock
    from tests.dashboard_fixtures import demo_site

    with frozen_dashboard_clock():
        data, out = demo_site(tmp_path_factory.mktemp("desk"))
    return data, out


def test_weekly_snapshot_stores_the_ratings_and_the_site_renders_them(site):
    data, out = site
    store = Store(data)
    snap = store.load(store.dates()[-1])
    stored = snap["decision_desk"]
    assert stored["spec_version"] == "2026-10-17.4" and stored["entries"]
    payload, is_stored = site_desk.payload_for(snap)
    assert is_stored and payload is stored
    page = (out / "desk.html").read_text(encoding="utf-8")
    assert page.count("<h1") == 1 and "Rule-based research rating, not advice" in page
    assert "Preview, not tracked" not in page
    assert 'href="desk.html" aria-current=page' in page
    for e in stored["entries"]:
        assert f'href="desk/{e["ticker"]}.html"' in page
        trace = (out / "desk" / f"{e['ticker']}.html").read_text(encoding="utf-8")
        assert "1. Analysts" in trace and "Back to the Buy/Sell desk" in trace
    csv_text = (out / "downloads" / f"{snap['as_of']}_buy_sell_desk.csv").read_text(encoding="utf-8")
    assert csv_text.splitlines()[0].startswith("ticker,name,rating,net_vote,trader")
    rows = [r for r in csv.reader(io.StringIO(csv_text)) if r]
    assert len(rows) == len(stored["entries"]) + 1
    method = (out / "methodology.html").read_text(encoding="utf-8")
    assert 'id="buy-sell-desk"' in method


def test_older_snapshot_gets_a_labelled_untracked_preview(site):
    data, _ = site
    store = Store(data)
    snap = dict(store.load(store.dates()[-1]))
    snap.pop("decision_desk")
    snap["spec_version"] = "2026-10-14.9"
    payload, is_stored = site_desk.payload_for(snap)
    assert not is_stored and payload["entries"]
    page = site_desk.desk_page(snap, None, payload, is_stored)
    assert "Preview, not tracked" in page and "Tracking starts with the first weekly snapshot" in page
