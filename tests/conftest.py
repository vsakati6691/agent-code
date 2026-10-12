from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agent_trading.config import load_settings

ROOT = Path(__file__).resolve().parents[1]


def make_bars(n: int = 300, start: float = 100.0, drift: float = 0.001, vol: float = 0.01,
              seed: int = 0, end: str = "2026-10-09", volume: float = 2_000_000) -> pd.DataFrame:
    """Synthetic but internally consistent daily OHLCV bars."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=end, periods=n)
    rets = drift + vol * rng.standard_normal(n)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start], close[:-1]]) * (1 + 0.002 * rng.standard_normal(n))
    high = np.maximum(open_, close) * (1 + np.abs(0.005 * rng.standard_normal(n)))
    low = np.minimum(open_, close) * (1 - np.abs(0.005 * rng.standard_normal(n)))
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                       "volume": np.full(n, volume)}, index=dates)
    df.index.name = "date"
    return df


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
