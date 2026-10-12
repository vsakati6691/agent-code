"""Statistical uncertainty: block-bootstrap intervals and small-sample warnings."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


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


