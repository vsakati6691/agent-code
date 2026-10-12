"""Execution service: validate, persist, submit, verify, reconcile.

Order of operations for every request:
1. refuse a decision that already has an order (decision_id is unique);
2. resolve earlier unresolved orders by looking them up at the broker;
3. read fresh account state and a quote from the broker;
4. apply the daily-loss halt and the drawdown kill switch;
5. run the deterministic validator; a refusal is recorded as BLOCKED;
6. persist the attempt (PENDING, with a new ref_id) BEFORE submitting;
7. submit once; a timeout or any unexpected error leaves the order UNKNOWN;
8. read the order back from the broker and store its real state.

An UNKNOWN order is never resubmitted. It is looked up on every run, blocks
new orders in the same symbol, and stays until the broker reports it or the
owner records that it was not placed.

Modes: `dry_run` validates and records but never calls submit(); `paper`
sends to a simulated broker. There is no live mode in this build: the service
refuses `live` and refuses any broker that reports `is_live`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import Settings
from ..killswitch import engage as engage_kill_switch
from ..killswitch import status as kill_switch_status
from .broker import Broker
from .ledger import OrderLedger
from .models import (BLOCKED, DRY_RUN, NOT_SENT, OPEN, PARTIALLY_FILLED, PENDING, REJECTED, SUBMITTED, TERMINAL,
                     UNKNOWN, AccountState, BrokerError, BrokerNotSent, BrokerRejected, OrderRequest)
from .validator import ExecutionLimits, validate

ET = ZoneInfo("America/New_York")
MODES = ("dry_run", "paper")
STALE_UNRESOLVED_MINUTES = 30
OWNER_NOT_PLACED_PHRASE = "I checked the broker and this order does not exist"


class ModeError(RuntimeError):
    """The mode and broker do not match; nothing may run."""


def verify_mode(mode: str, broker: Broker) -> None:
    if mode == "live":
        raise ModeError("live execution is not available in this build (no live broker adapter)")
    if mode not in MODES:
        raise ModeError(f"unknown execution mode {mode!r}; expected one of {MODES}")
    if getattr(broker, "is_live", True):
        raise ModeError(f"{mode} mode refuses broker {getattr(broker, 'name', '?')!r}, which reports is_live")


@dataclass
class ExecutionResult:
    decision_id: str
    state: str
    ref_id: str | None = None
    reasons: list[str] = field(default_factory=list)
    broker_id: str | None = None
    filled_quantity: float = 0.0


@dataclass
class HealthReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    stale_unresolved: list[str] = field(default_factory=list)


class ExecutionService:
    def __init__(self, settings: Settings, broker: Broker, ledger: OrderLedger, mode: str,
                 limits: ExecutionLimits | None = None, clock=None) -> None:
        verify_mode(mode, broker)
        self.settings = settings
        self.broker = broker
        self.ledger = ledger
        self.mode = mode
        self.limits = limits or ExecutionLimits.from_settings(settings)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        ledger.clock = self.clock               # one clock for decisions and ledger timestamps

    # --- orders ------------------------------------------------------------
    def execute(self, req: OrderRequest) -> ExecutionResult:
        prior = self.ledger.by_decision(req.decision_id)
        if prior is not None:
            return ExecutionResult(req.decision_id, prior["state"], prior["ref_id"],
                                   ["duplicate decision: already handled, not sent again"], prior["broker_id"],
                                   prior["filled_quantity"])
        self.resolve_unresolved()
        now = self.clock()
        account, quote, problems = None, None, []
        try:
            account = self.broker.account()
            quote = self.broker.quotes([req.symbol]).get(req.symbol)
        except BrokerError as exc:
            problems.append(f"broker unavailable: {exc}")
        halted = self._loss_controls(account, now) if account else ""
        reasons = problems + validate(req, self.settings, self.limits, account, quote, self.ledger.unresolved(),
                                      self.ledger.buys_on(now.astimezone(ET).date(), self.mode), now, halted)
        if reasons:
            ref = self.ledger.create(req, self.mode, BLOCKED, "; ".join(reasons))
            return ExecutionResult(req.decision_id, BLOCKED, ref, reasons)

        ref = self.ledger.create(req, self.mode, PENDING)
        if self.mode == "dry_run":
            self.ledger.update(ref, DRY_RUN, "dry run: validated, not sent")
            return ExecutionResult(req.decision_id, DRY_RUN, ref)
        try:
            bo = self.broker.submit(req, ref)
            self.ledger.update(ref, SUBMITTED, broker=bo)
        except BrokerNotSent as exc:
            self.ledger.update(ref, NOT_SENT, str(exc))
        except BrokerRejected as exc:
            self.ledger.update(ref, REJECTED, str(exc))
        except Exception as exc:  # noqa: BLE001 - any other outcome is ambiguous by definition
            self.ledger.update(ref, UNKNOWN, f"{type(exc).__name__}: {exc}")
        row = self._refresh(self.ledger.get(ref))
        return ExecutionResult(req.decision_id, row["state"], ref, [row["reason"]] if row["reason"] else [],
                               row["broker_id"], row["filled_quantity"])

    def resolve_unresolved(self) -> list[str]:
        """Look up every unresolved order at the broker. Never resubmits."""
        return [f"{r['symbol']} {r['side']} {r['ref_id'][:8]}: {r['state']} -> {n['state']}"
                for r in self.ledger.unresolved()
                if (n := self._refresh(r))["state"] != r["state"]]

    def _refresh(self, row: dict) -> dict:
        if row["state"] in TERMINAL:
            return row
        try:
            bo = self.broker.order_by_ref(row["ref_id"])
        except BrokerError as exc:
            self.ledger.log("lookup_failed", {"error": str(exc)}, row["ref_id"])
            return row
        if bo is None:
            if row["state"] in (PENDING, SUBMITTED):
                self.ledger.update(row["ref_id"], UNKNOWN, "broker has no order with this ref_id; not resubmitted")
        elif bo.ledger_state != row["state"] or bo.filled_quantity != row["filled_quantity"]:
            self.ledger.update(row["ref_id"], bo.ledger_state, broker=bo)
        return self.ledger.get(row["ref_id"])

    def owner_mark_not_placed(self, ref_id: str, confirmation: str) -> None:
        """The owner confirms an UNKNOWN order never reached the broker."""
        if confirmation.strip() != OWNER_NOT_PLACED_PHRASE:
            raise ValueError(f'needs the exact confirmation "{OWNER_NOT_PLACED_PHRASE}"')
        row = self.ledger.get(ref_id)
        if row is None or row["state"] != UNKNOWN:
            raise ValueError("only an UNKNOWN order can be marked not placed")
        self.ledger.update(ref_id, NOT_SENT, "owner confirmed the order does not exist at the broker")

    # --- risk state ----------------------------------------------------------
    def _loss_controls(self, account: AccountState, now: datetime) -> str:
        """Daily loss halts buys; a drawdown from the high-water mark engages the kill switch."""
        al = self.settings.account_limits
        day = now.astimezone(ET).date().isoformat()
        start = self.ledger.get_meta(f"day_start_value:{self.mode}:{day}")
        if start is None:
            start = account.total_value
            self.ledger.set_meta(f"day_start_value:{self.mode}:{day}", start)
        hwm = max(self.ledger.get_meta(f"high_water:{self.mode}", 0.0), account.total_value)
        self.ledger.set_meta(f"high_water:{self.mode}", hwm)
        if hwm > 0 and account.total_value < hwm * (1 - al.drawdown_review_pct):
            engage_kill_switch(self.settings, f"drawdown {1 - account.total_value / hwm:.1%} from high-water "
                                              f"${hwm:,.2f} (limit {al.drawdown_review_pct:.0%})", by="execution")
        if start > 0 and account.total_value < start * (1 - al.daily_loss_limit_pct):
            return f"daily loss {1 - account.total_value / start:.2%} exceeds {al.daily_loss_limit_pct:.0%}"
        return ""

    # --- health, reconciliation, halt ------------------------------------------
    def reconcile(self, account: AccountState) -> list[str]:
        """Broker positions must equal the baseline plus the ledger's fills."""
        baseline = self.ledger.get_meta(f"baseline:{self.mode}")
        if baseline is None:
            self.ledger.set_meta(f"baseline:{self.mode}", {"positions": account.positions,
                                                           "at": account.fetched_at.isoformat()})
            self.ledger.log("baseline", {"mode": self.mode, "positions": account.positions})
            return []
        expected = dict(baseline["positions"])
        for r in self.ledger.orders():
            if r["mode"] == self.mode and r["filled_quantity"]:
                sign = 1 if r["side"] == "buy" else -1
                expected[r["symbol"]] = expected.get(r["symbol"], 0.0) + sign * r["filled_quantity"]
        problems = []
        for sym in sorted(set(expected) | set(account.positions)):
            want, have = expected.get(sym, 0.0), account.positions.get(sym, 0.0)
            if abs(want - have) > 1e-6:
                problems.append(f"{sym}: broker holds {have:g}, ledger expects {want:g}")
        return problems

    def health_check(self) -> HealthReport:
        """Startup / periodic check. Engages the kill switch on failed reconciliation."""
        report = HealthReport(ok=True)
        report.resolved = self.resolve_unresolved()
        now = self.clock()
        for r in self.ledger.unresolved():
            if r["state"] == UNKNOWN or now - datetime.fromisoformat(r["updated_at"]) > timedelta(
                    minutes=STALE_UNRESOLVED_MINUTES):
                report.stale_unresolved.append(f"{r['symbol']} {r['side']} {r['ref_id'][:8]} is {r['state']}")
        try:
            account = self.broker.account()
        except BrokerError as exc:
            report.problems.append(f"broker unavailable: {exc}")
            account = None
        if account is not None:
            mismatches = self.reconcile(account)
            if mismatches:
                engage_kill_switch(self.settings, "reconciliation failed: " + "; ".join(mismatches), by="execution")
                report.problems += mismatches
        ks = kill_switch_status(self.settings)
        if ks.engaged:
            report.problems.append(f"kill switch engaged ({ks.reason})")
        report.ok = not report.problems and not report.stale_unresolved
        return report

    def halt(self, reason: str) -> list[str]:
        """Kill switch: block new orders and cancel every open order the ledger knows."""
        engage_kill_switch(self.settings, reason, by="execution")
        out = []
        for r in self.ledger.unresolved():
            if r["state"] in (OPEN, PARTIALLY_FILLED, SUBMITTED) and r["broker_id"]:
                try:
                    bo = self.broker.cancel(r["broker_id"])
                    self.ledger.update(r["ref_id"], bo.ledger_state, "cancelled by halt", broker=bo)
                    out.append(f"{r['symbol']} {r['ref_id'][:8]}: {bo.ledger_state}")
                except BrokerError as exc:
                    out.append(f"{r['symbol']} {r['ref_id'][:8]}: cancel failed ({exc})")
        return out
