"""Weekly run state and the completed-session clock; no private account data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ..market_calendar import is_trading_day, previous_trading_day
from . import spec
from .providers import Providers

log = logging.getLogger("agent_trading.dashboard.pipeline")


ET = ZoneInfo("America/New_York")


BENCHMARKS = sorted({b.benchmark for b in spec.BANDS})


MIN_SP500_COVERAGE = 0.90


class RunFailed(RuntimeError):
    """The run cannot produce a trustworthy snapshot (the last good dashboard stays up)."""


def as_of_for(now: datetime) -> date:
    """The latest completed NYSE session at `now`: today after 18:00 ET on a trading day, else the one before."""
    et = now.astimezone(ET)
    d = et.date()
    if is_trading_day(d) and et.hour >= 18:
        return d
    return previous_trading_day(d)


@dataclass
class Context:
    as_of: date
    providers: Providers
    started: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    notes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    excluded: dict[str, dict[str, str]] = field(default_factory=lambda: {b.key: {} for b in spec.BANDS})
    budget_hit: set[str] = field(default_factory=set)
    transient_failures: int = 0  # requests that still failed after their retries (429/5xx/timeouts)
    limit: int | None = None
    quotes: dict = field(default_factory=dict)
    histories: dict = field(default_factory=dict)
    facts: dict = field(default_factory=dict)
    decision_extras: dict = field(default_factory=dict)
    earnings_reason: str | None = None

    def exclude(self, band: str, ticker: str, reason: str) -> None:
        self.excluded[band].setdefault(ticker, reason)
