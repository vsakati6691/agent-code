"""Tournament engine and validation: timing, costs, constraints, no look-ahead, registry."""

import json

import numpy as np
import pandas as pd
import pytest

from agent_trading.research import tournament as T
from agent_trading.research.candidates import Market, candidates
from agent_trading.research.engine import Constraints, metrics, simulate


def flat(n=10, cols=("A",), price=100.0):
    idx = pd.bdate_range("2020-01-01", periods=n)
    df = pd.DataFrame(price, index=idx, columns=list(cols))
    return df.copy(), df.copy()


def weights_on(index, day, **w):
    out = pd.DataFrame(np.nan, index=index, columns=list(w))
    out.loc[index[day]] = list(w.values())
    return out


def test_decision_at_close_fills_next_open():
    opens, closes = flat()
    opens.iloc[3:] = 110.0
    closes.iloc[3:] = 110.0
    early = simulate(weights_on(closes.index, 1, A=1.0), opens, closes, 0.0)  # bought day 2 at 100
    late = simulate(weights_on(closes.index, 2, A=1.0), opens, closes, 0.0)  # bought day 3 at 110
    assert (1 + early.returns).prod() == pytest.approx(1.10)
    assert (1 + late.returns).prod() == pytest.approx(1.0)


def test_costs_charged_per_side_and_no_leverage():
    opens, closes = flat(cols=("A", "B"))
    sim = simulate(weights_on(closes.index, 0, A=1.5, B=1.5), opens, closes, 0.01)
    assert sim.exposure.max() <= 1.0 + 1e-12  # capped at 100% invested
    assert (1 + sim.returns).prod() == pytest.approx(1 / 1.01)  # one buy at 1% cost
    w = weights_on(closes.index, 0, A=1.0, B=0.0)
    w.loc[closes.index[4]] = [0.0, 0.0]
    sim = simulate(w, opens, closes, 0.01)
    assert (1 + sim.returns).prod() == pytest.approx(0.99 / 1.01)  # round trip
    assert sim.activity["entries"].sum() == 1 and sim.activity["exits"].sum() == 1


def test_account_constraints_cap_position_gross_and_daily_buys():
    cols = ("A", "B", "C", "D", "E", "F", "G", "H", "I")
    opens, closes = flat(n=12, cols=cols)
    c = Constraints(max_weight=0.10, max_gross=0.80, max_daily_buy=0.20, max_daily_entries=3)
    sim = simulate(weights_on(closes.index, 0, **{k: 1 / 9 for k in cols}), opens, closes, 0.0, c)
    assert sim.exposure.max() <= 0.80 + 1e-9
    assert (sim.activity["entries"] <= 3).all()
    assert sim.exposure.iloc[1] == pytest.approx(0.20)  # first day: $200 of $1,000
    assert sim.exposure.iloc[-1] == pytest.approx(0.80)  # reached over several days


@pytest.mark.parametrize("cand", [c for c in candidates()], ids=lambda c: c.name)
def test_candidates_have_no_look_ahead(cand):
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2006-01-02", "2010-12-31")
    syms = sorted({*cand.assets, "SPY", "BIL"})
    closes = pd.DataFrame(
        {s: 100 * np.exp(np.cumsum(0.0003 + 0.01 * rng.standard_normal(len(idx)))) for s in syms}, index=idx
    )
    mkt = Market(closes.copy(), closes.copy(), set(syms))
    cut = idx[int(len(idx) * 0.7)]
    base = cand.weights(mkt).loc[:cut]
    shocked = closes.copy()
    shocked.loc[shocked.index > cut] *= 3.0
    after = cand.weights(Market(shocked, shocked, set(syms))).loc[:cut]
    pd.testing.assert_frame_equal(base, after)


def test_deflated_sharpe_penalises_more_trials():
    rng = np.random.default_rng(1)
    r = pd.Series(0.0004 + 0.01 * rng.standard_normal(2500))
    few = T.deflated_sharpe(r, [0.01, 0.02, 0.015])
    many = T.deflated_sharpe(r, list(np.linspace(-0.04, 0.04, 200)))
    assert 0 <= many < few <= 1


def test_metrics_basic():
    r = pd.Series([0.01, -0.005] * 300, index=pd.bdate_range("2020-01-01", periods=600))
    m = metrics(r)
    assert m["cagr"] > 0 and m["max_drawdown"] == pytest.approx(-0.005) and m["win_rate_months"] == 1.0


def test_registry_is_append_only(tmp_path):
    path = tmp_path / "registry.jsonl"
    T.append_registry(path, [{"strategy": "X", "test_evaluated": True}])
    first = path.read_text(encoding="utf-8")
    T.append_registry(path, [{"strategy": "X", "test_evaluated": True}, {"strategy": "Y", "test_evaluated": False}])
    text = path.read_text(encoding="utf-8")
    assert text.startswith(first) and len(text.splitlines()) == 3
    assert T.prior_test_evaluations(path) == {"X": 2}
    assert all(json.loads(line) for line in text.splitlines())
