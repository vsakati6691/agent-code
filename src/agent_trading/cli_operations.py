"""Daily reports, account reconciliation, paper simulation and existing kill-switch commands."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from .cli_common import _account, _journal, _load
from .config import Settings


def cmd_daily(settings: Settings, args) -> int:
    from .daily import run_daily, write

    text, ctx = run_daily(settings, args.as_of, run_paper=not args.no_paper, label=args.label or "")
    print(f"Run log: {ctx.manifest_path}")
    if ctx.missed_run:
        print(f"WARNING: MISSED RUN: {ctx.missed_run}")
    if ctx.spec_warning:
        print(f"WARNING: {ctx.spec_warning}")
    path = write(settings, text, args.as_of, args.label or "")
    if ctx.coverage:
        c = ctx.coverage
        print(
            f"Strategy A: scanned {c['scanned']}/{c['expected']} constituents ({c['ratio']:.1%}); "
            f"{len(ctx.scan.actionable) if ctx.scan else 0} actionable"
        )
    for d in ctx.desk:
        print(f"Strategy B: {d.symbol:<5} {d.action} ({d.confidence})")
    for e in ctx.paper_events:
        print(f"Paper: {e}")
    for w in ctx.paper_warnings:
        print(f"Paper WARNING: {w}")
    print(f"Report written: {path}")
    return 0


def cmd_account(settings: Settings, args) -> int:
    from .account import SnapshotError, import_snapshot

    if args.action == "import":
        try:
            snap, problems = import_snapshot(settings, Path(args.path))
        except (SnapshotError, ValueError) as exc:
            print(f"Snapshot rejected: {exc}")
            return 2
    else:
        result = _account(settings)
        if result is None:
            print("No account snapshot imported.")
            return 1
        snap, problems = result
    print(f"{snap.nickname or 'account'} ••{snap.account_last4} as of {snap.fetched_at}")
    print(f"  value ${snap.total_value:,.2f}  cash ${snap.cash:,.2f}  buying power ${snap.buying_power:,.2f}")
    print(f"  positions {len(snap.positions)}  open orders {len(snap.open_orders)}")
    print("  status: " + ("verified" if not problems else "NOT VERIFIED: " + "; ".join(problems)))
    return 0 if not problems else 2


def cmd_paper(settings: Settings, args) -> int:
    """Paper status (positions marked to the latest cached close). The paper
    broker itself runs inside `daily`."""
    from .paper import PaperBroker

    broker = PaperBroker(settings, _journal(settings))
    held = broker.journal.open_trades()
    args.symbols = sorted(set(held["symbol"])) if not held.empty else []
    bars = _load(settings, args)[1].bars if args.symbols else {}
    positions = broker.positions(bars, args.as_of)
    pending = broker.orders("pending")
    s = broker.journal.summary(settings.paper_starting_equity, settings.risk.stop_risk_buffer)
    cash = broker.journal.cash(settings.paper_starting_equity)
    mv = float(positions["market_value"].sum()) if not positions.empty else 0.0
    print(
        f"Paper equity ${cash + mv:,.2f} (cash ${cash:,.2f} + positions ${mv:,.2f}) · "
        f"realized P&L ${s['realized_pnl']:,.2f} · planned open risk ${s['open_risk']:,.2f}"
    )
    with pd.option_context("display.width", 160, "display.float_format", "{:.2f}".format):
        print("\nOpen positions:\n" + ("none" if positions.empty else positions.to_string(index=False)))
        cols = ["id", "created_date", "symbol", "side", "quantity", "ref_price", "stop_price", "reason"]
        print("\nPending orders:\n" + ("none" if pending.empty else pending[cols].to_string(index=False)))
    return 0


def cmd_kill_switch(settings: Settings, args) -> int:
    """Persistent kill switch for live tickets. Engaging is always allowed;
    releasing needs the owner's exact confirmation phrase."""
    from . import killswitch

    if args.action == "engage":
        st = killswitch.engage(settings, args.reason or "engaged by the owner", by="owner")
    elif args.action == "release":
        try:
            st = killswitch.release(settings, args.confirm or "")
        except ValueError as exc:
            print(f"Not released: {exc}", file=sys.stderr)
            return 2
    else:
        st = killswitch.status(settings)
    print(
        f"Kill switch: {'ENGAGED' if st.engaged else 'off'}"
        + (f" since {st.engaged_at} by {st.by}: {st.reason}" if st.engaged else "")
    )
    return 0
