"""Plain data types shared by the execution service, the ledger and brokers.

Quantities are whole shares: fractional orders are market-only at Robinhood,
and this service sends limit orders only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# Ledger states. Terminal states never change again.
PENDING = "pending"            # persisted, not yet handed to the broker
SUBMITTED = "submitted"        # broker accepted the request; status not yet read back
UNKNOWN = "unknown"            # outcome ambiguous (timeout etc.): NEVER resubmit, only look it up
OPEN = "open"
PARTIALLY_FILLED = "partially_filled"
FILLED = "filled"
CANCELLED = "cancelled"
REJECTED = "rejected"
NOT_SENT = "not_sent"          # broker provably never received it (e.g. connection refused)
BLOCKED = "blocked"            # the validator refused it; never sent
DRY_RUN = "dry_run"            # dry-run mode: validated and recorded, never sent

UNRESOLVED = frozenset({PENDING, SUBMITTED, UNKNOWN, OPEN, PARTIALLY_FILLED})
TERMINAL = frozenset({FILLED, CANCELLED, REJECTED, NOT_SENT, BLOCKED, DRY_RUN})

# Robinhood order states -> ledger states.
BROKER_STATES = {
    "new": OPEN, "queued": OPEN, "confirmed": OPEN, "unconfirmed": OPEN,
    "partially_filled": PARTIALLY_FILLED, "filled": FILLED,
    "cancelled": CANCELLED, "canceled": CANCELLED, "rejected": REJECTED,
    "failed": REJECTED, "voided": CANCELLED,
}


class BrokerError(Exception):
    """Base class for broker failures."""


class BrokerTimeout(BrokerError):
    """No answer: the order may or may not have reached the broker."""


class BrokerNotSent(BrokerError):
    """The request provably never reached the broker (safe to treat as not placed)."""


class BrokerRejected(BrokerError):
    """The broker received the order and refused it."""


@dataclass(frozen=True)
class OrderRequest:
    decision_id: str        # one strategy decision -> at most one order, ever
    strategy: str
    symbol: str
    side: str               # "buy" | "sell"
    quantity: int           # whole shares
    limit_price: float
    time_in_force: str = "gfd"

    @property
    def notional(self) -> float:
        return self.quantity * self.limit_price


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    last: float
    as_of: datetime


@dataclass(frozen=True)
class BrokerOrder:
    ref_id: str
    broker_id: str
    symbol: str
    side: str
    quantity: float
    filled_quantity: float
    average_price: float | None
    state: str              # broker's own state string

    @property
    def ledger_state(self) -> str:
        return BROKER_STATES.get(self.state.lower(), UNKNOWN)


@dataclass(frozen=True)
class AccountState:
    account_last4: str
    fetched_at: datetime
    total_value: float
    cash: float
    settled_cash: float
    buying_power: float
    positions: dict[str, float] = field(default_factory=dict)
    open_orders: list[BrokerOrder] = field(default_factory=list)
