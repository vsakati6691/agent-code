"""Isolation and behavioral checks for the audit's mechanical refactors."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from threading import Barrier

import pytest

from agent_trading.dashboard import site_layout
from agent_trading.dashboard.render_context import CURRENT_RENDER, RenderContext, rendering


def test_renderer_contexts_do_not_leak_across_threads_or_nested_failures():
    barrier = Barrier(2)

    def render(symbol):
        with rendering(RenderContext({symbol: symbol}, "?v=" + symbol)):
            barrier.wait(timeout=10)
            page = site_layout.page("test", "body", "index.html")
            with pytest.raises(RuntimeError), rendering(RenderContext({"NESTED": "nested"}, "?v=nested")):
                raise RuntimeError("nested build failed")
            assert CURRENT_RENDER.get().asset_version == "?v=" + symbol
        assert CURRENT_RENDER.get() is None
        return page

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(render, ["AAA", "BBB"]))
    assert "?v=AAA" in a and "?v=BBB" not in a and "BBB" not in a
    assert "?v=BBB" in b and "?v=AAA" not in b and "AAA" not in b


def test_shared_finra_schema_and_public_parser_math_imports():
    from agent_trading.dashboard import options, options_math, provider_parsers, providers, short_interest
    from agent_trading.dashboard.finra_schema import COLUMNS

    assert providers.EXTERNAL_PROVIDERS["short_interest"]["columns"] is COLUMNS is short_interest.COLUMNS
    assert providers.parse_cboe_quote is provider_parsers.parse_cboe_quote
    assert options.bs_call is options_math.bs_call


def test_comparison_builds_ownership_index_once(monkeypatch):
    from agent_trading.dashboard import compare, pipeline_external

    calls = []
    monkeypatch.setattr(pipeline_external, "subjects", lambda *args: calls.append(args) or {})
    entries = [
        {"ticker": name, "asset_type": "operating company", "key_metrics": {"revenue": 1}} for name in ("A", "B", "C")
    ]
    payload = compare.payload({"as_of": "2026-10-12", "bands": {}, "watchlist": {"entries": entries}}, {})
    assert len(payload["entries"]) == 3 and len(calls) == 1


def test_cache_is_read_once_per_symbol(settings, monkeypatch):
    from agent_trading.data import service
    from tests.test_data_service import FakeClient

    calls = []
    monkeypatch.setattr(service, "read_cache", lambda _, symbol: calls.append(symbol))
    statuses = service.MarketDataService(settings, FakeClient()).refresh(["A", "B"], date(2026, 10, 12))
    assert calls == ["A", "B"] and all(s.startswith("updated") for s in statuses.values())


def test_cli_default_date_uses_new_york(monkeypatch):
    from agent_trading import cli

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 12, 1, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(cli, "datetime", Clock)
    assert cli.build_parser().parse_args(["daily"]).as_of == date(2026, 10, 11)


def test_inferred_entry_date_skips_exchange_holiday(settings):
    from agent_trading.live import LiveLedger, Ticket, prepare
    from tests.test_live import snap

    ledger = LiveLedger(settings.resolve(settings.paths.journal_db))
    ledger.add_tickets(date(2026, 7, 2), [Ticket("SPY", "buy", 1, 100, 95, "C-gtaa", "test")])
    account = snap(cash=900, positions=[{"symbol": "SPY", "quantity": 1, "average_buy_price": 100}])
    result = prepare(settings, ledger, account, date(2026, 7, 6))
    assert result.positions["SPY"].entry_date == date(2026, 7, 6)
    assert any("actual fill date is unknown" in w for w in result.warnings)


@pytest.mark.parametrize("stop_day,gap", [("2026-02-02", False), ("2026-02-03", False), ("2026-02-03", True)])
def test_backtest_engines_agree_on_gap_intraday_and_entry_day_stops(settings, stop_day, gap):
    from dataclasses import replace

    import pandas as pd

    from agent_trading.backtest.engine import run_backtest
    from agent_trading.backtest.portfolio import run_allocation

    settings = replace(settings, costs=replace(settings.costs, commission_per_order=0.25))
    frame = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e6},
        index=pd.bdate_range("2026-01-02", "2026-02-06"),
    )
    stopped = pd.Timestamp(stop_day)
    if gap:
        frame.loc[stopped, ["open", "high", "low", "close"]] = [85.0, 86.0, 84.0, 85.0]
    else:
        frame.loc[stopped, "low"] = 90.0
    rows = frame.assign(atr=2.0, momentum=1.0, entry=False, exit=False)
    rows.loc[pd.Timestamp("2026-01-30"), "entry"] = True
    rows.loc[stopped, "exit"] = True  # a same-day close signal cannot override the intraday stop
    bars = {"SYN": frame}
    start = pd.Timestamp("2026-01-30")
    event = run_backtest(bars, settings, start=start, prepared={"SYN": rows.to_dict("index")})
    allocation = run_allocation(bars, settings, lambda day, history: {"SYN": 1.0}, start=start)
    assert len(event.trades) == len(allocation.trades) == 1
    assert event.trades == allocation.trades
    pd.testing.assert_series_equal(event.equity, allocation.equity)
    trade = event.trades[0]
    assert trade.entry_date == date(2026, 2, 2)
    assert trade.exit_date == stopped.date() and trade.exit_reason == "stop"
    raw_exit = 85.0 if gap else trade.stop
    assert trade.exit_price == pytest.approx(raw_exit * (1 - settings.costs.per_side))
    assert trade.commission == 0.5
    assert event.equity.iloc[-1] == pytest.approx(settings.paper_starting_equity + trade.pnl)
