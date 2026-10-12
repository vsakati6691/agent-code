"""Durable order ledger (SQLite).

Every order attempt is written here BEFORE it is handed to a broker, with a
fresh ref_id that doubles as the broker idempotency key. A decision_id is
unique, so one strategy decision can never produce two orders, even across
restarts. Every state change is also appended to an event log that is never
rewritten.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import PENDING, TERMINAL, UNRESOLVED, BrokerOrder, OrderRequest

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    ref_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL,
    strategy TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    limit_price REAL NOT NULL,
    state TEXT NOT NULL,
    broker_id TEXT,
    filled_quantity REAL NOT NULL DEFAULT 0,
    average_price REAL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    ref_id TEXT,
    event TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


ET = ZoneInfo("America/New_York")


class DuplicateDecision(Exception):
    """This decision_id already has an order; it must not be sent again."""


class OrderLedger:
    def __init__(self, path: Path, clock=None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con, con:
            con.executescript(SCHEMA)

    def _now(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat(timespec="seconds")

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    # --- writes ----------------------------------------------------------
    def create(self, req: OrderRequest, mode: str, state: str = PENDING, reason: str = "") -> str:
        """Persist a new attempt and return its ref_id. Raises DuplicateDecision."""
        ref_id = str(uuid.uuid4())
        now = self._now()
        try:
            with closing(self._connect()) as con, con:
                con.execute(
                    "INSERT INTO orders (ref_id, decision_id, mode, strategy, symbol, side, quantity, limit_price,"
                    " state, reason, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ref_id, req.decision_id, mode, req.strategy, req.symbol, req.side, req.quantity,
                     req.limit_price, state, reason, now, now))
                self._event(con, ref_id, "created", {"state": state, "reason": reason, "decision_id": req.decision_id})
        except sqlite3.IntegrityError:
            raise DuplicateDecision(f"decision {req.decision_id} already has an order") from None
        return ref_id

    def update(self, ref_id: str, state: str, reason: str = "", broker: BrokerOrder | None = None) -> None:
        with closing(self._connect()) as con, con:
            row = con.execute("SELECT state FROM orders WHERE ref_id = ?", (ref_id,)).fetchone()
            if row is None:
                raise KeyError(ref_id)
            if row["state"] in TERMINAL and row["state"] != state:
                raise ValueError(f"order {ref_id} is already {row['state']}")
            fields = {"state": state, "updated_at": self._now()}
            if reason:
                fields["reason"] = reason
            if broker is not None:
                fields.update(broker_id=broker.broker_id, filled_quantity=broker.filled_quantity,
                              average_price=broker.average_price)
            sets = ", ".join(f"{k} = ?" for k in fields)
            con.execute(f"UPDATE orders SET {sets} WHERE ref_id = ?", (*fields.values(), ref_id))
            self._event(con, ref_id, "state", {"from": row["state"], "to": state, "reason": reason,
                                                "broker_state": broker.state if broker else None})

    def log(self, event: str, detail: dict, ref_id: str | None = None) -> None:
        with closing(self._connect()) as con, con:
            self._event(con, ref_id, event, detail)

    def set_meta(self, key: str, value) -> None:
        with closing(self._connect()) as con, con:
            con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(value)))

    def _event(self, con: sqlite3.Connection, ref_id: str | None, event: str, detail: dict) -> None:
        con.execute("INSERT INTO events (at, ref_id, event, detail) VALUES (?,?,?,?)",
                    (self._now(), ref_id, event, json.dumps(detail, default=str)))

    # --- reads -------------------------------------------------------------
    def get(self, ref_id: str) -> dict | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM orders WHERE ref_id = ?", (ref_id,)).fetchone()
        return dict(row) if row else None

    def by_decision(self, decision_id: str) -> dict | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM orders WHERE decision_id = ?", (decision_id,)).fetchone()
        return dict(row) if row else None

    def orders(self, states: set[str] | frozenset[str] | None = None) -> list[dict]:
        with closing(self._connect()) as con:
            rows = [dict(r) for r in con.execute("SELECT * FROM orders ORDER BY created_at, rowid")]
        return [r for r in rows if states is None or r["state"] in states]

    def unresolved(self) -> list[dict]:
        return self.orders(UNRESOLVED)

    def events(self, ref_id: str | None = None) -> list[dict]:
        with closing(self._connect()) as con:
            if ref_id is None:
                rows = con.execute("SELECT * FROM events ORDER BY id").fetchall()
            else:
                rows = con.execute("SELECT * FROM events WHERE ref_id = ? ORDER BY id", (ref_id,)).fetchall()
        return [dict(r) | {"detail": json.loads(r["detail"])} for r in rows]

    def get_meta(self, key: str, default=None):
        with closing(self._connect()) as con:
            row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def buys_on(self, day: date, mode: str) -> tuple[int, float]:
        """(entries, notional) of buys sent or being sent on New York calendar day `day`."""
        n, total = 0, 0.0
        for r in self.orders():
            if (r["mode"] == mode and r["side"] == "buy" and datetime.fromisoformat(r["created_at"]).astimezone(ET).date() == day
                    and r["state"] not in {"blocked", "rejected", "not_sent", "dry_run"}):
                n += 1
                total += r["quantity"] * r["limit_price"]
        return n, total
