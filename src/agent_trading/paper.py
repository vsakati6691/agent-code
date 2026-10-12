"""Paper broker: turns research signals into simulated orders and fills them
from validated daily bars, with the same timing, costs and RiskEngine as the
backtest.

This module has no connection to any brokerage. It reads and writes only the
local SQLite journal.

Daily cycle (run after the close of `as_of`):
  1. fill orders created on earlier days at the first later bar's open;
  2. check protective stops on each bar since the last run;
  3. from `as_of`'s close, queue exits for positions with an exit signal and
     entries for approved candidates, to be filled at the next open.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from .config import Settings
from .data.service import EarningsData
from .journal import Journal
from .risk import Holding, PortfolioState, RiskEngine, RiskViolation

ORDERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_date  TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity      REAL NOT NULL CHECK (quantity > 0),
    ref_price     REAL NOT NULL CHECK (ref_price > 0),
    stop_price    REAL,
    trade_id      INTEGER,
    reason        TEXT,
    status        TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'filled', 'cancelled')),
    fill_date     TEXT,
    fill_price    REAL,
    note          TEXT,
    CHECK (side = 'sell' OR (stop_price IS NOT NULL AND stop_price > 0 AND stop_price < ref_price))
);
CREATE TABLE IF NOT EXISTS paper_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS paper_equity (date TEXT PRIMARY KEY, equity REAL NOT NULL);
"""


@dataclass(frozen=True)
class Intent:
    """A strategy's request; the broker still applies every risk check."""
    symbol: str
    side: str                 # "buy" or "sell"
    ref_price: float
    stop: float | None = None
    strategy: str = "legacy"
    reason: str = ""
    priority: float = 0.0     # higher first


@dataclass(frozen=True)
class Proposal:
    symbol: str
    ref_price: float
    stop: float
    quantity: float
    risk: float
    notional: float
    approved: bool
    reason: str
    momentum: float = float("nan")
    note: str = ""


@dataclass
class RunResult:
    events: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    new_orders: list[Proposal] = field(default_factory=list)


def returns_frame(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame()
    return pd.DataFrame({s: df["close"] for s, df in bars.items()}).sort_index().pct_change()


def _last_close(df: pd.DataFrame | None, on_or_before: pd.Timestamp) -> float | None:
    if df is None:
        return None
    hist = df.loc[:on_or_before, "close"]
    return None if hist.empty else float(hist.iloc[-1])


def earnings_within(earnings: EarningsData | None, symbol: str, as_of: date, days: int) -> date | None:
    if earnings is None or not earnings.available:
        return None
    t = earnings.table
    hits = t[(t["symbol"] == symbol) & (t["reportDate"] >= as_of)]
    if hits.empty:
        return None
    nxt = min(hits["reportDate"])
    return nxt if (nxt - as_of).days <= days else None


def portfolio_state(
    journal: Journal,
    settings: Settings,
    bars: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
    reserved_cash: float = 0.0,
) -> PortfolioState:
    """Paper portfolio marked to the latest close on or before `as_of`."""
    open_df = journal.open_trades()
    holdings = []
    market_value = 0.0
    for t in open_df.itertuples() if not open_df.empty else []:
        holdings.append(Holding(t.symbol, t.quantity, t.entry_price, t.stop_price))
        last = _last_close(bars.get(t.symbol), as_of)
        market_value += t.quantity * (last if last is not None else t.entry_price)
    cash = journal.cash(settings.paper_starting_equity)
    return PortfolioState(cash + market_value, cash - reserved_cash, tuple(holdings))


def propose_entries(
    screen: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    state: PortfolioState,
    settings: Settings,
    earnings: EarningsData | None,
    as_of: date,
    exclude: set[str] | frozenset[str] = frozenset(),
) -> list[Proposal]:
    """Rank entry signals by momentum and size each through the RiskEngine.

    Approved proposals consume risk and cash for the ones ranked below them.
    """
    if screen.empty:
        return []
    engine = RiskEngine(settings)
    returns = returns_frame(bars)
    proposals = []
    cands = screen[screen["entry_signal"]].sort_values("momentum", ascending=False)
    for sym, row in cands.iterrows():
        if sym in exclude:
            continue
        stop = row["close"] - settings.risk.atr_stop_multiple * row["atr"]
        nxt = earnings_within(earnings, sym, as_of, settings.reports.earnings_warning_days)
        note = "" if (earnings is not None and earnings.available) else "earnings unverified"
        if nxt is not None and settings.paper.skip_entries_before_earnings:
            proposals.append(Proposal(sym, row["close"], stop, 0, 0, 0, False, f"earnings on {nxt}", row["momentum"]))
            continue
        d = engine.evaluate_entry(sym, float(row["close"]), float(stop), state, returns)
        proposals.append(Proposal(sym, row["close"], stop, d.quantity, d.risk_amount, d.notional,
                                  d.approved, d.reason, row["momentum"], note))
        if d.approved:
            state = replace(
                state,
                cash=state.cash - d.notional,
                holdings=state.holdings + (Holding(sym, d.quantity, float(row["close"]), float(stop)),),
            )
    return proposals


class PaperBroker:
    def __init__(self, settings: Settings, journal: Journal) -> None:
        if settings.mode != "paper":
            raise RiskViolation("PaperBroker only runs in paper mode")
        self.settings = settings
        self.journal = journal
        self.cost = settings.costs.per_side
        self.commission = settings.costs.commission_per_order
        with closing(self._connect()) as conn, conn:
            conn.executescript(ORDERS_SCHEMA)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(paper_orders)")}
            if "strategy" not in cols:
                conn.execute("ALTER TABLE paper_orders ADD COLUMN strategy TEXT NOT NULL DEFAULT 'legacy'")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.journal.path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- persistence -------------------------------------------------------

    def _meta(self, key: str) -> str | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM paper_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row["value"]

    def _set_meta(self, key: str, value: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO paper_meta (key, value) VALUES (?, ?)", (key, value))

    def orders(self, status: str | None = None) -> pd.DataFrame:
        sql = "SELECT * FROM paper_orders" + (" WHERE status = ?" if status else "") + " ORDER BY id"
        with closing(self._connect()) as conn:
            return pd.read_sql_query(sql, conn, params=(status,) if status else ())

    def _add_order(self, created: date, symbol: str, side: str, qty: float, ref: float,
                   stop: float | None, reason: str, trade_id: int | None = None, strategy: str = "legacy") -> int:
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO paper_orders (created_date, symbol, side, quantity, ref_price, stop_price, trade_id, reason, strategy)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (created.isoformat(), symbol, side, qty, ref, stop, trade_id, reason, strategy),
            )
            return int(cur.lastrowid)

    def equity_history(self) -> pd.Series:
        with closing(self._connect()) as conn:
            df = pd.read_sql_query("SELECT date, equity FROM paper_equity ORDER BY date", conn)
        return pd.Series(df["equity"].values, index=pd.to_datetime(df["date"]), dtype=float)

    def _record_equity(self, as_of: date, equity: float) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO paper_equity (date, equity) VALUES (?, ?)", (as_of.isoformat(), equity))

    def status(self, bars: dict[str, pd.DataFrame], as_of: date):
        from .risk import trading_status

        equity = portfolio_state(self.journal, self.settings, bars, pd.Timestamp(as_of)).equity
        return trading_status(self.equity_history(), equity, self.settings.risk, pd.Timestamp(as_of))

    def _finish_order(self, order_id: int, status: str, when: date | None = None,
                      price: float | None = None, trade_id: int | None = None, note: str = "") -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE paper_orders SET status = ?, fill_date = ?, fill_price = ?,"
                " trade_id = COALESCE(?, trade_id), note = ? WHERE id = ?",
                (status, when.isoformat() if when else None, price, trade_id, note, order_id),
            )

    # --- daily cycle ---------------------------------------------------------

    def run(
        self,
        bars: dict[str, pd.DataFrame],
        screen: pd.DataFrame | None,
        earnings: EarningsData | None,
        as_of: date,
        intents: list[Intent] | None = None,
    ) -> RunResult:
        """Process fills/stops up to `as_of`, then queue orders from `intents`
        (strategy A/B) or, when intents is None, from the legacy `screen`."""
        from .risk import trading_status

        result = RunResult()
        last_processed = self._meta("last_processed_date")
        start = date.fromisoformat(last_processed) if last_processed else as_of
        days = sorted({ts for df in bars.values() for ts in df.index if start < ts.date() <= as_of})
        for day in days:
            self._fill_pending(day, bars, result)
            self._check_stops(day, bars, result)
        self._expire_stale(as_of, result)
        if last_processed is None or as_of > start:
            self._set_meta("last_processed_date", as_of.isoformat())

        equity = portfolio_state(self.journal, self.settings, bars, pd.Timestamp(as_of)).equity
        status = trading_status(self.equity_history(), equity, self.settings.risk, pd.Timestamp(as_of))
        self._record_equity(as_of, equity)

        if self._meta("last_signal_date") == as_of.isoformat():
            result.warnings.append(f"signals for {as_of} were already generated; no new orders queued")
            return result
        self._queue_time_exits(bars, as_of, result)
        if not status.new_entries_allowed:
            result.warnings.append(f"new entries blocked: {status.reason}")
        if intents is None:
            self._queue_signals(bars, screen if screen is not None else pd.DataFrame(), earnings, as_of, result,
                                allow_entries=status.new_entries_allowed)
        else:
            self._queue_intents(bars, intents, as_of, result, allow_entries=status.new_entries_allowed)
        self._set_meta("last_signal_date", as_of.isoformat())
        return result

    def _queue_time_exits(self, bars, as_of: date, result: RunResult) -> None:
        limits = self.settings.risk.max_holding_days
        open_df = self.journal.open_trades()
        pending = self.orders("pending")
        pending_sells = set(pending.loc[pending["side"] == "sell", "symbol"]) if not pending.empty else set()
        for t in open_df.itertuples() if not open_df.empty else []:
            limit = limits.get(t.symbol)
            if limit is None or t.symbol in pending_sells:
                continue
            held = int(np.busday_count(date.fromisoformat(t.entry_date), as_of))
            if held >= limit:
                last = _last_close(bars.get(t.symbol), pd.Timestamp(as_of)) or t.entry_price
                self._add_order(as_of, t.symbol, "sell", t.quantity, float(last), None,
                                f"max holding period ({limit} days)", int(t.id), getattr(t, "strategy", "legacy"))
                result.events.append(f"queued SELL {t.symbol} (held {held} days, limit {limit})")

    def _queue_intents(self, bars, intents: list[Intent], as_of: date, result: RunResult, allow_entries: bool) -> None:
        pending = self.orders("pending")
        pending_syms = set(pending["symbol"]) if not pending.empty else set()
        open_df = self.journal.open_trades()
        held = {t.symbol: t for t in open_df.itertuples()} if not open_df.empty else {}

        for it in [i for i in intents if i.side == "sell"]:
            t = held.get(it.symbol)
            if t is None:
                result.warnings.append(f"ignored SELL {it.symbol}: no paper position (short selling is not allowed)")
            elif it.symbol not in pending_syms:
                self._add_order(as_of, it.symbol, "sell", t.quantity, it.ref_price, None, it.reason, int(t.id), it.strategy)
                pending_syms.add(it.symbol)
                result.events.append(f"queued SELL {it.symbol} ({it.strategy}: {it.reason})")

        buys = sorted([i for i in intents if i.side == "buy"], key=lambda i: -i.priority)
        if not buys:
            return
        if not allow_entries:
            for it in buys:
                result.new_orders.append(Proposal(it.symbol, it.ref_price, it.stop or 0, 0, 0, 0, False,
                                                  "blocked by loss limit"))
            return
        buy_pending = pending[pending["side"] == "buy"] if not pending.empty else pending
        reserved = float((buy_pending["quantity"] * buy_pending["ref_price"]).sum()) if not buy_pending.empty else 0.0
        state = portfolio_state(self.journal, self.settings, bars, pd.Timestamp(as_of), reserved)
        if not buy_pending.empty:
            state = replace(state, holdings=state.holdings + tuple(
                Holding(o.symbol, o.quantity, o.ref_price, o.stop_price) for o in buy_pending.itertuples()))
        engine = RiskEngine(self.settings)
        returns = returns_frame(bars)
        for it in buys:
            if it.symbol in held or it.symbol in pending_syms:
                result.new_orders.append(Proposal(it.symbol, it.ref_price, it.stop or 0, 0, 0, 0, False,
                                                  "already held or pending (duplicate signal ignored)"))
                continue
            if it.stop is None:
                result.new_orders.append(Proposal(it.symbol, it.ref_price, 0, 0, 0, 0, False, "no stop defined"))
                continue
            d = engine.evaluate_entry(it.symbol, it.ref_price, it.stop, state, returns)
            result.new_orders.append(Proposal(it.symbol, it.ref_price, it.stop, d.quantity, d.risk_amount,
                                              d.notional, d.approved, d.reason, note=it.strategy))
            if not d.approved:
                continue
            self._add_order(as_of, it.symbol, "buy", d.quantity, it.ref_price, it.stop, it.reason, None, it.strategy)
            pending_syms.add(it.symbol)
            state = replace(state, cash=state.cash - d.notional,
                            holdings=state.holdings + (Holding(it.symbol, d.quantity, it.ref_price, it.stop),))
            result.events.append(f"queued BUY {it.symbol} x{d.quantity:g} ({it.strategy}; ref {it.ref_price:.2f}, "
                                 f"stop {it.stop:.2f}, planned risk ${d.risk_amount:.2f})")

    def _fill_pending(self, day: pd.Timestamp, bars: dict[str, pd.DataFrame], result: RunResult) -> None:
        pending = self.orders("pending")
        if pending.empty:
            return
        # sells first so their cash is available, as in the backtest
        pending = pending.sort_values(["side", "id"], ascending=[False, True])
        for o in pending.itertuples():
            if date.fromisoformat(o.created_date) >= day.date():
                continue
            df = bars.get(o.symbol)
            if df is None or day not in df.index:
                continue
            bar = df.loc[day]
            if o.side == "sell":
                self._fill_sell(o, day, float(bar["open"]), result)
            else:
                self._fill_buy(o, day, float(bar["open"]), bars, result)

    def _fill_sell(self, o, day: pd.Timestamp, open_price: float, result: RunResult) -> None:
        open_df = self.journal.open_trades()
        if open_df.empty or o.trade_id not in set(open_df["id"]):
            self._finish_order(o.id, "cancelled", note="position already closed")
            return
        fill = open_price * (1 - self.cost)
        self.journal.close_trade(int(o.trade_id), fill, day.date(), o.reason or "exit signal", self.commission)
        self._finish_order(o.id, "filled", day.date(), fill)
        result.events.append(f"{day.date()} SELL {o.symbol} x{o.quantity:g} @ {fill:.2f} ({o.reason})")

    def _fill_buy(self, o, day: pd.Timestamp, open_price: float, bars: dict[str, pd.DataFrame], result: RunResult) -> None:
        if open_price <= o.stop_price:
            self._finish_order(o.id, "cancelled", note=f"opened at {open_price:.2f}, at or below stop {o.stop_price:.2f}")
            result.events.append(f"{day.date()} cancelled BUY {o.symbol}: gapped below its stop")
            return
        fill = open_price * (1 + self.cost)
        prev = day - pd.Timedelta(days=1)
        state = portfolio_state(self.journal, self.settings, bars, prev)
        state = replace(state, cash=state.cash - self.commission)
        known = returns_frame(bars).loc[:prev]
        d = RiskEngine(self.settings).evaluate_entry(o.symbol, fill, o.stop_price, state, known)
        if not d.approved:
            self._finish_order(o.id, "cancelled", note=f"risk re-check at fill: {d.reason}")
            result.events.append(f"{day.date()} cancelled BUY {o.symbol}: {d.reason}")
            return
        qty = min(o.quantity, d.quantity)  # a higher open shrinks the size, never grows it
        trade_id = self.journal.open_trade(o.symbol, qty, fill, o.stop_price, day.date(), o.reason or "",
                                           self.commission, getattr(o, "strategy", "legacy"))
        self._finish_order(o.id, "filled", day.date(), fill, trade_id)
        result.events.append(f"{day.date()} BUY {o.symbol} x{qty:g} @ {fill:.2f}, stop {o.stop_price:.2f}")

    def _check_stops(self, day: pd.Timestamp, bars: dict[str, pd.DataFrame], result: RunResult) -> None:
        open_df = self.journal.open_trades()
        for t in open_df.itertuples() if not open_df.empty else []:
            df = bars.get(t.symbol)
            if df is None or day not in df.index or date.fromisoformat(t.entry_date) > day.date():
                continue
            bar = df.loc[day]
            if bar["low"] <= t.stop_price:
                raw = min(float(bar["open"]), t.stop_price)
                fill = raw * (1 - self.cost)
                self.journal.close_trade(int(t.id), fill, day.date(), "stop", self.commission)
                self._cancel_pending_for_trade(int(t.id))
                result.events.append(f"{day.date()} STOP {t.symbol} x{t.quantity:g} @ {fill:.2f}")

    def _cancel_pending_for_trade(self, trade_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE paper_orders SET status = 'cancelled', note = 'position stopped out'"
                " WHERE status = 'pending' AND trade_id = ?",
                (trade_id,),
            )

    def _expire_stale(self, as_of: date, result: RunResult) -> None:
        pending = self.orders("pending")
        for o in pending.itertuples() if not pending.empty else []:
            age = int(np.busday_count(date.fromisoformat(o.created_date), as_of))
            if age > self.settings.paper.order_expiry_days:
                self._finish_order(o.id, "cancelled", note=f"expired after {age} business days without a valid bar")
                result.events.append(f"expired {o.side.upper()} {o.symbol} (no valid price data)")

    def _queue_signals(self, bars, screen: pd.DataFrame, earnings, as_of: date, result: RunResult,
                       allow_entries: bool = True) -> None:
        pending = self.orders("pending")
        pending_syms = set(pending["symbol"]) if not pending.empty else set()
        open_df = self.journal.open_trades()

        for t in open_df.itertuples() if not open_df.empty else []:
            if t.symbol not in screen.index:
                result.warnings.append(
                    f"{t.symbol}: no valid data today, so its exit signal and stop cannot be evaluated"
                )
                continue
            if screen.at[t.symbol, "exit_signal"] and t.symbol not in pending_syms:
                self._add_order(as_of, t.symbol, "sell", t.quantity, float(screen.at[t.symbol, "close"]),
                                None, "exit signal", int(t.id))
                result.events.append(f"queued SELL {t.symbol} (exit signal) for next open")

        if not allow_entries or screen.empty:
            return
        reserved = float((pending.loc[pending["side"] == "buy", "quantity"] * pending.loc[pending["side"] == "buy", "ref_price"]).sum()) if not pending.empty else 0.0
        state = portfolio_state(self.journal, self.settings, bars, pd.Timestamp(as_of), reserved)
        pending_buys = pending[pending["side"] == "buy"] if not pending.empty else pending
        if not pending_buys.empty:
            state = replace(state, holdings=state.holdings + tuple(
                Holding(o.symbol, o.quantity, o.ref_price, o.stop_price) for o in pending_buys.itertuples()))
        held = set(open_df["symbol"]) if not open_df.empty else set()
        for p in propose_entries(screen, bars, state, self.settings, earnings, as_of, held | pending_syms):
            if p.approved:
                self._add_order(as_of, p.symbol, "buy", p.quantity, float(p.ref_price), float(p.stop),
                                f"entry signal (momentum {p.momentum:+.1%})")
                result.events.append(f"queued BUY {p.symbol} x{p.quantity:g} (ref {p.ref_price:.2f}, stop {p.stop:.2f}, risk ${p.risk:.2f})")
            result.new_orders.append(p)

    # --- reporting -----------------------------------------------------------

    def positions(self, bars: dict[str, pd.DataFrame], as_of: date) -> pd.DataFrame:
        open_df = self.journal.open_trades()
        if open_df.empty:
            return open_df
        ts = pd.Timestamp(as_of)
        out = open_df[["id", "symbol", "quantity", "entry_date", "entry_price", "stop_price"]].copy()
        out["last"] = [_last_close(bars.get(s), ts) for s in out["symbol"]]
        out["unrealized"] = out["quantity"] * (out["last"] - out["entry_price"])
        out["market_value"] = out["quantity"] * out["last"]
        return out
