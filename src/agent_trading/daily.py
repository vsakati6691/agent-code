"""Daily research orchestration: validated inputs, strategy signals, paper simulation, manual tickets and reports."""

from __future__ import annotations

from datetime import date

import pandas as pd

from . import regime as regime_mod
from .config import Settings
from .daily_context import DISCLAIMER as DISCLAIMER
from .daily_context import DailyContext as DailyContext
from .daily_inputs import _earnings_lookup as _earnings_lookup
from .daily_intents import _desk_intents as _desk_intents
from .daily_intents import _gtaa_intents as _gtaa_intents
from .daily_manifest import _write_manifest as _write_manifest
from .daily_report import _fmt as _fmt
from .daily_report import _pct as _pct
from .daily_report import _render_tickets as _render_tickets
from .daily_report import _table as _table
from .daily_report import render as render
from .daily_report import write as write
from .daily_tickets import _run_live as _run_live
from .data.service import MarketDataService
from .data.snapshots import high_impact_events, load_snapshot
from .data.universe import coverage, load_universe, universe_problems
from .journal import Journal
from .paper import Intent, PaperBroker
from .strategies.desk import Position, next_session, run_desk
from .strategies.scanner import run_scan


def run_daily(settings: Settings, as_of: date, run_paper: bool = True, label: str = "") -> tuple[str, DailyContext]:
    from .manifest import code_version, config_hash, missed_postclose

    ctx = DailyContext(as_of)
    ctx.code = code_version(settings.base_dir)
    ctx.config_hash = config_hash(settings)
    if label == "premarket" and (missed := missed_postclose(settings, as_of)) is not None:
        ctx.missed_run = (
            f"no post-close run log for {missed} (data/runs/{missed}_postclose_*.json): the scheduled "
            "post-close run did not run or did not finish. Tickets shown here may be stale, and that "
            "day's paper fills, stops and loss-limit checks did not happen. Check the scheduled task "
            "and rerun the post-close cycle."
        )
    svc = MarketDataService(settings)
    journal = Journal(settings.resolve(settings.paths.journal_db))

    # --- inputs
    universe = load_universe(settings)
    problems = universe_problems(universe, settings, as_of)
    ctx.universe_note = (
        "; ".join(problems)
        if problems
        else f"{len(universe.tickers)} constituents as of {universe.as_of} ({universe.source})"
    )
    snaps = {k: load_snapshot(settings, k) for k in ("fundamentals", "quotes", "news", "filings", "econ")}
    ctx.snapshots = snaps
    for k, s in snaps.items():
        if s is None:
            ctx.data_notes.append(f"{k}: not available")
        else:
            ctx.data_notes.append(
                f"{k}: {len(s.table)} rows from {s.source}, fetched {s.fetched_at:%Y-%m-%d %H:%M} UTC "
                f"({s.age_hours():.0f}h old)"
            )
    fund = (
        snaps["fundamentals"].table
        if snaps["fundamentals"] is not None and snaps["fundamentals"].age_hours() <= 72
        else None
    )
    quotes = snaps["quotes"].table if snaps["quotes"] is not None and snaps["quotes"].age_hours() <= 24 else None
    cal = svc.earnings(as_of)
    lookup = _earnings_lookup(fund, cal, as_of)

    # --- Strategy A
    sc = settings.scanner
    gtaa_assets = list(settings.gtaa.assets) if settings.gtaa.enabled else []
    desk_syms = list(
        dict.fromkeys(
            [*settings.desk.symbols, settings.desk.underlying, settings.desk.nvda_benchmark, sc.benchmark, *gtaa_assets]
        )
    )
    loaded_desk = svc.load(desk_syms, as_of)
    bench = loaded_desk.bars.get(sc.benchmark)
    if bench is not None:
        ctx.market = regime_mod.current(bench, settings.regime)
    if universe is not None and not problems:
        loaded = svc.load(universe.tickers, as_of)
        ctx.coverage = coverage(universe, list(loaded.bars), loaded.rejected)
        ctx.scan = run_scan(loaded.bars, settings, as_of, fund, quotes, cal.table if cal.available else None, bench)
    elif universe is not None:
        ctx.data_notes.append("Strategy A skipped: " + "; ".join(problems))

    # --- Strategy B
    open_df = journal.open_trades()
    positions = (
        {
            t.symbol: Position(t.quantity, t.entry_price, t.stop_price, date.fromisoformat(t.entry_date))
            for t in open_df.itertuples()
        }
        if not open_df.empty
        else {}
    )
    events = high_impact_events(snaps["econ"], next_session(as_of), settings.desk.event_blackout_days)
    ctx.desk_regime, ctx.desk = run_desk(loaded_desk.bars, settings, as_of, positions, events, lookup)

    # --- paper broker
    intents: list[Intent] = _desk_intents(ctx.desk)
    if gtaa_assets:
        from .strategies import gtaa as gtaa_mod

        ctx.gtaa = gtaa_mod.signals(loaded_desk.bars, pd.Timestamp(as_of), gtaa_assets, settings.gtaa.sma_months)
        cal_days = list(bench.index) if bench is not None else []
        ctx.gtaa_rebalance = gtaa_mod.is_rebalance_day(cal_days, as_of)
        if ctx.gtaa_rebalance:
            held_c = (
                set(open_df.loc[open_df["strategy"] == "C-gtaa", "symbol"])
                if not open_df.empty and "strategy" in open_df
                else set()
            )
            intents += _gtaa_intents(settings, ctx.gtaa, loaded_desk.bars, held_c)
    if ctx.scan is not None:
        for s in ctx.scan.actionable:
            intents.append(
                Intent(
                    s.ticker,
                    "buy",
                    s.entry_ref,
                    s.stop,
                    "A-scanner",
                    f"scanner rank {s.rank} (score {s.composite:.2f})",
                    s.composite,
                )
            )
        tbl = ctx.scan.table
        for sym in positions:
            if sym in tbl.index and sym not in settings.desk.symbols:
                row = tbl.loc[sym]
                if row["close"] < row["sma50"] or row["setup"] == "bearish":
                    intents.append(
                        Intent(
                            sym,
                            "sell",
                            float(row["close"]),
                            None,
                            "A-scanner",
                            "close below the 50-day SMA" if row["close"] < row["sma50"] else "setup turned bearish",
                        )
                    )
    all_bars = dict(loaded_desk.bars)
    if ctx.scan is not None:
        all_bars.update(loaded.bars)
    broker = PaperBroker(settings, journal)
    frozen = broker._meta("spec_config_hash")
    if run_paper and frozen is None:
        broker._set_meta("spec_config_hash", ctx.config_hash)
        broker._set_meta("spec_start_date", as_of.isoformat())
        frozen = ctx.config_hash
    if frozen is not None and frozen != ctx.config_hash:
        ctx.spec_warning = (
            f"configuration changed during the paper evaluation (frozen {frozen}, now {ctx.config_hash}); "
            "results after the change are a new experiment, not the same out-of-sample period"
        )
    if run_paper and all_bars:
        res = broker.run(all_bars, as_of, intents)
        ctx.paper_events, ctx.paper_warnings, ctx.proposals = res.events, res.warnings, res.new_orders
    ctx.status = broker.status(all_bars, as_of) if all_bars else None

    # --- live tickets (manual: written here, placed by the owner in the app)
    ctx.live = _run_live(settings, journal, ctx, loaded_desk.bars, all_bars, events, lookup, issue=run_paper)
    ctx.manifest_path = str(_write_manifest(settings, ctx, label, intents, broker, frozen))
    text = render(settings, ctx, journal, broker, all_bars)
    return text, ctx
