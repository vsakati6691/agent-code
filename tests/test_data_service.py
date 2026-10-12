import logging
from datetime import date

import pandas as pd
import pytest

from agent_trading.data.alphavantage import (
    AlphaVantageClient,
    AlphaVantageError,
    parse_daily_json,
    parse_earnings_csv,
)
from agent_trading.data.cache import merge_bars, read_cache, write_cache
from agent_trading.data.service import MarketDataService, import_csv
from agent_trading.logging_setup import RedactingFilter, redact, register_secret

from .conftest import make_bars

SAMPLE = {
    "Meta Data": {},
    "Time Series (Daily)": {
        "2026-10-09": {"1. open": "10", "2. high": "11", "3. low": "9", "4. close": "10.5", "5. volume": "1000"},
        "2026-10-08": {"1. open": "9", "2. high": "10", "3. low": "8.5", "4. close": "9.5", "5. volume": "900"},
    },
}


def test_parse_daily_json_sorted():
    df = parse_daily_json(SAMPLE, "X")
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-10-08", "2026-10-09"]
    assert df.loc["2026-10-09", "close"] == 10.5


@pytest.mark.parametrize("key", ["Information", "Note", "Error Message"])
def test_api_notices_raise(key):
    with pytest.raises(AlphaVantageError):
        parse_daily_json({key: "premium feature / rate limit"}, "X")


def test_parse_earnings_csv():
    text = "symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\r\nNVDA,NVIDIA CORPORATION,2026-11-18,2026-10-31,2.47,USD,\r\n"
    df = parse_earnings_csv(text)
    assert df.iloc[0]["reportDate"] == date(2026, 11, 18)
    with pytest.raises(AlphaVantageError):
        parse_earnings_csv('{"Information": "rate limit"}')


def test_merge_prefers_new_data():
    old = make_bars(n=10, end="2026-10-08")
    new = make_bars(n=3, end="2026-10-09", start=999)
    merged = merge_bars(old, new)
    assert merged.index.is_unique and len(merged) == 11
    assert merged.loc["2026-10-09", "close"] == new.loc["2026-10-09", "close"]


class FakeClient:
    def __init__(self, fail=()):
        self.calls_made = 0
        self.fail = set(fail)

    def daily_bars(self, symbol, outputsize="compact"):
        self.calls_made += 1
        if symbol in self.fail:
            raise AlphaVantageError(f"{symbol}: boom")
        return make_bars(n=100)

    def earnings_calendar(self, horizon="3month"):
        self.calls_made += 1
        return parse_earnings_csv("symbol,name,reportDate,fiscalDateEnding,estimate,currency,timeOfTheDay\nAAA,A,2026-10-15,2026-09-30,1.0,USD,\n")


def test_refresh_respects_budget_and_reserves_earnings_call(settings):
    from dataclasses import replace

    s = replace(settings, data=replace(settings.data, daily_request_budget=3, min_history_bars=50))
    client = FakeClient()
    svc = MarketDataService(s, client)
    status = svc.refresh(["A", "B", "C", "D"], date(2026, 10, 12))
    assert sum(m.startswith("updated") for m in status.values()) == 2
    assert sum("budget" in m for m in status.values()) == 2
    svc.refresh_earnings(date(2026, 10, 12))
    assert client.calls_made == 3
    e = svc.earnings(date(2026, 10, 12))
    assert e.available and "Alpha Vantage" in e.source


def test_failed_fetch_is_reported_not_raised(settings):
    svc = MarketDataService(settings, FakeClient(fail={"BAD"}))
    status = svc.refresh(["BAD"], date(2026, 10, 12))
    assert status["BAD"].startswith("fetch failed")


def test_load_rejects_missing_and_stale(settings):
    cache = settings.resolve(settings.data.cache_dir)
    write_cache(cache, "GOOD", make_bars())
    write_cache(cache, "OLD", make_bars(end="2026-08-01"))
    res = MarketDataService(settings).load(["GOOD", "OLD", "NONE"], date(2026, 10, 12))
    assert set(res.bars) == {"GOOD"}
    assert set(res.rejected) == {"OLD", "NONE"}


def test_missing_earnings_is_flagged_unverified(settings):
    e = MarketDataService(settings).earnings(date(2026, 10, 12))
    assert not e.available and e.error


def test_import_csv(settings, tmp_path):
    src = tmp_path / "x.csv"
    make_bars(n=120).reset_index().to_csv(src, index=False)
    assert import_csv(settings, "X", src) == 120
    assert len(read_cache(settings.resolve(settings.data.cache_dir), "X")) == 120


RH_PAYLOAD = {
    "data": {"results": [{"symbol": "SPY", "interval": "day", "bars": [
        {"begins_at": "2026-10-08T00:00:00Z", "open_price": "774.86", "close_price": "773.93",
         "high_price": "777.09", "low_price": "770.435", "volume": 40431076, "session": "reg"},
        {"begins_at": "2026-10-09T00:00:00Z", "open_price": "776.24", "close_price": "778.57",
         "high_price": "779.42", "low_price": "775.14", "volume": 22624488, "session": "reg"},
        {"begins_at": "2026-10-10T00:00:00Z", "open_price": "1", "close_price": "1",
         "high_price": "1", "low_price": "1", "volume": 0, "interpolated": True},
    ]}]},
    "guide": "...",
}


def test_parse_robinhood_skips_interpolated():
    from agent_trading.data.robinhood import parse_historicals

    df = parse_historicals(RH_PAYLOAD)["SPY"]
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-10-08", "2026-10-09"]
    assert df.loc["2026-10-09", "close"] == 778.57


def test_parse_robinhood_rejects_intraday():
    from agent_trading.data.robinhood import parse_historicals

    bad = {"data": {"results": [{**RH_PAYLOAD["data"]["results"][0], "interval": "hour"}]}}
    with pytest.raises(ValueError, match="daily"):
        parse_historicals(bad)


def test_import_robinhood_merges_into_cache(settings, tmp_path):
    import json

    from agent_trading.data.service import import_robinhood

    path = tmp_path / "rh.json"
    path.write_text(json.dumps(RH_PAYLOAD))
    assert import_robinhood(settings, path) == {"SPY": 2}


def test_api_key_never_logged(caplog):
    register_secret("SUPERSECRETKEY123")
    assert "SUPERSECRETKEY123" not in redact("GET https://x/query?symbol=A&apikey=SUPERSECRETKEY123")
    assert "abcd1234" not in redact("url?apikey=abcd1234&x=1")
    record = logging.LogRecord("t", logging.INFO, "", 0, "key is %s", ("SUPERSECRETKEY123",), None)
    RedactingFilter().filter(record)
    assert "SUPERSECRETKEY123" not in record.getMessage()


def test_client_sends_key_but_errors_hide_it():
    class Resp:
        status_code = 500

    class Session:
        def get(self, url, params, timeout):
            assert params["apikey"] == "k-123456"
            return Resp()

    client = AlphaVantageClient("k-123456", session=Session(), pause_seconds=0)
    with pytest.raises(AlphaVantageError) as exc:
        client.daily_bars("SPY")
    assert "k-123456" not in str(exc.value)
