"""SQLite paper-trade journal. Long-only, paper-only, enforced by the schema."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path

import pandas as pd

from .risk import planned_risk

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    mode         TEXT NOT NULL CHECK (mode = 'paper'),
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL CHECK (side = 'long'),
    quantity     REAL NOT NULL CHECK (quantity > 0),
    entry_date   TEXT NOT NULL,
    entry_price  REAL NOT NULL CHECK (entry_price > 0),
    stop_price   REAL NOT NULL CHECK (stop_price > 0 AND stop_price < entry_price),
    thesis       TEXT,
    exit_date    TEXT,
    exit_price   REAL CHECK (exit_price IS NULL OR exit_price > 0),
    exit_reason  TEXT,
    fees         REAL NOT NULL DEFAULT 0,
    notes        TEXT
);
"""


class Journal:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
            if "strategy" not in cols:  # migrate journals created before strategies A/B
                conn.execute("ALTER TABLE trades ADD COLUMN strategy TEXT NOT NULL DEFAULT 'legacy'")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def open_trade(
        self,
        symbol: str,
        quantity: float,
        entry_price: float,
        stop_price: float,
        entry_date: date,
        thesis: str = "",
        fees: float = 0.0,
        strategy: str = "legacy",
    ) -> int:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO trades (mode, symbol, side, quantity, entry_date, entry_price, stop_price, thesis, fees, strategy)"
                " VALUES ('paper', ?, 'long', ?, ?, ?, ?, ?, ?, ?)",
                (symbol.upper(), quantity, entry_date.isoformat(), entry_price, stop_price, thesis, fees, strategy),
            )
            return int(cur.lastrowid)

    def close_trade(
        self, trade_id: int, exit_price: float, exit_date: date, reason: str = "", fees: float = 0.0
    ) -> None:
        with closing(self._connect()) as conn, conn:
            row = conn.execute("SELECT exit_date FROM trades WHERE id = ?", (trade_id,)).fetchone()
            if row is None:
                raise KeyError(f"trade {trade_id} not found")
            if row["exit_date"] is not None:
                raise ValueError(f"trade {trade_id} is already closed")
            conn.execute(
                "UPDATE trades SET exit_price = ?, exit_date = ?, exit_reason = ?, fees = fees + ? WHERE id = ?",
                (exit_price, exit_date.isoformat(), reason, fees, trade_id),
            )

    def trades(self) -> pd.DataFrame:
        with closing(self._connect()) as conn:
            df = pd.read_sql_query("SELECT * FROM trades ORDER BY id", conn)
        if df.empty:
            return df
        df["initial_risk"] = df["quantity"] * (df["entry_price"] - df["stop_price"])
        df["pnl"] = df["quantity"] * (df["exit_price"] - df["entry_price"]) - df["fees"]
        df["r_multiple"] = df["pnl"] / df["initial_risk"]
        return df

    def open_trades(self) -> pd.DataFrame:
        df = self.trades()
        return df[df["exit_date"].isna()] if not df.empty else df

    def closed_trades(self) -> pd.DataFrame:
        df = self.trades()
        return df[df["exit_date"].notna()] if not df.empty else df

    def open_risk(self, buffer: float = 0.0) -> float:
        df = self.open_trades()
        return float(sum(planned_risk(r.quantity, r.entry_price, r.stop_price, buffer) for r in df.itertuples()))

    def realized_pnl(self) -> float:
        df = self.closed_trades()
        return float(df["pnl"].sum()) if not df.empty else 0.0

    def cash(self, starting_equity: float) -> float:
        """Paper cash: starting equity + realized P&L - cost of open positions."""
        open_df = self.open_trades()
        committed = (
            float((open_df["quantity"] * open_df["entry_price"] + open_df["fees"]).sum()) if not open_df.empty else 0.0
        )
        return starting_equity + self.realized_pnl() - committed

    def summary(self, starting_equity: float, buffer: float = 0.0) -> dict:
        closed = self.closed_trades()
        n = len(closed)
        wins = closed[closed["pnl"] > 0] if n else closed
        losses = closed[closed["pnl"] <= 0] if n else closed
        gross_loss = abs(losses["pnl"].sum()) if n else 0.0
        realized = self.realized_pnl()
        return {
            "starting_equity": starting_equity,
            "realized_pnl": realized,
            "equity_realized": starting_equity + realized,
            "closed_trades": n,
            "open_trades": len(self.open_trades()),
            "win_rate": len(wins) / n if n else 0.0,
            "avg_r": float(closed["r_multiple"].mean()) if n else 0.0,
            "profit_factor": float(wins["pnl"].sum() / gross_loss) if n and gross_loss > 0 else None,
            "open_risk": self.open_risk(buffer),
        }
