from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agent_trading.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def synthetic_broker_identity(monkeypatch):
    """Tests never depend on the owner's environment or real account suffix."""
    monkeypatch.setenv("BROKER_ACCOUNT_LAST4", "1234")


@pytest.fixture(autouse=True)
def isolated_provider_budget(monkeypatch, tmp_path):
    """Mock requests must never consume the owner's persisted request budget."""
    monkeypatch.setenv("AGENT_PROVIDER_BUDGET_PATH", str(tmp_path / "provider-budget.sqlite3"))


def make_bars(
    n: int = 300,
    start: float = 100.0,
    drift: float = 0.001,
    vol: float = 0.01,
    seed: int = 0,
    end: str = "2026-10-09",
    volume: float = 2_000_000,
) -> pd.DataFrame:
    """Synthetic but internally consistent daily OHLCV bars."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=end, periods=n)
    rets = drift + vol * rng.standard_normal(n)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start], close[:-1]]) * (1 + 0.002 * rng.standard_normal(n))
    high = np.maximum(open_, close) * (1 + np.abs(0.005 * rng.standard_normal(n)))
    low = np.minimum(open_, close) * (1 - np.abs(0.005 * rng.standard_normal(n)))
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": np.full(n, volume)}, index=dates
    )
    df.index.name = "date"
    return df


def trend_rows(bars: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """Prepared engine rows for a simple trend rule (enter above rising SMAs,
    exit below the 50-day): exercises the engine independently of any strategy."""
    from agent_trading.backtest.desk_backtest import _frame
    from agent_trading.indicators import sma

    rows = {}
    for sym, df in bars.items():
        c = df["close"]
        s20, s50 = sma(c, 20), sma(c, 50)
        rows[sym] = _frame(df, (c > s20) & (s20 > s50), c < s50).to_dict("index")
    return rows


@pytest.fixture
def settings(tmp_path):
    s = load_settings(ROOT / "config" / "settings.yaml")
    return replace(s, base_dir=tmp_path)


@pytest.fixture
def bars():
    return {
        "UP": make_bars(seed=1, drift=0.002, start=50),
        "FLAT": make_bars(seed=2, drift=0.0, start=80),
        "DOWN": make_bars(seed=3, drift=-0.0015, start=120),
    }
