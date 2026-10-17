"""Process-safe daily Alpha Vantage budget, shared by local and dashboard clients.

Only day, request count and a stop flag are stored, never credentials or URLs.
Each actual attempt is reserved before the request, including failed attempts.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

DAILY_CEILING = 24  # the existing local cap; dashboard per-run cap also remains in force


class DailyBudgetExceeded(RuntimeError):
    pass


def default_budget_path() -> Path:
    return Path(os.environ.get("AGENT_PROVIDER_BUDGET_PATH", ".cache/provider-budget.sqlite3"))


def quota_notice(body: bytes) -> bool:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        return False
    return isinstance(payload, dict) and any(payload.get(k) for k in ("Information", "Note"))


class DailyRequestBudget:
    def __init__(self, path: Path | None = None, limit: int = DAILY_CEILING, day: date | None = None):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= DAILY_CEILING:
            raise ValueError("daily request budget may only tighten the existing cap")
        self.path = path if path is not None else default_budget_path()
        self.limit = limit
        self.day = day

    def _update(self, *, reserve: bool = False, block: bool = False) -> int:
        day = (self.day or datetime.now(UTC).date()).isoformat()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS av_budget (day TEXT PRIMARY KEY, used INTEGER NOT NULL, stopped INTEGER NOT NULL)"
                )
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("INSERT OR IGNORE INTO av_budget VALUES (?, 0, 0)", (day,))
                used, stopped = connection.execute(
                    "SELECT used, stopped FROM av_budget WHERE day = ?", (day,)
                ).fetchone()
                if block:
                    connection.execute("UPDATE av_budget SET stopped = 1 WHERE day = ?", (day,))
                    return 0
                if reserve:
                    if stopped or used >= self.limit:
                        raise DailyBudgetExceeded("Alpha Vantage daily budget spent or provider stopped for today")
                    connection.execute("UPDATE av_budget SET used = used + 1 WHERE day = ?", (day,))
                    used += 1
                return 0 if stopped else max(0, self.limit - used)
        except (OSError, sqlite3.Error):
            raise DailyBudgetExceeded("Alpha Vantage daily budget unavailable; no request made") from None

    def reserve(self) -> None:
        self._update(reserve=True)

    def stop(self) -> None:
        self._update(block=True)

    def remaining(self) -> int:
        return self._update()
