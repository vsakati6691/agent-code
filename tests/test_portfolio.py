"""Allocation (target-weight) engine: timing, risk caps, no look-ahead, stops."""

from dataclasses import replace

import pandas as pd
import pytest

from agent_trading.backtest.portfolio import month_end_flags, run_allocation

from .conftest import make_bars


def equal(symbols):
    def fn(day, history):
        return {s: 1 / len(symbols) for s in symbols}

    return fn


@pytest.fixture
def three():
    return {s: make_bars(n=300, seed=i, drift=0.0005, vol=0.008, start=50 + 10 * i) for i, s in enumerate("ABC")}


def test_month_end_flags():
    dates = list(pd.to_datetime(["2026-01-29", "2026-01-30", "2026-02-02", "2026-02-27", "2026-03-02"]))
    assert month_end_flags(dates) == [False, True, False, True, True]


def test_first_fills_at_open_after_first_month_end(settings, three):
    res = run_allocation(three, settings, equal(list(three)))
    dates = list(three["A"].index)
    flags = month_end_flags(dates)
    # the first month-end with a full ATR(14) history behind it
    first_me = next(d for i, (d, f) in enumerate(zip(dates, flags, strict=False)) if f and i >= 14)
    first_fill = dates[dates.index(first_me) + 1]
    entries = sorted(t.entry_date for t in res.trades)
    assert entries[0] == first_fill.date()
    for t in res.trades:
        if t.entry_date == first_fill.date():
            assert t.entry_price == pytest.approx(
                three[t.symbol].loc[first_fill, "open"] * (1 + settings.costs.per_side)
            )


def test_weights_fn_never_sees_the_future(settings, three):
    seen = []

    def fn(day, history):
        for df in history.values():
            assert df.index.max() <= day
        seen.append(day)
        return {"A": 1.0}

    run_allocation(three, settings, fn)
    assert len(seen) >= 10


def test_existing_risk_caps_bind(settings, three):
    res = run_allocation(three, settings, equal(list(three)))
    buffer = settings.risk.stop_risk_buffer
    for t in res.trades:
        equity_before = res.equity.loc[: pd.Timestamp(t.entry_date) - pd.Timedelta(days=1)]
        eq = equity_before.iloc[-1] if not equity_before.empty else settings.paper_starting_equity
        assert t.quantity * (t.entry_price - t.stop) * (1 + buffer) <= 0.005 * eq + 0.01  # 0.5% of current equity
        assert t.quantity * t.entry_price <= 0.25 * eq + 0.01
    # with the per-trade cap, an equal-weight target of $333 per name is never reached
    assert max(t.quantity * t.entry_price for t in res.trades) < 1000 / 3


def test_relaxed_caps_track_buy_and_hold(settings, three):
    loose = replace(
        settings,
        risk=replace(
            settings.risk,
            risk_per_trade_pct=0.01,
            max_open_risk_pct=0.05,
            max_correlated_risk_pct=0.05,
            max_position_pct=1.0,
            atr_stop_multiple=50.0,
            stop_risk_buffer=0.0,
        ),
    )
    one = {"A": three["A"]}
    res = run_allocation(one, loose, equal(["A"]))
    assert res.metrics["trades"] >= 1
    assert res.trades[0].exit_reason == "end of test"  # wide stop never hit, never dropped


def test_dropped_symbol_sold_next_open(settings, three):
    dates = list(three["A"].index)
    month_ends = [d for d, f in zip(dates, month_end_flags(dates), strict=False) if f]
    cutoff = month_ends[3]  # hold B for a few months, then drop it

    def fn(day, history):
        return {"A": 0.3, "B": 0.3} if day < cutoff else {"A": 0.3}

    res = run_allocation(three, settings, fn)
    b = [t for t in res.trades if t.symbol == "B"]
    assert b and b[0].exit_reason in ("rebalance: dropped from target", "stop")
    if b[0].exit_reason.startswith("rebalance"):
        day = pd.Timestamp(b[0].exit_date)
        assert b[0].exit_price == pytest.approx(three["B"].loc[day, "open"] * (1 - settings.costs.per_side))


def test_stopped_position_waits_for_next_rebalance(settings):
    df = make_bars(n=120, seed=3, drift=0.0, vol=0.01, start=100)
    dates = list(df.index)
    flags = month_end_flags(dates)
    me = [d for d, f in zip(dates, flags, strict=False) if f]
    crash_day = dates[dates.index(me[1]) - 5]  # inside the second month of holding
    df.loc[crash_day:, ["open", "high", "low", "close"]] *= 0.9
    df.loc[crash_day, "open"] = df.loc[crash_day, "close"] / 0.9 * 0.97
    df.loc[crash_day, "high"] = max(df.loc[crash_day, "high"], df.loc[crash_day, "open"])
    df.loc[crash_day, "low"] = min(df.loc[crash_day, "low"], df.loc[crash_day, "open"]) * 0.85
    res = run_allocation({"A": df}, settings, equal(["A"]))
    stopped = [t for t in res.trades if t.exit_reason == "stop"]
    assert stopped
    s = stopped[0]
    reentries = [t for t in res.trades if t.entry_date > s.exit_date]
    if reentries:
        next_me = next(d for d in me if d.date() >= s.exit_date)
        assert reentries[0].entry_date > next_me.date()


def test_interest_and_accounting(settings, three):
    rate = pd.Series(0.03 / 252, index=three["A"].index)
    res = run_allocation(three, settings, equal(list(three)), cash_rate=rate)
    assert res.metrics["interest_earned"] > 0
    pnl = res.equity.iloc[-1] - settings.paper_starting_equity
    assert pnl == pytest.approx(res.metrics["trading_pnl"] + res.metrics["interest_earned"], abs=0.02)
