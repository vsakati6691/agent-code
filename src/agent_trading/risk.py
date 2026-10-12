"""Position sizing and hard trading guardrails.

Sizing: risk a fixed fraction of equity between entry and stop, capped by the
aggregate open-risk limit, a per-position notional cap, and available cash
(cash cap = no margin).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

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


def planned_risk(quantity: float, entry: float, stop: float) -> float:
    return quantity * max(0.0, entry - stop)


def size_position(
    equity: float,
    cash: float,
    entry_price: float,
    stop_price: float,
    open_risk: float,
    cfg: RiskConfig,
) -> SizeDecision:
    if entry_price <= 0 or equity <= 0:
        return SizeDecision(0.0, 0.0, 0.0, "invalid equity or price")
    if stop_price >= entry_price:
        raise RiskViolation("stop must be below entry (long-only)")
    if stop_price <= 0:
        raise RiskViolation("stop must be positive")

    per_share = entry_price - stop_price
    per_trade = equity * cfg.risk_per_trade_pct
    remaining = equity * cfg.max_open_risk_pct - open_risk
    if remaining <= 0:
        return SizeDecision(0.0, 0.0, 0.0, "aggregate open-risk limit reached")
    risk_label = "risk per trade" if per_trade <= remaining else "aggregate open-risk limit"
    budget = min(per_trade, remaining)

    candidates = {
        risk_label: budget / per_share,
        "max position size": equity * cfg.max_position_pct / entry_price,
        "available cash": max(0.0, cash) / entry_price,
    }
    limited_by = min(candidates, key=candidates.get)
    qty = _floor(candidates[limited_by], cfg.fractional_shares)
    if qty <= 0:
        return SizeDecision(0.0, 0.0, 0.0, f"size rounds to zero ({limited_by})")
    if qty * entry_price < cfg.min_order_notional:
        return SizeDecision(0.0, 0.0, 0.0, f"below ${cfg.min_order_notional:g} minimum order ({limited_by})")
    return SizeDecision(qty, planned_risk(qty, entry_price, stop_price), qty * entry_price, limited_by)


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
    if order.quantity <= 0 or order.price <= 0:
        raise RiskViolation("quantity and price must be positive")
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
    """Validate a manually entered paper trade against the risk limits. Returns its risk."""
    if stop >= entry:
        raise RiskViolation("stop must be below entry (long-only)")
    risk = planned_risk(quantity, entry, stop)
    tolerance = 0.01  # one cent of rounding slack
    if risk > equity * cfg.risk_per_trade_pct + tolerance:
        raise RiskViolation(
            f"trade risk ${risk:.2f} exceeds {cfg.risk_per_trade_pct:.2%} of equity (${equity * cfg.risk_per_trade_pct:.2f})"
        )
    if open_risk + risk > equity * cfg.max_open_risk_pct + tolerance:
        raise RiskViolation(
            f"open risk would be ${open_risk + risk:.2f}, above the {cfg.max_open_risk_pct:.2%} limit (${equity * cfg.max_open_risk_pct:.2f})"
        )
    if quantity * entry > equity * cfg.max_position_pct + tolerance:
        raise RiskViolation(f"position notional exceeds {cfg.max_position_pct:.0%} of equity")
    return risk
