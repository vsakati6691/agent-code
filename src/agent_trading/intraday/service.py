"""Restart-safe local scheduling, with deadlines and no delayed entry-job catch-up."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from .calendar import NY, jobs
from .config import Settings
from .engine import Simulator
from .models import Snapshot
from .providers import DataProvider, MassiveProvider
from .reporting import write_report
from .scanner import scan
from .store import Store


class Service:
    def __init__(
        self,
        store: Store,
        cfg: Settings,
        provider: DataProvider,
        reports: str | Path = "reports/intraday",
        clock=lambda: datetime.now(UTC),
    ):
        self.store, self.cfg, self.provider = store, cfg, provider
        self.engine = Simulator(store, cfg)
        self.reports, self.clock = reports, clock

    def collect(self, now: datetime, stocks: bool) -> Snapshot:
        held = [p["underlying"] for p in self.store.rows("positions") if p["quantity"]]
        pending = [o["underlying"] for o in self.store.rows("orders") if o["status"] in {"pending", "partial"}]
        if isinstance(self.provider, MassiveProvider) and not stocks:
            # Position monitoring does not wait for a full-universe collection.
            snap = Snapshot(
                observed_at=now,
                membership_at=now,
                membership_source="monitor only",
                universe={},
                bars={},
                source="Massive position monitor",
                feed="realtime",
            )
        else:
            snap = self.provider.snapshot(now, include_stocks=stocks)
        if isinstance(self.provider, MassiveProvider):
            symbols = held + pending
            if stocks:
                result = scan(snap, self.clock(), self.cfg)
                symbols += [s.symbol for s in result.top("CALL") + result.top("PUT")]
            snap = self.provider.enrich(snap, symbols, self.clock())
        return snap

    def manual_scan(self, *, enter: bool = False):
        now = self.clock()
        snap = self.collect(now, True)
        return self.engine.cycle(snap, self.clock(), enter=enter)

    def prepare(self):
        now = self.clock()
        snap = self.provider.snapshot(now, include_stocks=True)
        watchlist = []
        for symbol, sector in snap.universe.items():
            past = [b for b in snap.bars.get(symbol, []) if b.end.astimezone(NY).date() < now.astimezone(NY).date()]
            latest_day = max((b.end.astimezone(NY).date() for b in past), default=None)
            previous = [b for b in past if b.end.astimezone(NY).date() == latest_day]
            watchlist.append(
                {
                    "symbol": symbol,
                    "sector": sector,
                    "support": min((b.low for b in previous), default=None),
                    "resistance": max((b.high for b in previous), default=None),
                    "bar_date": str(latest_day),
                    "event_status": snap.events[symbol].status if symbol in snap.events else "unknown",
                }
            )
        result = {
            "at": now.isoformat(),
            "feed": snap.feed,
            "source": snap.source,
            "watchlist": watchlist,
            "events": {k: v.model_dump(mode="json") for k, v in snap.events.items()},
            "problems": snap.problems,
        }
        with self.store.transaction():
            self.store.set("preparation", json.dumps(result))
            self.store.event(now, "premarket_preparation", {"members": len(watchlist), "problems": snap.problems})
        return result

    def tick(self) -> None:
        now = self.clock().astimezone(NY)
        with self.store.transaction():
            self.store.set("heartbeat", now.isoformat())
        due = []
        for kind, at in jobs(now.date()):
            if at > now:
                continue
            key = f"{kind}:{at.isoformat()}"
            with self.store.transaction():
                if self.store.db.execute("SELECT 1 FROM runs WHERE job=?", (key,)).fetchone():
                    continue
                stale = kind == "scan" and (now - at).total_seconds() > 60
                self.store.db.execute(
                    "INSERT INTO runs VALUES (?,?,?)", (key, now.isoformat(), "missed" if stale else "claimed")
                )
                if stale:
                    self.store.event(
                        now, "missed_scan", {"scheduled": at.isoformat(), "reason": "no catch-up entry orders"}
                    )
                else:
                    due.append((key, kind))
        # Flatten and monitor positions BEFORE a potentially slow full-universe scan.
        positions = any(p["quantity"] for p in self.store.rows("positions"))
        pending = any(o["status"] in {"pending", "partial"} for o in self.store.rows("orders"))
        if positions or pending:
            try:
                snap = self.collect(now, False)
                self.engine.monitor(snap, self.clock())
            except Exception as exc:
                self.failure(now, exc)
        for key, kind in sorted(due, key=lambda pair: {"flatten": 0, "prepare": 1, "scan": 2, "report": 3}[pair[1]]):
            try:
                if kind == "report":
                    write_report(self.store, self.cfg, self.reports, now.date())
                elif kind == "flatten":
                    self.engine.controls(now, enabled=False)
                    if positions:
                        self.engine.monitor(self.collect(now, False), self.clock(), force_exit=True)
                elif self.store.get("running") == "true":
                    if kind == "prepare":
                        self.prepare()
                    else:
                        self.manual_scan(enter=True)
                with self.store.transaction():
                    self.store.db.execute("UPDATE runs SET status='done' WHERE job=?", (key,))
            except Exception as exc:
                self.failure(now, exc)
                with self.store.transaction():
                    self.store.db.execute("UPDATE runs SET status='failed' WHERE job=?", (key,))

    def failure(self, now: datetime, exc: Exception) -> None:
        # Exception text may contain keys or URLs from third-party libraries. Persist only type.
        with self.store.transaction():
            self.engine._cancel_buys(now, "provider failure")
            self.store.set("enabled", "false")
            self.store.event(
                now,
                "provider_failure",
                {"reason": type(exc).__name__, "action": "entries disabled; inspect provider/data coverage"},
            )

    def run(self):
        try:
            while self.store.get("running") == "true" or any(p["quantity"] for p in self.store.rows("positions")):
                self.tick()
                time.sleep(5)
        except KeyboardInterrupt:
            self.engine.controls(self.clock(), running=False, enabled=False)
            self.store.event(
                self.clock(), "service_stopped", {"reason": "process interrupted; monitoring stops with process"}
            )


def explain_latest(store: Store) -> dict:
    """Optional deterministic research notes; no paid AI dependency or write-back to strategy."""
    raw = store.get("last_scan")
    if not raw:
        return {"status": "no scan"}
    result = json.loads(raw)
    return {
        "signals": [
            {
                "symbol": s["symbol"],
                "direction": s["right"],
                "score": s["score"],
                "evidence": s["factors"],
                "conflicts": s["reasons"] if not s["qualified"] else [],
                "hypothesis": "compare this setup across unseen sessions before changing weights",
            }
            for s in result["signals"]
        ],
        "coverage_problems": result["problems"],
        "authority": "explanation only; cannot change risk, configuration, or order state",
    }
