"""Dashboard HTTP client (allow-list, bounded retries, budgets, cache) and provider parsers."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest
import requests

from agent_trading.dashboard import providers as pv
from agent_trading.dashboard.http import BudgetExceeded, FetchError, HttpClient, ProviderLimits

PKG = Path(__file__).resolve().parents[1] / "src" / "agent_trading" / "dashboard"


class Resp:
    def __init__(self, status=200, body=b"{}", headers=None):
        self.status_code, self.content, self.headers = status, body, headers or {}


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None, allow_redirects=True, headers=None):
        self.calls.append((url, params, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(responses, tmp_path=None, budget=10):
    s = Session(responses)
    c = HttpClient(
        tmp_path,
        "test research test@example.com",
        session=s,
        sleep=lambda x: None,
        limits={
            "sec": ProviderLimits(0, budget),
            "cboe": ProviderLimits(0, budget),
            "alphavantage": ProviderLimits(0, budget),
        },
    )
    return c, s


def test_only_allow_listed_https_hosts():
    c, s = client([])
    for url in ("https://evil.example.com/x", "http://data.sec.gov/x", "ftp://data.sec.gov/x"):
        with pytest.raises(FetchError, match="host not allowed"):
            c.get_bytes(url)
    assert s.calls == []


def test_retries_transient_errors_then_succeeds():
    c, s = client([Resp(503), requests.ConnectionError(), Resp(200, b'{"ok": 1}')])
    assert c.get_json("https://data.sec.gov/x") == {"ok": 1}
    assert len(s.calls) == 3


def test_retries_are_bounded_and_permanent_errors_fail_fast():
    c, s = client([Resp(503)] * 5)
    with pytest.raises(FetchError, match="after 3 attempts"):
        c.get_bytes("https://data.sec.gov/x")
    assert len(s.calls) == 3
    c, s = client([Resp(404)])
    with pytest.raises(FetchError, match="HTTP 404"):
        c.get_bytes("https://data.sec.gov/x")
    assert len(s.calls) == 1


def test_rate_limit_honours_retry_after_and_slows_the_provider():
    waits = []
    c, s = client([Resp(429, headers={"Retry-After": "30"}), Resp(429), Resp(429), Resp(200, b"ok")])
    c.sleep = waits.append
    assert c.get_bytes("https://cdn-api.cboe.com/x") == b"ok"
    assert 30 in waits and len(s.calls) == 4  # 429 gets more than the usual 3 attempts
    assert c.limits["cboe"].min_interval > 0 and c.usage()["rate_limited"]["cboe"] == 3
    from agent_trading.dashboard.http import DEFAULT_LIMITS

    d = HttpClient(None, "ua x@y.z", session=Session([Resp(429), Resp(200)]), sleep=lambda x: None)
    d.get_bytes("https://cdn-api.cboe.com/y")
    assert DEFAULT_LIMITS["cboe"].min_interval == 0.5 < d.limits["cboe"].min_interval  # defaults untouched
    c, s = client([Resp(429)] * 9)
    c.sleep = lambda x: None
    with pytest.raises(FetchError, match="after 5 attempts"):
        c.get_bytes("https://cdn-api.cboe.com/x")


def test_throttled_provider_recovers_gradually_but_not_below_base():
    from agent_trading.dashboard.http import DEFAULT_LIMITS, RECOVER_AFTER

    c = HttpClient(
        None, "ua x@y.z", session=Session([Resp(429)] + [Resp(200)] * (3 * RECOVER_AFTER)), sleep=lambda x: None
    )
    c.get_bytes("https://cdn-api.cboe.com/a")
    slow = c.limits["cboe"].min_interval
    for i in range(3 * RECOVER_AFTER - 1):
        c.get_bytes(f"https://cdn-api.cboe.com/{i}")
    assert DEFAULT_LIMITS["cboe"].min_interval <= c.limits["cboe"].min_interval < slow


def test_budget_is_enforced():
    c, s = client([Resp(200)] * 5, budget=2)
    c.get_bytes("https://data.sec.gov/a")
    c.get_bytes("https://data.sec.gov/b")
    with pytest.raises(BudgetExceeded):
        c.get_bytes("https://data.sec.gov/c")
    assert c.budget_left("sec") == 0


def test_redirects_only_within_the_same_provider():
    c, s = client([Resp(307, headers={"Location": "https://cdn-api.cboe.com/x"}), Resp(200, b"1")])
    assert c.get_bytes("https://cdn.cboe.com/x") == b"1"
    c, s = client([Resp(307, headers={"Location": "https://evil.example.com/x"})])
    with pytest.raises(FetchError):
        c.get_bytes("https://cdn.cboe.com/x")


def test_cache_avoids_refetch_and_never_stores_the_api_key(tmp_path):
    c, s = client([Resp(200, b"abc")], tmp_path)
    url = "https://www.alphavantage.co/query"
    assert c.get_bytes(url, {"function": "X", "apikey": "SECRETKEY123"}, max_age_hours=1) == b"abc"
    assert c.get_bytes(url, {"function": "X", "apikey": "SECRETKEY123"}, max_age_hours=1) == b"abc"
    assert len(s.calls) == 1 and c.cache_hits == 1
    assert not any("SECRETKEY123" in p.name for p in tmp_path.iterdir())


def test_dashboard_has_one_network_module_and_no_private_imports():
    """Only http.py may touch the network; nothing may import account, ticket or broker code."""
    forbidden = {"account", "live", "order_gate", "killswitch", "journal", "paper", "execution", "daily"}
    for path in PKG.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = set(node.module.split("."))
                assert not parts & forbidden, f"{path.name} imports {node.module}"
        text = path.read_text(encoding="utf-8")
        if path.name != "http.py":
            assert "requests." not in text and "urllib.request" not in text, path.name
    assert "def post" not in (PKG / "http.py").read_text(encoding="utf-8")
    assert ".post(" not in (PKG / "http.py").read_text(encoding="utf-8")


# --- parsers ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, etf, reason",
    [
        ("Apple Inc. - Common Stock", False, None),
        ("Alphabet Inc. Class A Common Stock", False, None),
        ("Foo Corp Warrants", False, "not common stock"),
        ("Bar Acquisition Corp Class A Ordinary Shares", False, "blank-check"),
        ("Vanguard Total Market ETF", True, "ETF"),
        ("Baz Holdings Depositary Shares", False, "not common"),
        ("Qux 8.00% Series A Preferred Stock", False, "not common"),
    ],
)
def test_common_stock_rules(name, etf, reason):
    got = pv.common_stock_reason(name, etf, False, "")
    assert (got is None) if reason is None else (reason in got)


def test_symbol_directories_and_canonical_tickers():
    nasdaq = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\nZZZT|Test|Q|Y|N|100|N|N\nFile Creation Time: x|||||||\n"
    )
    other = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "BRK.B|Berkshire Hathaway Inc. New Common Stock|N|BRK.B|N|40|N|BRK.B\n"
    )
    df = pv.parse_symbol_directories(nasdaq, other)
    assert df.loc["BRK.B", "exchange"] == "NYSE" and bool(df.loc["ZZZT", "test_issue"])
    assert pv.canonical("BRK-B") == pv.canonical("brk/b") == "BRK.B"


def test_sp500_table_parse_and_size_check():
    tick = lambda i: "".join(chr(65 + (i // 26**k) % 26) for k in range(3))  # noqa: E731 - AAA, BAA, ...
    rows = "".join(
        f"<tr><td><a>{tick(i)}</a></td><td>Co {i}</td><td>Energy</td><td>Oil</td><td>X</td><td>2000-01-01</td>"
        f"<td>{1000 + i}</td></tr>"
        for i in range(500)
    )
    html = (
        '<table id="constituents"><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th>'
        "<th>HQ</th><th>Date added</th><th>CIK</th></tr>" + rows + "</table>"
    )
    df = pv.parse_sp500({"parse": {"text": html}})
    assert len(df) == 500 and df.iloc[0]["sector"] == "Energy" and df.iloc[0]["cik"] == 1000
    with pytest.raises(FetchError):
        pv.parse_sp500({"parse": {"text": html.replace(rows, "")}})


def test_cboe_history_drops_padding_without_fabricating_ranges():
    raw = {
        "data": [
            {"date": "2026-01-02", "open": 0, "high": 10, "low": 9, "close": 9.5, "volume": 1},
            {"date": "2026-01-05", "open": 10.6, "high": 10.5, "low": 9.9, "close": 10.2, "volume": 1},
            {"date": "2026-01-06", "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0},
        ]
    }
    df = pv.parse_cboe_history(raw)
    assert len(df) == 2 and df.attrs["dropped_bars"] == 1
    assert df.loc["2026-01-02", "open"] == 0 and df.loc["2026-01-05", "high"] == 10.5


def test_cboe_quote_keeps_the_session_range_and_volume():
    raw = {
        "timestamp": "2026-10-17 00:05:25",
        "data": {
            "symbol": "IJH",
            "open": 73.19,
            "high": 73.455,
            "low": 72.12,
            "close": 72.35,
            "prev_day_close": 73.03,
            "price_change": -0.68,
            "volume": 8881319,
            "iv30": 16.199,
            "last_trade_time": "2026-10-16T15:59:59",
        },
    }
    q = pv.parse_cboe_quote(raw)
    assert (q.open, q.high, q.low, q.close, q.prev_close, q.volume) == (73.19, 73.455, 72.12, 72.35, 73.03, 8881319)
    assert q.change == -0.68
    bare = pv.parse_cboe_quote({"data": {"symbol": "IJH", "close": 72.35}})
    assert (bare.open, bare.high, bare.low, bare.volume, bare.change) == (None, None, None, None, None)


def test_cboe_chain_and_occ_parse():
    assert pv.parse_occ("AAPL270115C00250000") == {
        "root": "AAPL",
        "expiration": date(2027, 1, 15),
        "type": "call",
        "strike": 250.0,
    }
    assert pv.parse_occ("BRKB270115C00500000")["root"] == "BRKB"
    raw = {
        "timestamp": "t",
        "data": {
            "symbol": "AAPL",
            "close": 100,
            "current_price": 101,
            "last_trade_time": "2026-10-09T16:00:00",
            "options": [{"option": "AAPL270115C00250000", "bid": 1, "ask": 1.1, "iv": 0.3, "delta": "x"}],
        },
    }
    under, rows = pv.parse_cboe_chain(raw)
    assert under["close"] == 100 and rows[0]["delta"] is None and rows[0]["strike"] == 250


def test_share_frames_pick_latest_on_or_before_as_of():
    frames = [
        {"data": [{"cik": 1, "end": "2026-07-01", "val": 10}, {"cik": 2, "end": "2026-11-01", "val": 5}]},
        {"data": [{"cik": 1, "end": "2026-04-01", "val": 9}, {"cik": 2, "end": "2026-05-01", "val": 4}]},
    ]
    out = pv.parse_share_frames(frames, date(2026, 10, 9))
    assert out == {1: (10.0, "2026-07-01"), 2: (4.0, "2026-05-01")}
    assert pv.share_frame_periods(date(2026, 2, 1)) == ["CY2026Q1I", "CY2025Q4I", "CY2025Q3I"]


def test_sic_sector_mapping():
    assert pv.sector_from_sic("7372") == "Information Technology"
    assert pv.sector_from_sic("1311") == "Energy" and pv.sector_from_sic(None) == "Unknown"
