"""Statistical uncertainty, multiple-testing correction, and robustness checks."""
from __future__ import annotations

import itertools
import math
from dataclasses import replace
from statistics import NormalDist

import numpy as np
import pandas as pd

from ..config import Settings, StrategyConfig
from .engine import prepare, run_backtest

TRADING_DAYS = 252
STRATEGY_FIELDS = {f for f in StrategyConfig.__dataclass_fields__}
EULER_GAMMA = 0.5772156649
_N = NormalDist()


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


def deflated_sharpe(returns: pd.Series, n_trials: int, trial_sharpes_annual: list[float]) -> dict:
    """Bailey & López de Prado (2014) Deflated Sharpe Ratio.

    Probability that the true Sharpe exceeds the best Sharpe expected from
    `n_trials` unskilled configurations, given the variance of the Sharpes
    actually observed across those trials. Accounts for skew and fat tails.
    """
    r = returns.dropna().to_numpy()
    t = len(r)
    if t < 30 or n_trials < 1 or r.std(ddof=1) == 0:
        return {"dsr": None, "n_trials": n_trials, "reason": "insufficient data"}
    sr = r.mean() / r.std(ddof=1)  # per-day Sharpe
    trial = np.asarray(trial_sharpes_annual, dtype=float) / math.sqrt(TRADING_DAYS)
    var_trials = float(trial.var(ddof=1)) if len(trial) > 1 else 0.0
    if n_trials > 1 and var_trials > 0:
        sr0 = math.sqrt(var_trials) * (
            (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
            + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e))
        )
    else:
        sr0 = 0.0
    centered = r - r.mean()
    m2 = (centered**2).mean()
    skew = float((centered**3).mean() / m2**1.5)
    kurt = float((centered**4).mean() / m2**2)  # Pearson (normal = 3)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if denom <= 0:
        return {"dsr": None, "n_trials": n_trials, "reason": "degenerate moments"}
    z = (sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom)
    return {
        "dsr": _N.cdf(z),
        "n_trials": n_trials,
        "sharpe_annual": sr * math.sqrt(TRADING_DAYS),
        "expected_max_sharpe_annual": sr0 * math.sqrt(TRADING_DAYS),
    }


def warnings_for(metrics: dict, boot: dict, min_trades: int, dsr: dict | None = None) -> list[str]:
    out = []
    if metrics.get("trades", 0) < min_trades:
        out.append(f"only {metrics.get('trades', 0)} trades (< {min_trades}): too few to draw conclusions")
    if boot.get("insufficient"):
        out.append(f"only {boot.get('n_days')} days: confidence intervals not computed")
    elif boot["sharpe_ci"][0] <= 0:
        out.append("95% interval for Sharpe includes zero: performance is not statistically distinguishable from zero")
    if dsr and dsr.get("dsr") is not None and dsr["dsr"] < 0.95:
        out.append(f"deflated Sharpe probability {dsr['dsr']:.0%} after {dsr['n_trials']} configurations tried "
                   "(< 95%): the result may be luck from testing many settings")
    return out


def sensitivity(
    bars: dict[str, pd.DataFrame], settings: Settings, grid: dict[str, list], start, end,
    cash_rate: pd.Series | None = None,
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
        m = run_backtest(bars, s, start, end, strat, prepared=prepared_cache[strat], cash_rate=cash_rate).metrics
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


def cost_sensitivity(
    bars: dict[str, pd.DataFrame], settings: Settings, start, end, levels_bps: list[float],
    cash_rate: pd.Series | None = None,
) -> tuple[list[dict], bool]:
    """Re-run at several all-in per-side costs. A real edge should degrade
    steadily as costs rise; non-monotonic results suggest noise."""
    prepared = prepare(bars, settings.strategy)
    rows = []
    for bps in levels_bps:
        s = replace(settings, costs=replace(settings.costs, slippage_bps=bps, spread_bps=0.0))
        m = run_backtest(bars, s, start, end, prepared=prepared, cash_rate=cash_rate).metrics
        rows.append({"cost_bps_per_side": bps, "cagr": m.get("cagr"), "sharpe": m.get("sharpe"),
                     "trades": m.get("trades")})
    cagrs = [r["cagr"] if r["cagr"] is not None else float("-inf") for r in rows]
    monotonic = all(a >= b - 1e-9 for a, b in zip(cagrs, cagrs[1:]))
    return rows, monotonic


def window_returns(equity: pd.Series, windows: dict[str, list[str]]) -> dict[str, float | None]:
    """Total return inside each named [start, end] window (None if not covered)."""
    out = {}
    for name, (start, end) in windows.items():
        w = equity.loc[start:end]
        if len(w) < 2 or equity.index[0] > pd.Timestamp(start):
            out[name] = None
            continue
        prior = equity.loc[:pd.Timestamp(start) - pd.Timedelta(days=1)]
        base = prior.iloc[-1] if not prior.empty else w.iloc[0]
        out[name] = float(w.iloc[-1] / base - 1)
    return out
