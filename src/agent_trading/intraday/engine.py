"""Quote-driven local simulator. An intent is never a fill; all mutations are atomic."""

import json
import math
from datetime import datetime

from .calendar import NY, aware, entry_window, session
from .config import Settings
from .models import Contract, Scan, Snapshot
from .options import cents, contract_problems, quote_problems, select
from .risk import RiskEngine
from .scanner import scan
from .store import Store

ACTIVE = "('pending','partial')"


class Simulator:
    def __init__(self, store: Store, cfg: Settings):
        self.store, self.cfg = store, cfg
        self.risk = RiskEngine(store, cfg)

    def controls(
        self, now: datetime, *, running: bool | None = None, enabled: bool | None = None, emergency: bool = False
    ) -> None:
        now = aware(now)
        with self.store.transaction():
            if emergency:
                self.store.set("killed", "true")  # deliberately no release path
                self.store.set("enabled", "false")
            if running is not None:
                self.store.set("running", str(running).lower())
            if enabled is not None:
                if enabled and self.store.get("killed") == "true":
                    raise ValueError("emergency stop is latched; entries cannot be re-enabled")
                self.store.set("enabled", str(enabled).lower())
            if emergency or running is False or enabled is False:
                self.store.set("auto_resume_day", "")
                self._cancel_buys(now, "entries disabled")
            self.store.event(
                now,
                "controls",
                {
                    "running": self.store.get("running"),
                    "enabled": self.store.get("enabled"),
                    "killed": self.store.get("killed"),
                },
            )

    def cash(self, now: datetime, settled: bool = True) -> int:
        # Sale proceeds remain unavailable until the next exchange session.
        total = cents(self.cfg.initial_capital)
        for f in self.store.rows("fills"):
            amount = f["quantity"] * f["price_cents"] * 100
            if f["side"] == "BUY":
                total -= amount + f["fee"]
            elif not settled or datetime.fromisoformat(f["time"]).astimezone(NY).date() < aware(now).date():
                total += amount - f["fee"]
        return total

    def _cancel_buys(self, now: datetime, reason: str) -> None:
        rows = self.store.db.execute(f"SELECT id FROM orders WHERE side='BUY' AND status IN {ACTIVE}").fetchall()
        for row in rows:
            self.store.db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (row[0],))
            self.store.event(now, "paper_order_cancelled", {"id": row[0], "reason": reason})

    def _reconcile(self, now: datetime) -> bool:
        positions = {p["contract"]: p for p in self.store.rows("positions")}
        quantities = {}
        costs = {}
        for f in self.store.db.execute(
            "SELECT o.contract,f.side,f.quantity,f.price_cents,f.fee,f.pnl FROM fills f JOIN orders o ON f.order_id=o.id"
        ):
            quantities[f[0]] = quantities.get(f[0], 0) + (f[2] if f[1] == "BUY" else -f[2])
            allocated = f[3] * 100 * f[2] + f[4] if f[1] == "BUY" else -(f[3] * 100 * f[2] - f[4] - f[5])
            costs[f[0]] = costs.get(f[0], 0) + allocated
        okay = all(
            quantities.get(k, 0) == p["quantity"] and costs.get(k, 0) == p["cost"] and p["cost"] >= 0
            for k, p in positions.items()
        )
        okay = okay and all(k in positions and q >= 0 for k, q in quantities.items())
        for o in self.store.rows("orders"):
            total = self.store.db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM fills WHERE order_id=?", (o["id"],)
            ).fetchone()[0]
            okay = okay and total == o["filled"] and 0 <= o["filled"] <= o["quantity"]
        if not okay or self.cash(now, settled=False) < 0:
            self.store.set("killed", "true")
            self.store.set("enabled", "false")
            self.store.event(now, "reconciliation_failed", {"message": "ledger mismatch; entries latched off"})
            return False
        return True

    def _fill(self, order: dict, quote: Contract, now: datetime) -> None:
        cfg, db = self.cfg, self.store.db
        submitted = datetime.fromisoformat(order["created"])
        if quote.quote_at <= submitted or quote_problems(quote, now, cfg, self.store.get("data_mode") == "fixture"):
            return
        if db.execute(
            "SELECT 1 FROM consumed WHERE order_id=? AND quote_at=?", (order["id"], quote.quote_at.isoformat())
        ).fetchone():
            return
        db.execute("INSERT INTO consumed VALUES (?,?)", (order["id"], quote.quote_at.isoformat()))
        buy = order["side"] == "BUY"
        if buy and contract_problems(
            quote,
            order["underlying"],
            json.loads(order["spec"])["right"],
            now,
            cfg,
            self.store.get("data_mode") == "fixture",
        ):
            return
        price = (
            math.ceil((quote.ask + cfg.slippage) * 100 - 1e-9)
            if buy
            else math.floor((quote.bid - cfg.slippage) * 100 + 1e-9)
        )
        if price <= 0 or (price > order["limit_cents"] if buy else price < order["limit_cents"]):
            return
        qty = min(order["quantity"] - order["filled"], quote.ask_size if buy else quote.bid_size)
        if qty <= 0:
            return
        fee = cents(cfg.fee_per_contract) * qty
        p = db.execute("SELECT * FROM positions WHERE contract=?", (quote.symbol,)).fetchone()
        pnl = 0
        if buy:
            cost = price * 100 * qty + fee
            if cost > self.cash(now):
                db.execute("UPDATE orders SET status='rejected' WHERE id=?", (order["id"],))
                self.store.event(now, "paper_order_rejected", {"id": order["id"], "reason": "settled cash"})
                return
            if p and p["quantity"]:
                db.execute(
                    "UPDATE positions SET quantity=quantity+?,cost=cost+? WHERE contract=?", (qty, cost, quote.symbol)
                )
            else:
                db.execute(
                    "INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?)",
                    (quote.symbol, quote.underlying, qty, cost, now.isoformat(), quote.model_dump_json()),
                )
        else:
            if not p or p["quantity"] < qty:
                self.store.set("killed", "true")
                self.store.event(now, "reconciliation_failed", {"reason": "exit exceeds held quantity"})
                return
            allocated = round(p["cost"] * qty / p["quantity"])
            pnl = price * 100 * qty - fee - allocated
            db.execute(
                "UPDATE positions SET quantity=quantity-?, cost=cost-? WHERE contract=?", (qty, allocated, quote.symbol)
            )
        db.execute(
            "INSERT INTO fills(order_id,time,side,quantity,price_cents,fee,pnl) VALUES (?,?,?,?,?,?,?)",
            (order["id"], now.isoformat(), order["side"], qty, price, fee, pnl),
        )
        filled = order["filled"] + qty
        db.execute(
            "UPDATE orders SET filled=?,status=? WHERE id=?",
            (filled, "filled" if filled == order["quantity"] else "partial", order["id"]),
        )
        self.store.event(
            now,
            "paper_fill" if buy else "position_exit",
            {
                "id": order["id"],
                "quantity": qty,
                "price": price / 100,
                "net_pnl": pnl / 100,
                "fill_type": "LOCAL SIMULATED",
            },
        )

    def _exit(self, p: dict, quote: Contract, now: datetime, reason: str) -> None:
        db = self.store.db
        if db.execute(
            f"SELECT 1 FROM orders WHERE contract=? AND side='SELL' AND status IN {ACTIVE}", (p["contract"],)
        ).fetchone():
            return
        limit = max(1, math.floor((quote.bid - self.cfg.slippage) * 100 + 1e-9))
        oid = f"exit:{p['contract']}:{now.isoformat()}"
        db.execute(
            "INSERT OR IGNORE INTO orders(id,day,underlying,contract,side,quantity,limit_cents,status,created,reason,spec) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                oid,
                now.date().isoformat(),
                p["underlying"],
                p["contract"],
                "SELL",
                p["quantity"],
                limit,
                "pending",
                now.isoformat(),
                reason,
                quote.model_dump_json(),
            ),
        )
        self.store.event(
            now,
            "paper_exit_submitted",
            {"id": oid, "reason": reason, "status": "pending; requires a later executable quote"},
        )

    def monitor(self, snap: Snapshot, now: datetime, result: Scan | None = None, force_exit: bool = False) -> None:
        now = aware(now)
        s = session(now.date())
        with self.store.transaction():
            if not self._reconcile(now):
                self._cancel_buys(now, "reconciliation failure")
                return
            last = self.store.get("last_tick")
            if last and now < datetime.fromisoformat(last):
                raise ValueError("out-of-order replay or clock rollback")
            self.store.set("last_tick", now.isoformat())
            killed = self.store.get("killed") == "true" or self.store.get("kill_day") == now.date().isoformat()
            flatten = force_exit or killed or not s or now >= s.flatten
            if (
                flatten
                or not entry_window(now)
                or self.store.get("enabled") != "true"
                or self.store.get("running") != "true"
            ):
                self._cancel_buys(now, "session or risk gate")
            if result is not None:
                valid_symbols = (
                    {x.symbol: x.right for x in result.signals if x.qualified} if not result.problems else {}
                )
                for order in self.store.db.execute(
                    f"SELECT id,underlying,spec FROM orders WHERE side='BUY' AND status IN {ACTIVE}"
                ).fetchall():
                    if valid_symbols.get(order["underlying"]) != json.loads(order["spec"])["right"]:
                        self.store.db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order["id"],))
                        self.store.event(
                            now,
                            "paper_order_cancelled",
                            {"id": order["id"], "reason": "signal invalidated before fill"},
                        )
            valid_snapshot = 0 <= (now - snap.observed_at).total_seconds() <= self.cfg.max_bar_age_seconds
            quotes = {c.symbol: c for c in snap.contracts} if valid_snapshot else {}
            if len(quotes) != len(snap.contracts) and valid_snapshot:
                quotes = {}  # ambiguous repeated contracts are not an executable book
            if self.store.get("data_mode") and snap.feed != self.store.get("data_mode"):
                quotes = {}
            for order in self.store.rows("orders"):
                if order["status"] not in {"pending", "partial"}:
                    continue
                age = (now - datetime.fromisoformat(order["created"])).total_seconds()
                if age >= self.cfg.order_timeout_seconds or order["day"] != now.date().isoformat():
                    self.store.db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order["id"],))
                    self.store.event(
                        now, "paper_order_cancelled", {"id": order["id"], "reason": "expired unfilled remainder"}
                    )
                elif s and s.open < now < s.close and order["contract"] in quotes:
                    self._fill(order, quotes[order["contract"]], now)
            positions = [p for p in self.store.rows("positions") if p["quantity"]]
            equity = self.cash(now, settled=False)
            complete = True
            reasons = {}
            marks = {}
            for p in positions:
                c = quotes.get(p["contract"])
                if not c or quote_problems(c, now, self.cfg, snap.feed == "fixture"):
                    complete = False
                    marks[p["contract"]] = {"price": None, "unrealized_pnl": None, "status": "unavailable or stale"}
                    self.store.event(
                        now, "missing_position_quote", {"contract": p["contract"], "exit_required": flatten}
                    )
                    continue  # never fabricate a close or a mark
                mark = (
                    max(0, math.floor((c.bid - self.cfg.slippage) * 100 + 1e-9)) * 100 * p["quantity"]
                    - cents(self.cfg.fee_per_contract) * p["quantity"]
                )
                equity += mark
                marks[p["contract"]] = {
                    "price": c.bid,
                    "quote_at": c.quote_at.isoformat(),
                    "unrealized_pnl": (mark - p["cost"]) / 100,
                    "status": c.feed,
                }
                ret = (mark - p["cost"]) / p["cost"]
                held = (now - datetime.fromisoformat(p["opened"])).total_seconds() / 60
                if flatten or datetime.fromisoformat(p["opened"]).date() < now.date():
                    reasons[p["contract"]] = "mandatory closure / emergency"
                elif held >= self.cfg.max_hold_minutes:
                    reasons[p["contract"]] = "maximum holding period"
                elif ret <= -self.cfg.stop_fraction:
                    reasons[p["contract"]] = "loss threshold (execution not guaranteed)"
                elif ret >= self.cfg.stop_fraction * self.cfg.reward_to_risk:
                    reasons[p["contract"]] = "profit target"
                elif result is not None:
                    signal = next((x for x in result.signals if x.symbol == p["underlying"]), None)
                    if result.problems or signal is None or not signal.qualified or signal.right != c.right:
                        reasons[p["contract"]] = "technical signal invalidated or unavailable"
            # Current-day realized net P&L plus conservatively marked open P&L.
            realized = sum(f["pnl"] for f in self.store.rows("fills") if f["time"][:10] == now.date().isoformat())
            unrealized = equity - self.cash(now, settled=False) - sum(p["cost"] for p in positions)
            if realized + unrealized <= -cents(self.cfg.daily_loss_budget):
                self.store.set("kill_day", now.date().isoformat())
                self._cancel_buys(now, "daily loss budget")
                for p in positions:
                    reasons[p["contract"]] = "daily loss budget"
                self.store.event(
                    now, "risk_limit", {"reason": "daily loss budget; unknown marks use zero for risk only"}
                )
            if not complete:
                self._cancel_buys(now, "unreliable position valuation")
            self.store.set("valuation_complete", str(complete).lower())
            self.store.set("marks", json.dumps(marks))
            self.store.db.execute(
                "INSERT OR REPLACE INTO equity VALUES (?,?,?)", (now.isoformat(), equity, int(complete))
            )
            for p in positions:
                if p["contract"] in reasons and p["contract"] in quotes and s and s.open < now < s.close:
                    c = quotes[p["contract"]]
                    if not quote_problems(c, now, self.cfg, snap.feed == "fixture"):
                        self._exit(p, c, now, reasons[p["contract"]])
            if positions and (not s or now >= s.close):
                self.store.set("killed", "true")
                self.store.set("enabled", "false")
                self.store.event(
                    now,
                    "unresolved_overnight_positions",
                    {"count": len(positions), "reason": "market closed without executable exit; never reported flat"},
                )

    def cycle(
        self, snap: Snapshot, now: datetime, *, enter: bool = False, only: set[str] | None = None, clock=None
    ) -> Scan:
        now = aware(now)
        result = scan(snap, now, self.cfg, only=only)
        if clock is not None:
            now = aware(clock())  # execution checks include the time spent calculating signals
        self.monitor(snap, now, result)
        with self.store.transaction():
            self.store.set("last_scan", result.model_dump_json())
            self.store.event(
                now, "scan", {"coverage": result.coverage, "problems": result.problems, "rejected": result.rejected}
            )
            if not enter or result.problems or self.store.get("valuation_complete") == "false":
                return result
            if self.store.get("data_mode") and self.store.get("data_mode") != snap.feed:
                self.store.event(
                    now, "rejected", {"reason": "cannot mix fixtures and observed market data in one ledger"}
                )
                return result
            if not self._reconcile(now):
                return result
            for signal in sorted(result.top("CALL") + result.top("PUT"), key=lambda s: (-s.score, s.symbol)):
                self.store.event(now, "qualified_signal", signal.model_dump(mode="json"))
                contract, rejected = select(
                    snap.contracts, signal.symbol, signal.right, now, self.cfg, snap.feed == "fixture"
                )
                if contract is None:
                    self.store.event(
                        now,
                        "skipped",
                        {
                            "symbol": signal.symbol,
                            "reason": "no eligible listed next-session contract",
                            "contracts": rejected,
                        },
                    )
                    continue
                limit = math.ceil((contract.ask + self.cfg.slippage) * 100 - 1e-9)
                decision = self.risk.assess(signal, contract, limit, now, snap.feed == "fixture", self.cash(now))
                if not decision.quantity:
                    self.store.event(now, "skipped", {"symbol": signal.symbol, "reasons": decision.reasons})
                    continue
                oid = f"entry:{now.date()}:{signal.symbol}"
                self.store.db.execute(
                    "INSERT INTO orders(id,day,underlying,contract,side,quantity,limit_cents,status,created,reason,spec) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        oid,
                        now.date().isoformat(),
                        signal.symbol,
                        contract.symbol,
                        "BUY",
                        decision.quantity,
                        limit,
                        "pending",
                        now.isoformat(),
                        json.dumps(signal.reasons),
                        contract.model_dump_json(),
                    ),
                )
                self.store.set("data_mode", snap.feed)
                self.store.event(
                    now,
                    "paper_order_submitted",
                    {
                        "id": oid,
                        "quantity": decision.quantity,
                        "limit": limit / 100,
                        "status": "pending",
                        "mode": "local_simulator",
                    },
                )
        return result
