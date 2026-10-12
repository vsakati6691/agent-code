"""Out-of-sample and walk-forward evaluation.

Parameters are chosen on a training window only, then applied unchanged to the
following test window. Only test-window results count as evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import Settings, StrategyConfig
from .engine import BacktestResult, prepare, run_backtest, strategy_grid
from .metrics import compute_metrics


def _all_dates(bars: dict[str, pd.DataFrame]) -> list[pd.Timestamp]:
    return sorted(set().union(*(df.index for df in bars.values()))) if bars else []


def warmup_bars(cfg: StrategyConfig) -> int:
    return max(cfg.slow_ma, cfg.momentum_lookback + 1, cfg.atr_period, cfg.volume_lookback + 1)


def in_out_of_sample(
    bars: dict[str, pd.DataFrame], settings: Settings, oos_fraction: float | None = None
) -> tuple[BacktestResult, BacktestResult]:
    """Run the configured strategy on an in-sample and a later out-of-sample span."""
    frac = oos_fraction if oos_fraction is not None else settings.walkforward.oos_fraction
    dates = _all_dates(bars)[warmup_bars(settings.strategy):]
    if len(dates) < 40:
        raise ValueError(f"not enough history after warm-up ({len(dates)} bars)")
    split = int(len(dates) * (1 - frac))
    prepared = prepare(bars, settings.strategy)
    ins = run_backtest(bars, settings, dates[0], dates[split - 1], prepared=prepared)
    oos = run_backtest(bars, settings, dates[split], dates[-1], prepared=prepared)
    return ins, oos


@dataclass
class WalkForwardResult:
    folds: list[dict]
    equity: pd.Series
    metrics: dict


def walk_forward(bars: dict[str, pd.DataFrame], settings: Settings,
                 cash_rate: pd.Series | None = None) -> WalkForwardResult:
    wf = settings.walkforward
    candidates = strategy_grid(settings.strategy, wf.grid)
    warm = max(warmup_bars(c) for c in candidates)
    dates = _all_dates(bars)[warm:]
    if len(dates) < wf.train_bars + wf.test_bars:
        raise ValueError(
            f"walk-forward needs {wf.train_bars + wf.test_bars} bars after a {warm}-bar warm-up; "
            f"only {len(dates)} available"
        )

    prepared = {id(c): prepare(bars, c) for c in candidates}
    equity = settings.paper_starting_equity
    folds: list[dict] = []
    curves: list[pd.Series] = []
    pnls: list[float] = []
    costs = 0.0
    exposure_days = 0.0

    i = 0
    while i + wf.train_bars + wf.test_bars <= len(dates):
        train = dates[i : i + wf.train_bars]
        test = dates[i + wf.train_bars : i + wf.train_bars + wf.test_bars]
        scored = [
            (run_backtest(bars, settings, train[0], train[-1], c, prepared=prepared[id(c)],
                          cash_rate=cash_rate).metrics.get("sharpe", 0.0), c)
            for c in candidates
        ]
        best_score, best = max(scored, key=lambda x: x[0])  # ties keep the earliest
        result = run_backtest(bars, settings, test[0], test[-1], best, equity, prepared=prepared[id(best)],
                              cash_rate=cash_rate)
        folds.append(
            {
                "train": f"{train[0].date()}..{train[-1].date()}",
                "test": f"{test[0].date()}..{test[-1].date()}",
                "chosen": {"fast_ma": best.fast_ma, "slow_ma": best.slow_ma, "momentum_lookback": best.momentum_lookback},
                "train_sharpe": round(best_score, 3),
                "test_return": result.metrics.get("total_return", 0.0),
                "test_trades": result.metrics.get("trades", 0),
            }
        )
        curves.append(result.equity)
        pnls.extend(t.pnl for t in result.trades)
        costs += sum(t.costs for t in result.trades)
        exposure_days += result.metrics.get("exposure", 0.0) * len(result.equity)
        equity = float(result.equity.iloc[-1])
        i += wf.test_bars

    curve = pd.concat(curves).sort_index()
    metrics = compute_metrics(curve, pnls, settings.paper_starting_equity, exposure_days / len(curve), costs)
    return WalkForwardResult(folds, curve, metrics)
