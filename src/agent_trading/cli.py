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
    svc = _service(settings, with_client=True)
    status = svc.refresh(_symbols(settings, args.symbols), args.as_of)
    svc.refresh_earnings(args.as_of)
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
        _journal(settings), args.as_of, status,
    )
    path = write_report(settings, text, args.as_of)
    print(f"Report written: {path}")
    return 0


def _backtest_bars(settings: Settings, args) -> dict:
    """Backtests validate completeness but not freshness (history may be older)."""
    from .data.cache import read_cache
    from .data.validation import DataQualityError, validate_bars

    cache_dir = settings.resolve(settings.data.cache_dir)
    bars = {}
    for sym in _symbols(settings, args.symbols):
        df = read_cache(cache_dir, sym)
        try:
            last = df.index[-1].date() if df is not None and not df.empty else args.as_of
            bars[sym] = validate_bars(df, sym, last, 0, settings.data.min_history_bars)
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


def cmd_journal(settings: Settings, args) -> int:
    j = _journal(settings)
    equity = settings.paper_starting_equity + j.realized_pnl()
    if args.action == "open":
        cash = j.cash(settings.paper_starting_equity)
        check_order(ProposedOrder(args.symbol, "buy", args.quantity, args.entry), settings, cash)
        risk = check_new_trade_risk(equity, j.open_risk(), args.quantity, args.entry, args.stop, settings.risk)
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
        s = j.summary(settings.paper_starting_equity)
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
    b.set_defaults(func=cmd_backtest)

    w = sub.add_parser("walkforward", help="walk-forward optimisation and out-of-sample evaluation")
    w.add_argument("--symbols", nargs="*")
    w.set_defaults(func=cmd_walkforward)

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
