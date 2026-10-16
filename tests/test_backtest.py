"""Backtest engine mechanics: timing, costs, risk sizing, accounting."""

from dataclasses import replace

import pandas as pd
import pytest

from agent_trading.backtest import run_backtest

from .conftest import make_bars, trend_rows


def bt(bars, settings, **kw):
    return run_backtest(bars, settings, prepared=trend_rows(bars), **kw)


def test_backtest_runs_and_accounts_consistently(settings, bars):
    res = bt(bars, settings)
    assert res.metrics["trades"] > 0
    # equity change must equal the sum of closed-trade P&L (everything is closed at the end)
    assert res.equity.iloc[-1] - settings.paper_starting_equity == pytest.approx(
        sum(t.pnl for t in res.trades), abs=1e-6
    )
    assert all(t.exit_date >= t.entry_date for t in res.trades)


def test_entries_fill_at_next_open_with_slippage(settings, bars):
    res = bt(bars, settings)
    slip = settings.costs.per_side
    for t in res.trades:
        df = bars[t.symbol]
        idx = df.index.get_loc(pd.Timestamp(t.entry_date))
        assert idx > 0, "cannot enter on the first bar: signal needs a prior close"
        assert t.entry_price == pytest.approx(df["open"].iloc[idx] * (1 + slip))


def test_risk_limits_respected_in_backtest(settings, bars):
    for t in bt(bars, settings).trades:
        risk = t.quantity * (t.entry_price - t.stop)
        assert risk <= settings.paper_starting_equity * 2 * settings.risk.risk_per_trade_pct  # equity can grow


def test_costs_reduce_returns(settings, bars):
    free = replace(settings, costs=replace(settings.costs, slippage_bps=0, spread_bps=0, commission_per_order=0))
    costly = replace(settings, costs=replace(settings.costs, slippage_bps=50, commission_per_order=1))
    assert bt(bars, costly).equity.iloc[-1] < bt(bars, free).equity.iloc[-1]


def test_downtrend_only_produces_few_entries(settings):
    assert bt({"DOWN": make_bars(seed=3, drift=-0.004, vol=0.005)}, settings).metrics["trades"] <= 2


def test_no_short_positions_ever(settings, bars):
    assert all(t.quantity > 0 and t.stop < t.entry_price for t in bt(bars, settings).trades)


def test_backtest_credits_interest_on_idle_cash(settings):
    flat_down = {"D": make_bars(n=200, drift=-0.003, vol=0.004)}  # no entries in a steady decline
    days = flat_down["D"].index
    res = bt(flat_down, settings, cash_rate=pd.Series(0.04 / 252, index=days))
    assert res.metrics["trades"] == 0 and res.metrics["interest_earned"] > 0
    expected = settings.paper_starting_equity * (1 + 0.04 / 252) ** len(days)
    assert res.equity.iloc[-1] == pytest.approx(expected, rel=1e-9)
