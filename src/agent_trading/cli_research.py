"""Research evaluation commands; holdout and acceptance rules are unchanged."""

from __future__ import annotations

import pandas as pd

from .cli_common import _backtest_bars
from .config import Settings


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
    lines = [
        "# Strategy B (desk) backtest",
        "",
        "> Rules from strategies/desk.py on daily bars; costs and RiskEngine limits as configured. "
        "Event and earnings blackouts are NOT modelled historically. Holdout (last 20%) untouched. "
        "**Trading P&L only**: idle cash earns nothing here, so returns and Sharpe measure the rules, "
        "not T-bill interest (with tiny positions, interest would dominate).",
        "",
    ]
    rates = None  # deliberately: isolate the rules' edge from cash interest
    groups = [
        [d.leveraged_long],
        [d.leveraged_inverse],
        ["NVDA"],
        [d.bitcoin_instrument],
        [d.leveraged_long, d.leveraged_inverse, "NVDA", d.bitcoin_instrument],
    ]
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
            lines += [
                f"### {name}: {start.date()} to {end.date()}",
                "",
                "| Variant | Return | CAGR | Sharpe (95% CI) | Max DD | Trades | Win % | Exposure |",
                "|---|---|---|---|---|---|---|---|",
            ]
            warn = []

            def row(label, m, boot=None):
                ci = (
                    ""
                    if boot is None
                    else (
                        " (n/a)"
                        if boot.get("insufficient")
                        else f" ({boot['sharpe_ci'][0]:.2f} to {boot['sharpe_ci'][1]:.2f})"
                    )
                )
                trades = m.get("trades", "-") if m.get("trades") else "-"
                win = f"{m['win_rate']:.0%}" if m.get("trades") else "-"
                expo = f"{m['exposure']:.0%}" if m.get("exposure") is not None else "-"
                lines.append(  # noqa: B023 - row is called synchronously within this iteration.
                    f"| {label} | {m['total_return']:+.1%} | {(m.get('cagr') or 0):+.1%} | {m['sharpe']:.2f}{ci} | "
                    f"{m['max_drawdown']:+.1%} | {trades} | {win} | {expo} |"
                )

            for k in (1, 2, 3):
                res = run_desk_backtest(bars, with_cost_multiplier(settings, k), syms, start, end, cash)
                boot = block_bootstrap(res.equity.pct_change(), 500, 20) if k == 1 else None
                row(f"Rules, {k}× costs", res.metrics, boot)
                if k == 1:
                    warn = warnings_for(res.metrics, boot, settings.evaluation.min_trades)
            if syms == [d.leveraged_long]:
                row(
                    "Same rule on QQQ (no leverage, same $ risk and 5-day limit)",
                    run_unlevered_baseline(bars, settings, start, end).metrics,
                )
            if syms == [d.leveraged_inverse]:
                lines.append("| Holding cash instead (trading P&L 0) | +0.0% | +0.0% | 0.00 | +0.0% | - | - | 0% |")
            row(
                f"{d.underlying} buy & hold",
                compute_metrics(
                    buy_and_hold(bars[d.underlying], start, end, 1000, settings.costs.per_side), [], 1000, 1.0
                ),
            )
            if len(syms) == 1:
                row(
                    f"{syms[0]} buy & hold",
                    compute_metrics(
                        buy_and_hold(bars[syms[0]], start, end, 1000, settings.costs.per_side), [], 1000, 1.0
                    ),
                )
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
    from .backtest.scanner_backtest import VARIANTS, run_ablation, run_account_backtest, summarize, with_cost_multiplier
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
    ablation = run_ablation(bars, spy, history, settings, top_n=args.top)
    frame = ablation["full"].frame()
    n = len(frame)
    t_end, v_end = (
        int(n * settings.evaluation.train_fraction),
        int(n * (settings.evaluation.train_fraction + settings.evaluation.validation_fraction)),
    )
    parts = {"train": frame.iloc[:t_end], "validation": frame.iloc[t_end:v_end]}
    cost = settings.costs.per_side
    snaps = sorted(history)
    lines = [
        "# Strategy A (S&P 500 scanner) point-in-time backtest",
        "",
        f"> Universe each month = latest stored S&P 500 snapshot on or before that date ({len(snaps)} snapshots, "
        f"{snaps[0]} to {snaps[-1]}; quarterly N-PORT lists to {snaps[-2]}, so later months reuse that list and miss "
        "newer additions). Price factors only (fundamentals are not point-in-time). Top "
        f"{args.top} eligible names, equal weight, next open to next month-end, net of "
        f"{settings.costs.per_side * 1e4:.1f} bps per side on turnover. Holdout = last "
        f"{n - v_end} months, untouched. Delisted names Robinhood no longer carries are missing (survivorship gap).",
        "",
    ]
    for name, part in parts.items():
        if part.empty:
            continue
        s = summarize(part)
        lines += [
            f"## {name}: {part.index[0]} to {part.index[-1]} ({s['top']['months']} months)",
            "",
            "| | Total | CAGR | Sharpe | Max DD |",
            "|---|---|---|---|---|",
        ]
        for label, key in [
            (f"Top {args.top} (strategy)", "top"),
            ("All eligible, equal weight", "universe"),
            ("SPY", "spy"),
        ]:
            st = s[key]
            lines.append(
                f"| {label} | {st['total']:+.1%} | {st['cagr']:+.1%} | {st['sharpe']:.2f} | {st['max_dd']:+.1%} |"
            )
        lines += [
            "",
            f"- Mean monthly excess vs SPY {s['excess_vs_spy_mean_monthly']:+.2%} (t = {s['excess_t_stat']:.2f}); "
            f"beat SPY in {s['hit_rate_vs_spy']:.0%} of months.",
            f"- Rank IC (score vs next-month return, all scored names): mean {s['ic_mean']:+.3f} (t = {s['ic_t_stat']:.2f}).",
            f"- Coverage: {s['avg_members']:.0f} listed members/month, {s['avg_scored']:.0f} scored, "
            f"{s['avg_eligible']:.0f} eligible; average turnover {s['avg_turnover']:.0%} of picks per month.",
            "- ⚠ |t| < 2: not statistically distinguishable from zero." if abs(s["excess_t_stat"]) < 2 else "",
            "",
        ]
    lines += [
        "## Factor ablation (does each idea add anything over plain momentum?)",
        "",
        f"{len(VARIANTS)} variants, all declared before running and evaluated on the same months; top {args.top} "
        "names each. **Multiple testing:** with 5 tries, at least one |t| > 2 would appear by chance about 20% of "
        "the time, so a single good row is weak evidence.",
        "",
    ]
    lines += [f"- **{v}**: {desc}" for v, desc in VARIANTS.items()] + [""]
    for name, (lo, hi) in {"train": (0, t_end), "validation": (t_end, v_end)}.items():
        lines += [
            f"### {name}",
            "",
            "| Variant | Gross CAGR | Net CAGR | Net CAGR at 3× costs | Sharpe | Excess vs SPY/mo (t) | IC (t) | Turnover | Eligible |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for v, bt_v in ablation.items():
            part = bt_v.frame().iloc[lo:hi]
            if part.empty:
                continue
            s = summarize(part)
            gross = summarize(part.assign(top_return=part["gross_return"]))["top"]["cagr"]
            stress = summarize(with_cost_multiplier(part, cost, 3))["top"]["cagr"]
            lines.append(
                f"| {v} | {gross:+.1%} | {s['top']['cagr']:+.1%} | {stress:+.1%} | {s['top']['sharpe']:.2f} | "
                f"{s['excess_vs_spy_mean_monthly']:+.2%} ({s['excess_t_stat']:.2f}) | "
                f"{s['ic_mean']:+.3f} ({s['ic_t_stat']:.2f}) | {s['avg_turnover']:.0%} | {s['avg_eligible']:.0f} |"
            )
        lines.append("")
    if not parts["validation"].empty:
        start, end = (
            pd.Timestamp(parts["train"].index[0]),
            pd.Timestamp(parts["validation"].index[-1]) + pd.offsets.MonthEnd(1),
        )
        acct = run_account_backtest(
            bars | {settings.scanner.benchmark: spy}, spy, history, settings, start, end, args.top
        )
        m = acct.metrics
        lines += [
            "## Under the real account limits ($5/trade, $15 total, $250 max, 2.5×ATR stops; trading P&L only)",
            "",
            f"{m['start']} to {m['end']}: return {m['total_return']:+.1%}, CAGR {(m['cagr'] or 0):+.1%}, Sharpe "
            f"{m['sharpe']:.2f}, max DD {m['max_drawdown']:+.1%}, {m['trades']} trades, win rate {m['win_rate']:.0%}, "
            f"exposure {m['exposure']:.0%}.",
            "",
        ]
    text = "\n".join(line for line in lines if line is not None)
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
    from .backtest.desk_backtest import with_cost_multiplier
    from .backtest.evaluation import make_splits
    from .backtest.metrics import compute_metrics
    from .backtest.portfolio import run_allocation
    from .backtest.stats import block_bootstrap
    from .data.dividends import load_dividends, total_return_bars
    from .data.rates import daily_cash_rate, load_monthly_rates
    from .strategies import gtaa

    g = settings.gtaa
    args.symbols = list(g.assets)
    price_bars = _backtest_bars(settings, args)
    missing = [a for a in g.assets if a not in price_bars]
    no_divs = [a for a in price_bars if load_dividends(settings, a) is None]
    bars = {s: total_return_bars(df, load_dividends(settings, s)) for s, df in price_bars.items()}
    dates = sorted(set().union(*(df.index for df in bars.values())))
    sp = make_splits(
        dates, 21 * g.sma_months + 5, settings.evaluation.train_fraction, settings.evaluation.validation_fraction
    )
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
        return replace(
            settings,
            risk=replace(
                settings.risk,
                risk_per_trade_pct=1.0,
                max_open_risk_pct=1.0,
                max_correlated_risk_pct=1.0,
                max_position_pct=max_pos + 1e-9,
                stop_risk_buffer=0.0,
            ),
        )

    signal_settings, single_settings = relaxed(1.0 / len(assets)), relaxed(1.0)
    cash = daily_cash_rate(load_monthly_rates(settings), pd.DatetimeIndex(dates))
    cost = settings.costs.per_side
    lines = [
        "# Strategy C (GTAA) backtest",
        "",
        f"> Assets {', '.join(assets)}; month-end {g.sma_months}-month SMA rule; next-open fills; "
        f"{cost * 1e4:.1f} bps per side. Holdout {sp.holdout[0].date()} to {sp.holdout[1].date()} untouched. "
        "**Total return**: prices back-adjusted for cash dividends (reinvested at the ex-date close)."
        + (f" No dividend file (treated as price-only): {no_divs}." if no_divs else "")
        + (f" Missing data: {missing}." if missing else ""),
        "",
        "Variants (all declared before running; none tuned on these results):",
        "- **C0** research baseline: the published rule, 1/7 per asset above its SMA, rest in T-bills, no stops.",
        "- **C1** the same signals under the account's real limits (RiskEngine sizing, ATR stops), trading P&L only.",
        f"- **C2** separate hypothesis: C0 scaled at entry so trailing 63-day basket volatility ≤ {c2_target_vol:.0%}, "
        f"exposure ≤ {c2_max_exposure:.0%} (no leverage); T-bills on cash.",
        f"- Benchmarks: SPY {g.sma_months}-month SMA timing (T-bills when out), SPY buy & hold, 7-asset equal weight; "
        "all total return.",
        "",
        "Multiple testing: 3 GTAA variants are reported; treat any single one's best period with caution.",
        "",
    ]
    header = [
        "| | Total | CAGR | Vol | Sharpe | Max DD | DD days | Worst month | Avg invested | Turnover | Trades |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    def row(label, m):
        wm = f"{m['worst_month']:+.1%}" if m.get("worst_month") is not None else "-"
        inv = f"{m['avg_invested']:.0%}" if m.get("avg_invested") is not None else "100%"
        return (
            f"| {label} | {m['total_return']:+.1%} | {(m.get('cagr') or 0):+.1%} | {(m.get('volatility') or 0):.1%} | "
            f"{m['sharpe']:.2f} | {m['max_drawdown']:+.1%} | {m.get('max_dd_duration_days', '-')} | {wm} | {inv} | "
            f"{m.get('turnover', 0):.2f} | {m.get('trades') or '-'} |"
        )

    for name, (start, end) in [("train", sp.train), ("validation", sp.validation)]:
        c0 = run_allocation(bars, signal_settings, wfn, start, end, cash_rate=cash, name="C0", use_stops=False)
        c0_price = run_allocation(
            price_bars, signal_settings, wfn, start, end, cash_rate=cash, name="C0 price", use_stops=False
        )
        c1 = run_allocation(bars, settings, wfn, start, end, name="C1")
        c2 = run_allocation(bars, signal_settings, c2_wfn, start, end, cash_rate=cash, name="C2", use_stops=False)
        timing = run_allocation(
            bars, single_settings, spy_timing, start, end, cash_rate=cash, name="SPY timing", use_stops=False
        )
        spy = compute_metrics(buy_and_hold(bars["SPY"], start, end, 1000, cost), [], 1000, 1.0)
        ew = compute_metrics(equal_weight(bars, start, end, 1000, cost), [], 1000, 1.0)
        b = block_bootstrap(c0.equity.pct_change(), 500, 20)
        ci = "n/a" if b.get("insufficient") else f"{b['sharpe_ci'][0]:.2f} to {b['sharpe_ci'][1]:.2f}"
        lines += [f"## {name}: {start.date()} to {end.date()}", "", *header]
        for label, m in [
            ("C0 GTAA research baseline (total return)", c0.metrics),
            ("C0 on price-only bars (old method, for comparison)", c0_price.metrics),
            ("C1 GTAA under account limits (trading P&L only)", c1.metrics),
            ("C2 GTAA volatility-managed", c2.metrics),
            (f"SPY {g.sma_months}-month timing", timing.metrics),
            ("SPY buy & hold", spy),
            ("7-asset equal weight buy & hold", ew),
        ]:
            lines.append(row(label, m))
        lines += ["", "Cost stress (C0):", ""]
        for k in (2, 3):
            m = run_allocation(
                bars, with_cost_multiplier(signal_settings, k), wfn, start, end, cash_rate=cash, use_stops=False
            ).metrics
            lines.append(
                f"- {k}× costs: total {m['total_return']:+.1%}, CAGR {(m.get('cagr') or 0):+.1%}, "
                f"Sharpe {m['sharpe']:.2f} (1×: {c0.metrics['sharpe']:.2f})."
            )
        years = sorted(set(c0.metrics["calendar_years"]) | set(spy["calendar_years"]))
        lines += [
            "",
            "Calendar years (partial first/last years marked by the period dates):",
            "",
            "| Year | C0 | C2 | SPY timing | SPY |",
            "|---|---|---|---|---|",
        ]
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


def cmd_tournament(settings: Settings, args) -> int:
    """Strategy tournament (research only): same data, costs, periods and metrics for every candidate."""
    from .research import report, tournament

    registry = settings.base_dir / "research" / "registry.jsonl"
    t, tested, meta = tournament.run(settings, registry, run_test=not args.no_test)
    text = report.render(t, tested, meta)
    out = settings.base_dir / "research" / f"TOURNAMENT_{args.as_of}.md"
    out.write_text(text, encoding="utf-8")
    for n, e in t.entries.items():
        sel = e.selection
        print(
            f"{n:18s} Sharpe {sel['sharpe']:.2f}  CAGR {sel['cagr']:+.1%}  MDD {sel['max_drawdown']:+.1%}  "
            f"{e.decision or 'benchmark'}"
        )
    print(f"\nRegistry: {registry} (run {meta['run_id']})\nReport: {out}")
    return 0
