"""The broker interface the execution service talks to.

Only `SimulatedBroker` implements it in this repository. A live adapter must
set `is_live = True`; the service refuses to pair a live broker with any mode
but `live`, and refuses a simulated broker in `live` mode.
"""

from __future__ import annotations

from typing import Protocol

from .models import AccountState, BrokerOrder, OrderRequest, Quote


class Broker(Protocol):
    name: str
    is_live: bool

    def account(self) -> AccountState: ...

    def quotes(self, symbols: list[str]) -> dict[str, Quote]: ...

    def submit(self, req: OrderRequest, ref_id: str) -> BrokerOrder:
        """Place a limit order. `ref_id` is the idempotency key: re-sending the
        same ref_id must never create a second order."""
        ...

    def order_by_ref(self, ref_id: str) -> BrokerOrder | None:
        """The order created with this ref_id, or None if the broker has none."""
        ...

    def cancel(self, broker_id: str) -> BrokerOrder: ...
