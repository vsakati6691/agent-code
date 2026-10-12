"""Manual live tickets for the real Agent-trading account.

This module never talks to a broker. From the latest verified read-only account
snapshot and the strategies' intents it writes ORDER TICKETS (symbol, side,
quantity, limit, stop) that the account owner places in the Robinhood app.

  * only strategies listed in `live.strategies` produce tickets;
  * sizing uses the real account, capped at `live.capital`, through the same
    RiskEngine and loss limits as the paper broker;
  * no tickets without a verified, fresh snapshot of the configured account;
  * stops come from the buy ticket that opened a position. A position with no
    ticket (opened by hand) has an unknown stop and counts in full as open risk.

Tickets are stored in the local journal database (`live_tickets`), so a later
run knows each live position's stop and entry date.
"""
from __future__ import annotations

import math
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .account import AccountSnapshot, verify_snapshot
from .config import Settings
from .paper import Intent, returns_frame
from .risk import Holding, PortfolioState, RiskEngine, TradingStatus, trading_status
from .strategies.desk import Position

LIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS live_tickets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_date  TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity      REAL NOT NULL CHECK (quantity > 0),
    limit_price   REAL NOT NULL CHECK (limit_price > 0),
    stop_price    REAL,
    strategy      TEXT NOT NULL,
    reason        TEXT,
    planned_risk  REAL NOT NULL DEFAULT 0,
    CHECK (side = 'sell' OR (stop_price IS NOT NULL AND stop_price > 0 AND stop_price < limit_price))
);
CREATE TABLE IF NOT EXISTS live_equity (date TEXT PRIMARY KEY, equity REAL NOT NULL);
"""


@dataclass(frozen=True)
class Ticket:
    symbol: str
    side: str                  # "buy" or "sell"
    quantity: float
    limit_price: float
    stop_price: float | None
    strategy: str
    reason: str
    planned_risk: float = 0.0

    @property
    def notional(self) -> float:
        return self.quantity * self.limit_price

    @property
    def fractional(self) -> bool:
        return abs(self.quantity - round(self.quantity)) > 1e-9


@dataclass
class LiveResult:
    enabled: bool
    verified: bool = False
    account_note: str = ""
    equity: float | None = None          # sizing equity (capped at live.capital)
    cash: float | None = None            # cash available to the strategies
    positions: dict[str, Position] = field(default_factory=dict)
    status: TradingStatus | None = None
    tickets: list[Ticket] = field(default_factory=list)
    tickets_date: str | None = None      # when the tickets shown were issued
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    previous_date: str | None = None     # the last earlier ticket day, checked against the account
    previous: list[str] = field(default_factory=list)


class LiveLedger:
    """Issued tickets and end-of-day live equity, in the journal database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(LIVE_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def latest_buy(self, symbol: str):
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT * FROM live_tickets WHERE symbol = ? AND side = 'buy' ORDER BY created_date DESC, id DESC LIMIT 1",
                (symbol,),
            ).fetchone()

    def replace_tickets(self, as_of: date, tickets: list[Ticket]) -> None:
        """Idempotent: a rerun for the same date replaces that date's tickets."""
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM live_tickets WHERE created_date = ?", (as_of.isoformat(),))
            conn.executemany(
                "INSERT INTO live_tickets (created_date, symbol, side, quantity, limit_price, stop_price, strategy,"
                " reason, planned_risk) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(as_of.isoformat(), t.symbol, t.side, t.quantity, t.limit_price, t.stop_price, t.strategy,
                  t.reason, t.planned_risk) for t in tickets],
            )

    def latest_tickets(self, before: date | None = None) -> tuple[str | None, list[Ticket]]:
        """The most recent day's tickets (optionally only days strictly before `before`)."""
        with closing(self._connect()) as conn:
            if before is None:
                row = conn.execute("SELECT MAX(created_date) AS d FROM live_tickets").fetchone()
            else:
                row = conn.execute("SELECT MAX(created_date) AS d FROM live_tickets WHERE created_date < ?",
                                   (before.isoformat(),)).fetchone()
            if row is None or row["d"] is None:
                return None, []
            rows = conn.execute("SELECT * FROM live_tickets WHERE created_date = ? ORDER BY id", (row["d"],)).fetchall()
        return row["d"], [Ticket(r["symbol"], r["side"], r["quantity"], r["limit_price"], r["stop_price"],
                                 r["strategy"], r["reason"] or "", r["planned_risk"]) for r in rows]

    def equity_history(self) -> pd.Series:
        with closing(self._connect()) as conn:
            df = pd.read_sql_query("SELECT date, equity FROM live_equity ORDER BY date", conn)
        return pd.Series(df["equity"].values, index=pd.to_datetime(df["date"]), dtype=float)

    def record_equity(self, as_of: date, equity: float) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO live_equity (date, equity) VALUES (?, ?)", (as_of.isoformat(), equity))


def prepare(settings: Settings, ledger: LiveLedger, snap: AccountSnapshot | None, as_of: date,
            record: bool = False) -> LiveResult:
    """Verify the snapshot and derive live positions, sizing equity and loss-limit status."""
    cfg = settings.live
    res = LiveResult(enabled=cfg.enabled)
    if not cfg.enabled:
        return res
    if snap is None:
        res.account_note = "no account snapshot imported"
        return res
    problems = verify_snapshot(snap, settings)
    if problems:
        res.account_note = "; ".join(problems)
        return res
    res.verified = True
    res.account_note = f"{snap.nickname} ••{snap.account_last4} as of {snap.fetched_at}"
    invested = max(0.0, snap.total_value - snap.cash)
    for p in snap.positions:
        if p["quantity"] <= 0:
            continue
        sym = p["symbol"]
        t = ledger.latest_buy(sym)
        avg = p.get("average_buy_price")
        if t is None:
            res.warnings.append(f"{sym}: position was not opened from a ticket; its stop is unknown, so its whole "
                                "value counts as open risk")
            # unknown cost basis: assume the whole invested amount (conservative)
            entry = avg or invested / p["quantity"]
            res.positions[sym] = Position(p["quantity"], entry, 0.0, as_of)
            continue
        entry = avg if avg else float(t["limit_price"])
        filled = np.busday_offset(np.datetime64(t["created_date"]), 1, roll="forward").astype(date)
        res.positions[sym] = Position(p["quantity"], entry, float(t["stop_price"]), filled)
    open_sells = {o["symbol"] for o in snap.open_orders if str(o.get("side", "")).lower() == "sell"}
    for sym, pos in res.positions.items():
        if pos.stop > 0 and sym not in open_sells:
            res.warnings.append(f"{sym}: no open sell order at the broker, so its stop-loss is not protected; "
                                f"place a good-till-cancelled stop-loss sell of {pos.quantity:g} at {pos.stop:.2f}")
    res.previous_date, res.previous = reconcile(ledger, snap, res.positions, as_of)
    res.equity = min(snap.total_value, cfg.capital)
    res.cash = max(0.0, min(snap.cash, cfg.capital - invested))
    if record:
        ledger.record_equity(as_of, snap.total_value)
    res.status = trading_status(ledger.equity_history(), snap.total_value, settings.risk, pd.Timestamp(as_of))
    return res


def reconcile(ledger: LiveLedger, snap: AccountSnapshot, positions: dict[str, Position],
              as_of: date) -> tuple[str | None, list[str]]:
    """What happened to the previous ticket day's tickets, judged from the account snapshot."""
    day, tickets = ledger.latest_tickets(before=as_of)
    open_by_side = {(o["symbol"], str(o.get("side", "")).lower()) for o in snap.open_orders}
    out = []
    for t in tickets:
        label = f"{t.side.upper()} {t.symbol} {t.quantity:g}"
        if t.side == "buy":
            if t.symbol in positions:
                out.append(f"{label}: filled (held: {positions[t.symbol].quantity:g})")
            elif (t.symbol, "buy") in open_by_side:
                out.append(f"{label}: order still open")
            else:
                out.append(f"{label}: not in the account (not placed, not filled, or already exited)")
        elif t.symbol not in positions:
            out.append(f"{label}: done (no longer held)")
        else:
            out.append(f"{label}: still held; place the sell if you still agree with it")
    return day, out


def holdings_of(positions: dict[str, Position]) -> tuple[Holding, ...]:
    # stop 0 => unknown stop: the full position counts as risk
    return tuple(Holding(s, p.quantity, p.entry_price, p.stop) for s, p in positions.items())


def build_tickets(settings: Settings, res: LiveResult, snap: AccountSnapshot, intents: list[Intent],
                  bars: dict[str, pd.DataFrame]) -> LiveResult:
    """Fill `res.tickets` (sells first, then sized buys) from the live strategies' intents."""
    cfg = settings.live
    buf = cfg.limit_buffer_pct
    live = [i for i in intents if i.strategy in cfg.strategies]
    open_syms = {o["symbol"] for o in snap.open_orders}
    open_buys = [o for o in snap.open_orders if str(o.get("side", "")).lower() == "buy"]

    selling: set[str] = set()
    for it in [i for i in live if i.side == "sell"]:
        pos = res.positions.get(it.symbol)
        if pos is None or it.symbol in selling:
            continue  # nothing held: nothing to sell (no short selling)
        ref = it.ref_price if it.ref_price > 0 else pos.entry_price
        reason = it.reason + ("; cancel its open stop order first" if it.symbol in open_syms else "")
        res.tickets.append(Ticket(it.symbol, "sell", pos.quantity, round(ref * (1 - buf), 2), None, it.strategy, reason))
        selling.add(it.symbol)

    buys = sorted([i for i in live if i.side == "buy"], key=lambda i: -i.priority)
    if not buys:
        return res
    if res.status is not None and not res.status.new_entries_allowed:
        res.skipped += [f"{i.symbol}: {res.status.reason}" for i in buys]
        return res
    if open_buys:
        res.skipped += [f"{i.symbol}: the account has an open buy order; fill or cancel it first" for i in buys]
        return res
    state = PortfolioState(res.equity, res.cash, holdings_of(res.positions))
    engine = RiskEngine(settings)
    returns = returns_frame(bars)
    for it in buys:
        if it.symbol in res.positions or it.symbol in selling:
            res.skipped.append(f"{it.symbol}: already held in the account")
            continue
        if it.stop is None or not math.isfinite(it.ref_price) or it.ref_price <= 0:
            res.skipped.append(f"{it.symbol}: no valid price or stop")
            continue
        limit = round(it.ref_price * (1 + buf), 2)
        stop = round(it.stop, 2)
        d = engine.evaluate_entry(it.symbol, limit, stop, state, returns)
        if not d.approved:
            res.skipped.append(f"{it.symbol}: {d.reason}")
            continue
        res.tickets.append(Ticket(it.symbol, "buy", d.quantity, limit, stop, it.strategy, it.reason, d.risk_amount))
        state = PortfolioState(state.equity, state.cash - d.notional,
                               state.holdings + (Holding(it.symbol, d.quantity, limit, stop),))
    return res
