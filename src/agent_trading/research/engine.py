"""Target-weight backtest engine used by every tournament candidate.

Timing: a candidate's target weights are decided from data up to day t's
close (rows of the weights frame; NaN row = no new decision). They are traded at
day t+1's OPEN, with the per-side cost applied to the traded notional. Between
decisions, holdings drift with prices. Long-only, no leverage: sells are done
before buys, and buys never exceed cash.

Optional account constraints mirror the real account's hard limits:
- `max_weight`: a position at most this fraction of equity at entry ($100/$1,000);
- `max_gross`: total invested fraction ($800/$1,000);
- `max_daily_buy`: buys per day as a fraction of equity ($200/$1,000);
- `max_daily_entries`: new positions per day.

Targets that cannot be reached in one day carry over to the next days until a
new decision replaces them. Idle cash earns `cash_rate` (default 0).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Constraints:
    max_weight: float = 1.0
    max_gross: float = 1.0
    max_daily_buy: float | None = None
    max_daily_entries: int | None = None

    @property
    def label(self) -> str:
        if self == Constraints():
            return "unconstrained"
        return (
            f"max {self.max_weight:.0%}/position, {self.max_gross:.0%} gross, "
            f"{self.max_daily_buy:.0%}/day buys, {self.max_daily_entries} entries/day"
        )


ACCOUNT_CONSTRAINTS = Constraints(max_weight=0.10, max_gross=0.80, max_daily_buy=0.20, max_daily_entries=3)


@dataclass
class SimResult:
    returns: pd.Series  # daily strategy returns (close to close)
    exposure: pd.Series  # invested fraction at each close
    activity: pd.DataFrame  # per day: turnover (traded notional / equity), entries, exits, costs


def _apply_caps(target: np.ndarray, c: Constraints) -> np.ndarray:
    w = np.clip(np.nan_to_num(target, nan=0.0), 0.0, None)
    w = np.minimum(w, c.max_weight)
    gross = w.sum()
    cap = min(1.0, c.max_gross)
    if gross > cap:
        w = w * cap / gross
    return w


def simulate(
    weights: pd.DataFrame,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    cost_per_side: float,
    constraints: Constraints = Constraints(),
    cash_rate: float = 0.0,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> SimResult:
    """Run the weights through the market. `weights` columns must be a subset of the price columns."""
    cols = list(weights.columns)
    o = opens[cols].to_numpy(dtype=float)
    cl = closes[cols].ffill().to_numpy(dtype=float)
    w_arr = weights.reindex(closes.index).to_numpy(dtype=float)
    idx = closes.index
    lo = 0 if start is None else int(idx.searchsorted(start))
    hi = len(idx) if end is None else int(idx.searchsorted(end, side="right"))
    n = len(cols)
    shares = np.zeros(n)
    cash = 1.0
    pending: np.ndarray | None = None
    daily_cash = (1 + cash_rate) ** (1 / 252) - 1
    equity, exposure, activity = [], [], []
    prev_close = np.full(n, np.nan)
    for i in range(lo, hi):
        turnover = costs = 0.0
        entries = exits = 0
        if pending is not None:
            px = o[i]
            tradable = np.isfinite(px) & (px > 0)
            mark = np.where(tradable, px, np.nan_to_num(prev_close, nan=0.0))
            eq_open = cash + float(np.nansum(shares * mark))
            target_val = _apply_caps(np.where(tradable, pending, shares * mark / eq_open), constraints) * eq_open
            cur_val = shares * mark
            delta = np.where(tradable, target_val - cur_val, 0.0)
            # sells first (proceeds net of costs)
            sell = np.where(delta < -1e-9, -delta, 0.0)
            if sell.any():
                sold_shares = np.divide(sell, mark, out=np.zeros(n), where=mark > 0)
                closed = (shares > 0) & (shares - sold_shares <= 1e-12)
                exits += int(closed.sum())
                shares = np.where(closed, 0.0, shares - sold_shares)
                cash += float(sell.sum()) * (1 - cost_per_side)
                costs += float(sell.sum()) * cost_per_side
                turnover += float(sell.sum()) / eq_open
            buy = np.where(delta > 1e-9, delta, 0.0)
            done = True
            if buy.any():
                new = (shares <= 0) & (buy > 0)
                if constraints.max_daily_entries is not None and new.sum() > constraints.max_daily_entries:
                    order = np.argsort(-np.where(new, target_val, -np.inf))
                    allowed = set(order[: constraints.max_daily_entries].tolist())
                    blocked = np.array([new[j] and j not in allowed for j in range(n)])
                    buy = np.where(blocked, 0.0, buy)
                    done = False
                budget = cash / (1 + cost_per_side)
                if constraints.max_daily_buy is not None:
                    budget = min(budget, constraints.max_daily_buy * eq_open)
                total = float(buy.sum())
                if total > budget + 1e-12:
                    buy = buy * (budget / total)
                    done = done and total - budget < 1e-6
                total = float(buy.sum())
                if total > 0:
                    entries += int(((shares <= 0) & (buy > 0)).sum())
                    shares = shares + np.divide(buy, mark, out=np.zeros(n), where=mark > 0)
                    cash -= total * (1 + cost_per_side)
                    costs += total * cost_per_side
                    turnover += total / eq_open
            if done or constraints == Constraints():
                pending = None
        cash *= 1 + daily_cash
        c = np.where(np.isfinite(cl[i]), cl[i], np.nan_to_num(prev_close, nan=0.0))
        invested = float(np.nansum(shares * c))
        eq = cash + invested
        equity.append(eq)
        exposure.append(invested / eq if eq > 0 else 0.0)
        activity.append((turnover, entries, exits, costs / eq if eq > 0 else 0.0))
        prev_close = c
        decision = w_arr[i]
        if np.isfinite(decision).any() and i < hi - 1:
            pending = np.nan_to_num(decision, nan=0.0)
    eq_s = pd.Series(equity, index=idx[lo:hi], dtype=float)
    rets = eq_s.pct_change().fillna(eq_s.iloc[0] - 1.0 if len(eq_s) else 0.0)
    act = pd.DataFrame(activity, index=idx[lo:hi], columns=["turnover", "entries", "exits", "costs"])
    return SimResult(rets, pd.Series(exposure, index=idx[lo:hi]), act)


# ---------------------------------------------------------------- metrics

TD = 252


def max_drawdown(rets: pd.Series) -> float:
    eq = (1 + rets).cumprod()
    return float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0


def metrics(rets: pd.Series, cash_rets: pd.Series | None = None, sim: SimResult | None = None) -> dict:
    r = rets.dropna()
    n = len(r)
    if n < 2:
        return {"days": n}
    growth = float((1 + r).prod())
    years = n / TD
    cagr = growth ** (1 / years) - 1 if growth > 0 else -1.0
    vol = float(r.std(ddof=1) * math.sqrt(TD))
    excess = r - (cash_rets.reindex(r.index).fillna(0.0) if cash_rets is not None else 0.0)
    sd = float(excess.std(ddof=1))
    sharpe = float(excess.mean() / sd * math.sqrt(TD)) if sd > 0 else 0.0
    downside = excess[excess < 0]
    dd_sd = float(np.sqrt((downside**2).sum() / n)) if len(downside) else 0.0
    sortino = float(excess.mean() / dd_sd * math.sqrt(TD)) if dd_sd > 0 else float("nan")
    mdd = max_drawdown(r)
    monthly = (1 + r).groupby(r.index.to_period("M")).prod() - 1
    pos, neg = monthly[monthly > 0].sum(), -monthly[monthly < 0].sum()
    out = {
        "days": n,
        "years": round(years, 2),
        "cagr": cagr,
        "vol": vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": cagr / abs(mdd) if mdd < 0 else float("nan"),
        "win_rate_months": float((monthly > 0).mean()),
        "profit_factor_months": float(pos / neg) if neg > 0 else float("inf"),
        "worst_month": float(monthly.min()),
        "best_month": float(monthly.max()),
        "skew": float(r.skew()),
        "kurtosis": float(r.kurt() + 3),
    }
    if sim is not None:
        act = sim.activity.loc[r.index[0] : r.index[-1]]
        out.update(
            {
                "avg_exposure": float(sim.exposure.loc[r.index[0] : r.index[-1]].mean()),
                "turnover_per_year": float(act["turnover"].sum() / years),
                "trades": int(act["entries"].sum() + act["exits"].sum()),
                "cost_drag_per_year": float(act["costs"].sum() / years),
            }
        )
    return out
