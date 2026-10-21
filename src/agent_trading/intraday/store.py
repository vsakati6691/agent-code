"""Durable local-only ledger. SQLite transactions serialize competing app processes."""

import hashlib
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from ..logging_setup import redact_details
from . import STRATEGY_VERSION
from .config import Settings

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders(
 id TEXT PRIMARY KEY, day TEXT NOT NULL, underlying TEXT NOT NULL, contract TEXT NOT NULL,
 side TEXT NOT NULL CHECK(side IN ('BUY','SELL')), quantity INTEGER NOT NULL CHECK(quantity>0),
 filled INTEGER NOT NULL DEFAULT 0, limit_cents INTEGER NOT NULL CHECK(limit_cents>0),
 status TEXT NOT NULL, created TEXT NOT NULL, reason TEXT NOT NULL, spec TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS positions(
 contract TEXT PRIMARY KEY, underlying TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=0),
 cost INTEGER NOT NULL, opened TEXT NOT NULL, spec TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fills(
 id INTEGER PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id), time TEXT NOT NULL,
 side TEXT NOT NULL, quantity INTEGER NOT NULL, price_cents INTEGER NOT NULL, fee INTEGER NOT NULL,
 pnl INTEGER NOT NULL, label TEXT NOT NULL DEFAULT 'LOCAL SIMULATED FILL');
CREATE TABLE IF NOT EXISTS consumed(order_id TEXT NOT NULL, quote_at TEXT NOT NULL, PRIMARY KEY(order_id,quote_at));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, time TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs(job TEXT PRIMARY KEY, time TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS equity(time TEXT PRIMARY KEY, cents INTEGER NOT NULL, complete INTEGER NOT NULL);
"""


class Store:
    def __init__(self, path: str | Path, cfg: Settings):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=15, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        fingerprint = hashlib.sha256((STRATEGY_VERSION + cfg.model_dump_json()).encode()).hexdigest()
        with self.transaction():
            previous = self.get("configuration")
            if previous and previous != fingerprint:
                raise ValueError(
                    "configuration changed: use a separate research database; do not reinterpret an existing ledger"
                )
            self.set("configuration", fingerprint)
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('enabled','false')")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('running','false')")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES ('killed','false')")

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
        )

    def rows(self, table: str) -> list[dict]:
        if table not in {"orders", "positions", "fills", "events", "runs", "equity"}:
            raise ValueError("unknown ledger table")
        return [dict(r) for r in self.db.execute(f"SELECT * FROM {table}")]  # table is allow-listed

    def event(self, now: datetime, kind: str, payload: dict) -> None:
        safe = json.dumps(redact_details(payload), allow_nan=False, default=str)
        self.db.execute("INSERT INTO events(time,kind,payload) VALUES (?,?,?)", (now.isoformat(), kind, safe))
        log.info("%s %s", kind, safe)

    def close(self):
        self.db.close()
