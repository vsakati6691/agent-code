import numpy as np
import pandas as pd
import pytest

from agent_trading.config import StrategyConfig
from agent_trading.indicators import add_indicators, atr, macd, rate_of_change, rsi, sma, true_range, volume_ratio

from .conftest import make_bars


def test_sma_known_values():
    s = pd.Series([1.0, 2, 3, 4, 5])
    out = sma(s, 3)
    assert out.isna().sum() == 2
    assert list(out.iloc[2:]) == [2.0, 3.0, 4.0]


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 50, dtype=float))
    down = pd.Series(np.arange(50, 1, -1, dtype=float))
    assert rsi(up, 14).dropna().eq(100).all()
    assert rsi(down, 14).dropna().lt(1e-9).all()
    mixed = rsi(make_bars(seed=5)["close"], 14).dropna()
    assert mixed.between(0, 100).all()


def test_true_range_uses_previous_close():
    df = pd.DataFrame({"high": [10.0, 12], "low": [9.0, 11], "close": [9.5, 11.5]})
    assert list(true_range(df)) == [1.0, 2.5]  # gap up: high - prev close


def test_atr_positive_after_warmup():
    a = atr(make_bars(), 14)
    assert a.iloc[:13].isna().all()
    assert (a.dropna() > 0).all()


def test_indicators_are_causal():
    """Changing a future bar must not change any earlier indicator value."""
    df = make_bars(n=200)
    cfg = StrategyConfig()
    base = add_indicators(df, cfg)
    shocked = df.copy()
    shocked.iloc[150:, shocked.columns.get_loc("close")] *= 1.5
    shocked["high"] = shocked[["high", "close"]].max(axis=1)
    after = add_indicators(shocked, cfg)
    cols = ["sma_fast", "sma_slow", "momentum", "rsi", "atr", "macd", "vol_ratio"]
    pd.testing.assert_frame_equal(base.iloc[:150][cols], after.iloc[:150][cols])


def test_macd_and_roc_and_volume_ratio():
    close = make_bars()["close"]
    m = macd(close)
    assert {"macd", "macd_signal", "macd_hist"} <= set(m.columns)
    assert rate_of_change(pd.Series([100.0, 110.0]), 1).iloc[-1] == pytest.approx(0.10)
    v = volume_ratio(pd.Series([100.0] * 20 + [300.0]), 20)
    assert v.iloc[-1] == pytest.approx(3.0)
