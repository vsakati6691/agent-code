"""Exercise SDK-shaped data, denied entitlements, causal books and unattended operation."""

from datetime import datetime, timedelta
from decimal import Decimal as D
from types import SimpleNamespace as Obj

import longbridge.openapi as sdk
import pytest

from agent_trading.intraday.calendar import NY, next_session, session
from agent_trading.intraday.config import Settings
from agent_trading.intraday.demo import demo_snapshot
from agent_trading.intraday.engine import Simulator
from agent_trading.intraday.longbridge_api import CalendarReader, DataUnavailable, LongbridgeAPI
from agent_trading.intraday.longbridge_provider import (
    BarCache,
    LongbridgeProvider,
    candle,
    complete_day,
    news_time,
    occ_symbol,
    previous_sessions,
    vendor_symbol,
)
from agent_trading.intraday.notifications import emit_alerts
from agent_trading.intraday.options import quote_problems
from agent_trading.intraday.providers import FileProvider
from agent_trading.intraday.scanner import scan
from agent_trading.intraday.service import Service
from agent_trading.intraday.store import Store

NOW = datetime(2026, 10, 20, 9, 50, tzinfo=NY)
SYMBOL = "ALFA261021C100000.US"


class FakeAPI:
    sdk = sdk

    def __init__(self):
        self.calls = []
        self.bid, self.ask, self.size = D("0.38"), D("0.40"), 1
        self.now = NOW
        self.dates = [next_session(NOW.date())]
        self.headlines = []
        self.calendar = Obj(list=[], next_date="")
        self.greek_missing = False
        self.fail = None

    def on_candle(self, callback):
        self.callback = callback

    def call(self, context, method, *args):
        self.calls.append((context, method, args))
        if method == self.fail:
            raise DataUnavailable("Longbridge quote: market-data permission denied")
        if method == "option_chain_expiry_date_list":
            return self.dates
        if method == "option_chain_info_by_date":
            return [
                Obj(standard=True, call_symbol=SYMBOL, put_symbol=""),
                Obj(standard=False, call_symbol="OLD261021C100000.US", put_symbol=""),
            ]
        if method == "option_quote":
            return [
                Obj(
                    symbol=s,
                    timestamp=self.now,
                    volume=200,
                    open_interest=1000,
                    expiry_date=next_session(NOW.date()),
                    strike_price=D(100),
                    contract_multiplier=D(100),
                    contract_size=D(100),
                    direction=sdk.OptionDirection.Call,
                    underlying_symbol="ALFA.US",
                    implied_volatility=D("0.3"),
                    trade_status=sdk.TradeStatus.Normal,
                )
                for s in args[0]
            ]
        if method == "calc_indexes":
            return [
                Obj(
                    symbol=s,
                    delta=D("0.5"),
                    gamma=D("0.1"),
                    theta=None if self.greek_missing else D("-5"),
                    vega=D("10"),
                )
                for s in args[0]
            ]
        if method == "quote":
            return [
                Obj(symbol=s, timestamp=self.now, last_done=D(100), trade_status=sdk.TradeStatus.Normal)
                for s in args[0]
            ]
        if method == "depth":
            return Obj(
                bids=[Obj(position=1, price=self.bid, volume=self.size)],
                asks=[Obj(position=1, price=self.ask, volume=self.size)],
            )
        if method == "news":
            return self.headlines
        if method == "finance_calendar":
            return self.calendar
        return []


@pytest.fixture
def provider(tmp_path):
    api = FakeAPI()
    p = LongbridgeProvider(Settings(), api=api, cache=tmp_path / "cache", clock=lambda: api.now)
    return p


def test_sdk_shape_and_symbols(provider):
    assert occ_symbol(SYMBOL) == "O:ALFA261021C00100000"
    assert vendor_symbol(occ_symbol(SYMBOL)) == SYMBOL
    assert occ_symbol("BRK.B261021P5000.US") == "O:BRK.B261021P00005000"
    with pytest.raises(ValueError):
        occ_symbol("AAPL.US")
    snap = provider.enrich(demo_snapshot(NOW, provider.cfg), ["ALFA"], NOW)
    assert len(snap.contracts) == 1
    c = snap.contracts[0]
    assert c.quote_time_basis == "changed_depth_receipt"
    assert c.greek_units == "longbridge_raw"
    assert not quote_problems(c, NOW, provider.cfg)


def test_no_expiry_fallback_and_adjusted_contracts(provider):
    provider.api.dates = [NOW.date() + timedelta(days=3)]
    snap = provider.enrich(demo_snapshot(NOW, provider.cfg), ["ALFA"], NOW)
    assert not snap.contracts
    assert not any(m == "option_quote" for _, m, _ in provider.api.calls)


def test_unchanged_books_age_and_persist_across_restart(provider):
    snap = demo_snapshot(NOW, provider.cfg)
    first = provider.enrich(snap, ["ALFA"], NOW).contracts[0]
    provider.api.now += timedelta(seconds=31)
    later = provider.enrich(snap, ["ALFA"], provider.api.now).contracts[0]
    assert later.quote_at == first.quote_at
    assert "stale or future quote" in quote_problems(later, provider.api.now, provider.cfg)
    restarted = LongbridgeProvider(provider.cfg, api=provider.api, cache=provider.cache.path, clock=provider.clock)
    again = restarted.enrich(snap, ["ALFA"], provider.api.now).contracts[0]
    assert again.quote_at == first.quote_at
    provider.api.size = 2
    changed = restarted.enrich(snap, ["ALFA"], provider.api.now).contracts[0]
    assert changed.quote_at == provider.api.now


def test_receipt_time_does_not_hide_stale_option_trade(provider):
    c = provider.enrich(demo_snapshot(NOW, provider.cfg), ["ALFA"], NOW).contracts[0]
    stale = c.model_copy(update={"volume_at": NOW - timedelta(minutes=5)})
    assert "receipt-timed depth requires a recent option trade" in quote_problems(stale, NOW, provider.cfg)


def test_missing_greeks_and_permission_error_fail_closed(provider):
    snap = demo_snapshot(NOW, provider.cfg)
    provider.api.greek_missing = True
    assert not provider.enrich(snap, ["ALFA"], NOW).contracts
    provider.api.fail = "option_quote"
    denied = provider.enrich(snap, ["ALFA"], NOW)
    assert denied.problems and not denied.contracts
    count = len(provider.api.calls)
    provider.enrich(snap, ["ALFA"], NOW)
    assert len(provider.api.calls) == count  # no entitlement retry loop


def test_exact_held_expiry_monitor_does_not_query_new_chain(provider):
    snap = demo_snapshot(NOW, provider.cfg)
    held = provider.enrich(snap, ["ALFA"], NOW).contracts[0]
    provider.set_holdings([held])
    provider.api.calls.clear()
    provider.api.now += timedelta(days=1)
    result = provider.enrich(snap, [], provider.api.now)
    assert result.contracts[0].symbol == held.symbol
    assert not any("chain" in m for _, m, _ in provider.api.calls)


def raw_bar(at, volume=100):
    return Obj(timestamp=at, open=D(100), high=D(101), low=D(99), close=D(100), volume=volume, turnover=D(100) * volume)


def test_bar_end_vwap_and_no_partial_or_zero_volume():
    raw = raw_bar(NOW - timedelta(minutes=1))
    b = candle(raw, NOW)
    assert b.end == NOW and b.vwap == 100
    assert candle(raw, NOW - timedelta(seconds=1)) is None
    assert candle(raw_bar(NOW - timedelta(minutes=1), 0), NOW) is None
    assert candle(raw_bar(NOW.replace(hour=8)), NOW) is None


def test_cache_rejects_incomplete_sessions_and_roundtrips(tmp_path):
    cache = BarCache(tmp_path)
    day = NOW.date() - timedelta(days=1)
    s = session(day)
    bars = [candle(raw_bar(s.open + timedelta(minutes=i)), NOW) for i in range(390)]
    assert complete_day(bars, day)
    cache.save("ALFA", day, bars[:-1])
    assert cache.load("ALFA", day) == []
    cache.save("ALFA", day, bars)
    assert cache.load("ALFA", day) == bars
    assert len(previous_sessions(NOW.date(), 10)) == 10


def test_push_accepts_confirmed_bars_only(provider):
    provider.api.callback("ALFA.US", Obj(is_confirmed=False, candlestick=raw_bar(NOW - timedelta(minutes=1))))
    assert not provider._bars
    provider.api.callback("ALFA.US", Obj(is_confirmed=True, candlestick=raw_bar(NOW - timedelta(minutes=1))))
    assert len(provider._bars["ALFA"]) == 1


def test_event_screen_and_calendar_invalidation(provider):
    provider.refresh_calendar(NOW)
    provider.refresh_event("ALFA", NOW)
    assert provider._events["ALFA"].status == "clear"
    provider.api.headlines = [Obj(title="Company cuts earnings guidance", published_at=str(int(NOW.timestamp())))]
    provider.refresh_event("ALFA", NOW)
    assert provider._events["ALFA"].status == "blocked"
    assert provider._news["ALFA"][0]["source"].endswith("(unverified headline)")
    provider.refresh_calendar(NOW + timedelta(minutes=10))
    assert not provider._events
    assert news_time(str(int(NOW.timestamp()))) == NOW
    with pytest.raises(DataUnavailable, match="stale"):
        provider.refresh_event("ALFA", NOW + timedelta(minutes=26))


def test_calendar_truncation_never_claims_clear(provider):
    provider.api.calendar = Obj(list=[Obj(count=1, infos=[])], next_date="")
    with pytest.raises(DataUnavailable, match="incomplete"):
        provider.refresh_calendar(NOW)
    assert provider._calendar_at is None


def test_calendar_reader_is_fixed_get_and_preserves_optional_count():
    calls = []

    def request(method, path):
        calls.append((method, path))
        return {"list": [{"date": "2026-10-20", "infos": [{"symbol": "ALFA.US", "star": 0}]}]}

    reader = CalendarReader(Obj(request=request), sdk)
    result = reader.finance_calendar(sdk.CalendarCategory.Report, "2026-10-20", "2026-10-20", "US", 100)
    assert result.list[0].count is None
    assert calls[0][0] == "GET"
    assert calls[0][1].startswith("/v1/quote/finance_calendar?")
    assert "offset=100" in calls[0][1]
    with pytest.raises(DataUnavailable):
        reader.finance_calendar(sdk.CalendarCategory.Report, "2026-10-20", "2026-10-20", "invalid")
    assert len(calls) == 1


def test_calendar_reads_all_pages_and_rejects_repeated_page(provider):
    calls = []

    def page(context, method, *args):
        calls.append(args[-1])
        rows = [Obj(symbol=f"S{i}.US", content="earnings") for i in range(100)] if args[-1] == 0 else []
        return Obj(list=[Obj(date="2026-10-20", count=100, infos=rows)], next_date="")

    provider.api.call = page
    assert len(provider._calendar_rows(sdk.CalendarCategory.Report, NOW.date())) == 100
    assert calls == [0, 100]
    first = page(None, None, 0)
    provider.api.call = lambda *args: first
    with pytest.raises(DataUnavailable, match="repeated"):
        provider._calendar_rows(sdk.CalendarCategory.Report, NOW.date())


def test_transport_rejects_non_read_methods_before_network():
    api = object.__new__(LongbridgeAPI)
    with pytest.raises(DataUnavailable, match="read-only"):
        api.call("quote", "delete_watchlist_group", 1)
    with pytest.raises(DataUnavailable, match="read-only"):
        api.call("account", "anything")


def test_credentials_and_endpoint_overrides(monkeypatch):
    for prefix in ["LONGBRIDGE", "LONGPORT"]:
        for suffix in ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN", "HTTP_URL", "QUOTE_WS_URL", "TRADE_WS_URL", "LOG_PATH"]:
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)
    with pytest.raises(DataUnavailable, match="credentials missing"):
        LongbridgeAPI()
    for suffix in ["APP_KEY", "APP_SECRET", "ACCESS_TOKEN"]:
        monkeypatch.setenv(f"LONGBRIDGE_{suffix}", "unit-test-placeholder")
    monkeypatch.setenv("LONGBRIDGE_HTTP_URL", "https://example.invalid")
    with pytest.raises(DataUnavailable, match="overrides"):
        LongbridgeAPI()


def test_local_console_and_outbox_are_automatic_and_deduplicated(tmp_path, capsys):
    store = Store(tmp_path / "book.db", Settings())
    store.event(NOW, "paper_fill", {"label": "LOCAL SIMULATED FILL"})
    assert emit_alerts(store, tmp_path / "alerts.jsonl") == 1
    assert "LOCAL PAPER" in capsys.readouterr().out
    assert emit_alerts(store, tmp_path / "alerts.jsonl") == 0
    assert capsys.readouterr().out == ""
    store.close()


def test_startup_entitlement_failure_disables_entries(provider, tmp_path):
    store = Store(tmp_path / "book.db", provider.cfg)
    Simulator(store, provider.cfg).controls(NOW, running=True, enabled=True)
    provider.api.fail = "option_quote"
    service = Service(store, provider.cfg, provider, clock=lambda: NOW)
    with pytest.raises(DataUnavailable):
        service.run()
    assert store.get("enabled") == "false"
    assert not store.rows("orders")
    store.close()


def test_sdk_boundary_has_no_trade_or_generic_http_contexts():
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1] / "src/agent_trading/intraday"
    attributes = {
        n.attr
        for p in root.glob("*.py")
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(n, ast.Attribute)
    }
    assert not attributes & {"TradeContext", "AsyncTradeContext", "submit_order", "replace_order", "cancel_order"}


def test_targeted_monitor_preserves_breadth_and_qualification():
    cfg = Settings()
    snap = demo_snapshot(NOW, cfg)
    whole = scan(snap, NOW, cfg)
    target = scan(snap, NOW, cfg, only={"ALFA"})
    assert target.coverage == whole.coverage
    assert target.signals == [s for s in whole.signals if s.symbol == "ALFA"]


def test_daily_resume_and_manual_disable_are_distinct(tmp_path):
    cfg = Settings()
    store = Store(tmp_path / "book.db", cfg)
    clock = [NOW.replace(hour=15, minute=30)]
    sim = Simulator(store, cfg)
    sim.controls(NOW, running=False, enabled=True)
    svc = Service(
        store, cfg, FileProvider(tmp_path / "absent.json"), reports=tmp_path / "reports", clock=lambda: clock[0]
    )
    svc.tick()
    assert store.get("enabled") == "false"
    tomorrow = next_session(NOW.date())
    assert store.get("auto_resume_day") == tomorrow.isoformat()
    sim.controls(clock[0], running=True)
    clock[0] = datetime.combine(tomorrow, NOW.replace(hour=8, minute=0).timetz())
    svc.tick()
    assert store.get("enabled") == "true"
    with store.transaction():
        store.set("auto_resume_day", next_session(tomorrow).isoformat())
    sim.controls(clock[0], enabled=False)
    assert store.get("auto_resume_day") == ""
    store.close()


def test_provider_failure_cancels_automatic_resume(tmp_path, provider):
    store = Store(tmp_path / "book.db", provider.cfg)
    store.set("auto_resume_day", next_session(NOW.date()).isoformat())
    Service(store, provider.cfg, provider).failure(NOW, RuntimeError("secret-provider-detail"))
    assert store.get("auto_resume_day") == ""
    assert "secret-provider-detail" not in str(store.rows("events"))
    store.close()
