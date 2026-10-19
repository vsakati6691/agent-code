"""Fault injection and ranking integration for the live dashboard gaps."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from agent_trading.dashboard import institutional_fallback as fmp
from agent_trading.dashboard import pipeline_external, pipeline_phases, short_term, site_short_term, spec
from agent_trading.dashboard.http import FetchError, ProviderLimits
from agent_trading.dashboard.pipeline_context import Context
from agent_trading.dashboard.providers import Providers
from agent_trading.dashboard.short_term_store import ShortTermStore
from agent_trading.dashboard.site_sector import status as sector_status
from tests.test_dashboard_http import Resp, client
from tests.test_dashboard_resilience import score

NOW = datetime(2026, 10, 19, 15, 0, tzinfo=UTC)


def aggregate(**changes):
    return {"symbol": "NVDA", "date": "2026-06-30", "investorsHolding": 300, "numberOf13Fshares": 12345, **changes}


def test_sec_failure_executes_actual_http_fmp_adapter_and_keeps_neutrality():
    http, session = client([Resp(200, json.dumps([aggregate()]).encode())])
    http.limits["fmp"] = ProviderLimits(0, 10)
    providers = Providers(http, fmp_key="synthetic")
    row = pipeline_external.institutional_record(
        [],
        {},
        "NVDA",
        NOW.date(),
        {"state": "provider_error", "reason": "SEC failed"},
        providers=providers,
        current_collection=True,
    )
    assert row["state"] == row["fallback_status"] == "available"
    assert row["provider"] == "fmp" and row["primary_state"] == "provider_error"
    assert row["holder_count"] == 300 and row["score_adjustment"] == 0
    assert session.calls[0][0] == fmp.ENDPOINT
    assert session.calls[0][1] == {"symbol": "NVDA", "year": 2026, "quarter": 2, "apikey": "synthetic"}


@pytest.mark.parametrize("body", [b"{}", b"[]", b"null", b"<html>error</html>", b'{"Error Message":"bad"}'])
def test_both_institutional_providers_fail_without_crashing_or_zero_ownership(body):
    http, session = client([Resp(200, body)])
    http.limits["fmp"] = ProviderLimits(0, 10)
    row = pipeline_external.institutional_record(
        [],
        {},
        "NVDA",
        NOW.date(),
        {"state": "provider_error"},
        providers=Providers(http, fmp_key="synthetic"),
        current_collection=True,
    )
    assert len(session.calls) == 1
    assert row["state"] == row["fallback_status"] == "provider_error"
    assert row["score_adjustment"] == 0 and "holder_count" not in row


@pytest.mark.parametrize(
    "change",
    [
        {"symbol": "MU"},
        {"date": "2026-09-30"},
        {"investorsHolding": None},
        {"investorsHolding": True},
        {"investorsHolding": -1},
        {"numberOf13Fshares": float("nan")},
        {"numberOf13Fshares": 1.2},
    ],
)
def test_fmp_rejects_incorrect_identity_and_malformed_counts(change):
    with pytest.raises(FetchError):
        fmp.parse([aggregate(**change)], "NVDA", date(2026, 6, 30), NOW.isoformat())


def test_no_fmp_backfill_or_unnecessary_fallback(monkeypatch):
    p = Mock(fmp_key="synthetic")
    for current, state in [(False, "provider_error"), (True, "available")]:
        monkeypatch.setattr(pipeline_external.institutions, "company", lambda *args, state=state: {"state": state})
        pipeline_external.institutional_record([], {}, "NVDA", NOW.date(), providers=p, current_collection=current)
    p.institutional_holders.assert_not_called()
    assert fmp.eligible_quarter(date(2026, 8, 13)) == date(2026, 3, 31)
    assert fmp.eligible_quarter(date(2026, 8, 14)) == date(2026, 6, 30)


def test_sector_deduction_runs_before_real_candidate_cutoff(monkeypatch):
    band = replace(spec.BANDS[0], universe="sp500", max_results=4)
    monkeypatch.setattr(spec, "BANDS", [band])
    rows = [
        {"ticker": f"T{i}", "score": score(f"T{i}", 80 - i), "sector": "Technology", "metrics": {}} for i in range(4)
    ]
    rows.append({"ticker": "E", "score": score("E", 74), "sector": "Energy", "metrics": {}})
    for row in rows:
        row["bars"] = pd.DataFrame({"close": [99, 100, 101]})
    monkeypatch.setattr(pipeline_phases, "evaluate", lambda *a: rows)
    monkeypatch.setattr(pipeline_phases, "tradable_only", lambda ctx, band, ranked, *args: ranked)

    def detail(ctx, band, row, *args):
        s = row["score"]
        return {
            "ticker": s.ticker,
            "rank": s.rank,
            "composite": s.composite,
            "components": {},
            "raw_composite": s.raw_composite,
            "sector_penalty": s.sector_penalty,
        }

    monkeypatch.setattr(pipeline_phases, "candidate_detail", detail)
    ctx = Context(NOW.date(), Mock())
    result = pipeline_phases.score_bands(
        ctx, {}, pd.DataFrame(), pd.DataFrame(), [], [], {band.benchmark: None}, None, Mock(), [], {}
    )[0][band.key]
    assert result["candidates"][0]["ticker"] == "E"  # originally below the top-four cutoff
    assert result["candidates"][1]["composite"] == 70
    assert result["sector_adjustment"]["eligible_penalized"] == 4
    assert "applied before selection" in sector_status({"bands": {band.key: result}}, [band.key])
    assert "pending a new collection" in sector_status(
        {"bands": {"large": {"candidates": [{"ticker": "A"}]}}}, ["large"]
    )


def underlying(symbol="NVDA", **changes):
    return {
        "symbol": symbol,
        "price": 100,
        "timestamp": "2026-10-19T14:45:00Z",
        "last_trade_time": "2026-10-19T10:45:00",
        **changes,
    }


def contract(expiry="261019", kind="C", symbol="NVDA", **changes):
    return {
        "option": f"{symbol}{expiry}{kind}00100000",
        "bid": 1,
        "ask": 1.1,
        "open_interest": 100,
        "volume": 50,
        **changes,
    }


def test_real_expiries_calendar_dte_and_ask_loss_without_time_model():
    row = short_term.select("NVDA", underlying(), [contract(), contract("261020"), contract("261023", "P")], NOW)
    assert row["state"] == "available"
    assert [(r["window"], r["dte"]) for r in row["rows"]] == [("0DTE", 0), ("1DTE", 1), ("Next listed expiry", 1)]
    assert row["rows"][0]["premium"] == row["rows"][0]["max_premium_loss"] == 110
    assert "probability" not in row["rows"][0]
    row = short_term.select("NVDA", underlying(), [contract("261023")], NOW)
    assert [(r["window"], r["dte"]) for r in row["rows"]] == [("Next listed expiry", 4)]


@pytest.mark.parametrize(
    "changes",
    [
        {"bid": 0},
        {"ask": 0.9},
        {"ask": 2},
        {"volume": 9},
        {"open_interest": 99},
        {"volume": 10.5},
        {"bid": True},
        {"bid": float("nan")},
        {"option": "NVDA1261019C00100000"},
        {"option": "NVDA261018C00100000"},
        {"option": "MU261019C00100000"},
    ],
)
def test_invalid_adjusted_and_illiquid_contracts_never_enter_short_term_lists(changes):
    assert short_term.select("NVDA", underlying(), [contract(**changes)], NOW)["rows"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"price": None},
        {"price": 0},
        {"price": True},
        {"symbol": "MU"},
        {"timestamp": "2026-10-19"},
        {"timestamp": "2026-10-19T14:34:59Z"},
        {"timestamp": "2026-10-19T15:01:01Z"},
        {"last_trade_time": "2026-10-16T10:45:00"},
        {"last_trade_time": None},
    ],
)
def test_stale_future_missing_and_mismatched_underlying_rejected(changes):
    row = short_term.select("NVDA", underlying(**changes), [contract()], NOW)
    assert row["state"] == "unavailable" and row["rows"] == []


def test_duplicate_contracts_and_empty_chain():
    assert short_term.select("NVDA", underlying(), [contract(), contract(bid=1.05)], NOW)["rows"] == []
    assert short_term.select("NVDA", underlying(), [], NOW)["state"] == "unavailable"
    with pytest.raises(ValueError):
        short_term.select("NVDA", underlying(), [], NOW.replace(tzinfo=None))


def test_normalized_duplicate_and_overflow_rejected():
    duplicate = contract(option=contract()["option"].lower() + " ")
    assert short_term.select("NVDA", underlying(), [contract(), duplicate], NOW)["rows"] == []
    assert short_term.select("NVDA", underlying(), [contract(bid=1e308, ask=1e308)], NOW)["rows"] == []


def test_chain_parser_preserves_boolean_invalidity_before_scanner():
    from agent_trading.dashboard.provider_parsers import parse_cboe_chain

    raw = {
        "timestamp": underlying()["timestamp"],
        "data": {
            "symbol": "NVDA",
            "current_price": 100,
            "last_trade_time": underlying()["last_trade_time"],
            "options": [contract(bid=True)],
        },
    }
    under, rows = parse_cboe_chain(raw)
    assert rows[0]["bid"] is None
    assert short_term.select("NVDA", under, rows, NOW)["rows"] == []


def test_cli_uses_fresh_bounded_client_and_refresh_receives_fmp_key(tmp_path, monkeypatch):
    from agent_trading.dashboard import __main__ as cli
    from agent_trading.dashboard import refresh

    seen = []

    def capture(provider, now=None):
        seen.append(provider)
        return {"status": "failed", "collected_at": NOW.isoformat(), "symbols": []}

    monkeypatch.setattr(short_term, "collect", capture)
    args = SimpleNamespace(data=str(tmp_path), cache=None, commit="fixture", as_of=None, no_options=True)
    assert cli.cmd_short_term(args) == 2
    http = seen[0].http
    assert http.fresh_only and http.timeout == 10 and http.limits["cboe"].budget == 12
    assert http.deadline <= http.clock() + 120
    assert ShortTermStore(tmp_path).latest() is None
    monkeypatch.setenv("FMP_API_KEY", "synthetic-fmp")
    monkeypatch.setattr(refresh, "run", lambda path, provider, *a, **kw: capture(provider))
    assert cli.cmd_refresh(args) == 2
    assert seen[-1].fmp_key == "synthetic-fmp"


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-10-19T20:00:00Z",
        "2026-10-19T13:29:59Z",
        "2026-10-18T15:00:00Z",
        "2026-11-27T18:00:00Z",
        "2026-12-24T18:00:00Z",
        "2026-07-03T15:00:00Z",
    ],
)
def test_market_close_early_close_holiday_weekend_no_network(stamp):
    p = Mock()
    payload = short_term.collect(p, datetime.fromisoformat(stamp))
    assert payload["status"] == "closed"
    p.option_chain.assert_not_called()


def test_partial_failure_isolates_symbols_and_all_failure_keeps_last_good(tmp_path):
    p = SimpleNamespace(option_chain=Mock(side_effect=lambda t: (underlying(t), [contract(symbol=t)])))
    store = ShortTermStore(tmp_path)
    payload = short_term.collect(p, NOW)
    assert payload["status"] == "ok" and p.option_chain.call_count == 4
    assert store.write(payload, "fixture")
    assert not store.write(payload, "fixture")
    before = (store.folder(store.key(payload)) / "scan.json").read_bytes()
    p.option_chain.side_effect = FetchError("failed")
    failed = short_term.collect(p, NOW)
    assert failed["status"] == "failed" and not store.write(failed)
    assert store.latest() == payload and store.verify_all() == []
    assert (store.folder(store.key(payload)) / "scan.json").read_bytes() == before
    p.option_chain.side_effect = [FetchError("failed")] * 3 + [(underlying("AVGO"), [contract(symbol="AVGO")])]
    partial = short_term.collect(p, NOW)
    assert partial["status"] == "partial" and partial["symbols"][-1]["rows"]
    (store.folder(store.key(payload)) / "scan.json").write_bytes(b"{}")
    assert store.verify_all()
    with pytest.raises(ValueError):
        store.latest()


def test_short_term_render_empty_collected_escaped_and_runtime_expiry_status():
    assert "No short-term scan collected" in site_short_term.desk(None)
    payload = short_term.collect(SimpleNamespace(option_chain=lambda t: (underlying(t), [contract(symbol=t)])), NOW)
    html = site_short_term.desk(payload)
    assert "0DTE" in html and "1DTE" in html and "Next listed expiry" in html
    assert 'data-short-expiry="2026-10-19T16:00:00-04:00"' in html
    assert "freshness unchecked" in html
    assert "Expired / research cutoff passed" in site_short_term.JS and "Stale observation" in site_short_term.JS
    payload["symbols"][0]["reason"] = "<script>bad</script>"
    assert "<script>bad</script>" not in site_short_term.desk(payload)


def test_stored_intraday_data_cannot_leak_into_customer_build(tmp_path):
    from agent_trading.dashboard import site_customer
    from agent_trading.dashboard.site import build_site
    from tests.dashboard_ci import check_links

    data = tmp_path / "data"
    payload = short_term.collect(SimpleNamespace(option_chain=lambda t: (underlying(t), [contract(symbol=t)])), NOW)
    ShortTermStore(data).write(payload)
    full, customer = tmp_path / "full", tmp_path / "customer"
    build_site(data, full)
    build_site(data, customer, edition="customer")
    assert (full / "options-short-term.html").exists()
    assert (full / "assets/short-term.js").exists()
    assert "Within delayed quote age limit" in (full / "assets/short-term.js").read_text(encoding="utf-8")
    assert not (customer / "options-short-term.html").exists()
    assert not (customer / "assets/short-term.js").exists()
    assert not (customer / "short-term").exists()
    assert site_customer.check(customer) == []
    assert check_links(full) == check_links(customer) == []
