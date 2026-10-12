"""Event loop over daily bars.

Timing model (no look-ahead):
  * signals are computed from day t's close;
  * exits and entries are filled at day t+1's open, adjusted for slippage;
  * stops are checked against each day's low; a gap through the stop fills at
    the open, otherwise at the stop, both less slippage.
Sizing uses the same risk module as paper trading.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import pandas as pd

from ..config import Settings, StrategyConfig
from ..indicators import add_indicators
from ..risk import planned_risk, size_position
from ..strategy import generate_signals
from .metrics import compute_metrics


@dataclass
class Trade:
    symbol: str
    entry_date: date
    entry_price: float
    quantity: float
    stop: float
    exit_date: date | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    commission: float = 0.0
    slippage_cost: float = 0.0  # informational: already embedded in the fill prices

    @property
    def costs(self) -> float:
        return self.commission + self.slippage_cost

    @property
    def pnl(self) -> float:
        if self.exit_price is None:
            return 0.0
        return self.quantity * (self.exit_price - self.entry_price) - self.commission


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[Trade]
    metrics: dict
    params: dict = field(default_factory=dict)

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([{**t.__dict__, "costs": t.costs, "pnl": t.pnl} for t in self.trades])


def prepare(bars: dict[str, pd.DataFrame], cfg: StrategyConfig) -> dict[str, dict]:
    """Indicators + signals per symbol, as {symbol: {timestamp: row-dict}}."""
    prepared = {}
    for sym, df in bars.items():
        ind = add_indicators(df, cfg)
        frame = ind.join(generate_signals(ind, cfg))
        prepared[sym] = frame.to_dict("index")
    return prepared


def run_backtest(
    bars: dict[str, pd.DataFrame],
    settings: Settings,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    strategy: StrategyConfig | None = None,
    initial_equity: float | None = None,
    prepared: dict[str, dict] | None = None,
) -> BacktestResult:
    cfg = strategy or settings.strategy
    rows = prepared if prepared is not None else prepare(bars, cfg)
    risk_cfg = settings.risk
    slip = settings.costs.slippage_bps / 10_000
    commission = settings.costs.commission_per_order
    initial = initial_equity if initial_equity is not None else settings.paper_starting_equity

    dates = sorted(set().union(*(r.keys() for r in rows.values()))) if rows else []
    if start is not None:
        dates = [d for d in dates if d >= start]
    if end is not None:
        dates = [d for d in dates if d <= end]

    cash = initial
    positions: dict[str, Trade] = {}
    closed: list[Trade] = []
    last_close: dict[str, float] = {}
    pending_entries: list[tuple[str, float, float]] = []
    pending_exits: set[str] = set()
    curve: dict[pd.Timestamp, float] = {}
    days_exposed = 0

    def close(sym: str, when: pd.Timestamp, raw_price: float, reason: str) -> None:
        nonlocal cash
        trade = positions.pop(sym)
        fill = raw_price * (1 - slip)
        cash += trade.quantity * fill - commission
        trade.exit_date, trade.exit_price, trade.exit_reason = when.date(), fill, reason
        trade.commission += commission
        trade.slippage_cost += trade.quantity * raw_price * slip
        closed.append(trade)

    for d in dates:
        # 1. exits signalled yesterday, filled at today's open
        for sym in list(pending_exits):
            bar = rows[sym].get(d)
            if bar is not None and sym in positions:
                close(sym, d, bar["open"], "exit signal")
                pending_exits.discard(sym)

        # 2. entries signalled yesterday, strongest momentum first
        equity_est = cash + sum(t.quantity * last_close.get(s, t.entry_price) for s, t in positions.items())
        for sym, atr_value, _ in sorted(pending_entries, key=lambda x: -x[2]):
            bar = rows[sym].get(d)
            if bar is None or sym in positions:
                continue
            fill = bar["open"] * (1 + slip)
            stop = fill - risk_cfg.atr_stop_multiple * atr_value
            if stop <= 0:
                continue
            open_risk = sum(planned_risk(t.quantity, t.entry_price, t.stop) for t in positions.values())
            decision = size_position(equity_est, cash - commission, fill, stop, open_risk, risk_cfg)
            if decision.quantity <= 0:
                continue
            cash -= decision.quantity * fill + commission
            positions[sym] = Trade(
                sym, d.date(), fill, decision.quantity, stop,
                commission=commission,
                slippage_cost=decision.quantity * bar["open"] * slip,
            )
        pending_entries = []

        # 3. protective stops
        for sym in list(positions):
            bar = rows[sym].get(d)
            if bar is not None and bar["low"] <= positions[sym].stop:
                close(sym, d, min(bar["open"], positions[sym].stop), "stop")

        # 4. mark to market
        for sym, r in rows.items():
            bar = r.get(d)
            if bar is not None:
                last_close[sym] = bar["close"]
        if positions:
            days_exposed += 1
        curve[d] = cash + sum(t.quantity * last_close[s] for s, t in positions.items())

        # 5. signals from today's close, acted on tomorrow
        for sym, r in rows.items():
            bar = r.get(d)
            if bar is None:
                continue
            if sym in positions:
                if bar["exit"]:
                    pending_exits.add(sym)
            elif bar["entry"] and pd.notna(bar["atr"]):
                pending_entries.append((sym, float(bar["atr"]), float(bar["momentum"])))

    # Close anything still open at the final close so results are comparable.
    if dates:
        final = dates[-1]
        for sym in list(positions):
            close(sym, final, last_close[sym], "end of test")
        curve[final] = cash

    equity = pd.Series(curve, dtype=float).sort_index()
    exposure = days_exposed / len(dates) if dates else 0.0
    metrics = compute_metrics(
        equity, [t.pnl for t in closed], initial, exposure, sum(t.costs for t in closed)
    )
    return BacktestResult(equity, closed, metrics, params=cfg.__dict__.copy())


def strategy_grid(base: StrategyConfig, grid: dict[str, list]) -> list[StrategyConfig]:
    configs = [base]
    for key, values in grid.items():
        configs = [replace(c, **{key: v}) for c in configs for v in values]
    return [c for c in configs if c.fast_ma < c.slow_ma]
