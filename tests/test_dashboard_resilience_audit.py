"""Failure injection across provider, cache, sector, calendar and publication boundaries."""

import json
from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from agent_trading.calendar_dates import calendar_day
from agent_trading.dashboard import macro, pipeline_phases
from agent_trading.dashboard.earnings_cadence import OUTLIER, future_schedule, validate
from agent_trading.dashboard.http import FetchError
from agent_trading.dashboard.pipeline_collect import _guard, verify_earnings
from agent_trading.dashboard.pipeline_context import Context
from agent_trading.dashboard.pipeline_details import concentration_warnings
from agent_trading.dashboard.providers import AV_URL, Providers, parse_earnings_8k
from agent_trading.dashboard.refresh import collect, run
from agent_trading.dashboard.refresh_store import MAX_DAY_BYTES, RefreshStore
from agent_trading.dashboard.sector_balance import sector_penalty
from agent_trading.data.alphavantage import parse_earnings_csv
from tests.test_dashboard_http import Resp, client
from tests.test_dashboard_refresh import NOW, RefreshProviders, file_hashes, weekly
from tests.test_dashboard_resilience import AS_OF, fmp_http, score
from tests.test_dashboard_site import _Prov

BAD_BODIES = [b"", b"{broken", b"null", b"[]", b"{}", b'"text"', b"[null]", b"\xff", b'{"bad":NaN}']


@pytest.mark.parametrize("body", BAD_BODIES)
@pytest.mark.parametrize("endpoint", ["profile", "quote"])
def test_both_fallbacks_fail_preserving_good_cache_and_logging(tmp_path, caplog, body, endpoint):
    http, session = fmp_http([Resp(body=body), Resp(body=body)])
    http.cache_dir, http.fresh_only = tmp_path, True
    av_function = "OVERVIEW" if endpoint == "profile" else "GLOBAL_QUOTE"
    old_av = (
        {"Symbol": "A", "Name": "Example", "MarketCapitalization": "1000000"}
        if endpoint == "profile"
        else {"Global Quote": {"01. symbol": "A", "05. price": "10", "07. latest trading day": "2026-10-09"}}
    )
    old_fmp = (
        [{"symbol": "A", "companyName": "Example", "marketCap": 1000000}]
        if endpoint == "profile"
        else [{"symbol": "A", "price": 10, "timestamp": NOW.timestamp()}]
    )
    for url, params, old in (
        (AV_URL, {"function": av_function, "symbol": "A"}, old_av),
        (f"https://financialmodelingprep.com/stable/{endpoint}", {"symbol": "A"}, old_fmp),
    ):
        http._write_cache(http._key(url, params, ""), json.dumps(old).encode())
    before = file_hashes(tmp_path)
    p = Providers(http, av_key="synthetic", fmp_key="synthetic")
    ctx = Context(AS_OF, p)
    fn = (lambda: p.overview("A")) if endpoint == "profile" else (lambda: p.daily_quote("A", AS_OF))
    value, reason = _guard(ctx, "overview" if endpoint == "profile" else "quotes", fn)
    assert value is None and reason and ctx.problems and caplog.records
    assert {k: v for k, v in file_hashes(tmp_path).items() if k.endswith(".gz")} == before
    assert len(session.calls) == 2
    assert "synthetic" not in caplog.text


def test_invalid_existing_cache_refetches_and_cache_io_failure_is_nonfatal(tmp_path, monkeypatch, caplog):
    http, session = client([Resp(body=b'{"ok": 1}')], tmp_path)
    url = "https://data.sec.gov/example"
    key = http._key(url, None, "")
    http._write_cache(key, b"{bad old cache")
    assert http.get_json(url, max_age_hours=24) == {"ok": 1}
    assert len(session.calls) == 1 and "invalid cached" in caplog.text
    original = (tmp_path / f"{key}.gz").read_bytes()
    monkeypatch.setattr(type(tmp_path), "replace", Mock(side_effect=OSError("blocked")))
    http._write_cache(key, b'{"new": 2}')
    assert (tmp_path / f"{key}.gz").read_bytes() == original
    assert "previous entry preserved" in caplog.text


@pytest.mark.parametrize("value", [None, "", "  ", "Unknown", "N/A", "Other", "unrecognized tag", [], float("nan")])
def test_unknown_sectors_retain_nonzero_scores_and_remain_in_denominator(value):
    scores = [score("A", 70), score("B", 65), score("C", 60), score("D", 55)]
    ranked = sector_penalty(scores, {"A": "Energy", "B": "Energy", "C": value, "D": value}, 4)
    assert [(s.ticker, s.composite, s.sector_penalty) for s in ranked] == [
        ("A", 70, 0),
        ("B", 65, 0),
        ("C", 60, 0),
        ("D", 55, 0),
    ]


def test_sector_aliases_combine_and_all_missing_warning_does_not_crash():
    ranked = sector_penalty([score("A", 70), score("B", 60)], {"A": " Technology ", "B": "INFORMATION   TECHNOLOGY"}, 2)
    assert [s.sector_penalty for s in ranked] == [30, 30]
    warnings = concentration_warnings([{"ticker": "A", "sector": None, "bars": pd.DataFrame({"close": [1, 2]})}])
    assert len(warnings) == 1 and "missing or unrecognized" in warnings[0]


@pytest.mark.parametrize(
    "value,expected",
    [
        ("2026-11-06", date(2026, 11, 6)),
        ("2026-11-06T00:30:00+00:00", date(2026, 11, 5)),
        ("2026-11-06T00:30:00-05:00", date(2026, 11, 6)),
        (datetime.fromisoformat("2026-07-01T03:30:00+00:00"), date(2026, 6, 30)),
        (pd.Timestamp("2026-11-06T00:30:00Z"), date(2026, 11, 5)),
        (None, None),
        (pd.NaT, None),
        (float("nan"), None),
        ("bad", None),
        ({}, None),
    ],
)
def test_calendar_date_normalization(value, expected):
    assert calendar_day(value) == expected


@pytest.mark.parametrize(
    "scheduled,gap,eligible",
    [
        ("2026-11-06T00:30:00Z", 21, True),
        ("2026-11-06T00:30:00-05:00", 22, False),
        ("2026-11-07T00:30:00+14:00", 22, False),
    ],
)
def test_timezone_aware_outlier_boundary(scheduled, gap, eligible):
    checked = validate(scheduled, "2026-10-15T18:00:00-04:00", AS_OF)
    assert checked["deviation_days"] == gap and checked["event_eligible"] is eligible


def test_sparse_history_skips_missing_dates_and_drops_future_filings():
    dates = [None, "bad", "2026-07-30T20:00:00Z", "2026-04-29", "2026-10-10T04:01:00Z"]
    sub = {"filings": {"recent": {"form": ["8-K"] * 5, "items": ["2.02"] * 5, "filingDate": dates}}}
    assert parse_earnings_8k(sub, AS_OF) == ["2026-07-30", "2026-04-29"]
    check = verify_earnings(Context(AS_OF, _Prov(500, sub)), 1, "2026-11-25T20:00:00Z")
    assert check["last_results"] == "2026-07-30" and check["expected_date"] == "2026-10-30"
    assert check["validation_status"] == OUTLIER and not check["event_eligible"]
    assert verify_earnings(Context(AS_OF, _Prov(500, {})), 1, "2026-10-15")["expected_date"] is None


def test_calendar_csv_and_schedule_normalize_mixed_offsets():
    text = "symbol,reportDate,fiscalDateEnding\nAAA,2026-11-06T00:30:00Z,2026-09-30\nBBB,2026-11-06,2026-09-30\n"
    calendar = parse_earnings_csv(text)
    assert future_schedule(calendar, AS_OF) == {"AAA": "2026-11-05", "BBB": "2026-11-06"}
    assert future_schedule(calendar, AS_OF, {"AAA"}) == {"AAA": "2026-11-05"}


@pytest.mark.parametrize("calendar", [None, pd.DataFrame(columns=["symbol", "reportDate"]), pd.DataFrame({"bad": [1]})])
def test_refresh_retains_quarantine_when_calendar_fails_or_omits_symbol(tmp_path, calendar):
    snap = weekly(tmp_path)
    snap["bands"]["large"]["candidates"][0]["earnings_check"] = {
        "next_scheduled": "2026-11-25",
        "expected_date": "2026-10-29",
        "outlier": True,
    }
    p = RefreshProviders()
    p.earnings_calendar = Mock(return_value=calendar)
    result = collect(p, snap, AS_OF, True, NOW.isoformat())
    assert result["earnings_validation"]["AAA"]["validation_status"] == OUTLIER
    assert "chain:AAA" not in p.calls and "AAA" not in result["options"]["underlyings"]


def test_full_pipeline_retains_quarantine_when_calendar_omits_symbol():
    ctx = Context(AS_OF, _Prov(0, {}))
    ctx.prior_earnings_checks["AAA"] = {"next_scheduled": "2026-11-25", "expected_date": "2026-10-29", "outlier": True}
    bands = {"large": {"candidates": [{"ticker": "AAA", "cik": 1, "next_earnings": None}]}}
    assert pipeline_phases.collect_events(ctx, bands, {}, {}) == []
    assert bands["large"]["candidates"][0]["earnings_check"]["validation_status"] == OUTLIER
    ctx.providers.option_chain = Mock(side_effect=AssertionError("quarantined"))
    pipeline_phases.collect_derivatives(ctx, bands, {}, None, True, None, "calendar unavailable")
    ctx.providers.option_chain.assert_not_called()


def test_refresh_calendar_size_depends_on_relevant_tickers_only(tmp_path):
    p, snap = RefreshProviders(), weekly(tmp_path)
    p.earnings_calendar = Mock(
        return_value=pd.DataFrame(
            {"symbol": ["AAA"] + [f"IGNORED{i}" for i in range(5000)], "reportDate": [date(2026, 11, 1)] * 5001}
        )
    )
    result = collect(p, snap, AS_OF, True, NOW.isoformat())
    assert set(result["earnings_validation"]) == {"AAA"}
    assert len(json.dumps(result).encode()) < MAX_DAY_BYTES
    assert RefreshStore(tmp_path).write(result)


def test_total_quote_outage_keeps_last_publication_and_allows_retry(tmp_path, caplog):
    weekly(tmp_path)
    before = file_hashes(tmp_path)
    p = RefreshProviders()
    p.quote = Mock(return_value=None)
    assert run(tmp_path, p, AS_OF, now=NOW, options_enabled=False)["status"] == "failed"
    assert file_hashes(tmp_path) == before and RefreshStore(tmp_path).dates() == []
    assert "retaining last published" in caplog.text
    assert run(tmp_path, RefreshProviders(), AS_OF, now=NOW, options_enabled=False)["status"] == "ok"


def test_next_day_refresh_preserves_quarantine_first_discovered_in_daily_data(tmp_path):
    weekly(tmp_path)
    # No weekly anomaly yet: the most recent daily observation is authoritative for quarantine.
    RefreshStore(tmp_path).write(
        {
            "as_of": str(AS_OF),
            "weekly_as_of": str(AS_OF),
            "spec_version": "2026-10-19.2",
            "earnings_validation": {
                "AAA": {"next_scheduled": "2026-11-25", "expected_date": "2026-10-29", "outlier": True}
            },
        }
    )
    p = RefreshProviders()
    original_quote = p.quote
    p.quote = lambda symbol: replace(original_quote(symbol), last_trade=datetime(2026, 10, 12, 16))
    result = run(tmp_path, p, date(2026, 10, 12), now=NOW.replace(day=12))
    assert result["earnings_validation"]["AAA"]["validation_status"] == OUTLIER
    assert "chain:AAA" not in p.calls


@pytest.mark.parametrize("raw,metadata", [([], {}), ({}, []), ({"observations": []}, {"seriess": [None]})])
def test_malformed_macro_data_is_explicit_provider_error(raw, metadata):
    http = SimpleNamespace(get_json=Mock(side_effect=[raw, metadata] * len(macro.SERIES)))
    out = macro.collect(SimpleNamespace(http=http, fred_key="synthetic"), AS_OF)
    assert out["state"] == "provider_error"
    assert all(row["state"] == "provider_error" for row in out["series"].values())


@pytest.mark.parametrize("raw", [[], {"data": []}, {"data": {"symbol": "AAA", "options": [None]}}])
def test_malformed_option_chain_is_caught_and_not_cached(tmp_path, raw):
    http, _ = client([Resp(body=json.dumps(raw).encode())], tmp_path)
    ctx = Context(AS_OF, Providers(http))
    value, reason = _guard(ctx, "cboe", ctx.providers.option_chain, "AAA")
    assert value is None and reason and not list(tmp_path.glob("*.gz"))


def test_optional_av_has_one_attempt_and_fmp_keeps_bounded_retries():
    http, session = fmp_http([Resp(503)] * 6)
    waits = []
    http.sleep = waits.append
    ctx = Context(AS_OF, Providers(http, av_key="synthetic", fmp_key="synthetic"))
    assert _guard(ctx, "overview", ctx.providers.overview, "A")[0] is None
    assert len(session.calls) == 4 and waits == [2, 4]
    assert http.used == {"alphavantage": 1, "fmp": 3}


@pytest.mark.parametrize("value", [pd.NA, pd.NaT, None, "", "bad"])
def test_missing_or_invalid_schedule_never_triggers(value):
    assert validate(value, None, AS_OF)["event_eligible"] is False


def test_manual_release_during_outage_preserves_known_event(tmp_path):
    from agent_trading.dashboard.earnings_verdicts import EarningsVerdicts

    verdicts = EarningsVerdicts(
        {"AAA": {"checked_at": str(AS_OF), "reports": [{"date": "2026-10-15", "confirmed": True}]}}
    )
    prior = {"next_scheduled": "2026-10-15", "expected_date": "2026-12-01", "outlier": True}
    snap, p = weekly(tmp_path), RefreshProviders()
    p.earnings_calendar = Mock(return_value=None)
    snap["bands"]["large"]["candidates"][0]["earnings_check"] = prior
    result = collect(p, snap, AS_OF, True, NOW.isoformat(), earnings_verdicts=verdicts)
    assert result["earnings_validation"]["AAA"]["validation_status"] == "Manually verified"
    assert result["options"]["3m"]["calls"]["rows"][0]["events_before_expiry"][0]["date"] == "2026-10-15"
    ctx = Context(AS_OF, _Prov(0, {}))
    ctx.prior_earnings_checks["AAA"], ctx.earnings_verdicts = prior, verdicts
    events = pipeline_phases.collect_events(ctx, {"large": {"candidates": [{"ticker": "AAA", "cik": 1}]}}, {}, {})
    assert events[0]["date"] == "2026-10-15"


@pytest.mark.parametrize("body", [b"", b"{}", b"symbol,reportDate,fiscalDateEnding\nAAA,,2026-09-30"])
def test_bad_calendar_does_not_replace_cached_csv(tmp_path, body):
    good = b"symbol,reportDate,fiscalDateEnding\nAAA,2026-10-15,2026-09-30"
    http, _ = client([Resp(body=body)], tmp_path)
    params = {"function": "EARNINGS_CALENDAR", "horizon": "12month"}
    key = http._key(AV_URL, params, "")
    http._write_cache(key, good)
    http.fresh_only = True
    old = (tmp_path / f"{key}.gz").read_bytes()
    with pytest.raises(FetchError):
        Providers(http, av_key="synthetic").earnings_calendar()
    assert (tmp_path / f"{key}.gz").read_bytes() == old


def test_malformed_sec_facts_and_insider_metadata_stay_local_to_company():
    from agent_trading.dashboard.pipeline_collect import _facts
    from agent_trading.dashboard.sec_insiders import collect as collect_insiders

    http, _ = client([Resp(body=b'{"facts":[1]}'), Resp(body=b'{"filings":[1]}')])
    p = Providers(http)
    ctx = Context(AS_OF, p)
    facts, reason = _facts(ctx, 1)
    assert facts is None and "validation" in reason
    assert collect_insiders(p, 1, AS_OF)["state"] == "provider_error"
