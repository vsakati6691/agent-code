"""Run the existing reconciled account, hard-limit and kill-switch gates for manual tickets."""

from __future__ import annotations

from . import killswitch, order_gate
from . import live as live_mod
from .account import load_saved_snapshot
from .config import Settings
from .daily_context import DailyContext
from .daily_intents import _desk_intents, _gtaa_intents
from .journal import Journal
from .live import LiveLedger, LiveResult
from .paper import Intent
from .strategies.desk import run_desk


def _run_live(
    settings: Settings, journal: Journal, ctx: DailyContext, desk_bars, all_bars, events, lookup, issue: bool
) -> LiveResult:
    """Re-run the live strategies against the REAL account's positions and write tickets.

    Tickets are issued only by the main (post-close) cycle; other runs show the
    latest issued tickets without changing them."""
    ledger = LiveLedger(journal.path)
    snap = load_saved_snapshot(settings)
    res = live_mod.prepare(settings, ledger, snap, ctx.as_of, record=issue)
    if not res.enabled:
        return res
    if not issue or not res.verified:
        res.tickets_date, res.tickets = ledger.latest_tickets()
        if issue:
            res.warnings.append("no new tickets: the account snapshot is not verified")
        return res
    live_intents: list[Intent] = []
    if "B-desk" in settings.live.strategies:
        _, ctx.live_desk = run_desk(desk_bars, settings, ctx.as_of, res.positions, events, lookup)
        live_intents += _desk_intents(ctx.live_desk)
    if "C-gtaa" in settings.live.strategies and ctx.gtaa_rebalance:
        live_intents += _gtaa_intents(settings, ctx.gtaa, desk_bars, set(res.positions))
    if "A-scanner" in settings.live.strategies and ctx.scan is not None:
        live_intents += [
            Intent(s.ticker, "buy", s.entry_ref, s.stop, "A-scanner", f"scanner rank {s.rank}", s.composite)
            for s in ctx.scan.actionable
        ]
    res = live_mod.build_tickets(settings, res, snap, live_intents, all_bars)
    # final fail-closed gate: only approved tickets are ever written
    gate = order_gate.check_tickets(
        settings, res.tickets, snap, ctx.as_of, all_bars, res.status, issued_today=res.issued_today
    )
    if gate.engage_kill_switch:
        killswitch.engage(settings, gate.engage_kill_switch)
        res.warnings.append(
            f"KILL SWITCH ENGAGED: {gate.engage_kill_switch}. Review the account, then release it "
            "with `kill-switch release`"
        )
    res.warnings += [f"order gate blocked all tickets: {b}" for b in gate.blockers]
    res.skipped += [f"{t.symbol} ({t.side}): order gate: {why}" for t, why in gate.rejected if not gate.blockers]
    # append-only per ticket day: earlier same-day tickets may already be placed, so they are never replaced
    ledger.add_tickets(ctx.as_of, gate.approved)
    res.tickets = ledger.tickets_on(ctx.as_of)
    res.tickets_date = ctx.as_of.isoformat()
    return res
