"""Performance statistics for an equity curve and a list of closed trades."""
from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

TRADING_DAYS = 252


def compute_metrics(equity: pd.Series, pnls: Iterable[float], initial: float, exposure: float = 0.0, costs: float = 0.0) -> dict:
    pnls = list(pnls)
    if equity.empty:
        return {"bars": 0, "trades": len(pnls)}
    final = float(equity.iloc[-1])
    total_return = final / initial - 1
    years = len(equity) / TRADING_DAYS
    cagr = (final / initial) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan")
    rets = equity.pct_change().dropna()
    std = rets.std()
    sharpe = math.sqrt(TRADING_DAYS) * rets.mean() / std if std and std > 0 else 0.0
    drawdown = equity / equity.cummax() - 1

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_loss = abs(sum(losses))
    return {
        "start": str(equity.index[0].date()),
        "end": str(equity.index[-1].date()),
        "bars": len(equity),
        "initial_equity": round(initial, 2),
        "final_equity": round(final, 2),
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": float(sharpe),
        "max_drawdown": float(drawdown.min()),
        "trades": len(pnls),
        "win_rate": len(wins) / len(pnls) if pnls else 0.0,
        "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "profit_factor": sum(wins) / gross_loss if gross_loss > 0 else None,
        "exposure": exposure,
        "total_costs": round(costs, 2),
    }
