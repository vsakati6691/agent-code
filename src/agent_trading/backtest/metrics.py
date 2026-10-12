"""Performance statistics for an equity curve and a list of closed trades."""
from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

TRADING_DAYS = 252


def _nan_to_none(x: float) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def compute_metrics(
    equity: pd.Series,
    pnls: Iterable[float],
    initial: float,
    exposure: float = 0.0,
    costs: float = 0.0,
    traded_notional: float = 0.0,
    holding_days: Iterable[int] | None = None,
) -> dict:
    pnls = list(pnls)
    holding = list(holding_days or [])
    if equity.empty:
        return {"bars": 0, "trades": len(pnls)}
    final = float(equity.iloc[-1])
    total_return = final / initial - 1
    years = len(equity) / TRADING_DAYS
    cagr = (final / initial) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan")

    # include the step from initial capital to the first mark
    rets = pd.concat([pd.Series([initial]), equity.reset_index(drop=True)]).pct_change().dropna()
    std = rets.std()
    sharpe = math.sqrt(TRADING_DAYS) * rets.mean() / std if std and std > 0 else 0.0
    downside = math.sqrt((rets.clip(upper=0) ** 2).mean())
    sortino = math.sqrt(TRADING_DAYS) * rets.mean() / downside if downside > 0 else None
    drawdown = equity / equity.cummax().clip(lower=initial) - 1

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_loss = abs(sum(losses))
    avg_equity = float(equity.mean())
    return {
        "start": str(equity.index[0].date()),
        "end": str(equity.index[-1].date()),
        "bars": len(equity),
        "initial_equity": round(initial, 2),
        "final_equity": round(final, 2),
        "total_return": total_return,
        "cagr": _nan_to_none(cagr),
        "volatility": float(std * math.sqrt(TRADING_DAYS)) if std == std else None,
        "sharpe": float(sharpe),
        "sortino": sortino,
        "max_drawdown": float(min(0.0, drawdown.min())),
        "trades": len(pnls),
        "win_rate": len(wins) / len(pnls) if pnls else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "profit_factor": sum(wins) / gross_loss if gross_loss > 0 else None,
        "exposure": exposure,
        "turnover": traded_notional / avg_equity / years if years > 0 and avg_equity > 0 else 0.0,
        "avg_holding_days": sum(holding) / len(holding) if holding else None,
        "total_costs": round(costs, 2),
    }
