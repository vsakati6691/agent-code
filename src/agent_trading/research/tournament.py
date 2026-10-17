"""Strategy tournament: hypothesis -> candidate -> data checks -> backtest -> stress -> benchmarks -> registry -> decision.

Every candidate runs through the same data, cost model, periods and metrics.

Periods (chronological, fixed before any result was seen):
  TRAIN       2008-10-01 .. 2016-12-30   (GFC tail, 2011, 2015-16)
  VALIDATION  2017-01-03 .. 2021-12-31   (Q4 2018, COVID crash and rebound)
  TEST        2022-01-03 .. end of data  (2022 bear market, 2025 sell-off)

Selection uses TRAIN and VALIDATION only. TEST is evaluated once, in the
final stage, for the benchmarks, the incumbent (GTAA = live Strategy C) and
candidates that passed. Each test evaluation is recorded in the registry,
and the consumed 2022+ holdout is sealed against further evaluation.

Acceptance rules (ACCEPTANCE) are fixed in code before running.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

from ..backtest.stats import block_bootstrap
from ..config import Settings
from ..data.cache import read_cache
from ..data.dividends import load_dividends, total_return_bars
from ..manifest import code_version
from .candidates import CASH as CASH
from .candidates import Candidate, Market, candidates
from .engine import ACCOUNT_CONSTRAINTS, Constraints, max_drawdown, metrics, simulate

PERIODS = {
    "train": ("2008-10-01", "2016-12-30"),
    "validation": ("2017-01-03", "2021-12-31"),
    "test": ("2022-01-03", None),
}
SELECTION = ("2008-10-01", "2021-12-31")  # train + validation
REGIMES = {
    "GFC tail 2008-10..2009-03": ("2008-10-01", "2009-03-09"),
    "Euro crisis 2011": ("2011-07-22", "2011-10-03"),
    "2015-16 sell-off": ("2015-07-20", "2016-02-11"),
    "Q4 2018": ("2018-09-20", "2018-12-24"),
    "COVID crash 2020": ("2020-02-19", "2020-03-23"),
    "2022 bear (test)": ("2022-01-03", "2022-10-12"),
    "2025 sell-off (test)": ("2025-02-19", "2025-04-08"),
}
COST_MULTIPLES = (1, 2, 3)
WF_YEARS = range(2011, 2022)

ACCEPTANCE = {
    "min_excess_cagr_vs_cash": 0.01,  # CAGR above BIL by >= 1%/yr, in train AND validation
    "min_sharpe_each": 0.30,  # Sharpe (excess of BIL) in train AND validation
    "max_drawdown_floor": -0.25,  # no worse than -25% in train or validation
    "min_bootstrap_sharpe_lo": 0.0,  # 95% CI lower bound on train+validation Sharpe
    "min_deflated_sharpe_prob": 0.90,  # probability true Sharpe > 0 after N trials
    "max_grid_sharpe_range": 0.50,  # sensitivity: grid Sharpe range (all grid points must be > 0)
    "min_cost_retention_3x": 0.70,  # Sharpe at 3x costs / Sharpe at 1x
    "max_sharpe_shortfall_vs_bench": 0.10,  # Sharpe not below the best simple benchmark by more than this
}
TEST_PASS = {"min_sharpe": 0.0, "max_drawdown_floor": -0.25}

DATA_SYMBOLS = sorted(
    {
        "SPY",
        "QQQ",
        "IWM",
        "EFA",
        "EEM",
        "VNQ",
        "DBC",
        "GLD",
        "IEF",
        "TLT",
        "BIL",
        "XLK",
        "XLF",
        "XLE",
        "XLV",
        "XLI",
        "XLY",
        "XLP",
        "XLU",
        "XLB",
    }
)
KNOWN_FIXES = {"EEM": "2008-01-18"}  # unadjusted 3:1 split and zero-volume bars before this date


# ---------------------------------------------------------------- data


@dataclass
class DataReport:
    rows: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    fingerprint: str = ""


def load_market(settings: Settings, symbols: list[str] = DATA_SYMBOLS) -> tuple[Market, DataReport]:
    """Load cached daily bars, apply dividends where on file, validate, align to SPY's calendar."""
    cache = settings.resolve(settings.data.cache_dir)
    rep = DataReport()
    opens, closes, tr = {}, {}, set()
    spy = read_cache(cache, "SPY")
    if spy is None:
        raise FileNotFoundError("SPY is not in the price cache")
    cal = spy.index[spy.index <= pd.Timestamp(SELECTION[1])]
    h = hashlib.sha256()
    for sym in symbols:
        df = read_cache(cache, sym)
        if df is not None:
            df = df.loc[: SELECTION[1]].copy()
        if df is None or df.empty:
            rep.problems.append(f"{sym}: not in the cache (candidates using it are affected)")
            continue
        if sym in KNOWN_FIXES:
            df = df.loc[KNOWN_FIXES[sym] :]
        bad = df[(df[["open", "high", "low", "close"]] <= 0).any(axis=1) | df[["open", "close"]].isna().any(axis=1)]
        if len(bad):
            rep.problems.append(f"{sym}: {len(bad)} bars with missing or non-positive prices dropped")
            df = df.drop(bad.index)
        if df.empty:
            rep.problems.append(f"{sym}: no valid selection-period bars")
            continue
        divs = load_dividends(settings, sym)
        if divs is not None:
            divs = divs.loc[: SELECTION[1]]
        if divs is not None and not divs.empty:
            df = total_return_bars(df, divs)
            tr.add(sym)
        elif divs is not None:
            tr.add(sym)  # an empty file means "pays no dividends" (e.g. GLD)
        jump = df["close"].pct_change().abs()
        big = jump[jump > 0.25]
        missing = int(len(cal[(cal >= df.index[0]) & (cal <= df.index[-1])].difference(df.index)))
        rep.rows.append(
            {
                "symbol": sym,
                "first": str(df.index[0].date()),
                "last": str(df.index[-1].date()),
                "bars": len(df),
                "missing_vs_spy": missing,
                "max_abs_daily_move": float(jump.max()),
                "total_return": sym in tr,
            }
        )
        if len(big):
            rep.problems.append(
                f"{sym}: {len(big)} daily moves above 25% (largest {big.max():.0%} on "
                f"{big.idxmax().date()}); check for an unadjusted split"
            )
        if missing > 5:
            rep.problems.append(f"{sym}: {missing} SPY trading days missing")
        opens[sym] = df["open"].reindex(cal)
        closes[sym] = df["close"].reindex(cal)
        h.update(sym.encode())
        h.update(np.round(df["close"].to_numpy(dtype=float), 6).tobytes())
    rep.fingerprint = h.hexdigest()[:16]
    return Market(pd.DataFrame(opens), pd.DataFrame(closes), tr), rep


# ---------------------------------------------------------------- statistics


def deflated_sharpe(returns: pd.Series, trial_sharpes: list[float]) -> float:
    """Bailey & Lopez de Prado (2014): P(true Sharpe > 0 | the best of N trials), daily units."""
    r = returns.dropna()
    n = len(r)
    sd = r.std(ddof=1)
    if n < 30 or sd <= 0 or len(trial_sharpes) < 2:
        return float("nan")
    sr = r.mean() / sd
    var_trials = float(np.var(trial_sharpes, ddof=1))
    nd = NormalDist()
    gamma = 0.5772156649
    N = len(trial_sharpes)
    sr0 = math.sqrt(var_trials) * ((1 - gamma) * nd.inv_cdf(1 - 1 / N) + gamma * nd.inv_cdf(1 - 1 / (N * math.e)))
    skew, kurt = float(r.skew()), float(r.kurt() + 3)
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr * sr))
    return float(nd.cdf((sr - sr0) * math.sqrt(n - 1) / denom))


def sharpe_diff_ci(
    a: pd.Series, b: pd.Series, n: int = 1000, block: int = 20, seed: int = 0
) -> tuple[float, float, float]:
    """Paired circular block bootstrap of Sharpe(a) - Sharpe(b) (both excess of the same cash series)."""
    df = pd.concat([a, b], axis=1).dropna().to_numpy()
    m = len(df)
    if m < 2 * block:
        return float("nan"), float("nan"), float("nan")

    def sh(x):
        s = x.std(ddof=1)
        return x.mean() / s * math.sqrt(252) if s > 0 else 0.0

    rng = np.random.default_rng(seed)
    nb = math.ceil(m / block)
    diffs = np.empty(n)
    for i in range(n):
        idx = ((rng.integers(0, m, nb)[:, None] + np.arange(block)) % m).ravel()[:m]
        s = df[idx]
        diffs[i] = sh(s[:, 0]) - sh(s[:, 1])
    return float(sh(df[:, 0]) - sh(df[:, 1])), float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def _slice(s: pd.Series, period: tuple[str, str | None]) -> pd.Series:
    return s.loc[period[0] : period[1]] if period[1] else s.loc[period[0] :]


# ---------------------------------------------------------------- tournament


@dataclass
class Entry:
    cand: Candidate
    sims: dict = field(default_factory=dict)  # (param, cost multiple, constraints label) -> SimResult
    periods: dict = field(default_factory=dict)  # period -> metrics (default param, 1x costs)
    selection: dict = field(default_factory=dict)  # train+validation metrics
    grid: dict = field(default_factory=dict)  # param -> selection Sharpe
    costs: dict = field(default_factory=dict)  # multiple -> selection Sharpe
    account: dict = field(default_factory=dict)  # period -> metrics under the account constraints
    walk_forward: dict = field(default_factory=dict)
    regimes: dict = field(default_factory=dict)
    bootstrap: dict = field(default_factory=dict)
    vs_spy: tuple = ()
    dsr: float = float("nan")
    checks: dict = field(default_factory=dict)
    decision: str = ""
    reasons: list[str] = field(default_factory=list)
    test: dict = field(default_factory=dict)
    test_account: dict = field(default_factory=dict)
    test_vs_spy: tuple = ()


class Tournament:
    def __init__(self, settings: Settings, mkt: Market, data: DataReport, cands: list[Candidate] | None = None):
        self.settings = settings
        self.mkt = Market(
            mkt.opens.loc[: SELECTION[1]].copy(), mkt.closes.loc[: SELECTION[1]].copy(), set(mkt.total_return)
        )
        self.data = data
        self.cost = settings.costs.per_side
        self.entries = {c.name: Entry(c) for c in (cands or candidates())}
        self.cash = None

    def _sim(self, e: Entry, param, mult: int = 1, constraints: Constraints = Constraints()):
        key = (param, mult, constraints.label)
        if key not in e.sims:
            w = e.cand.weights(self.mkt, param)
            missing = [c for c in w.columns if c not in self.mkt.closes]
            if missing:
                raise KeyError(f"{e.cand.name}: no data for {missing}")
            e.sims[key] = simulate(w, self.mkt.opens, self.mkt.closes, self.cost * mult, constraints)
        return e.sims[key]

    def run_selection(self) -> None:
        """Everything except the test period."""
        bench_cash = self.entries["BENCH_CASH"]
        self.cash = self._sim(bench_cash, None).returns
        for e in self.entries.values():
            c = e.cand
            base = self._sim(e, c.default)
            for p in ("train", "validation"):
                e.periods[p] = metrics(_slice(base.returns, PERIODS[p]), _slice(self.cash, PERIODS[p]), base)
            sel = _slice(base.returns, SELECTION)
            e.selection = metrics(sel, _slice(self.cash, SELECTION), base)
            e.bootstrap = block_bootstrap(sel - _slice(self.cash, SELECTION).reindex(sel.index).fillna(0.0))
            for name, rng in REGIMES.items():
                if "(test)" in name:
                    continue
                r = base.returns.loc[rng[0] : rng[1]]
                e.regimes[name] = {"return": float((1 + r).prod() - 1), "max_drawdown": max_drawdown(r)}
            acct = self._sim(e, c.default, 1, ACCOUNT_CONSTRAINTS)
            for p in ("train", "validation"):
                e.account[p] = metrics(_slice(acct.returns, PERIODS[p]), _slice(self.cash, PERIODS[p]), acct)
            if c.benchmark:
                continue
            for p in c.grid:
                s = self._sim(e, p)
                e.grid[p] = metrics(_slice(s.returns, SELECTION), _slice(self.cash, SELECTION), s)["sharpe"]
            for m in COST_MULTIPLES:
                s = self._sim(e, c.default, m)
                e.costs[m] = metrics(_slice(s.returns, SELECTION), _slice(self.cash, SELECTION), s)["sharpe"]
            e.walk_forward = self._walk_forward(e)
        spy = self._excess(self._sim(self.entries["BENCH_SPY"], None).returns, SELECTION)
        trial_sharpes = []
        for e in self.entries.values():
            if not e.cand.benchmark:
                for p in e.cand.grid or (e.cand.default,):
                    s = self._sim(e, p)
                    ex = self._excess(s.returns, SELECTION)
                    trial_sharpes.append(float(ex.mean() / ex.std(ddof=1)))
        self.n_trials = len(trial_sharpes)
        for e in self.entries.values():
            ex = self._excess(self._sim(e, e.cand.default).returns, SELECTION)
            e.vs_spy = sharpe_diff_ci(ex, spy)
            if not e.cand.benchmark:
                e.dsr = deflated_sharpe(ex, trial_sharpes)
        for e in self.entries.values():
            if not e.cand.benchmark:
                self._decide(e)

    def _excess(self, rets: pd.Series, period) -> pd.Series:
        r = _slice(rets, period)
        return r - _slice(self.cash, period).reindex(r.index).fillna(0.0)

    def _walk_forward(self, e: Entry) -> dict:
        """Each year, use the grid point with the best Sharpe on all earlier selection data."""
        if len(e.cand.grid) < 2:
            return {}
        sims = {p: self._sim(e, p) for p in e.cand.grid}
        chosen, pieces = {}, []
        for y in WF_YEARS:
            hist = (SELECTION[0], f"{y - 1}-12-31")
            best = max(
                e.cand.grid, key=lambda p: metrics(_slice(sims[p].returns, hist), _slice(self.cash, hist))["sharpe"]
            )
            chosen[y] = best
            pieces.append(sims[best].returns.loc[f"{y}-01-01" : f"{y}-12-31"])
        wf = pd.concat(pieces)
        span = (f"{WF_YEARS[0]}-01-01", f"{WF_YEARS[-1]}-12-31")
        fixed = _slice(self._sim(e, e.cand.default).returns, span)
        return {
            "chosen": chosen,
            "wf": metrics(wf, _slice(self.cash, span)),
            "default": metrics(fixed, _slice(self.cash, span)),
        }

    def _decide(self, e: Entry) -> None:
        a = ACCEPTANCE
        cash = {p: metrics(_slice(self.cash, PERIODS[p]))["cagr"] for p in ("train", "validation")}
        bench = max(self.entries[b].selection["sharpe"] for b in ("BENCH_SPY", "BENCH_6040"))
        spy_mdd = self.entries["BENCH_SPY"].selection["max_drawdown"]
        tr, va = e.periods["train"], e.periods["validation"]
        grid = list(e.grid.values())
        c = {
            "beats_cash_train_and_validation": all(
                e.periods[p]["cagr"] >= cash[p] + a["min_excess_cagr_vs_cash"] for p in cash
            ),
            "sharpe_train_and_validation": min(tr["sharpe"], va["sharpe"]) >= a["min_sharpe_each"],
            "drawdown_train_and_validation": min(tr["max_drawdown"], va["max_drawdown"]) >= a["max_drawdown_floor"],
            "bootstrap_sharpe_ci_above_zero": (not e.bootstrap.get("insufficient"))
            and e.bootstrap["sharpe_ci"][0] > a["min_bootstrap_sharpe_lo"],
            "deflated_sharpe": e.dsr >= a["min_deflated_sharpe_prob"],
            "parameter_robust": bool(grid) and min(grid) > 0 and max(grid) - min(grid) <= a["max_grid_sharpe_range"],
            "cost_robust": e.costs[1] > 0 and e.costs[3] >= a["min_cost_retention_3x"] * e.costs[1],
            "not_worse_than_simple_benchmarks": e.selection["sharpe"] >= bench - a["max_sharpe_shortfall_vs_bench"]
            and e.selection["max_drawdown"] > spy_mdd,
        }
        e.checks = c
        e.reasons = [k for k, ok in c.items() if not ok]
        e.decision = "ACCEPTED (paper candidate)" if not e.reasons else "REJECTED"

    def run_test(self, names: list[str]) -> None:
        """Compatibility entry point: the registered 2022+ holdout was consumed on 2026-10-12."""
        raise HoldoutConsumedError(
            "The 2022+ holdout is already consumed and sealed. New evaluation requires a separately "
            "preregistered holdout and owner authorization; use selection-only research."
        )


# ---------------------------------------------------------------- registry


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if not math.isfinite(float(x)) else round(float(x), 6)
    if isinstance(x, np.integer):
        return int(x)
    return x


def registry_records(t: Tournament, run_id: str, when: str, code: dict, tested: list[str]) -> list[dict]:
    out = []
    for e in t.entries.values():
        c = e.cand
        out.append(
            _clean(
                {
                    "run_id": run_id,
                    "recorded_at": when,
                    "strategy": c.name,
                    "version": c.version,
                    "family": c.family,
                    "benchmark": c.benchmark,
                    "hypothesis": c.hypothesis,
                    "rules": c.rules,
                    "default_param": c.default,
                    "grid": list(c.grid),
                    "assets": list(c.assets),
                    "notes": c.notes,
                    "code_commit": code.get("commit"),
                    "code_dirty": code.get("dirty"),
                    "data_fingerprint": t.data.fingerprint,
                    "data_problems": t.data.problems,
                    "price_only_assets": sorted(set(c.assets) - t.mkt.total_return),
                    "periods": PERIODS,
                    "cost_per_side": t.cost,
                    "cost_multiples": list(COST_MULTIPLES),
                    "metrics": e.periods,
                    "selection": e.selection,
                    "account_constrained": e.account,
                    "grid_sharpe": e.grid,
                    "cost_sharpe": e.costs,
                    "walk_forward": e.walk_forward,
                    "bootstrap": e.bootstrap,
                    "sharpe_vs_spy_ci": e.vs_spy,
                    "deflated_sharpe_prob": e.dsr,
                    "n_trials": t.n_trials,
                    "regimes": e.regimes,
                    "checks": e.checks,
                    "test_evaluated": c.name in tested,
                    "test": e.test,
                    "test_account_constrained": e.test_account,
                    "test_sharpe_vs_spy_ci": e.test_vs_spy,
                    "decision": e.decision or ("benchmark" if c.benchmark else ""),
                    "failed_checks": e.reasons,
                    "acceptance_rules": ACCEPTANCE,
                    "test_pass_rules": TEST_PASS,
                }
            )
        )
    return out


def append_registry(path: Path, records: list[dict]) -> int:
    """Append-only: earlier lines are never rewritten. Returns how many earlier test evaluations exist per run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    return len(records)


class HoldoutConsumedError(ValueError):
    """The current holdout cannot be evaluated again."""


def prior_test_evaluations(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                r = json.loads(line)
            except ValueError:
                raise ValueError(
                    f"registry line {number} is malformed; history must be reviewed, never rewritten"
                ) from None
            if (
                not isinstance(r, dict)
                or not isinstance(r.get("test_evaluated"), bool)
                or not isinstance(r.get("strategy"), str)
                or not r["strategy"]
            ):
                raise ValueError(f"registry line {number} has an invalid evaluation record")
            if r["test_evaluated"]:
                counts[r["strategy"]] = counts.get(r["strategy"], 0) + 1
    return counts


def run(settings: Settings, registry: Path, run_test: bool = False) -> tuple[Tournament, list[str], dict]:
    prior = prior_test_evaluations(registry)
    if run_test:
        raise HoldoutConsumedError("The 2022+ holdout is already consumed and sealed; use selection-only research")
    mkt, data = load_market(settings)
    t = Tournament(settings, mkt, data)
    t.run_selection()
    tested: list[str] = []
    when = datetime.now(UTC).isoformat(timespec="seconds")
    code = code_version(settings.base_dir)
    run_id = hashlib.sha256(f"{when}{code}".encode()).hexdigest()[:10]
    append_registry(registry, registry_records(t, run_id, when, code, tested))
    return t, tested, {"run_id": run_id, "recorded_at": when, "code": code, "prior_test_evaluations": prior}
