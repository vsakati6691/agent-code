"""In-memory simulated broker for paper trading and failure drills.

It mimics the parts of a real broker the execution service depends on:
ref_id de-duplication, limit orders that fill only when marketable, partial
fills, rejections, cancellation and settlement of sale proceeds (T+1). Faults
can be queued to rehearse timeouts and outages. Nothing here can reach a real
broker.
"""
from __future__ import annotations

import itertools
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone

from .models import (AccountState, BrokerNotSent, BrokerOrder, BrokerRejected, BrokerTimeout,
                     OrderRequest, Quote)

# Faults, consumed one per submit() call:
#   "timeout_after_accept"  - the order is created, but the caller sees a timeout
#   "timeout_before_accept" - nothing is created, and the caller sees a timeout
#   "not_sent"              - connection refused before sending
#   "reject"                - the broker refuses the order
#   "partial"               - only half the quantity fills now
FAULTS = {"timeout_after_accept", "timeout_before_accept", "not_sent", "reject", "partial"}


class SimulatedBroker:
    name = "simulated"
    is_live = False

    def __init__(self, cash: float, positions: dict[str, float] | None = None,
                 quotes: dict[str, Quote] | None = None, account_last4: str = "SIM0",
                 slippage_bps: float = 0.0, clock=None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.cash = cash
        self.unsettled = 0.0
        self.positions = dict(positions or {})
        self._quotes = dict(quotes or {})
        self.account_last4 = account_last4
        self.slippage_bps = slippage_bps
        self.orders: dict[str, BrokerOrder] = {}      # by ref_id
        self._limit_prices: dict[str, float] = {}     # by ref_id
        self.faults: deque[str] = deque()
        self.submit_calls = 0
        self._ids = itertools.count(1)
        self.down = False                              # account()/quotes() raise while True

    # --- test controls -------------------------------------------------
    def inject(self, *faults: str) -> None:
        unknown = set(faults) - FAULTS
        if unknown:
            raise ValueError(f"unknown faults {sorted(unknown)}")
        self.faults.extend(faults)

    def set_quote(self, quote: Quote) -> None:
        self._quotes[quote.symbol] = quote

    def settle(self) -> None:
        """Next business day: sale proceeds become settled cash."""
        self.unsettled = 0.0

    def fill_open_orders(self) -> None:
        """Re-check resting limit orders against the current quotes."""
        for ref, o in list(self.orders.items()):
            if o.state in ("confirmed", "partially_filled"):
                self._try_fill(ref, o.quantity - o.filled_quantity)

    # --- Broker interface ---------------------------------------------
    def account(self) -> AccountState:
        if self.down:
            raise BrokerTimeout("simulated outage")
        value = self.cash + sum(q * self._quotes[s].last for s, q in self.positions.items() if s in self._quotes)
        open_orders = [o for o in self.orders.values() if o.state in ("confirmed", "partially_filled")]
        return AccountState(self.account_last4, self.clock(), value, self.cash,
                            max(0.0, self.cash - self.unsettled), self.cash,
                            {s: q for s, q in self.positions.items() if q > 0}, open_orders)

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        if self.down:
            raise BrokerTimeout("simulated outage")
        return {s: self._quotes[s] for s in symbols if s in self._quotes}

    def submit(self, req: OrderRequest, ref_id: str) -> BrokerOrder:
        self.submit_calls += 1
        if ref_id in self.orders:                     # idempotent: same ref_id, same order
            return self.orders[ref_id]
        fault = self.faults.popleft() if self.faults else None
        if fault == "not_sent":
            raise BrokerNotSent("connection refused")
        if fault == "timeout_before_accept":
            raise BrokerTimeout("no response")
        if fault == "reject":
            self.orders[ref_id] = self._new(req, ref_id, "rejected")
            raise BrokerRejected("rejected by simulated broker")
        if req.side == "buy" and req.notional > self.cash - self.unsettled + 1e-9:
            self.orders[ref_id] = self._new(req, ref_id, "rejected")
            raise BrokerRejected("insufficient settled cash")
        if req.side == "sell" and req.quantity > self.positions.get(req.symbol, 0) + 1e-9:
            self.orders[ref_id] = self._new(req, ref_id, "rejected")
            raise BrokerRejected("insufficient shares")
        self.orders[ref_id] = self._new(req, ref_id, "confirmed")
        self._try_fill(ref_id, req.quantity // 2 if fault == "partial" else req.quantity)
        if fault == "timeout_after_accept":
            raise BrokerTimeout("no response (order was accepted)")
        return self.orders[ref_id]

    def order_by_ref(self, ref_id: str) -> BrokerOrder | None:
        if self.down:
            raise BrokerTimeout("simulated outage")
        return self.orders.get(ref_id)

    def cancel(self, broker_id: str) -> BrokerOrder:
        for ref, o in self.orders.items():
            if o.broker_id == broker_id:
                if o.state in ("confirmed", "partially_filled"):
                    self.orders[ref] = replace(o, state="cancelled")
                return self.orders[ref]
        raise BrokerRejected(f"no order {broker_id}")

    # --- internals ------------------------------------------------------
    def _new(self, req: OrderRequest, ref_id: str, state: str) -> BrokerOrder:
        self._limit_prices[ref_id] = req.limit_price
        return BrokerOrder(ref_id, f"sim-{next(self._ids)}", req.symbol, req.side, req.quantity, 0.0, None, state)

    def _try_fill(self, ref_id: str, qty: float) -> None:
        o = self.orders[ref_id]
        q = self._quotes.get(o.symbol)
        if q is None or qty <= 0:
            return
        limit = self._limit_prices[ref_id]
        slip = self.slippage_bps / 10_000
        px = q.ask * (1 + slip) if o.side == "buy" else q.bid * (1 - slip)
        if ((o.side == "buy" and px > limit) or (o.side == "sell" and px < limit)):
            return
        filled = o.filled_quantity + qty
        avg = ((o.average_price or 0.0) * o.filled_quantity + px * qty) / filled
        if o.side == "buy":
            self.cash -= px * qty
            self.positions[o.symbol] = self.positions.get(o.symbol, 0) + qty
        else:
            self.cash += px * qty
            self.unsettled += px * qty
            self.positions[o.symbol] = self.positions.get(o.symbol, 0) - qty
        state = "filled" if filled >= o.quantity - 1e-9 else "partially_filled"
        self.orders[ref_id] = replace(o, filled_quantity=filled, average_price=avg, state=state)
