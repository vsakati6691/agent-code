from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from agent_trading.config import RiskConfig
from agent_trading.risk import (
    Holding,
    PortfolioState,
    RiskEngine,
    correlated_risk,
    planned_risk,
    size_position,
)

CFG = RiskConfig(stop_risk_buffer=0.2)


def corr_returns(n=80, seed=0):
    rng = np.random.default_rng(seed)
    base = rng.standard_normal(n) * 0.01
    return pd.DataFrame({
        "A": base,
        "A2": base + rng.standard_normal(n) * 0.001,   # ~0.99 correlated with A
        "B": rng.standard_normal(n) * 0.01,            # independent
    }, index=pd.bdate_range("2026-01-01", periods=n))


def test_stop_buffer_shrinks_size():
    plain = size_position(1000, 1000, 100, 95, 0, RiskConfig())
    buffered = size_position(1000, 1000, 100, 95, 0, CFG)
    assert plain.quantity == 1.0
    assert buffered.quantity == pytest.approx(0.8333, abs=1e-4)
    assert buffered.risk_amount <= 5.0 + 1e-9  # buffered loss still within $5


def test_planned_risk_includes_buffer():
    assert planned_risk(1, 100, 95, 0.2) == pytest.approx(6.0)


def test_correlated_positions_share_budget(settings):
    s = replace(settings, risk=CFG)
    engine = RiskEngine(s)
    held = PortfolioState(1000, 900, (Holding("A", 1.0, 100, 95),))  # $6.00 planned risk
    rets = corr_returns()
    twin = engine.evaluate_entry("A2", 100, 95, held, rets)
    other = engine.evaluate_entry("B", 100, 95, held, rets)
    assert other.approved and other.reason == "risk per trade"
    assert twin.approved and twin.reason == "correlated-risk limit"
    assert twin.risk_amount + 6.0 <= 10.0 + 1e-6
    assert twin.risk_amount < other.risk_amount


def test_unknown_correlation_is_treated_as_correlated():
    state = PortfolioState(1000, 900, (Holding("A", 1, 100, 95),))
    assert correlated_risk("NEW", state, corr_returns(), CFG) == pytest.approx(6.0)
    assert correlated_risk("B", state, corr_returns(n=10), CFG) == pytest.approx(6.0)  # too little history
    assert correlated_risk("B", state, corr_returns(), CFG) == 0.0


def test_engine_rejects_unverified_data_held_and_live_mode(settings):
    state = PortfolioState(1000, 1000, (Holding("A", 0.5, 100, 95),))
    engine = RiskEngine(settings)
    assert not engine.evaluate_entry("X", 100, 95, state, data_verified=False).approved
    assert engine.evaluate_entry("A", 100, 95, state).reason == "already held"
    assert not RiskEngine(replace(settings, mode="live")).evaluate_entry("X", 100, 95, state).approved
    assert not engine.evaluate_entry("X", 100, 101, state).approved  # stop above entry
    assert not engine.evaluate_entry("X", float("nan"), 95, state).approved


def test_engine_never_exceeds_aggregate_limit(settings):
    engine = RiskEngine(settings)
    rets = corr_returns()
    state = PortfolioState(1000, 1000)
    total = 0.0
    for sym in ["A", "B", "C", "D", "E"]:
        d = engine.evaluate_entry(sym, 100, 95, state, rets)
        if d.approved:
            total += d.risk_amount
            state = replace(state, cash=state.cash - d.notional,
                            holdings=state.holdings + (Holding(sym, d.quantity, 100, 95),))
    assert total <= 1000 * settings.risk.max_open_risk_pct + 1e-6


def test_cost_per_side(settings):
    c = settings.costs
    assert c.per_side == pytest.approx((c.slippage_bps + c.spread_bps / 2) / 10_000)
