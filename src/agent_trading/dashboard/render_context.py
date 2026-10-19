"""Per-build renderer state, isolated across concurrent and nested builds."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class RenderContext:
    symbols: dict[str, str] = field(default_factory=dict)
    asset_version: str = ""
    private: bool = False
    edition: str = "full"  # "customer": see site_customer


CURRENT_RENDER: ContextVar[RenderContext | None] = ContextVar("dashboard_render", default=None)


def customer() -> bool:
    """True while rendering the customer edition (no options, desk, watchlist or broker-derived data)."""
    context = CURRENT_RENDER.get()
    return context is not None and context.edition == "customer"


@contextmanager
def rendering(context: RenderContext) -> Iterator[RenderContext]:
    token = CURRENT_RENDER.set(context)
    try:
        yield context
    finally:
        CURRENT_RENDER.reset(token)
