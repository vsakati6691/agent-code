from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from agent_trading import regime
from agent_trading.backtest import run_backtest
from agent_trading.backtest.benchmarks import buy_and_hold, equal_weight, trend_timing
from agent_trading.backtest.evaluation import evaluate, holdout_uses, make_splits, render_markdown
from agent_trading.backtest.metrics import compute_metrics
from agent_trading.backtest.stats import block_bootstrap, sensitivity, warnings_for
from agent_trading.config import RegimeConfig

from .conftest import make_bars


def test_metrics_sortino_turnover_and_drawdown_from_initial():
    eq = pd.Series([990.0, 1010.0, 980.0, 1020.0], index=pd.bdate_range("2026-01-01", periods=4))
    m = compute_metrics(eq, [10, -5], 1000.0, traded_notional=2000.0, holding_days=[3, 5])
    assert m["max_drawdown"] == pytest.approx(980 / 1010 - 1)
    assert m["sortino"] is not None and m["avg_holding_days"] == 4
    assert m["turnover"] > 0
    first_day_loss = compute_metrics(pd.Series([950.0], index=pd.bdate_range("2026-01-01", periods=1)), [], 1000.0)
    assert first_day_loss["max_drawdown"] == pytest.approx(-0.05)


def test_buy_and_hold_costs_and_values():
    df = make_bars(n=50)
    eq = buy_and_hold(df, df.index[0], df.index[-1], 1000, 0.001)
    assert eq.iloc[-1] == pytest.approx(1000 / (df["open"].iloc[0] * 1.001) * df["close"].iloc[-1])


def test_trend_timing_has_no_lookahead():
    df = make_bars(n=300, drift=0.001)
    base = trend_timing(df, df.index[250], df.index[-1], 1000, 0.0)
    shocked = df.copy()
    shocked.iloc[-1, :4] *= 0.5
    shocked.iloc[-1, shocked.columns.get_loc("high")] = shocked.iloc[-1][["open", "close"]].max()
    after = trend_timing(shocked, df.index[250], df.index[-1], 1000, 0.0)
    pd.testing.assert_series_equal(base.iloc[:-1], after.iloc[:-1])


def test_equal_weight_handles_misaligned_dates():
    a = make_bars(n=60, seed=1)
    b = make_bars(n=60, seed=2).drop(make_bars(n=60, seed=2).index[30])
    eq = equal_weight({"A": a, "B": b}, a.index[0], a.index[-1], 1000, 0.0)
    assert not eq.isna().any() and len(eq) == 60


def test_regime_labels():
    up = make_bars(n=300, drift=0.003, vol=0.005)
    down = make_bars(n=300, drift=-0.003, vol=0.005, start=500)
    cfg = RegimeConfig()
    assert regime.current(up, cfg)["trend"] == "bull"
    assert regime.current(down, cfg)["trend"] == "bear"
    wild = make_bars(n=300, drift=0, vol=0.04)
    assert regime.current(wild, cfg)["volatility"] == "high"
    labels = regime.classify(up, cfg)
    assert labels["trend"].iloc[:199].isna().all()  # not enough history for the 200-day MA


def test_performance_by_regime_partitions_days():
    df = make_bars(n=400, drift=0.0005, vol=0.015)
    regimes = regime.classify(df, RegimeConfig())
    eq = 1000 * df["close"] / df["close"].iloc[0]
    table = regime.performance_by_regime(eq, regimes)
    assert table["days"].sum() == len(eq) - 1  # every day is attributed
    assert "unclassified" in set(table["trend"])  # warm-up days are shown, not dropped


def test_bootstrap_intervals_contain_point_estimate():
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.normal(0.001, 0.01, 500))
    b = block_bootstrap(rets, n_samples=300, block=20)
    lo, hi = b["sharpe_ci"]
    assert lo < b["sharpe"] < hi
    assert block_bootstrap(rets.iloc[:10])["insufficient"]


def test_small_sample_warnings():
    w = warnings_for({"trades": 5}, {"insufficient": False, "sharpe_ci": (-0.5, 1.2)}, 30)
    assert any("too few" in x for x in w) and any("includes zero" in x for x in w)


def test_splits_are_chronological_and_disjoint():
    dates = list(pd.bdate_range("2023-01-02", periods=700))
    s = make_splits(dates, 100, 0.6, 0.2)
    assert s.train[1] < s.validation[0] <= s.validation[1] < s.holdout[0] <= s.holdout[1]
    assert s.train[0] == dates[100]
    with pytest.raises(ValueError):
        make_splits(dates[:150], 100, 0.6, 0.2)


def test_sensitivity_flags_and_ranks(settings):
    bars = {"A": make_bars(n=400, seed=4, drift=0.001), "B": make_bars(n=400, seed=6, drift=0.0005)}
    dates = bars["A"].index
    table, summary = sensitivity(bars, settings, {"fast_ma": [10, 20], "atr_stop_multiple": [2.0, 2.5]},
                                 dates[100], dates[-1])
    assert summary["combinations"] == 4 and len(table) == 4
    assert summary["default_rank"] is not None
    assert "fragile" in summary


@pytest.fixture
def long_bars():
    spy = make_bars(n=760, seed=11, drift=0.0006, vol=0.01, start=400, volume=5e7)
    return {"SPY": spy, **{f"S{i}": make_bars(n=760, seed=20 + i, drift=0.0008, vol=0.015, volume=5e6) for i in range(4)}}


def test_evaluate_does_not_touch_holdout_by_default(settings, long_bars):
    s = replace(settings, evaluation=replace(settings.evaluation, bootstrap_samples=100,
                                             sensitivity_grid={"fast_ma": [10, 20]}))
    rep = evaluate(long_bars, s)
    assert all("HOLDOUT" not in p.name for p in rep.periods)
    assert holdout_uses(s) == 0
    for p in rep.periods:
        assert pd.Timestamp(p.end) < rep.splits.holdout[0]
        assert "SPY buy & hold" in p.benchmarks
    md = render_markdown(rep)
    assert "survivorship bias" in md and "Walk-forward" in md


def test_evaluate_holdout_is_logged(settings, long_bars):
    s = replace(settings, evaluation=replace(settings.evaluation, bootstrap_samples=50, sensitivity_grid={}))
    rep1 = evaluate(long_bars, s, use_holdout=True)
    assert rep1.holdout_uses == 1 and rep1.periods[-1].name.startswith("HOLDOUT")
    rep2 = evaluate(long_bars, s, use_holdout=True)
    assert any("no longer untouched" in w for w in rep2.periods[-1].warnings)
