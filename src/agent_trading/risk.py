"""Position sizing and hard trading guardrails.

Every entry (backtest, paper broker, report, manual journal) goes through the
same rules here:

* risk a fixed fraction of equity between entry and stop, planned with a
  buffer for stops that fill worse than their price (gaps);
* cap aggregate open risk, and the combined risk of highly correlated positions;
* cap position notional, and never exceed available cash (no margin);
* long-only, paper-only, stocks/ETFs only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .config import RiskConfig, Settings

QTY_DECIMALS = 4


class RiskViolation(ValueError):
    """An order or trade that policy forbids."""


@dataclass(frozen=True)
class SizeDecision:
    quantity: float
    risk_amount: float
    notional: float
    limited_by: str


def _floor(qty: float, fractional: bool) -> float:
    if fractional:
        factor = 10**QTY_DECIMALS
        return math.floor(qty * factor) / factor
    return float(math.floor(qty))


def planned_risk(quantity: float, entry: float, stop: float, buffer: float = 0.0) -> float:
    """Dollar loss if the stop fills `buffer` x stop-distance worse than its price."""
    return quantity * max(0.0, entry - stop) * (1 + buffer)


def size_position(
    equity: float,
    cash: float,
    entry_price: float,
    stop_price: float,
    open_risk: float,
    cfg: RiskConfig,
    correlated_remaining: float | None = None,
) -> SizeDecision:
    if entry_price <= 0 or equity <= 0:
        return SizeDecision(0.0, 0.0, 0.0, "invalid equity or price")
    if stop_price >= entry_price:
        raise RiskViolation("stop must be below entry (long-only)")
    if stop_price <= 0:
        raise RiskViolation("stop must be positive")

    per_share = (entry_price - stop_price) * (1 + cfg.stop_risk_buffer)
    remaining = equity * cfg.max_open_risk_pct - open_risk
    if remaining <= 0:
        return SizeDecision(0.0, 0.0, 0.0, "aggregate open-risk limit reached")
    risk_caps = {"risk per trade": equity * cfg.risk_per_trade_pct, "aggregate open-risk limit": remaining}
    if correlated_remaining is not None:
        if correlated_remaining <= 0:
            return SizeDecision(0.0, 0.0, 0.0, "correlated-risk limit reached")
        risk_caps["correlated-risk limit"] = correlated_remaining
    risk_label = min(risk_caps, key=risk_caps.get)

    candidates = {
        risk_label: risk_caps[risk_label] / per_share,
        "max position size": equity * cfg.max_position_pct / entry_price,
        "available cash": max(0.0, cash) / entry_price,
    }
    limited_by = min(candidates, key=candidates.get)
    qty = _floor(candidates[limited_by], cfg.fractional_shares)
    if qty <= 0:
        return SizeDecision(0.0, 0.0, 0.0, f"size rounds to zero ({limited_by})")
    if qty * entry_price < cfg.min_order_notional:
        return SizeDecision(0.0, 0.0, 0.0, f"below ${cfg.min_order_notional:g} minimum order ({limited_by})")
    risk = planned_risk(qty, entry_price, stop_price, cfg.stop_risk_buffer)
    return SizeDecision(qty, risk, qty * entry_price, limited_by)


# ---------------------------------------------------------------- engine


@dataclass(frozen=True)
class Holding:
    symbol: str
    quantity: float
    entry_price: float
    stop_price: float


@dataclass(frozen=True)
class PortfolioState:
    equity: float
    cash: float
    holdings: tuple[Holding, ...] = field(default_factory=tuple)

    def open_risk(self, buffer: float) -> float:
        return sum(planned_risk(h.quantity, h.entry_price, h.stop_price, buffer) for h in self.holdings)

    def holds(self, symbol: str) -> bool:
        return any(h.symbol == symbol for h in self.holdings)


@dataclass(frozen=True)
class EntryDecision:
    symbol: str
    approved: bool
    quantity: float
    risk_amount: float
    notional: float
    reason: str


def correlated_risk(symbol: str, state: PortfolioState, returns: pd.DataFrame | None, cfg: RiskConfig) -> float:
    """Planned risk of holdings correlated with `symbol`.

    Fail-safe: when correlation cannot be measured (missing or short history),
    the holding is treated as correlated.
    """
    total = 0.0
    min_obs = cfg.correlation_lookback // 2
    x = None
    cols: dict[str, int] = {}
    if returns is not None and symbol in returns.columns:
        window = returns.iloc[-cfg.correlation_lookback :]
        arr = window.to_numpy(dtype=float)
        cols = {c: i for i, c in enumerate(window.columns)}
        x = arr[:, cols[symbol]]
    for h in state.holdings:
        corr = 1.0
        if x is not None and h.symbol in cols:
            y = arr[:, cols[h.symbol]]
            mask = ~(np.isnan(x) | np.isnan(y))
            if mask.sum() >= min_obs:
                xs, ys = x[mask] - x[mask].mean(), y[mask] - y[mask].mean()
                denom = np.sqrt((xs * xs).sum() * (ys * ys).sum())
                if denom > 0:
                    corr = float((xs * ys).sum() / denom)
        if corr >= cfg.max_correlation:
            total += planned_risk(h.quantity, h.entry_price, h.stop_price, cfg.stop_risk_buffer)
    return total


class RiskEngine:
    """Single place where entries are approved and sized."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cfg = settings.risk

    def evaluate_entry(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
        state: PortfolioState,
        returns: pd.DataFrame | None = None,
        data_verified: bool = True,
    ) -> EntryDecision:
        def reject(reason: str) -> EntryDecision:
            return EntryDecision(symbol, False, 0.0, 0.0, 0.0, reason)

        if self.settings.mode != "paper":
            return reject("only paper trading is enabled")
        if not data_verified:
            return reject("market data not verified (stale or incomplete)")
        if state.holds(symbol):
            return reject("already held")
        for group in self.cfg.exclusive_groups:
            if symbol in group:
                clash = [h.symbol for h in state.holdings if h.symbol in group and h.symbol != symbol]
                if clash:
                    return reject(f"cannot hold {symbol} together with {', '.join(clash)}")
        if not (math.isfinite(entry_price) and math.isfinite(stop_price)):
            return reject("non-finite price")
        cfg = self.cfg
        if symbol in cfg.symbol_risk_pct:  # instrument-specific (tighter) per-trade risk
            cfg = replace(cfg, risk_per_trade_pct=cfg.symbol_risk_pct[symbol])
        try:
            corr_remaining = None
            if state.holdings:
                corr_remaining = state.equity * cfg.max_correlated_risk_pct - correlated_risk(
                    symbol, state, returns, cfg
                )
            d = size_position(
                state.equity,
                state.cash,
                entry_price,
                stop_price,
                state.open_risk(cfg.stop_risk_buffer),
                cfg,
                corr_remaining,
            )
        except RiskViolation as exc:
            return reject(str(exc))
        if d.quantity <= 0:
            return reject(d.limited_by)
        return EntryDecision(symbol, True, d.quantity, d.risk_amount, d.notional, d.limited_by)


# ---------------------------------------------------------------- circuit breakers


@dataclass(frozen=True)
class TradingStatus:
    new_entries_allowed: bool
    reason: str
    day_pnl: float
    drawdown: float
    peak_equity: float


def trading_status(
    equity_history: pd.Series, current_equity: float, cfg: RiskConfig, today: pd.Timestamp | None = None
) -> TradingStatus:
    """Daily-loss and max-drawdown circuit breakers.

    `equity_history`: end-of-day paper equity by date (earlier days only, or
    including today). The day's P&L is measured from the last close before today.
    Fail-safe: a non-finite equity blocks new entries.
    """
    if not math.isfinite(current_equity):
        return TradingStatus(False, "paper equity could not be computed", 0.0, 0.0, 0.0)
    hist = equity_history.dropna()
    prior = hist[hist.index < today] if today is not None else hist
    base = float(prior.iloc[-1]) if not prior.empty else current_equity
    peak = max([current_equity, *hist.tolist()]) if not hist.empty else current_equity
    day_pnl = current_equity - base
    drawdown = peak - current_equity
    if drawdown >= peak * cfg.max_drawdown_pct - 1e-9:
        return TradingStatus(
            False,
            f"SHUTDOWN: drawdown ${drawdown:.2f} from peak ${peak:.2f} "
            f"reached the {cfg.max_drawdown_pct:.0%} limit; review before resuming",
            day_pnl,
            drawdown,
            peak,
        )
    if -day_pnl >= base * cfg.daily_loss_limit_pct - 1e-9:
        return TradingStatus(
            False,
            f"daily loss ${-day_pnl:.2f} reached the {cfg.daily_loss_limit_pct:.0%} limit; no new entries today",
            day_pnl,
            drawdown,
            peak,
        )
    return TradingStatus(True, "ok", day_pnl, drawdown, peak)


# ---------------------------------------------------------------- order checks


@dataclass(frozen=True)
class ProposedOrder:
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    price: float
    asset_type: str = "equity"
    held_quantity: float = 0.0


def check_order(order: ProposedOrder, settings: Settings, cash: float) -> None:
    """Raise RiskViolation if an order breaks policy. Applies to paper orders too."""
    if settings.mode != "paper":
        raise RiskViolation("only paper trading is enabled")
    if order.asset_type not in ("equity", "etf"):
        raise RiskViolation(f"asset type {order.asset_type!r} is not allowed (stocks/ETFs only)")
    values = (order.quantity, order.price, order.held_quantity, cash)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise RiskViolation("order values and cash must be finite numbers")
    if order.quantity <= 0 or order.price <= 0 or order.held_quantity < 0 or cash < 0:
        raise RiskViolation("quantity and price must be positive; cash and holdings must be non-negative")
    if not math.isfinite(order.quantity * order.price):
        raise RiskViolation("order notional must be finite")
    if order.side == "buy":
        if order.quantity * order.price > cash + 1e-9:
            raise RiskViolation("order exceeds available cash (margin is not allowed)")
    elif order.side == "sell":
        if order.quantity > order.held_quantity + 1e-9:
            raise RiskViolation("sell exceeds held quantity (short selling is not allowed)")
    else:
        raise RiskViolation(f"unknown side {order.side!r}")


def check_new_trade_risk(
    equity: float, open_risk: float, quantity: float, entry: float, stop: float, cfg: RiskConfig
) -> float:
    """Validate a manually entered paper trade against the risk limits. Returns its planned risk."""
    values = (equity, open_risk, quantity, entry, stop)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise RiskViolation("trade risk inputs must be finite numbers")
    if min(equity, quantity, entry, stop) <= 0 or open_risk < 0:
        raise RiskViolation("trade risk inputs must be positive; open risk must be non-negative")
    if stop >= entry:
        raise RiskViolation("stop must be below entry (long-only)")
    risk = planned_risk(quantity, entry, stop, cfg.stop_risk_buffer)
    tolerance = 0.01  # one cent of rounding slack
    if risk > equity * cfg.risk_per_trade_pct + tolerance:
        raise RiskViolation(
            f"trade risk ${risk:.2f} (incl. {cfg.stop_risk_buffer:.0%} stop buffer) exceeds "
            f"{cfg.risk_per_trade_pct:.2%} of equity (${equity * cfg.risk_per_trade_pct:.2f})"
        )
    if open_risk + risk > equity * cfg.max_open_risk_pct + tolerance:
        raise RiskViolation(
            f"open risk would be ${open_risk + risk:.2f}, above the {cfg.max_open_risk_pct:.2%} limit (${equity * cfg.max_open_risk_pct:.2f})"
        )
    if quantity * entry > equity * cfg.max_position_pct + tolerance:
        raise RiskViolation(f"position notional exceeds {cfg.max_position_pct:.0%} of equity")
    return risk
