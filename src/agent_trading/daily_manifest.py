"""Record the daily run manifest without changing its ledger or configuration evidence."""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .daily_context import DailyContext
from .paper import PaperBroker


def _write_manifest(settings: Settings, ctx: DailyContext, label: str, intents, broker: PaperBroker, frozen) -> Path:
    from .manifest import write_manifest

    scan = ctx.scan
    payload = {
        "as_of": ctx.as_of,
        "label": label,
        "mode": settings.mode,
        "code": ctx.code,
        "config_hash": ctx.config_hash,
        "frozen_spec_hash": frozen,
        "spec_start_date": broker._meta("spec_start_date"),
        "spec_warning": ctx.spec_warning or None,
        "missed_run": ctx.missed_run or None,
        "inputs": {
            k: (None if s is None else {"source": s.source, "fetched_at": s.fetched_at, "rows": len(s.table)})
            for k, s in ctx.snapshots.items()
        },
        "universe": ctx.universe_note,
        "coverage": ctx.coverage,
        "data_notes": ctx.data_notes,
        "scanner": None
        if scan is None
        else {
            "scanned": len(scan.table),
            "research_top": [
                {"ticker": s.ticker, "rank": s.rank, "score": s.composite, "setup": s.setup} for s in scan.research
            ],
            "actionable": [
                {
                    "ticker": s.ticker,
                    "entry_ref": s.entry_ref,
                    "stop": s.stop,
                    "target": s.target,
                    "evidence": s.evidence,
                    "risks": s.risks,
                }
                for s in scan.actionable
            ],
            "rejected": scan.rejected,
            "bearish": scan.bearish,
        },
        "desk": [
            {
                "symbol": d.symbol,
                "action": d.action,
                "confidence": d.confidence,
                "price": d.price,
                "price_date": d.price_date,
                "stop": d.stop,
                "reasons": d.reasons,
            }
            for d in ctx.desk
        ],
        "gtaa": {"rebalance_day": ctx.gtaa_rebalance, "signals": ctx.gtaa},
        "intents": [i.__dict__ for i in intents],
        "proposals": [p.__dict__ for p in ctx.proposals],
        "paper_events": ctx.paper_events,
        "paper_warnings": ctx.paper_warnings,
        "risk_status": None if ctx.status is None else ctx.status.__dict__,
        "live": None
        if ctx.live is None or not ctx.live.enabled
        else {
            "verified": ctx.live.verified,
            "account": ctx.live.account_note,
            "equity": ctx.live.equity,
            "cash": ctx.live.cash,
            "status": None if ctx.live.status is None else ctx.live.status.__dict__,
            "tickets_date": ctx.live.tickets_date,
            "tickets": [t.__dict__ for t in ctx.live.tickets],
            "skipped": ctx.live.skipped,
            "warnings": ctx.live.warnings,
            "previous_date": ctx.live.previous_date,
            "previous": ctx.live.previous,
        },
    }
    return write_manifest(settings, ctx.as_of, label, payload)
