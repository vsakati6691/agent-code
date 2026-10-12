"""GTAA (Strategy C), point-in-time universe history, and the scanner backtest."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from agent_trading.backtest.portfolio import run_allocation
from agent_trading.backtest.scanner_backtest import run_signal_backtest, summarize
from agent_trading.data.universe import members_on, normalize_name, parse_index_fund
from agent_trading.strategies import gtaa

from .conftest import make_bars


def test_gtaa_signals_and_weights():
    up = make_bars(n=400, drift=0.002, vol=0.005, start=100)
    down = make_bars(n=400, drift=-0.002, vol=0.005, start=100, seed=3)
    hist = {"UP": up, "DOWN": down}
    day = up.index[-1]
    sig = gtaa.signals(hist, day, ["UP", "DOWN", "NONE"], 10)
    assert sig["UP"]["above"] is True and sig["DOWN"]["above"] is False
    assert sig["NONE"]["above"] is None and sig["NONE"]["reason"] == "no data"
    assert gtaa.weights(hist, day, ["UP", "DOWN"], 10) == {"UP": 0.5}


def test_gtaa_needs_enough_months():
    short = make_bars(n=120)
    s = gtaa.signals({"X": short}, short.index[-1], ["X"], 10)["X"]
    assert s["above"] is None and "months" in s["reason"]


def test_gtaa_uses_only_past_data():
    df = make_bars(n=400, drift=0.001)
    day = df.index[300]
    base = gtaa.signals({"X": df}, day, ["X"], 10)["X"]
    shocked = df.copy()
    shocked.iloc[301:, :4] *= 0.3
    assert gtaa.signals({"X": shocked}, day, ["X"], 10)["X"] == base


def test_rebalance_day_detection():
    days = list(pd.bdate_range("2026-09-24", "2026-10-02"))
    assert gtaa.is_rebalance_day(days, date(2026, 9, 30))
    assert not gtaa.is_rebalance_day(days, date(2026, 9, 29))
    assert gtaa.is_rebalance_day([], date(2026, 10, 30))   # Friday before a new month
    assert not gtaa.is_rebalance_day([], date(2026, 10, 12))


def test_gtaa_allocation_without_stops_reaches_target_weights(settings):
    from dataclasses import replace

    up = {f"A{c}": make_bars(n=400, drift=0.001, vol=0.006, seed=i, start=50) for i, c in enumerate("BC")}
    relaxed = replace(settings, risk=replace(settings.risk, risk_per_trade_pct=1.0, max_open_risk_pct=1.0,
                                             max_correlated_risk_pct=1.0, max_position_pct=0.5 + 1e-9,
                                             stop_risk_buffer=0.0))
    res = run_allocation(up, relaxed, lambda d, h: gtaa.weights(h, d, list(up), 10), use_stops=False)
    assert res.trades and max(t.quantity * t.entry_price for t in res.trades) > 300  # ~1/2 of equity each
    assert all(t.exit_reason != "stop" for t in res.trades)


def test_name_resolution_for_filings_without_tickers(settings):
    from dataclasses import replace

    s = replace(settings, scanner=replace(settings.scanner, min_constituents=2))
    raw = {"fund": {"as_of": "2021-06-30"}, "holdings": [
        {"ticker": None, "name": "Accenture PLC", "weight": 1, "asset_class": "equity"},
        {"ticker": "BRK/B", "name": "Berkshire Hathaway Inc", "weight": 1, "asset_class": "equity"},
        {"ticker": "MSFT", "name": "Microsoft Corp", "weight": 1, "asset_class": "equity"}]}
    u = parse_index_fund(raw, s, name_map={normalize_name("ACCENTURE PLC-CL A"): "ACN"})
    assert set(u.tickers) == {"ACN", "BRK.B", "MSFT"}
    assert normalize_name("Accenture PLC") == normalize_name("ACCENTURE PLC CLASS A")


def test_members_on_uses_latest_snapshot_before_date():
    hist = {date(2020, 3, 31): ["A", "B"], date(2020, 6, 30): ["A", "C"]}
    assert members_on(hist, date(2020, 5, 1)) == ["A", "B"]
    assert members_on(hist, date(2020, 7, 1)) == ["A", "C"]
    assert members_on(hist, date(2020, 1, 1)) == []


def test_scanner_backtest_uses_point_in_time_members(settings):
    from dataclasses import replace

    s = replace(settings, scanner=replace(settings.scanner, min_avg_dollar_volume=1e6))
    end = "2026-09-30"
    bars = {f"S{c}": make_bars(n=420, seed=i, drift=0.0008 * (i % 3), vol=0.012, volume=4e6, start=40 + i, end=end)
            for i, c in enumerate("ABCDEFGHIJKL")}
    spy = make_bars(n=420, seed=99, drift=0.0004, vol=0.008, volume=8e7, start=300, end=end)
    early = list(bars)[:6]
    late = list(bars)[6:]
    switch = spy.index[350].date()
    hist = {spy.index[280].date(): early, switch: late}
    bt = run_signal_backtest(bars, spy, hist, s, top_n=3)
    f = bt.frame()
    assert len(f) >= 3
    for m in bt.months:
        allowed = set(early) if m.signal_date < switch else set(late)
        assert set(m.picks) <= allowed
    summary = summarize(f)
    assert {"top", "spy", "universe", "ic_mean"} <= set(summary)
