"""Cash interest, deflated Sharpe, cost sensitivity, and stress windows."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from agent_trading.backtest import run_backtest
from agent_trading.backtest.benchmarks import trend_timing
from agent_trading.backtest.stats import cost_sensitivity, deflated_sharpe, window_returns
from agent_trading.data.alphavantage import AlphaVantageError, parse_treasury_json
from agent_trading.data.rates import daily_cash_rate

from .conftest import make_bars


def test_parse_treasury_and_errors():
    s = parse_treasury_json({"data": [{"date": "2026-09-01", "value": "4.00"},
                                      {"date": "2026-08-01", "value": "."}]})
    assert list(s.index) == [pd.Timestamp("2026-09-01")] and s.iloc[0] == 4.0
    with pytest.raises(AlphaVantageError):
        parse_treasury_json({"Information": "rate limit"})


def test_daily_rate_uses_previous_month_only():
    monthly = pd.Series([1.0, 5.0], index=pd.to_datetime(["2026-01-01", "2026-02-01"]))
    days = pd.bdate_range("2026-01-15", "2026-03-10")
    r = daily_cash_rate(monthly, days)
    assert r.loc["2026-01-20"] == 0.0                         # January's average isn't known in January
    assert r.loc["2026-02-10"] == pytest.approx(0.01 / 252)   # February uses January's 1%
    assert r.loc["2026-03-02"] == pytest.approx(0.05 / 252)   # March uses February's 5%


def test_backtest_credits_interest_on_idle_cash(settings):
    flat_down = {"D": make_bars(n=200, drift=-0.003, vol=0.004)}  # no entries in a steady decline
    days = flat_down["D"].index
    rate = pd.Series(0.04 / 252, index=days)
    res = run_backtest(flat_down, settings, cash_rate=rate)
    assert res.metrics["trades"] == 0
    assert res.metrics["interest_earned"] > 0
    expected = settings.paper_starting_equity * (1 + 0.04 / 252) ** len(days)
    assert res.equity.iloc[-1] == pytest.approx(expected, rel=1e-9)


def test_trend_timing_cash_earns_interest():
    df = make_bars(n=300, drift=-0.002, vol=0.005)  # mostly below its 200-day average => in cash
    rate = pd.Series(0.05 / 252, index=df.index)
    with_rate = trend_timing(df, df.index[220], df.index[-1], 1000, 0.0, cash_rate=rate)
    without = trend_timing(df, df.index[220], df.index[-1], 1000, 0.0)
    assert with_rate.iloc[-1] > without.iloc[-1]


def test_deflated_sharpe_penalises_many_trials():
    rng = np.random.default_rng(1)
    rets = pd.Series(rng.normal(0.0006, 0.01, 1500))
    few = deflated_sharpe(rets, 1, [1.0])
    many = deflated_sharpe(rets, 200, list(rng.normal(0.5, 0.4, 200)))
    assert few["dsr"] > many["dsr"]
    assert 0 <= many["dsr"] <= 1
    assert deflated_sharpe(rets.iloc[:10], 5, [1, 2])["dsr"] is None


def test_deflated_sharpe_low_for_noise():
    rng = np.random.default_rng(2)
    noise = pd.Series(rng.normal(0.0, 0.01, 1000))
    assert deflated_sharpe(noise, 50, list(rng.normal(0.0, 0.5, 50)))["dsr"] < 0.5


def test_cost_sensitivity_reports_each_level(settings, bars):
    dates = bars["UP"].index
    rows, monotonic = cost_sensitivity(bars, settings, dates[0], dates[-1], [0, 25, 100])
    assert [r["cost_bps_per_side"] for r in rows] == [0, 25, 100]
    assert rows[0]["cagr"] >= rows[-1]["cagr"]
    assert isinstance(monotonic, bool)


def test_window_returns():
    eq = pd.Series([100.0, 110.0, 99.0, 120.0], index=pd.bdate_range("2026-01-05", periods=4))
    out = window_returns(eq, {"dip": ["2026-01-06", "2026-01-07"], "before": ["2025-12-01", "2025-12-31"]})
    assert out["dip"] == pytest.approx(99 / 100 - 1)   # measured from the prior close
    assert out["before"] is None                       # not covered by the curve
