"""Target-weight (allocation) backtest with month-end rebalancing.

At each month-end close a weights function returns target weights, using only
data up to that close. Orders fill at the next open with the usual costs.

Risk policy (unchanged per-position limits, "option a"): every position gets an
ATR protective stop and is sized by the same RiskEngine as the swing strategy,
so its notional is min(target weight x equity, RiskEngine size). A stopped-out
position stays out until the next rebalance. Positions that remain in the
target are not resized at rebalance (avoids churn); positions dropped from the
target are sold at the next open.
"""
from __future__ import annotations

import math
from typing import Callable

import pandas as pd

from ..config import Settings
from ..indicators import atr
from ..risk import Holding, PortfolioState, RiskEngine, _floor
from .engine import BacktestResult, Trade
from .metrics import compute_metrics

WeightsFn = Callable[[pd.Timestamp, dict[str, pd.DataFrame]], dict[str, float]]


def month_end_flags(dates: list[pd.Timestamp]) -> list[bool]:
    """True on the last trading day of each month (from the trading calendar)."""
    return [i + 1 == len(dates) or dates[i + 1].month != d.month for i, d in enumerate(dates)]


def run_allocation(
    bars: dict[str, pd.DataFrame],
    settings: Settings,
    weights_fn: WeightsFn,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    initial_equity: float | None = None,
    cash_rate: pd.Series | None = None,
    name: str = "allocation",
) -> BacktestResult:
    risk_cfg = settings.risk
    engine = RiskEngine(settings)
    slip = settings.costs.per_side
    commission = settings.costs.commission_per_order
    initial = initial_equity if initial_equity is not None else settings.paper_starting_equity

    rows = {s: df[["open", "high", "low", "close"]].to_dict("index") for s, df in bars.items()}
    atrs = {s: atr(df, settings.strategy.atr_period).to_dict() for s, df in bars.items()}
    returns = pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index().pct_change()
    all_dates = sorted(set().union(*(df.index for df in bars.values()))) if bars else []
    is_month_end = dict(zip(all_dates, month_end_flags(all_dates)))
    dates = [d for d in all_dates if (start is None or d >= start) and (end is None or d <= end)]
    rate_by_day = cash_rate.to_dict() if cash_rate is not None else {}

    cash = initial
    positions: dict[str, Trade] = {}
    closed: list[Trade] = []
    last_close: dict[str, float] = {}
    curve: dict[pd.Timestamp, float] = {}
    target: dict[str, float] | None = None
    pending_sells: set[str] = set()
    days_exposed, interest = 0, 0.0
    prev_day: pd.Timestamp | None = None

    def close(sym: str, when: pd.Timestamp, raw: float, reason: str) -> None:
        nonlocal cash
        t = positions.pop(sym)
        fill = raw * (1 - slip)
        cash += t.quantity * fill - commission
        t.exit_date, t.exit_price, t.exit_reason = when.date(), fill, reason
        t.commission += commission
        t.slippage_cost += t.quantity * raw * slip
        closed.append(t)

    for d in dates:
        # 1. rebalance decided at the previous month-end close, filled at today's open
        if target is not None:
            pending_sells |= {s for s in positions if target.get(s, 0.0) <= 0}
        for sym in list(pending_sells):
            bar = rows[sym].get(d)
            if sym not in positions:
                pending_sells.discard(sym)
            elif bar is not None:
                close(sym, d, bar["open"], "rebalance: dropped from target")
                pending_sells.discard(sym)
        if target is not None:
            equity_est = cash + sum(t.quantity * last_close.get(s, t.entry_price) for s, t in positions.items())
            known = returns.loc[:prev_day].iloc[-risk_cfg.correlation_lookback:] if prev_day is not None else None
            for sym, w in sorted(target.items(), key=lambda kv: -kv[1]):
                bar = rows.get(sym, {}).get(d)
                if w <= 0 or sym in positions or bar is None or prev_day is None:
                    continue
                atr_prev = atrs[sym].get(prev_day)
                if atr_prev is None or not math.isfinite(atr_prev):
                    continue
                fill = bar["open"] * (1 + slip)
                stop = fill - risk_cfg.atr_stop_multiple * atr_prev
                if stop <= 0:
                    continue
                state = PortfolioState(equity_est, cash - commission,
                                       tuple(Holding(s, t.quantity, t.entry_price, t.stop) for s, t in positions.items()))
                decision = engine.evaluate_entry(sym, fill, stop, state, known)
                if not decision.approved:
                    continue
                qty = _floor(min(decision.quantity, w * equity_est / fill), risk_cfg.fractional_shares)
                if qty <= 0 or qty * fill < risk_cfg.min_order_notional:
                    continue
                cash -= qty * fill + commission
                positions[sym] = Trade(sym, d.date(), fill, qty, stop, commission=commission,
                                       slippage_cost=qty * bar["open"] * slip)
            target = None

        # 2. protective stops
        for sym in list(positions):
            bar = rows[sym].get(d)
            if bar is not None and bar["low"] <= positions[sym].stop:
                close(sym, d, min(bar["open"], positions[sym].stop), "stop")

        # 3. mark to market and credit interest on idle cash
        for sym, r in rows.items():
            bar = r.get(d)
            if bar is not None:
                last_close[sym] = bar["close"]
        if positions:
            days_exposed += 1
        if cash > 0 and rate_by_day:
            credit = cash * float(rate_by_day.get(d, 0.0))
            cash += credit
            interest += credit
        curve[d] = cash + sum(t.quantity * last_close[s] for s, t in positions.items())

        # 4. month-end: new target from data known at this close
        if is_month_end.get(d) and d != dates[-1]:
            history = {s: df.loc[:d] for s, df in bars.items()}
            target = {s: float(w) for s, w in weights_fn(d, history).items() if s in bars}
        prev_day = d

    if dates:
        final = dates[-1]
        for sym in list(positions):
            close(sym, final, last_close[sym], "end of test")
        curve[final] = cash

    equity = pd.Series(curve, dtype=float).sort_index()
    metrics = compute_metrics(
        equity, [t.pnl for t in closed], initial, days_exposed / len(dates) if dates else 0.0,
        sum(t.costs for t in closed),
        traded_notional=sum(t.quantity * (t.entry_price + t.exit_price) for t in closed),
        holding_days=[(t.exit_date - t.entry_date).days for t in closed],
    )
    metrics["interest_earned"] = round(interest, 2)
    metrics["trading_pnl"] = round(sum(t.pnl for t in closed), 2)
    return BacktestResult(equity, closed, metrics, params={"strategy": name})
