"""Regression tests for neutral enrichment, bounded quotas and full short-expiry coverage."""

import json
import os
import time
from dataclasses import asdict
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_trading.dashboard import evidence, pipeline_external, short_term, site_short_term
from agent_trading.dashboard.http import FetchError, OptionalDataDeferred
from agent_trading.dashboard.pipeline_context import Context
from agent_trading.dashboard.pipeline_details import decision_enrichment
from agent_trading.dashboard.providers import Providers
from agent_trading.dashboard.sector_balance import sector_penalty
from agent_trading.provider_budget import DailyBudgetExceeded, DailyRequestBudget
from tests.test_dashboard_http import Resp, client
from tests.test_dashboard_live_gaps import NOW, contract, underlying
from tests.test_dashboard_resilience import score


def insider_body(ticker="A"):
    return json.dumps(
        {"data": [{"ticker": ticker, "transaction_date": "2026-10-16", "transaction_code": "P", "shares": "10"}]}
    ).encode()


def test_bulk_provider_error_counts_neutral_records_without_inventing_ownership(monkeypatch):
    monkeypatch.setattr(pipeline_external, "_bulk", Mock(side_effect=RuntimeError("provider_error")))
    monkeypatch.setattr(pipeline_external, "_short", lambda *a: {})
    companies = [{"ticker": f"T{i}"} for i in range(40)]
    bands = {"large": {"candidates": companies}}
    ctx = SimpleNamespace(
        as_of=NOW.date(), started="2026-10-19T22:00:00+00:00", providers=SimpleNamespace(fmp_key=None), facts={}
    )
    summary = pipeline_external.collect(ctx, bands, {}, None)["institutions"]
    assert summary["state"] == "provider_error" and summary["available"] == 0
    assert summary["neutral_fallback"] == 40 and summary["scoring_required"] is False
    for c in companies:
        row = c["external"]["institutions"]
        assert row["holder_count"] is row["reported_shares"] is None
        assert row["top_holders"] == [] and row["score_adjustment"] == 0
        assert row["source"].startswith("https://www.sec.gov/") and row["retrieved_at"] == ctx.started
    row = next(
        r
        for r in evidence.datasets({"as_of": str(NOW.date()), "external_datasets": {"institutions": summary}})
        if r["dataset"] == "13F institutional holders"
    )
    assert "40 neutral fallbacks" in row["coverage"] and "0 of 40" not in row["coverage"]
    assert row["state"] == "provider_error"  # honest source state, even though scoring is neutral


@pytest.mark.parametrize(
    "record", [None, [], {"state": "nonsense"}, {"state": "provider_error", "holder_count": 100, "top_holders": None}]
)
def test_malformed_or_failed_13f_cannot_leak_metrics(monkeypatch, record):
    monkeypatch.setattr(pipeline_external.institutions, "company", lambda *a: record)
    row = pipeline_external.institutional_record([], {}, "A", NOW.date())
    assert row["neutral_fallback"] and row["score_adjustment"] == 0
    assert row["holder_count"] is row["reported_shares"] is None and row["top_holders"] == []


def test_daily_insider_cache_survives_provider_stop_and_preserves_observation_time(tmp_path, monkeypatch):
    http, session = client([Resp(200, insider_body())], tmp_path)
    first = Providers(http, av_key="synthetic").insider_transactions("A")
    cached_file = next(tmp_path.glob("*.gz"))
    observed = time.time() - 3600
    os.utime(cached_file, (observed, observed))
    http.daily_budget.stop()
    http.used["alphavantage"] = http.limits["alphavantage"].budget
    p = Providers(http, av_key="synthetic")  # also survives a new provider instance/run
    p.annual_filing = lambda *a: {}
    ctx = Context(date(2026, 10, 16), p)
    ctx.budget_hit.add("alphavantage")
    monkeypatch.setattr("agent_trading.dashboard.pipeline_details.as_of_for", lambda now: ctx.as_of)
    result = decision_enrichment(ctx, {"ticker": "A", "cik": 1})
    assert result["insider_net"]["value"] == 10 and len(session.calls) == 1
    stamp = datetime.fromisoformat(result["insider_net"]["as_of"])
    assert abs(stamp.timestamp() - observed) < 0.01
    assert first["_observed_at"] != result["insider_net"]["as_of"]
    assert ctx.problems == []  # proactive capacity deferral is a note


def test_only_two_new_insider_calls_and_cache_hits_do_not_spend_allowance(tmp_path):
    http, session = client([Resp(200, insider_body("A")), Resp(200, insider_body("B"))], tmp_path)
    p = Providers(http, av_key="synthetic")
    for ticker in ("A", "A", "B", "B"):
        p.insider_transactions(ticker)
    with pytest.raises(OptionalDataDeferred):
        p.insider_transactions("C")
    assert len(session.calls) == 2 and http.daily_budget.remaining() == 22


def test_subsecond_filesystem_clock_skew_does_not_trigger_a_duplicate_request(tmp_path):
    http, session = client([Resp(200, insider_body())], tmp_path)
    p = Providers(http, av_key="synthetic")
    p.insider_transactions("A")
    cached_file = next(tmp_path.glob("*.gz"))
    observed = time.time() + 0.5
    os.utime(cached_file, (observed, observed))
    p.insider_transactions("A")
    assert len(session.calls) == 1 and http.cache_hits == 1


@pytest.mark.parametrize("age", [86401, -3600])
def test_stale_or_future_cache_never_substitutes_for_budget_deferred_insiders(tmp_path, age):
    http, session = client([Resp(200, insider_body())], tmp_path)
    p = Providers(http, av_key="synthetic")
    p.insider_transactions("A")
    cached_file = next(tmp_path.glob("*.gz"))
    observed = time.time() - age
    os.utime(cached_file, (observed, observed))
    http.daily_budget.stop()
    with pytest.raises(OptionalDataDeferred):
        p.insider_transactions("A")
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "body",
    [b"{}", b'{"data":null}', b'{"data":[null]}', b'{"data":[{"transaction_date":"bad"}]}', insider_body("WRONG")],
)
def test_malformed_insider_response_is_not_cached(tmp_path, body):
    http, session = client([Resp(200, body)], tmp_path)
    with pytest.raises(FetchError):
        Providers(http, av_key="synthetic").insider_transactions("A")
    assert len(session.calls) == 1 and not list(tmp_path.glob("*.gz"))


def test_optional_daily_reserve_and_transient_errors_never_retry(tmp_path):
    http, session = client([Resp(503)], tmp_path)
    p = Providers(http, av_key="synthetic")
    with pytest.raises(FetchError):
        p.insider_transactions("A")
    assert len(session.calls) == 1
    for _ in range(20):
        http.daily_budget.reserve()
    with pytest.raises(OptionalDataDeferred):
        p.insider_transactions("B")
    with pytest.raises(OptionalDataDeferred):
        p.overview("B")
    assert len(session.calls) == 1 and http.daily_budget.remaining() == 3
    other = DailyRequestBudget(http.daily_budget.path)
    with pytest.raises(DailyBudgetExceeded):
        other.reserve(min_remaining=3)
    other.reserve()  # the existing hard cap is unchanged for essential requests
    assert other.remaining() == 2


@pytest.mark.parametrize("count,expected", [(5, 0), (6, 6), (9, 24), (10, 30)])
def test_it_penalty_threshold_multiplier_and_idempotence(count, expected):
    scores = [score(f"T{i}", 80 - i) for i in range(10)]
    sectors = {s.ticker: "technology" if i < count else "Energy" for i, s in enumerate(scores)}
    ranked = sector_penalty(scores, sectors, 10)
    assert next(s for s in ranked if s.ticker == "T0").sector_penalty == expected
    assert all(s.composite >= 0 for s in ranked)
    assert [asdict(s) for s in sector_penalty(ranked, sectors, 10)] == [asdict(s) for s in ranked]
    assert sector_penalty([score("A", 2)], {"A": "Information Technology"}, 1)[0].composite == 0


def test_stronger_penalty_promotes_more_non_it_challengers():
    scores = [score(f"T{i}", 90 - i) for i in range(4)] + [score(f"E{i}", 75 - i) for i in range(4)]
    sectors = {s.ticker: "Technology" if s.ticker.startswith("T") else "Energy" for s in scores}
    assert all(s.ticker.startswith("E") for s in sector_penalty(scores, sectors, 4)[:4])


def test_all_calendar_expiries_including_seven_day_boundary_and_legacy_render():
    chain = [contract(f"2610{day}", kind) for day in range(19, 28) for kind in ("C", "P")]
    rows = short_term.select("NVDA", underlying(), chain, NOW)["rows"]
    assert {r["dte"] for r in rows} == {0, 1, 2, 3, 4, 7}  # weekend dates and 8+ DTE rejected
    assert len({r["option"] for r in rows}) == len(rows)
    payload = short_term.collect(SimpleNamespace(option_chain=lambda t: (underlying(t), [contract(symbol=t)])), NOW)
    payload.pop("windows")
    payload["spec_version"] = "2026-10-19.3"
    payload["symbols"][0]["rows"][0]["window"] = "Next listed expiry"
    original = json.dumps(payload, sort_keys=True)
    html = site_short_term.desk(payload)
    assert "Full 1–7 day coverage pending a new scan" in html and "Next listed expiry" in html
    assert json.dumps(payload, sort_keys=True) == original
