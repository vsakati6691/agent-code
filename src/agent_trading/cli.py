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

    if args.action == "import-history":
        from .data.universe import import_universe_history

        try:
            for h in sorted(import_universe_history(settings, [Path(p) for p in args.paths]), key=lambda x: x.as_of):
                print(f"{h.as_of}: {len(h.tickers)} constituents; unresolved {len(h.excluded)}")
        except (UniverseError, ValueError, KeyError) as exc:
            print(f"Historical list rejected: {exc}")
            return 2
        return 0
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


def cmd_dividends(settings: Settings, args) -> int:
    from .data.dividends import import_dividends_file

    s = import_dividends_file(settings, args.symbol.upper(), Path(args.path))
    span = f"{s.index.min().date()} to {s.index.max().date()}" if len(s) else "none"
    print(f"{args.symbol.upper()}: {len(s)} dividends ({span})")
    return 0


def cmd_daily(settings: Settings, args) -> int:
    from .daily import run_daily, write

    text, ctx = run_daily(settings, args.as_of, run_paper=not args.no_paper, label=args.label or "")
    print(f"Run log: {ctx.manifest_path}")
    if ctx.spec_warning:
        print(f"WARNING: {ctx.spec_warning}")
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
    from .backtest.desk_backtest import run_desk_backtest, run_unlevered_baseline, with_cost_multiplier
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
        lines += [f"## {' + '.join(syms)}", ""]
        for name, (start, end) in [("train", sp.train), ("validation", sp.validation)]:
            lines += [f"### {name}: {start.date()} to {end.date()}", "",
                      "| Variant | Return | CAGR | Sharpe (95% CI) | Max DD | Trades | Win % | Exposure |",
                      "|---|---|---|---|---|---|---|---|"]
            warn = []

            def row(label, m, boot=None):
                ci = "" if boot is None else (" (n/a)" if boot.get("insufficient")
                                              else f" ({boot['sharpe_ci'][0]:.2f} to {boot['sharpe_ci'][1]:.2f})")
                trades = m.get("trades", "-") if m.get("trades") else "-"
                win = f"{m['win_rate']:.0%}" if m.get("trades") else "-"
                expo = f"{m['exposure']:.0%}" if m.get("exposure") is not None else "-"
                lines.append(f"| {label} | {m['total_return']:+.1%} | {(m.get('cagr') or 0):+.1%} | {m['sharpe']:.2f}{ci} | "
                             f"{m['max_drawdown']:+.1%} | {trades} | {win} | {expo} |")

            for k in (1, 2, 3):
                res = run_desk_backtest(bars, with_cost_multiplier(settings, k), syms, start, end, cash)
                boot = block_bootstrap(res.equity.pct_change(), 500, 20) if k == 1 else None
                row(f"Rules, {k}× costs", res.metrics, boot)
                if k == 1:
                    warn = warnings_for(res.metrics, boot, settings.evaluation.min_trades)
            if syms == [d.leveraged_long]:
                row("Same rule on QQQ (no leverage, same $ risk and 5-day limit)",
                    run_unlevered_baseline(bars, settings, start, end).metrics)
            if syms == [d.leveraged_inverse]:
                lines.append("| Holding cash instead (trading P&L 0) | +0.0% | +0.0% | 0.00 | +0.0% | - | - | 0% |")
            row(f"{d.underlying} buy & hold", compute_metrics(
                buy_and_hold(bars[d.underlying], start, end, 1000, settings.costs.per_side), [], 1000, 1.0))
            if len(syms) == 1:
                row(f"{syms[0]} buy & hold", compute_metrics(
                    buy_and_hold(bars[syms[0]], start, end, 1000, settings.costs.per_side), [], 1000, 1.0))
            lines += [""] + [f"> ⚠ {w}" for w in warn] + [""]
    text = "\n".join(lines)
    reports = settings.resolve(settings.paths.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"desk_backtest_{args.as_of}.md"
    path.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nReport: {path}")
    return 0


def cmd_evaluate_scanner(settings: Settings, args) -> int:
    """Strategy A on point-in-time S&P 500 lists (train + validation; holdout untouched)."""
    from .backtest.scanner_backtest import run_account_backtest, run_signal_backtest, summarize
    from .data.universe import load_universe_history

    history = {d: t for d, t in load_universe_history(settings).items()}
    if len(history) < 2:
        print("Need historical constituent snapshots (universe import-history).")
        return 1
    args.symbols = sorted(set().union(*history.values()) | {settings.scanner.benchmark})
    bars = _backtest_bars(settings, args)
    spy = bars.pop(settings.scanner.benchmark, None)
    if spy is None:
        print("Benchmark data missing.")
        return 1
    bt = run_signal_backtest(bars, spy, history, settings, top_n=args.top)
    frame = bt.frame()
    n = len(frame)
    t_end, v_end = int(n * settings.evaluation.train_fraction), int(n * (settings.evaluation.train_fraction + settings.evaluation.validation_fraction))
    parts = {"train": frame.iloc[:t_end], "validation": frame.iloc[t_end:v_end]}
    snaps = sorted(history)
    lines = ["# Strategy A (S&P 500 scanner) point-in-time backtest", "",
             f"> Universe each month = latest stored S&P 500 snapshot on or before that date ({len(snaps)} snapshots, "
             f"{snaps[0]} to {snaps[-1]}; quarterly N-PORT lists to {snaps[-2]}, so later months reuse that list and miss "
             "newer additions). Price factors only (fundamentals are not point-in-time). Top "
             f"{args.top} eligible names, equal weight, next open to next month-end, net of "
             f"{settings.costs.per_side * 1e4:.1f} bps per side on turnover. Holdout = last "
             f"{n - v_end} months, untouched. Delisted names Robinhood no longer carries are missing (survivorship gap).", ""]
    for name, part in parts.items():
        if part.empty:
            continue
        s = summarize(part)
        lines += [f"## {name}: {part.index[0]} to {part.index[-1]} ({s['top']['months']} months)", "",
                  "| | Total | CAGR | Sharpe | Max DD |", "|---|---|---|---|---|"]
        for label, key in [(f"Top {args.top} (strategy)", "top"), ("All eligible, equal weight", "universe"), ("SPY", "spy")]:
            st = s[key]
            lines.append(f"| {label} | {st['total']:+.1%} | {st['cagr']:+.1%} | {st['sharpe']:.2f} | {st['max_dd']:+.1%} |")
        lines += ["",
                  f"- Mean monthly excess vs SPY {s['excess_vs_spy_mean_monthly']:+.2%} (t = {s['excess_t_stat']:.2f}); "
                  f"beat SPY in {s['hit_rate_vs_spy']:.0%} of months.",
                  f"- Rank IC (score vs next-month return, all scored names): mean {s['ic_mean']:+.3f} (t = {s['ic_t_stat']:.2f}).",
                  f"- Coverage: {s['avg_members']:.0f} listed members/month, {s['avg_scored']:.0f} scored, "
                  f"{s['avg_eligible']:.0f} eligible; average turnover {s['avg_turnover']:.0%} of picks per month.",
                  "- ⚠ |t| < 2: not statistically distinguishable from zero." if abs(s["excess_t_stat"]) < 2 else "", ""]
    if not parts["validation"].empty:
        start, end = pd.Timestamp(parts["train"].index[0]), pd.Timestamp(parts["validation"].index[-1]) + pd.offsets.MonthEnd(1)
        acct = run_account_backtest(bars | {settings.scanner.benchmark: spy}, spy, history, settings, start, end, args.top)
        m = acct.metrics
        lines += ["## Under the real account limits ($5/trade, $15 total, $250 max, 2.5×ATR stops; trading P&L only)", "",
                  f"{m['start']} to {m['end']}: return {m['total_return']:+.1%}, CAGR {(m['cagr'] or 0):+.1%}, Sharpe "
                  f"{m['sharpe']:.2f}, max DD {m['max_drawdown']:+.1%}, {m['trades']} trades, win rate {m['win_rate']:.0%}, "
                  f"exposure {m['exposure']:.0%}.", ""]
    text = "\n".join(l for l in lines if l is not None)
    reports = settings.resolve(settings.paths.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"scanner_backtest_{args.as_of}.md"
    path.write_text(text, encoding="utf-8")
    frame.to_csv(reports / f"scanner_backtest_months_{args.as_of}.csv")
    print(text)
    print(f"\nReport: {path}")
    return 0


def cmd_evaluate_gtaa(settings: Settings, args) -> int:
    """Strategy C (GTAA) on history: train + validation; holdout untouched."""
    from dataclasses import replace

    from .backtest.benchmarks import buy_and_hold, equal_weight
    from .backtest.evaluation import make_splits
    from .backtest.metrics import compute_metrics
    from .backtest.portfolio import run_allocation
    from .backtest.stats import block_bootstrap
    from .data.rates import daily_cash_rate, load_monthly_rates
    from .strategies import gtaa

    from .backtest.desk_backtest import with_cost_multiplier
    from .data.dividends import load_dividends, total_return_bars

    g = settings.gtaa
    args.symbols = list(g.assets)
    price_bars = _backtest_bars(settings, args)
    missing = [a for a in g.assets if a not in price_bars]
    no_divs = [a for a in price_bars if load_dividends(settings, a) is None]
    bars = {s: total_return_bars(df, load_dividends(settings, s)) for s, df in price_bars.items()}
    dates = sorted(set().union(*(df.index for df in bars.values())))
    sp = make_splits(dates, 21 * g.sma_months + 5, settings.evaluation.train_fraction, settings.evaluation.validation_fraction)
    assets = list(g.assets)
    c2_target_vol, c2_max_exposure = 0.10, 1.0  # C2 hypothesis, fixed before the first run (not tuned)

    def wfn(day, hist):
        return gtaa.weights(hist, day, assets, g.sma_months)

    def c2_wfn(day, hist):
        return gtaa.vol_managed_weights(hist, day, assets, g.sma_months, c2_target_vol, 63, c2_max_exposure)

    def spy_timing(day, hist):
        return {"SPY": 1.0} if gtaa.weights(hist, day, ["SPY"], g.sma_months) else {}

    def relaxed(max_pos):
        # research views: per-trade caps relaxed, no stops; position cap = the rule's own weight
        return replace(settings, risk=replace(settings.risk, risk_per_trade_pct=1.0, max_open_risk_pct=1.0,
                                              max_correlated_risk_pct=1.0, max_position_pct=max_pos + 1e-9,
                                              stop_risk_buffer=0.0))

    signal_settings, single_settings = relaxed(1.0 / len(assets)), relaxed(1.0)
    cash = daily_cash_rate(load_monthly_rates(settings), pd.DatetimeIndex(dates))
    cost = settings.costs.per_side
    lines = ["# Strategy C (GTAA) backtest", "",
             f"> Assets {', '.join(assets)}; month-end {g.sma_months}-month SMA rule; next-open fills; "
             f"{cost * 1e4:.1f} bps per side. Holdout {sp.holdout[0].date()} to {sp.holdout[1].date()} untouched. "
             "**Total return**: prices back-adjusted for cash dividends (reinvested at the ex-date close)."
             + (f" No dividend file (treated as price-only): {no_divs}." if no_divs else "")
             + (f" Missing data: {missing}." if missing else ""), "",
             "Variants (all declared before running; none tuned on these results):",
             "- **C0** research baseline: the published rule, 1/7 per asset above its SMA, rest in T-bills, no stops.",
             "- **C1** the same signals under the account's real limits (RiskEngine sizing, ATR stops), trading P&L only.",
             f"- **C2** separate hypothesis: C0 scaled at entry so trailing 63-day basket volatility ≤ {c2_target_vol:.0%}, "
             f"exposure ≤ {c2_max_exposure:.0%} (no leverage); T-bills on cash.",
             "- Benchmarks: SPY {0}-month SMA timing (T-bills when out), SPY buy & hold, 7-asset equal weight; all total return.".format(g.sma_months),
             "", f"Multiple testing: 3 GTAA variants are reported; treat any single one's best period with caution.", ""]
    header = ["| | Total | CAGR | Vol | Sharpe | Max DD | DD days | Worst month | Avg invested | Turnover | Trades |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]

    def row(label, m):
        wm = f"{m['worst_month']:+.1%}" if m.get("worst_month") is not None else "-"
        inv = f"{m['avg_invested']:.0%}" if m.get("avg_invested") is not None else "100%"
        return (f"| {label} | {m['total_return']:+.1%} | {(m.get('cagr') or 0):+.1%} | {(m.get('volatility') or 0):.1%} | "
                f"{m['sharpe']:.2f} | {m['max_drawdown']:+.1%} | {m.get('max_dd_duration_days', '-')} | {wm} | {inv} | "
                f"{m.get('turnover', 0):.2f} | {m.get('trades') or '-'} |")

    for name, (start, end) in [("train", sp.train), ("validation", sp.validation)]:
        c0 = run_allocation(bars, signal_settings, wfn, start, end, cash_rate=cash, name="C0", use_stops=False)
        c0_price = run_allocation(price_bars, signal_settings, wfn, start, end, cash_rate=cash, name="C0 price",
                                  use_stops=False)
        c1 = run_allocation(bars, settings, wfn, start, end, name="C1")
        c2 = run_allocation(bars, signal_settings, c2_wfn, start, end, cash_rate=cash, name="C2", use_stops=False)
        timing = run_allocation(bars, single_settings, spy_timing, start, end, cash_rate=cash, name="SPY timing",
                                use_stops=False)
        spy = compute_metrics(buy_and_hold(bars["SPY"], start, end, 1000, cost), [], 1000, 1.0)
        ew = compute_metrics(equal_weight(bars, start, end, 1000, cost), [], 1000, 1.0)
        b = block_bootstrap(c0.equity.pct_change(), 500, 20)
        ci = "n/a" if b.get("insufficient") else f"{b['sharpe_ci'][0]:.2f} to {b['sharpe_ci'][1]:.2f}"
        lines += [f"## {name}: {start.date()} to {end.date()}", "", *header]
        for label, m in [("C0 GTAA research baseline (total return)", c0.metrics),
                         ("C0 on price-only bars (old method, for comparison)", c0_price.metrics),
                         ("C1 GTAA under account limits (trading P&L only)", c1.metrics),
                         ("C2 GTAA volatility-managed", c2.metrics),
                         (f"SPY {g.sma_months}-month timing", timing.metrics),
                         ("SPY buy & hold", spy), ("7-asset equal weight buy & hold", ew)]:
            lines.append(row(label, m))
        lines += ["", "Cost stress (C0):", ""]
        for k in (2, 3):
            m = run_allocation(bars, with_cost_multiplier(signal_settings, k), wfn, start, end, cash_rate=cash,
                               use_stops=False).metrics
            lines.append(f"- {k}× costs: total {m['total_return']:+.1%}, CAGR {(m.get('cagr') or 0):+.1%}, "
                         f"Sharpe {m['sharpe']:.2f} (1×: {c0.metrics['sharpe']:.2f}).")
        years = sorted(set(c0.metrics["calendar_years"]) | set(spy["calendar_years"]))
        lines += ["", "Calendar years (partial first/last years marked by the period dates):", "",
                  "| Year | C0 | C2 | SPY timing | SPY |", "|---|---|---|---|---|"]
        for y in years:
            cells = [r.get("calendar_years", {}).get(y) for r in (c0.metrics, c2.metrics, timing.metrics, spy)]
            lines.append(f"| {y} | " + " | ".join("-" if v is None else f"{v:+.1%}" for v in cells) + " |")
        lines += ["", f"C0 Sharpe 95% interval (block bootstrap): {ci}.", ""]
    text = "\n".join(lines)
    reports = settings.resolve(settings.paths.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"gtaa_backtest_{args.as_of}.md"
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

    es = sub.add_parser("evaluate-scanner", help="point-in-time backtest of Strategy A (holdout untouched)")
    es.add_argument("--top", type=int, default=10)
    es.add_argument("--since", type=date.fromisoformat, help="ignore history before YYYY-MM-DD")
    es.set_defaults(func=cmd_evaluate_scanner, symbols=None)

    eg = sub.add_parser("evaluate-gtaa", help="backtest Strategy C (GTAA): signal view and account-limits view")
    eg.add_argument("--since", type=date.fromisoformat, help="ignore history before YYYY-MM-DD")
    eg.set_defaults(func=cmd_evaluate_gtaa, symbols=None)

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
