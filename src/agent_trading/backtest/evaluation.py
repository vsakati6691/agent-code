"""Chronological train / validation / holdout evaluation.

* Train:      parameters are chosen here (walk-forward grid, by Sharpe).
* Validation: the chosen and default parameters are tested here, with
              benchmarks, bootstrap intervals, and regime breakdowns.
* Holdout:    the most recent slice. It is only evaluated when explicitly
              requested, and every use is logged so it cannot silently become
              another tuning set.
Parameter sensitivity and walk-forward analysis use train + validation only.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .. import regime
from ..config import Settings, StrategyConfig
from .benchmarks import benchmark_table
from .engine import BacktestResult, prepare, run_backtest, strategy_grid
from .stats import block_bootstrap, sensitivity, warnings_for
from .walkforward import walk_forward, warmup_bars

HOLDOUT_LOG = "holdout_log.json"


@dataclass(frozen=True)
class Splits:
    train: tuple[pd.Timestamp, pd.Timestamp]
    validation: tuple[pd.Timestamp, pd.Timestamp]
    holdout: tuple[pd.Timestamp, pd.Timestamp]


def make_splits(dates: list[pd.Timestamp], warmup: int, train_frac: float, val_frac: float) -> Splits:
    usable = dates[warmup:]
    n = len(usable)
    if n < 120:
        raise ValueError(f"only {n} bars after a {warmup}-bar warm-up; need at least 120 for a three-way split")
    t_end = int(n * train_frac)
    v_end = int(n * (train_frac + val_frac))
    return Splits((usable[0], usable[t_end - 1]), (usable[t_end], usable[v_end - 1]), (usable[v_end], usable[-1]))


@dataclass
class PeriodResult:
    name: str
    start: str
    end: str
    strategy: dict
    bootstrap: dict
    benchmarks: dict[str, dict]
    by_trend: list[dict]
    by_volatility: list[dict]
    warnings: list[str]
    equity: pd.Series = field(repr=False, default_factory=pd.Series)
    trades: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)


@dataclass
class EvaluationReport:
    splits: Splits
    chosen: dict
    default: dict
    periods: list[PeriodResult]
    sensitivity_summary: dict
    sensitivity_table: pd.DataFrame
    walkforward: dict
    holdout_uses: int
    assumptions: dict
    n_symbols: int


def _strategy_params(cfg: StrategyConfig) -> dict:
    return {"fast_ma": cfg.fast_ma, "slow_ma": cfg.slow_ma, "momentum_lookback": cfg.momentum_lookback}


def _period(name, res: BacktestResult, bars, settings, start, end, regimes) -> PeriodResult:
    ev = settings.evaluation
    boot = block_bootstrap(res.equity.pct_change(), ev.bootstrap_samples, ev.bootstrap_block)
    trades = res.trades_frame()
    if not trades.empty and regimes is not None:
        labels = regimes["trend"].copy()
        labels.index = labels.index.date
        trades["regime_at_entry"] = [labels.get(d) for d in trades["entry_date"]]
    return PeriodResult(
        name, str(start.date()), str(end.date()), res.metrics, boot,
        benchmark_table(bars, settings.regime.benchmark, start, end, settings.paper_starting_equity, settings.costs.per_side),
        regime.performance_by_regime(res.equity, regimes, "trend").to_dict("records") if regimes is not None else [],
        regime.performance_by_regime(res.equity, regimes, "volatility").to_dict("records") if regimes is not None else [],
        warnings_for(res.metrics, boot, ev.min_trades),
        res.equity, trades,
    )


def _holdout_log(settings: Settings) -> Path:
    return settings.resolve(settings.paths.reports_dir) / HOLDOUT_LOG


def holdout_uses(settings: Settings) -> int:
    path = _holdout_log(settings)
    return len(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else 0


def _log_holdout(settings: Settings, splits: Splits, chosen: dict) -> int:
    path = _holdout_log(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    log = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    log.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "holdout": [str(splits.holdout[0].date()), str(splits.holdout[1].date())], "params": chosen})
    path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return len(log)


def evaluate(bars: dict[str, pd.DataFrame], settings: Settings, use_holdout: bool = False) -> EvaluationReport:
    ev, wf = settings.evaluation, settings.walkforward
    candidates = strategy_grid(settings.strategy, wf.grid)
    warm = max(warmup_bars(c) for c in candidates)
    dates = sorted(set().union(*(df.index for df in bars.values())))
    splits = make_splits(dates, warm, ev.train_fraction, ev.validation_fraction)
    bench = bars.get(settings.regime.benchmark)
    regimes = regime.classify(bench, settings.regime) if bench is not None else None

    # 1. choose parameters on the training window only
    prepared = {c: prepare(bars, c) for c in candidates}
    scored = [(run_backtest(bars, settings, *splits.train, c, prepared=prepared[c]).metrics.get("sharpe", 0.0), c)
              for c in candidates]
    _, best = max(scored, key=lambda x: x[0])

    periods = []
    for name, (start, end) in [("train", splits.train), ("validation", splits.validation)]:
        res = run_backtest(bars, settings, start, end, best, prepared=prepared[best])
        periods.append(_period(f"{name} (chosen params)", res, bars, settings, start, end, regimes))
    if settings.strategy not in prepared:
        prepared[settings.strategy] = prepare(bars, settings.strategy)
    res = run_backtest(bars, settings, *splits.validation, settings.strategy, prepared=prepared[settings.strategy])
    periods.append(_period("validation (default params)", res, bars, settings, *splits.validation, regimes))

    uses = holdout_uses(settings)
    if use_holdout:
        uses = _log_holdout(settings, splits, _strategy_params(best))
        res = run_backtest(bars, settings, *splits.holdout, best, prepared=prepared[best])
        p = _period("HOLDOUT (chosen params)", res, bars, settings, *splits.holdout, regimes)
        if uses > 1:
            p.warnings.insert(0, f"holdout has now been evaluated {uses} times; it is no longer untouched")
        periods.append(p)

    # 2. robustness on train + validation only (holdout excluded)
    dev_end = splits.validation[1]
    dev_bars = {s: df.loc[:dev_end] for s, df in bars.items()}
    grid = dict(ev.sensitivity_grid)
    sens_table, sens_summary = (sensitivity(dev_bars, settings, grid, splits.train[0], dev_end)
                                if grid else (pd.DataFrame(), {}))
    try:
        wf_res = walk_forward(dev_bars, settings)
        wf_summary = {"folds": wf_res.folds, "metrics": wf_res.metrics}
    except ValueError as exc:
        wf_summary = {"error": str(exc)}

    c = settings.costs
    return EvaluationReport(
        splits, _strategy_params(best), _strategy_params(settings.strategy), periods,
        sens_summary, sens_table, wf_summary, uses,
        {"slippage_bps_per_side": c.slippage_bps, "spread_bps": c.spread_bps,
         "commission_per_order": c.commission_per_order, "fills": "next open after signal",
         "stops": "daily low; gaps fill at the open", "prices": "split-adjusted, dividends excluded",
         "risk": asdict(settings.risk)},
        len(bars),
    )


# ---------------------------------------------------------------- rendering

def _p(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{x:+.{d}%}"


def _f(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f"{x:.{d}f}"


def render_markdown(rep: EvaluationReport) -> str:
    s = rep.splits
    out = [
        "# Strategy evaluation", "",
        "> Research output. Past performance does not guarantee future results. "
        "Results below are hypotheses until they hold up on data not used to build them.", "",
        f"- Universe: {rep.n_symbols} symbols (today's list: **survivorship bias** inflates results)",
        f"- Train {s.train[0].date()} → {s.train[1].date()} · validation {s.validation[0].date()} → "
        f"{s.validation[1].date()} · holdout {s.holdout[0].date()} → {s.holdout[1].date()} "
        f"(evaluated {rep.holdout_uses} time(s))",
        f"- Parameters chosen on train: {rep.chosen}; default: {rep.default}",
        f"- Costs: {rep.assumptions['slippage_bps_per_side']} bps slippage/side + {rep.assumptions['spread_bps']} bps spread; "
        f"fills {rep.assumptions['fills']}; {rep.assumptions['stops']}; {rep.assumptions['prices']}", "",
    ]
    for p in rep.periods:
        m, b = p.strategy, p.bootstrap
        out += [f"## {p.name}: {p.start} → {p.end}", ""]
        if p.warnings:
            out += [f"> ⚠ {w}" for w in p.warnings] + [""]
        out += ["| | Total | CAGR | Sharpe | Sortino | Max DD | Trades | Win % | PF | Exposure | Turnover/yr |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
        out.append(f"| **Strategy** | {_p(m.get('total_return'))} | {_p(m.get('cagr'))} | {_f(m.get('sharpe'))} | "
                   f"{_f(m.get('sortino'))} | {_p(m.get('max_drawdown'))} | {m.get('trades')} | "
                   f"{_p(m.get('win_rate'), 0)} | {_f(m.get('profit_factor'))} | {_p(m.get('exposure'), 0)} | "
                   f"{_f(m.get('turnover'), 1)}x |")
        for name, bm in p.benchmarks.items():
            out.append(f"| {name} | {_p(bm.get('total_return'))} | {_p(bm.get('cagr'))} | {_f(bm.get('sharpe'))} | "
                       f"{_f(bm.get('sortino'))} | {_p(bm.get('max_drawdown'))} | - | - | - | - | - |")
        if not b.get("insufficient"):
            out += ["", f"Bootstrap 95% intervals ({b['n_days']} days, block bootstrap): Sharpe "
                        f"{_f(b['sharpe_ci'][0])} to {_f(b['sharpe_ci'][1])}; annualised return "
                        f"{_p(b['ann_return_ci'][0])} to {_p(b['ann_return_ci'][1])}; "
                        f"P(Sharpe > 0) ≈ {b['prob_sharpe_positive']:.0%}."]
        for title, rows, key in [("Market trend", p.by_trend, "trend"), ("Volatility", p.by_volatility, "volatility")]:
            if rows:
                out += ["", f"By {title.lower()} (regime at prior close):", "",
                        f"| {title} | Days | Return | Annualised | Sharpe |", "|---|---|---|---|---|"]
                out += [f"| {r[key]} | {r['days']} | {_p(r['total_return'])} | {_p(r['annualized_return'])} | "
                        f"{_f(r['sharpe'])} |" for r in rows]
        out.append("")

    ss = rep.sensitivity_summary
    if ss:
        out += ["## Parameter sensitivity (train + validation)", "",
                f"- {ss['combinations']} combinations; {ss['share_positive_sharpe']:.0%} have Sharpe > 0; "
                f"best {_f(ss['best_sharpe'])}, median {_f(ss['median_sharpe'])}; default ranks "
                f"{ss['default_rank']} of {ss['combinations']}.",
                "- **Fragile: results depend on narrow parameter choices.**" if ss["fragile"]
                else "- Not flagged as fragile: most nearby parameter choices behave similarly.", ""]
        top = rep.sensitivity_table.head(5)
        out += ["Top 5:", "", "```", top.to_string(index=False, float_format=lambda v: f"{v:.3f}"), "```", ""]

    wf = rep.walkforward
    out += ["## Walk-forward (train + validation only)", ""]
    if "error" in wf:
        out.append(f"_Not run: {wf['error']}_")
    else:
        m = wf["metrics"]
        out.append(f"{len(wf['folds'])} folds; stitched out-of-sample: total {_p(m.get('total_return'))}, "
                   f"Sharpe {_f(m.get('sharpe'))}, max DD {_p(m.get('max_drawdown'))}, {m.get('trades')} trades.")
    out.append("")
    return "\n".join(out)


def save(rep: EvaluationReport, settings: Settings, as_of) -> tuple[Path, Path]:
    reports = settings.resolve(settings.paths.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    md = reports / f"evaluation_{as_of}.md"
    md.write_text(render_markdown(rep), encoding="utf-8")
    trades = pd.concat([p.trades.assign(period=p.name) for p in rep.periods if not p.trades.empty], ignore_index=True) \
        if any(not p.trades.empty for p in rep.periods) else pd.DataFrame()
    csv = reports / f"evaluation_trades_{as_of}.csv"
    trades.to_csv(csv, index=False)
    return md, csv
