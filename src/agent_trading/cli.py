"""Command-line parser and dispatch: python -m agent_trading <command>."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from .cli_common import _account as _account
from .cli_common import _backtest_bars as _backtest_bars
from .cli_common import _journal as _journal
from .cli_common import _load as _load
from .cli_common import _service as _service
from .cli_common import _symbols as _symbols
from .cli_common import log as log
from .cli_data import cmd_dividends as cmd_dividends
from .cli_data import cmd_fetch as cmd_fetch
from .cli_data import cmd_import_csv as cmd_import_csv
from .cli_data import cmd_import_robinhood as cmd_import_robinhood
from .cli_data import cmd_snapshot as cmd_snapshot
from .cli_data import cmd_universe as cmd_universe
from .cli_operations import cmd_account as cmd_account
from .cli_operations import cmd_daily as cmd_daily
from .cli_operations import cmd_kill_switch as cmd_kill_switch
from .cli_operations import cmd_paper as cmd_paper
from .cli_research import cmd_evaluate_desk as cmd_evaluate_desk
from .cli_research import cmd_evaluate_gtaa as cmd_evaluate_gtaa
from .cli_research import cmd_evaluate_scanner as cmd_evaluate_scanner
from .cli_research import cmd_tournament as cmd_tournament
from .config import ConfigError, load_settings
from .logging_setup import setup_logging
from .risk import RiskViolation


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agent-trading", description="Research and paper-trading toolkit (no live trading)."
    )
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

    ed = sub.add_parser("evaluate-desk", help="backtest Strategy B rules (train + validation; holdout untouched)")
    ed.add_argument("--since", type=date.fromisoformat, help="ignore history before YYYY-MM-DD")
    ed.set_defaults(func=cmd_evaluate_desk, symbols=None)

    es = sub.add_parser("evaluate-scanner", help="point-in-time backtest of Strategy A (holdout untouched)")
    es.add_argument("--top", type=int, default=10)
    es.add_argument("--since", type=date.fromisoformat, help="ignore history before YYYY-MM-DD")
    es.set_defaults(func=cmd_evaluate_scanner, symbols=None)

    eg = sub.add_parser(
        "evaluate-gtaa", help="backtest Strategy C (GTAA, total return): C0/C1/C2 variants vs benchmarks"
    )
    eg.add_argument("--since", type=date.fromisoformat, help="ignore history before YYYY-MM-DD")
    eg.set_defaults(func=cmd_evaluate_gtaa, symbols=None)

    pp = sub.add_parser("paper", help="simulated paper broker (never touches a real account)")
    psub = pp.add_subparsers(dest="action", required=True)
    psub.add_parser("status", help="paper positions, P&L and pending orders")
    pp.set_defaults(func=cmd_paper)

    u = sub.add_parser("universe", help="S&P 500 constituents (dynamic, from SPY holdings)")
    usub = u.add_subparsers(dest="action", required=True)
    ui = usub.add_parser("import", help="validate and store a saved Financial Datasets get_index_fund(SPY) JSON")
    ui.add_argument("path")
    usub.add_parser("show")
    usub.add_parser("symbols", help="print the tickers (for data collection)")
    uh = usub.add_parser("import-history", help="store historical get_index_fund(SPY, as_of=...) snapshots")
    uh.add_argument("paths", nargs="+")
    u.set_defaults(func=cmd_universe)

    sn = sub.add_parser("snapshot", help="import a saved MCP payload (fundamentals, quotes, news, filings, econ)")
    sn.add_argument("kind", choices=["fundamentals", "quotes", "news", "filings", "econ"])
    sn.add_argument("paths", nargs="+")
    sn.add_argument("--merge", action="store_true", help="append to today's snapshot instead of replacing it")
    sn.set_defaults(func=cmd_snapshot)

    dv = sub.add_parser("dividends", help="import cash dividends (Alpha Vantage DIVIDENDS JSON or ex_date,amount CSV)")
    dv.add_argument("symbol")
    dv.add_argument("path")
    dv.set_defaults(func=cmd_dividends)

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

    tn = sub.add_parser("tournament", help="strategy tournament: candidates vs benchmarks, walk-forward, registry")
    tn.add_argument("--no-test", action="store_true", help="selection only; leave the test period untouched")
    tn.set_defaults(func=cmd_tournament)

    k = sub.add_parser("kill-switch", help="persistent block on all live tickets (status | engage | release)")
    k.add_argument("action", choices=["status", "engage", "release"])
    k.add_argument("--reason", help="why it is engaged")
    k.add_argument("--confirm", help='release only: the exact phrase "I have reviewed the account"')
    k.set_defaults(func=cmd_kill_switch)
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
