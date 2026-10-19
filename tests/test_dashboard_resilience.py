"""Provider failures, sector penalties and earnings quarantines, with no network."""

import json
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from unittest.mock import Mock

import pandas as pd
import pytest
import requests

from agent_trading.dashboard import pipeline_external, pipeline_phases, scoring
from agent_trading.dashboard.earnings_cadence import OUTLIER, validate
from agent_trading.dashboard.fallbacks import daily_quote
from agent_trading.dashboard.http import FetchError, ProviderLimits, ProviderUnavailable
from agent_trading.dashboard.pipeline_context import Context
from agent_trading.dashboard.providers import Providers
from agent_trading.dashboard.sector_balance import sector_penalty
from agent_trading.data.alphavantage import AlphaVantageClient, AlphaVantageTransientError
from tests.test_dashboard_http import Resp, Session, client
from tests.test_dashboard_site import SUBS, _Prov

AS_OF = date(2026, 10, 9)


def score(ticker, value):
    return scoring.Score(ticker, value, {"growth": 0.7}, {}, [], None, 1, "high", "")


def test_sector_penalty_promotes_a_challenger_and_preserves_evidence():
    scores = [score(f"T{i}", 80 - i) for i in range(4)] + [score("E", 74)]
    sectors = {**{f"T{i}": "Information Technology" for i in range(4)}, "E": "Energy"}
    before = [asdict(s) for s in scores]
    ranked = sector_penalty(scores, sectors, 4)
    assert ranked[0].ticker == "E" and ranked[0].composite == 74
    assert ranked[1].raw_composite == 80 and ranked[1].composite == 70
    assert ranked[1].sector_penalty == 10
    assert [asdict(s) for s in scores] == before
    assert [asdict(s) for s in sector_penalty(ranked, sectors, 4)] == [asdict(s) for s in ranked]


@pytest.mark.parametrize("sectors", [{"A": "Energy", "B": "Technology"}, {"A": None, "B": "Unknown"}])
def test_no_penalty_at_half_or_for_unknown_sectors(sectors):
    assert all(s.sector_penalty == 0 for s in sector_penalty([score("A", 70), score("B", 70)], sectors, 2))
    assert sector_penalty([], {}, 5) == []


def test_all_one_sector_deducts_scores_without_fabricating_diversity():
    ranked = sector_penalty([score("B", 70), score("A", 70)], {"A": "Energy", "B": "Energy"}, 10)
    assert [(s.ticker, s.composite) for s in ranked] == [("A", 60), ("B", 60)]


@pytest.mark.parametrize("gap,eligible", [(-22, False), (-21, True), (0, True), (21, True), (22, False)])
def test_earnings_boundary_is_calendar_days(gap, eligible):
    expected = date(2026, 11, 15)
    result = validate(str(expected + timedelta(days=gap)), str(expected), AS_OF)
    assert result["deviation_days"] == gap and result["event_eligible"] is eligible
    if not eligible:
        assert result["validation_status"] == OUTLIER


def test_manual_release_is_exact_dated_confirmed_and_not_future_or_stale():
    manual = {"status": "verified", "confirmed": True, "broker_dates": ["2026-10-15"], "checked_at": "2026-10-09"}
    assert validate("2026-10-15", "2026-12-01", AS_OF, manual)["event_eligible"]
    for changes in (
        {"checked_at": "2026-09-01"},
        {"checked_at": "2026-10-10"},
        {"confirmed": False},
        {"broker_dates": ["2026-10-16"]},
    ):
        assert not validate("2026-10-15", "2026-12-01", AS_OF, {**manual, **changes})["event_eligible"]
    assert not validate("bad date", None, AS_OF)["event_eligible"]
    assert not validate(str(AS_OF), None, AS_OF)["event_eligible"]
    assert validate("2026-10-15", None, AS_OF)["validation_status"] == "Unverified: cadence unavailable"


def test_pipeline_quarantines_candidate_and_watchlist_before_options():
    p = _Prov(500, SUBS)
    p.option_chain = Mock(side_effect=AssertionError("must not fetch an outlier's option chain"))
    ctx = Context(AS_OF, p)
    c = {"ticker": "BAD", "cik": 1, "next_earnings": "2026-11-25"}
    bands = {"large": {"candidates": [c]}, "ai_large": {"candidates": [dict(c)]}}
    w = {"entries": [{"ticker": "BAD", "cik": 1, "asset_type": "operating company"}]}
    assert pipeline_phases.collect_events(ctx, bands, w, {"BAD": "2026-11-25"}) == []
    assert p.calls == 1
    assert c["earnings_check"]["validation_status"] == OUTLIER
    _, options = pipeline_phases.collect_derivatives(
        ctx, bands, {"BAD": "2026-11-25"}, pd.DataFrame(), True, None, None
    )
    assert options["underlyings"] == []
    p.option_chain.assert_not_called()


def test_quarantine_survives_sec_failure_and_manual_release_is_enforced_in_pipeline():
    from agent_trading.dashboard.earnings_verdicts import EarningsVerdicts

    ctx = Context(AS_OF, _Prov(0, {}))
    c = {"ticker": "BAD", "cik": 1, "next_earnings": "2026-10-15"}
    ctx.prior_earnings_checks["BAD"] = {
        "next_scheduled": "2026-10-15",
        "expected_date": "2026-12-01",
        "outlier": True,
    }
    bands = {"large": {"candidates": [c]}}
    assert pipeline_phases.collect_events(ctx, bands, {}, {"BAD": "2026-10-15"}) == []
    assert c["earnings_check"]["validation_status"] == OUTLIER
    # A moving cadence estimate cannot silently release this same quarantined record.
    ctx.earnings_checks[(1, "2026-10-15")] = {"next_scheduled": "2026-10-15", "expected_date": "2026-10-16"}
    assert pipeline_phases.collect_events(ctx, bands, {}, {"BAD": "2026-10-15"}) == []
    assert c["earnings_check"]["latest_cadence_estimate"] == "2026-10-16"
    ctx.earnings_verdicts = EarningsVerdicts(
        {
            "BAD": {
                "checked_at": "2026-10-09",
                "reports": [{"date": "2026-10-15", "confirmed": True}],
            }
        }
    )
    events = pipeline_phases.collect_events(ctx, bands, {}, {"BAD": "2026-10-15"})
    assert [e["ticker"] for e in events] == ["BAD"]
    assert c["earnings_check"]["validation_status"] == "Manually verified"


def test_malformed_sec_filing_dates_do_not_crash_calendar_preprocessing():
    from agent_trading.dashboard.pipeline_collect import verify_earnings

    sub = {"filings": {"recent": {"form": ["8-K"], "items": ["2.02"], "filingDate": ["2026-01-bad"]}}}
    result = verify_earnings(Context(AS_OF, _Prov(500, sub)), 1, "2026-10-15")
    assert "malformed" in result["last_results_status"] and result["expected_date"] is None


def test_desk_does_not_trigger_earnings_flag_for_quarantined_date():
    from agent_trading.dashboard.desk import risk_flags
    from tests.test_dashboard_desk import cand

    c = cand(next_earnings="2026-10-15")
    c["earnings_check"] = {"event_eligible": False, "validation_status": OUTLIER}
    flags, unchecked = risk_flags(c, AS_OF)
    assert "earnings" not in {f["key"] for f in flags} and OUTLIER in unchecked


def test_refresh_rechecks_changed_calendar_date_against_stored_cadence(tmp_path):
    from agent_trading.dashboard.refresh import collect
    from tests.test_dashboard_refresh import NOW, RefreshProviders, weekly

    p = RefreshProviders()
    p.earnings_calendar = lambda: pd.DataFrame([{"symbol": "AAA", "reportDate": date(2026, 11, 25)}])
    snap = weekly(tmp_path)
    snap["bands"]["large"]["candidates"][0]["earnings_check"] = {"expected_date": "2026-10-29"}
    result = collect(p, snap, AS_OF, True, NOW.isoformat())
    assert result["earnings_validation"]["AAA"]["validation_status"] == OUTLIER
    assert result["chain_status"]["AAA"]["status"] == "unavailable"
    assert "chain:AAA" not in p.calls and "AAA" not in result["options"]["underlyings"]


def test_13f_bulk_and_company_errors_are_neutral_without_fake_zero_holdings(monkeypatch):
    error = {"state": "provider_error", "reason": "unavailable"}
    record = pipeline_external.institutional_record([], {}, "A", AS_OF, error)
    assert record["score_adjustment"] == 0 and "holder_count" not in record
    monkeypatch.setattr(
        pipeline_external.institutions,
        "company",
        Mock(side_effect=[TypeError("bad"), {"state": "available", "holder_count": 4}]),
    )
    assert pipeline_external.institutional_record([], {}, "A", AS_OF)["state"] == "provider_error"
    assert pipeline_external.institutional_record([], {}, "B", AS_OF)["holder_count"] == 4


def fmp_http(responses):
    http, session = client(responses)
    http.limits["fmp"] = ProviderLimits(0, 10)
    return http, session


def profile_response(symbol="A"):
    return Resp(200, json.dumps([{"symbol": symbol, "companyName": "Example", "marketCap": 1000000}]).encode())


def test_av_quota_falls_back_for_each_company_without_retry_or_poisoning_cache(tmp_path):
    http, session = fmp_http([Resp(200, b'{"Note":"daily quota"}'), profile_response("A"), profile_response("B")])
    http.cache_dir = tmp_path
    p = Providers(http, av_key="synthetic", fmp_key="synthetic")
    assert p.overview("A")["MarketCapitalization"] == 1000000
    assert p.overview("B")["Symbol"] == "B"
    assert http.used == {"alphavantage": 1, "fmp": 2}
    assert len(list(tmp_path.glob("*.gz"))) == 2
    assert "ForwardPE" not in p.overview("A")
    assert len(session.calls) == 3


def test_fmp_fallback_is_not_suppressed_by_context_av_budget(monkeypatch):
    from agent_trading.dashboard.pipeline_details import decision_enrichment
    from tests.dashboard_clock import frozen_dashboard_clock

    http, _ = fmp_http([profile_response()])
    p = Providers(http, fmp_key="synthetic")
    p.annual_filing = lambda *args: {}
    ctx = Context(date(2026, 10, 16), p)
    ctx.budget_hit.add("alphavantage")
    with frozen_dashboard_clock():
        got = decision_enrichment(ctx, {"ticker": "A", "cik": 1})
    assert got["basic_fundamentals"]["MarketCapitalization"] == 1000000
    assert got["estimates"]["forward_pe"]["value"] is None
    assert "Financial Modeling Prep" in got["estimates"]["forward_pe"]["source"]


def test_exhausted_fallback_does_not_disable_other_quote_providers():
    from agent_trading.dashboard.pipeline_collect import _guard

    ctx = Context(AS_OF, None)
    getter = Mock(side_effect=[ProviderUnavailable("FMP unavailable"), {"close": 10}])
    assert _guard(ctx, "quotes", getter)[0] is None
    assert _guard(ctx, "quotes", getter)[0] == {"close": 10}
    assert "quotes" not in ctx.budget_hit


def test_av_daily_budget_uses_fmp_quote_and_rejects_stale_or_mismatched_quotes():
    stamp = datetime(2026, 10, 9, 20, 1, tzinfo=UTC).timestamp()
    raw = [{"symbol": "A", "timestamp": stamp, "price": 10, "previousClose": 9}]
    http, session = fmp_http([Resp(200, json.dumps(raw).encode())])
    http.used["alphavantage"] = http.limits["alphavantage"].budget
    p = Providers(http, av_key="synthetic", fmp_key="synthetic")
    q = p.daily_quote("A", AS_OF)
    assert q.close == 10 and "Financial Modeling Prep" in q.source and q.open is None
    assert len(session.calls) == 1
    for changed in ({"symbol": "B"}, {"timestamp": stamp - 86400}, {"price": "nan"}, {"timestamp": stamp - 7200}):
        with pytest.raises(FetchError):
            daily_quote([{**raw[0], **changed}], "A", AS_OF, "2026-10-09T22:00:00Z", "fmp")


def test_fmp_billing_error_stops_and_never_exposes_provider_body():
    http, session = fmp_http([Resp(200, b'{"Error Message":"secret billing text"}')])
    p = Providers(http, fmp_key="synthetic")
    for symbol in ("A", "B"):
        with pytest.raises(ProviderUnavailable, match="FMP error response|provider stopped") as exc:
            p.overview(symbol)
        assert "secret" not in str(exc.value)
    assert len(session.calls) == 1


def test_av_symbol_error_is_not_cached_or_a_provider_wide_stop(tmp_path):
    http, session = fmp_http([Resp(200, b'{"Error Message":"bad symbol"}'), profile_response()])
    http.cache_dir = tmp_path
    p = Providers(http, av_key="synthetic", fmp_key="synthetic")
    assert p.overview("A")["Symbol"] == "A"
    assert "alphavantage" not in http.unavailable and len(session.calls) == 2
    assert len(list(tmp_path.glob("*.gz"))) == 1


@pytest.mark.parametrize("dashboard", [True, False])
def test_av_transient_failures_use_bounded_exponential_backoff(monkeypatch, dashboard):
    responses = [Resp(503), requests.Timeout(), Resp(200, b"{}")]
    waits = []
    if dashboard:
        http, session = client(responses)
        http.sleep = waits.append
        http.get_json("https://www.alphavantage.co/query")
        assert http.used["alphavantage"] == 3
    else:
        monkeypatch.setattr("agent_trading.data.alphavantage.time.sleep", waits.append)
        session = Session(responses)
        av = AlphaVantageClient("synthetic", session=session, pause_seconds=0)
        av._get({"function": "OVERVIEW"})
        assert av.calls_made == 3
    assert waits == [2, 4] and len(session.calls) == 3


def test_local_retry_limit_and_daily_budget_count_every_attempt(monkeypatch):
    monkeypatch.setattr("agent_trading.data.alphavantage.time.sleep", lambda _: None)
    session = Session([Resp(503)] * 5)
    av = AlphaVantageClient("synthetic", session=session, pause_seconds=0)
    with pytest.raises(AlphaVantageTransientError):
        av._get({"function": "OVERVIEW"})
    assert av.calls_made == len(session.calls) == 3 and av.budget.remaining() == 21
