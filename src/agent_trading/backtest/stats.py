"""Statistical uncertainty and parameter-sensitivity analysis."""
from __future__ import annotations

import itertools
import math
from dataclasses import replace

import numpy as np
import pandas as pd

from ..config import Settings, StrategyConfig
from .engine import prepare, run_backtest

TRADING_DAYS = 252
STRATEGY_FIELDS = {f for f in StrategyConfig.__dataclass_fields__}


def _sharpe(r: np.ndarray) -> float:
    s = r.std(ddof=1)
    return float(math.sqrt(TRADING_DAYS) * r.mean() / s) if s > 0 else 0.0


def _ann_return(r: np.ndarray) -> float:
    growth = float(np.prod(1 + r))
    return growth ** (TRADING_DAYS / len(r)) - 1 if growth > 0 else -1.0


def block_bootstrap(
    returns: pd.Series, n_samples: int = 1000, block: int = 20, seed: int = 0
) -> dict:
    """Circular block bootstrap 95% intervals for annualised return and Sharpe."""
    r = returns.dropna().to_numpy()
    n = len(r)
    if n < max(2 * block, 20):
        return {"n_days": n, "insufficient": True}
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n / block)
    sharpes, anns = np.empty(n_samples), np.empty(n_samples)
    for i in range(n_samples):
        starts = rng.integers(0, n, blocks)
        idx = ((starts[:, None] + np.arange(block)) % n).ravel()[:n]
        sample = r[idx]
        sharpes[i], anns[i] = _sharpe(sample), _ann_return(sample)
    return {
        "n_days": n,
        "insufficient": False,
        "sharpe": _sharpe(r),
        "sharpe_ci": (float(np.percentile(sharpes, 2.5)), float(np.percentile(sharpes, 97.5))),
        "ann_return_ci": (float(np.percentile(anns, 2.5)), float(np.percentile(anns, 97.5))),
        "prob_sharpe_positive": float((sharpes > 0).mean()),
    }


def warnings_for(metrics: dict, boot: dict, min_trades: int) -> list[str]:
    out = []
    if metrics.get("trades", 0) < min_trades:
        out.append(f"only {metrics.get('trades', 0)} trades (< {min_trades}): too few to draw conclusions")
    if boot.get("insufficient"):
        out.append(f"only {boot.get('n_days')} days: confidence intervals not computed")
    elif boot["sharpe_ci"][0] <= 0:
        out.append("95% interval for Sharpe includes zero: performance is not statistically distinguishable from zero")
    return out


def sensitivity(
    bars: dict[str, pd.DataFrame], settings: Settings, grid: dict[str, list], start, end
) -> tuple[pd.DataFrame, dict]:
    """Run every grid combination on [start, end]; summarise robustness.

    Grid keys may be StrategyConfig fields or 'atr_stop_multiple' (risk).
    """
    keys = list(grid)
    prepared_cache: dict[StrategyConfig, dict] = {}
    rows = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        strat = replace(settings.strategy, **{k: v for k, v in params.items() if k in STRATEGY_FIELDS})
        if strat.fast_ma >= strat.slow_ma:
            continue
        risk = replace(settings.risk, **{k: v for k, v in params.items() if k == "atr_stop_multiple"})
        s = replace(settings, strategy=strat, risk=risk)
        if strat not in prepared_cache:
            prepared_cache[strat] = prepare(bars, strat)
        m = run_backtest(bars, s, start, end, strat, prepared=prepared_cache[strat]).metrics
        rows.append({**params, "sharpe": m.get("sharpe", 0.0), "total_return": m.get("total_return", 0.0),
                     "max_drawdown": m.get("max_drawdown", 0.0), "trades": m.get("trades", 0)})
    table = pd.DataFrame(rows).sort_values("sharpe", ascending=False).reset_index(drop=True)

    base = {k: (getattr(settings.strategy, k) if k in STRATEGY_FIELDS else getattr(settings.risk, k)) for k in keys}
    match = table
    for k, v in base.items():
        match = match[match[k] == v]
    default_rank = int(match.index[0]) + 1 if not match.empty else None
    share_pos = float((table["sharpe"] > 0).mean()) if len(table) else 0.0
    spread = float(table["sharpe"].iloc[0] - table["sharpe"].median()) if len(table) else 0.0
    summary = {
        "combinations": len(table),
        "share_positive_sharpe": share_pos,
        "best_sharpe": float(table["sharpe"].iloc[0]) if len(table) else None,
        "median_sharpe": float(table["sharpe"].median()) if len(table) else None,
        "default_rank": default_rank,
        "fragile": share_pos < 0.6 or spread > 1.0,
    }
    return table, summary
