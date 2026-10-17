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


CURRENT_RENDER: ContextVar[RenderContext | None] = ContextVar("dashboard_render", default=None)


@contextmanager
def rendering(context: RenderContext) -> Iterator[RenderContext]:
    token = CURRENT_RENDER.set(context)
    try:
        yield context
    finally:
        CURRENT_RENDER.reset(token)
