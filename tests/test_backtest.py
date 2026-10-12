from dataclasses import replace

import pandas as pd
import pytest

from agent_trading.backtest import in_out_of_sample, run_backtest, walk_forward
from agent_trading.backtest.engine import strategy_grid

from .conftest import make_bars


def test_backtest_runs_and_accounts_consistently(settings, bars):
    res = run_backtest(bars, settings)
    m = res.metrics
    assert m["trades"] > 0
    # equity change must equal the sum of closed-trade P&L (everything is closed at the end)
    assert res.equity.iloc[-1] - settings.paper_starting_equity == pytest.approx(sum(t.pnl for t in res.trades), abs=1e-6)
    assert all(t.exit_date >= t.entry_date for t in res.trades)


def test_entries_fill_at_next_open_with_slippage(settings, bars):
    res = run_backtest(bars, settings)
    slip = settings.costs.slippage_bps / 10_000
    for t in res.trades:
        df = bars[t.symbol]
        idx = df.index.get_loc(pd.Timestamp(t.entry_date))
        assert idx > 0, "cannot enter on the first bar: signal needs a prior close"
        assert t.entry_price == pytest.approx(df["open"].iloc[idx] * (1 + slip))


def test_risk_limits_respected_in_backtest(settings, bars):
    res = run_backtest(bars, settings)
    for t in res.trades:
        risk = t.quantity * (t.entry_price - t.stop)
        assert risk <= settings.paper_starting_equity * 2 * settings.risk.risk_per_trade_pct  # equity can grow


def test_costs_reduce_returns(settings, bars):
    free = replace(settings, costs=replace(settings.costs, slippage_bps=0, commission_per_order=0))
    costly = replace(settings, costs=replace(settings.costs, slippage_bps=50, commission_per_order=1))
    assert run_backtest(bars, costly).equity.iloc[-1] < run_backtest(bars, free).equity.iloc[-1]


def test_downtrend_only_produces_few_entries(settings):
    res = run_backtest({"DOWN": make_bars(seed=3, drift=-0.004, vol=0.005)}, settings)
    assert res.metrics["trades"] <= 2


def test_no_short_positions_ever(settings, bars):
    res = run_backtest(bars, settings)
    assert all(t.quantity > 0 and t.stop < t.entry_price for t in res.trades)


def test_in_out_of_sample_split_is_ordered(settings, bars):
    ins, oos = in_out_of_sample(bars, settings)
    assert ins.equity.index.max() < oos.equity.index.min()


def test_walk_forward_folds_do_not_overlap(settings):
    long_bars = {"A": make_bars(n=700, seed=4, drift=0.001), "B": make_bars(n=700, seed=6, drift=0.0005)}
    res = walk_forward(long_bars, settings)
    assert len(res.folds) >= 2
    assert res.equity.index.is_monotonic_increasing and not res.equity.index.has_duplicates
    for f in res.folds:
        train_end = f["train"].split("..")[1]
        test_start = f["test"].split("..")[0]
        assert train_end < test_start


def test_walk_forward_needs_enough_history(settings, bars):
    with pytest.raises(ValueError, match="walk-forward needs"):
        walk_forward(bars, settings)


def test_strategy_grid_expands(settings):
    grid = strategy_grid(settings.strategy, {"fast_ma": [10, 20], "momentum_lookback": [21, 63]})
    assert len(grid) == 4
