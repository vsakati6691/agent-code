"""Command-line entry point: python -m agent_trading <command>."""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from .config import ConfigError, Settings, get_api_key, load_settings
from .logging_setup import setup_logging
from .risk import ProposedOrder, RiskViolation, check_new_trade_risk, check_order

log = logging.getLogger("agent_trading")


def _service(settings: Settings, with_client: bool):
    from .data.alphavantage import AlphaVantageClient
    from .data.service import MarketDataService

    client = None
    if with_client:
        client = AlphaVantageClient(get_api_key(), pause_seconds=settings.data.request_pause_seconds)
    return MarketDataService(settings, client)


def _journal(settings: Settings):
    from .journal import Journal

    return Journal(settings.resolve(settings.paths.journal_db))


def _symbols(settings: Settings, arg: list[str] | None) -> list[str]:
    return [s.upper() for s in arg] if arg else settings.symbols


def _fmt_metrics(m: dict) -> str:
    keys = ["start", "end", "bars", "final_equity", "total_return", "cagr", "sharpe", "max_drawdown",
            "trades", "win_rate", "profit_factor", "exposure", "total_costs"]
    lines = []
    for k in keys:
        v = m.get(k)
        if isinstance(v, float) and k in ("total_return", "cagr", "max_drawdown", "win_rate", "exposure"):
            v = f"{v:+.2%}"
        elif isinstance(v, float):
            v = f"{v:.3f}"
        lines.append(f"  {k:<14} {v}")
    return "\n".join(lines)


# ------------------------------------------------------------------ commands

def cmd_fetch(settings: Settings, args) -> int:
    from .data.rates import refresh_rates

    svc = _service(settings, with_client=True)
    status = svc.refresh(_symbols(settings, args.symbols), args.as_of)
    svc.refresh_earnings(args.as_of)
    if refresh_rates(settings, svc.client, args.as_of):
        print("T-bill rates updated")
    for sym, msg in status.items():
        print(f"{sym:<6} {msg}")
    print(f"API calls used this run: {svc.client.calls_made}")
    return 0


def cmd_import_csv(settings: Settings, args) -> int:
    from .data.service import import_csv

    n = import_csv(settings, args.symbol.upper(), Path(args.path))
    print(f"{args.symbol.upper()}: cache now holds {n} bars")
    return 0


def cmd_import_robinhood(settings: Settings, args) -> int:
    from .data.service import import_robinhood

    for path in args.paths:
        for sym, n in import_robinhood(settings, Path(path)).items():
            print(f"{sym:<6} cache now holds {n} bars")
    return 0


def _load(settings: Settings, args):
    svc = _service(settings, with_client=False)
    loaded = svc.load(_symbols(settings, getattr(args, "symbols", None)), args.as_of)
    for reason in loaded.rejected.values():
        log.warning("Rejected: %s", reason)
    return svc, loaded


def cmd_screen(settings: Settings, args) -> int:
    from .screen import run_screen

    _, loaded = _load(settings, args)
    table = run_screen(loaded.bars, settings)
    if table.empty:
        print("No valid data. Run `fetch` first.")
        return 1
    cols = ["close", "change_pct", "momentum", "rsi", "atr_pct", "uptrend", "entry_signal", "exit_signal", "liquid"]
    with pd.option_context("display.width", 160, "display.float_format", "{:.3f}".format):
        print(table[cols])
    return 0


def cmd_report(settings: Settings, args) -> int:
    from .report import build_daily_report, write_report
    from .screen import run_screen

    status = None
    if not args.no_fetch:
        svc = _service(settings, with_client=True)
        status = svc.refresh(settings.symbols, args.as_of)
        svc.refresh_earnings(args.as_of)
    svc, loaded = _load(settings, args)
    text = build_daily_report(
        settings, loaded, run_screen(loaded.bars, settings), svc.earnings(args.as_of),
        _journal(settings), args.as_of, status, _account(settings),
    )
    path = write_report(settings, text, args.as_of)
    print(f"Report written: {path}")
    return 0


def _account(settings: Settings):
    from .account import load_saved_snapshot, verify_snapshot

    snap = load_saved_snapshot(settings)
    return None if snap is None else (snap, verify_snapshot(snap, settings))


def cmd_universe(settings: Settings, args) -> int:
    from .data.universe import UniverseError, import_universe, load_universe, universe_problems

    if args.action == "import":
        try:
            u = import_universe(settings, Path(args.path))
        except (UniverseError, ValueError, KeyError) as exc:
            print(f"Constituent list rejected: {exc}")
            return 2
    else:
        u = load_universe(settings)
        if u is None:
            print("No constituent list imported.")
            return 1
    print(f"{len(u.tickers)} constituents as of {u.as_of} ({u.source})")
    if u.excluded:
        print("Excluded rows: " + "; ".join(u.excluded))
    problems = universe_problems(u, settings, args.as_of)
    for p in problems:
        print(f"WARNING: {p}")
    if args.action == "symbols":
        print(" ".join(u.tickers))
    return 0 if not problems else 2


def cmd_snapshot(settings: Settings, args) -> int:
    from .data.snapshots import SnapshotDataError, import_snapshot_files

    try:
        snap = import_snapshot_files(settings, args.kind, [Path(p) for p in args.paths], merge=args.merge)
    except (SnapshotDataError, ValueError, KeyError) as exc:
        print(f"Snapshot rejected: {exc}")
        return 2
    print(f"{args.kind}: {len(snap.table)} rows stored ({snap.source})")
    return 0


def cmd_daily(settings: Settings, args) -> int:
    from .daily import run_daily, write

    text, ctx = run_daily(settings, args.as_of, run_paper=not args.no_paper)
    path = write(settings, text, args.as_of, args.label or "")
    if ctx.coverage:
        c = ctx.coverage
        print(f"Strategy A: scanned {c['scanned']}/{c['expected']} constituents ({c['ratio']:.1%}); "
              f"{len(ctx.scan.actionable) if ctx.scan else 0} actionable")
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
    from .paper import PaperBroker
    from .screen import run_screen

    svc, loaded = _load(settings, args)
    broker = PaperBroker(settings, _journal(settings))
    if args.action == "run":
        if not loaded.bars:
            print("No valid market data; paper run skipped (fail-safe).")
            return 2
        result = broker.run(loaded.bars, run_screen(loaded.bars, settings), svc.earnings(args.as_of), args.as_of)
        for line in result.events:
            print(line)
        for line in result.warnings:
            print(f"WARNING: {line}")
        if not result.events:
            print("No fills, stops, or new orders.")
        return 0
    positions = broker.positions(loaded.bars, args.as_of)
    pending = broker.orders("pending")
    s = broker.journal.summary(settings.paper_starting_equity, settings.risk.stop_risk_buffer)
    cash = broker.journal.cash(settings.paper_starting_equity)
    mv = float(positions["market_value"].sum()) if not positions.empty else 0.0
    print(f"Paper equity ${cash + mv:,.2f} (cash ${cash:,.2f} + positions ${mv:,.2f}) · "
          f"realized P&L ${s['realized_pnl']:,.2f} · planned open risk ${s['open_risk']:,.2f}")
    with pd.option_context("display.width", 160, "display.float_format", "{:.2f}".format):
        print("\nOpen positions:\n" + ("none" if positions.empty else positions.to_string(index=False)))
        cols = ["id", "created_date", "symbol", "side", "quantity", "ref_price", "stop_price", "reason"]
        print("\nPending orders:\n" + ("none" if pending.empty else pending[cols].to_string(index=False)))
    return 0


def _backtest_bars(settings: Settings, args) -> dict:
    """Backtests validate completeness but not freshness (history may be older).

    Old frozen stretches (pre-merger shells, thin pre-listing trading) are
    trimmed off; a recent freeze excludes the symbol.
    """
    from .data.cache import read_cache
    from .data.validation import DataQualityError, trim_frozen_history, validate_bars

    cache_dir = settings.resolve(settings.data.cache_dir)
    since = getattr(args, "since", None)
    bars = {}
    for sym in _symbols(settings, args.symbols):
        df = read_cache(cache_dir, sym)
        try:
            if df is None or df.empty:
                raise DataQualityError(f"{sym}: no data")
            if since is not None:
                df = df.loc[str(since):]
            df, note = trim_frozen_history(df, sym)
            if note:
                log.warning("%s", note)
            bars[sym] = validate_bars(df, sym, df.index[-1].date(), 0, settings.data.min_history_bars)
        except DataQualityError as exc:
            log.warning("Excluded from backtest: %s", exc)
    return bars


def cmd_backtest(settings: Settings, args) -> int:
    from .backtest import in_out_of_sample, run_backtest
    from .report import save_backtest

    bars = _backtest_bars(settings, args)
    if not bars:
        print("No usable data. Run `fetch` or `import-csv` first.")
        return 1
    full = run_backtest(bars, settings)
    print(f"Full period ({len(bars)} symbols, slippage {settings.costs.slippage_bps} bps/side):")
    print(_fmt_metrics(full.metrics))
    try:
        ins, oos = in_out_of_sample(bars, settings)
        print("\nIn-sample:")
        print(_fmt_metrics(ins.metrics))
        print("\nOut-of-sample (the number that matters):")
        print(_fmt_metrics(oos.metrics))
    except ValueError as exc:
        print(f"\nOut-of-sample split skipped: {exc}")
    reports = settings.resolve(settings.paths.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    full.trades_frame().to_csv(reports / "backtest_trades.csv", index=False)
    save_backtest(settings, "full period", full.metrics, full.equity)
    print(f"\nTrades: {reports / 'backtest_trades.csv'}")
    return 0


def cmd_walkforward(settings: Settings, args) -> int:
    from .backtest import walk_forward
    from .report import save_backtest

    bars = _backtest_bars(settings, args)
    try:
        result = walk_forward(bars, settings)
    except ValueError as exc:
        print(f"Walk-forward not possible: {exc}")
        return 1
    for f in result.folds:
        print(f"train {f['train']}  test {f['test']}  params {f['chosen']}  "
              f"train sharpe {f['train_sharpe']:.2f}  test return {f['test_return']:+.2%}  trades {f['test_trades']}")
    print("\nStitched out-of-sample result:")
    print(_fmt_metrics(result.metrics))
    save_backtest(settings, "walk-forward OOS", result.metrics, result.equity, {"folds": result.folds})
    return 0


def cmd_evaluate(settings: Settings, args) -> int:
    from .backtest.evaluation import evaluate, holdout_uses, save

    if args.holdout and holdout_uses(settings) > 0:
        print(f"Note: the holdout has already been evaluated {holdout_uses(settings)} time(s); "
              "repeated use turns it into a tuning set.")
    from .data.rates import load_monthly_rates, refresh_rates

    if settings.evaluation.cash_interest and load_monthly_rates(settings) is None:
        try:
            refresh_rates(settings, _service(settings, with_client=True).client, args.as_of)
        except ConfigError as exc:
            print(f"T-bill rates unavailable ({exc}); cash will earn no interest in this evaluation.")
    bars = _backtest_bars(settings, args)
    try:
        rep = evaluate(bars, settings, use_holdout=args.holdout)
    except ValueError as exc:
        print(f"Evaluation not possible: {exc}")
        return 1
    md, csv = save(rep, settings, args.as_of)
    for p in rep.periods:
        m = p.strategy
        spy = next((v for k, v in p.benchmarks.items() if "buy & hold" in k and "Equal" not in k), {})
        print(f"{p.name:<30} {p.start}..{p.end}  return {m.get('total_return', 0):+.2%}  sharpe {m.get('sharpe', 0):.2f}  "
              f"maxDD {m.get('max_drawdown', 0):+.2%}  trades {m.get('trades')}  | SPY {spy.get('total_return', float('nan')):+.2%}")
        for w in p.warnings:
            print(f"    ! {w}")
    if rep.sensitivity_summary:
        ss = rep.sensitivity_summary
        print(f"Sensitivity: {ss['share_positive_sharpe']:.0%} of {ss['combinations']} combos Sharpe>0; "
              f"fragile={ss['fragile']}")
    print(f"\nReport: {md}\nTrades: {csv}")
    return 0


def cmd_evaluate_desk(settings: Settings, args) -> int:
    """Strategy B rules on history: train + validation only (holdout untouched)."""
    from .backtest.benchmarks import buy_and_hold
    from .backtest.desk_backtest import run_desk_backtest
    from .backtest.evaluation import make_splits
    from .backtest.metrics import compute_metrics
    from .backtest.stats import block_bootstrap, warnings_for
    from .data.rates import daily_cash_rate, load_monthly_rates

    d = settings.desk
    args.symbols = list(dict.fromkeys([*d.symbols, d.underlying, d.nvda_benchmark]))
    bars = _backtest_bars(settings, args)
    rates = load_monthly_rates(settings)
    lines = ["# Strategy B (desk) backtest", "",
             "> Rules from strategies/desk.py on daily bars; costs and RiskEngine limits as configured. "
             "Event and earnings blackouts are NOT modelled historically. Holdout (last 20%) untouched. "
             "**Trading P&L only**: idle cash earns nothing here, so returns and Sharpe measure the rules, "
             "not T-bill interest (with tiny positions, interest would dominate).", ""]
    rates = None  # deliberately: isolate the rules' edge from cash interest
    groups = [[d.leveraged_long], [d.leveraged_inverse], ["NVDA"], [d.bitcoin_instrument],
              [d.leveraged_long, d.leveraged_inverse, "NVDA", d.bitcoin_instrument]]
    for syms in groups:
        syms = [s for s in syms if s in bars]
        if not syms:
            continue
        dates = sorted(set().union(*(bars[s].index for s in syms)))
        try:
            sp = make_splits(dates, 200, settings.evaluation.train_fraction, settings.evaluation.validation_fraction)
        except ValueError as exc:
            lines.append(f"## {'+'.join(syms)}: skipped ({exc})\n")
            continue
        cash = daily_cash_rate(rates, pd.DatetimeIndex(dates))
        lines += [f"## {' + '.join(syms)}", "",
                  "| Period | Return | CAGR | Sharpe (95% CI) | Max DD | Trades | Win % | Exposure | QQQ B&H | "
                  + ("Instrument B&H |" if len(syms) == 1 else "|"),
                  "|---|---|---|---|---|---|---|---|---|" + ("---|" if len(syms) == 1 else "")]
        for name, (start, end) in [("train", sp.train), ("validation", sp.validation)]:
            res = run_desk_backtest(bars, settings, syms, start, end, cash)
            m = res.metrics
            boot = block_bootstrap(res.equity.pct_change(), 500, 20)
            ci = "n/a" if boot.get("insufficient") else f"{boot['sharpe_ci'][0]:.2f} to {boot['sharpe_ci'][1]:.2f}"
            qqq = compute_metrics(buy_and_hold(bars[d.underlying], start, end, 1000, settings.costs.per_side), [], 1000)
            row = (f"| {name} {start.date()}..{end.date()} | {m['total_return']:+.1%} | {(m['cagr'] or 0):+.1%} | "
                   f"{m['sharpe']:.2f} ({ci}) | {m['max_drawdown']:+.1%} | {m['trades']} | {m['win_rate']:.0%} | "
                   f"{m['exposure']:.0%} | {qqq['total_return']:+.1%} |")
            if len(syms) == 1:
                own = compute_metrics(buy_and_hold(bars[syms[0]], start, end, 1000, settings.costs.per_side), [], 1000)
                row += f" {own['total_return']:+.1%} (DD {own['max_drawdown']:+.0%}) |"
            lines.append(row)
            for w in warnings_for(m, boot, settings.evaluation.min_trades):
                lines.append(f"|  ⚠ {w} |" + " |" * (8 if len(syms) == 1 else 7))
        lines.append("")
    text = "\n".join(lines)
    reports = settings.resolve(settings.paths.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"desk_backtest_{args.as_of}.md"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nReport: {path}")
    return 0


def cmd_journal(settings: Settings, args) -> int:
    j = _journal(settings)
    equity = settings.paper_starting_equity + j.realized_pnl()
    if args.action == "open":
        cash = j.cash(settings.paper_starting_equity)
        check_order(ProposedOrder(args.symbol, "buy", args.quantity, args.entry), settings, cash)
        buffer = settings.risk.stop_risk_buffer
        risk = check_new_trade_risk(equity, j.open_risk(buffer), args.quantity, args.entry, args.stop, settings.risk)
        tid = j.open_trade(args.symbol, args.quantity, args.entry, args.stop, args.as_of, args.thesis or "")
        print(f"Opened paper trade #{tid}: {args.symbol.upper()} x{args.quantity:g} @ {args.entry} stop {args.stop} (risk ${risk:.2f})")
    elif args.action == "close":
        open_df = j.open_trades()
        match = open_df[open_df["id"] == args.id] if not open_df.empty else open_df
        if match.empty:
            print(f"No open trade #{args.id}")
            return 1
        row = match.iloc[0]
        check_order(ProposedOrder(row.symbol, "sell", row.quantity, args.price, held_quantity=row.quantity), settings, 0)
        j.close_trade(args.id, args.price, args.as_of, args.reason or "")
        print(f"Closed paper trade #{args.id} @ {args.price}")
    else:
        df = j.trades()
        print("No trades yet." if df.empty else df.drop(columns=["mode", "side"]).to_string(index=False))
        s = j.summary(settings.paper_starting_equity, settings.risk.stop_risk_buffer)
        print(f"\nEquity (realized) ${s['equity_realized']:.2f} · open risk ${s['open_risk']:.2f} "
              f"(limit ${equity * settings.risk.max_open_risk_pct:.2f})")
    return 0


def cmd_dashboard(settings: Settings, args) -> int:
    from .report import build_dashboard, load_backtest

    reports = settings.resolve(settings.paths.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / "dashboard.html"
    path.write_text(build_dashboard(settings, _journal(settings), load_backtest(settings)), encoding="utf-8")
    print(f"Dashboard written: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agent-trading", description="Research and paper-trading toolkit (no live trading).")
    p.add_argument("--config", default="config/settings.yaml")
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD (default: today)")
    p.add_argument("--log-level", default="INFO")
    sub = p.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="update the local price cache (uses API requests)")
    f.add_argument("--symbols", nargs="*")
    f.set_defaults(func=cmd_fetch)

    i = sub.add_parser("import-csv", help="merge a CSV of daily bars (date,open,high,low,close,volume) into the cache")
    i.add_argument("symbol")
    i.add_argument("path")
    i.set_defaults(func=cmd_import_csv)

    ir = sub.add_parser("import-robinhood", help="merge saved Robinhood MCP get_equity_historicals JSON into the cache")
    ir.add_argument("paths", nargs="+")
    ir.set_defaults(func=cmd_import_robinhood)

    s = sub.add_parser("screen", help="screen cached data")
    s.add_argument("--symbols", nargs="*")
    s.set_defaults(func=cmd_screen)

    r = sub.add_parser("report", help="fetch data and write the daily research report")
    r.add_argument("--no-fetch", action="store_true", help="use cached data only")
    r.set_defaults(func=cmd_report)

    b = sub.add_parser("backtest", help="full-period plus in-sample/out-of-sample backtest")
    b.add_argument("--symbols", nargs="*")
    b.add_argument("--since", type=date.fromisoformat, help="ignore history before YYYY-MM-DD")
    b.set_defaults(func=cmd_backtest)

    w = sub.add_parser("walkforward", help="walk-forward optimisation and out-of-sample evaluation")
    w.add_argument("--symbols", nargs="*")
    w.add_argument("--since", type=date.fromisoformat, help="ignore history before YYYY-MM-DD")
    w.set_defaults(func=cmd_walkforward)

    ev = sub.add_parser("evaluate", help="train/validation(/holdout) evaluation with benchmarks, regimes, bootstrap, sensitivity")
    ev.add_argument("--symbols", nargs="*")
    ev.add_argument("--holdout", action="store_true", help="also evaluate the untouched holdout (logged; use sparingly)")
    ev.add_argument("--since", type=date.fromisoformat, help="ignore history before YYYY-MM-DD")
    ev.set_defaults(func=cmd_evaluate)

    ed = sub.add_parser("evaluate-desk", help="backtest Strategy B rules (train + validation; holdout untouched)")
    ed.add_argument("--since", type=date.fromisoformat, help="ignore history before YYYY-MM-DD")
    ed.set_defaults(func=cmd_evaluate_desk, symbols=None)

    j = sub.add_parser("journal", help="paper-trade journal")
    jsub = j.add_subparsers(dest="action", required=True)
    jo = jsub.add_parser("open")
    jo.add_argument("symbol")
    jo.add_argument("quantity", type=float)
    jo.add_argument("entry", type=float)
    jo.add_argument("stop", type=float)
    jo.add_argument("--thesis")
    jc = jsub.add_parser("close")
    jc.add_argument("id", type=int)
    jc.add_argument("price", type=float)
    jc.add_argument("--reason")
    jsub.add_parser("list")
    j.set_defaults(func=cmd_journal)

    d = sub.add_parser("dashboard", help="write the HTML performance dashboard")
    d.set_defaults(func=cmd_dashboard)

    pp = sub.add_parser("paper", help="simulated paper broker (never touches a real account)")
    psub = pp.add_subparsers(dest="action", required=True)
    psub.add_parser("run", help="fill pending paper orders, check stops, queue new orders from today's signals")
    psub.add_parser("status", help="paper positions, P&L and pending orders")
    pp.set_defaults(func=cmd_paper)

    u = sub.add_parser("universe", help="S&P 500 constituents (dynamic, from SPY holdings)")
    usub = u.add_subparsers(dest="action", required=True)
    ui = usub.add_parser("import", help="validate and store a saved Financial Datasets get_index_fund(SPY) JSON")
    ui.add_argument("path")
    usub.add_parser("show")
    usub.add_parser("symbols", help="print the tickers (for data collection)")
    u.set_defaults(func=cmd_universe)

    sn = sub.add_parser("snapshot", help="import a saved MCP payload (fundamentals, quotes, news, filings, econ)")
    sn.add_argument("kind", choices=["fundamentals", "quotes", "news", "filings", "econ"])
    sn.add_argument("paths", nargs="+")
    sn.add_argument("--merge", action="store_true", help="append to today's snapshot instead of replacing it")
    sn.set_defaults(func=cmd_snapshot)

    dl = sub.add_parser("daily", help="two-strategy cycle: S&P 500 scan, focused desk, paper broker, report")
    dl.add_argument("--no-paper", action="store_true", help="report only; do not run the paper broker")
    dl.add_argument("--label", choices=["premarket", "intraday", "postclose"], help="report file suffix")
    dl.set_defaults(func=cmd_daily)

    a = sub.add_parser("account", help="read-only broker account snapshot")
    asub = a.add_subparsers(dest="action", required=True)
    ai = asub.add_parser("import", help="validate and store a snapshot JSON saved from the Robinhood MCP")
    ai.add_argument("path")
    asub.add_parser("show")
    a.set_defaults(func=cmd_account)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    setup_logging(settings.resolve(settings.paths.logs_dir), args.log_level)
    try:
        return args.func(settings, args)
    except (ConfigError, RiskViolation) as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
