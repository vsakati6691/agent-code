"""Markdown report for a tournament run."""
from __future__ import annotations

import math

from .engine import ACCOUNT_CONSTRAINTS
from .tournament import ACCEPTANCE, PERIODS, REGIMES, TEST_PASS, Tournament


def _p(x, d=1):
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:+.{d}%}"


def _f(x, d=2):
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{d}f}"


def _row(name, m):
    if not m or "cagr" not in m:
        return f"| {name} | n/a |  |  |  |  |  |  |  |"
    return (f"| {name} | {_p(m['cagr'])} | {_f(m['sharpe'])} | {_f(m['sortino'])} | {_p(m['max_drawdown'])} | "
            f"{_p(m['vol'])} | {m.get('trades', 'n/a')} | {_f(m.get('turnover_per_year'), 1)} | {_p(m.get('avg_exposure'), 0)} |")


HEAD = ("| Strategy | CAGR | Sharpe | Sortino | Max DD | Vol | Trades | Turnover/yr | Exposure |\n"
        "|---|---|---|---|---|---|---|---|---|")


def render(t: Tournament, tested: list[str], meta: dict) -> str:
    es = t.entries
    out = [f"# Strategy tournament: {meta['recorded_at'][:10]}", "",
           "> Research output, not investment advice. Backtests are evidence with limits, not proof of future returns.", "",
           f"Run `{meta['run_id']}` · code `{meta['code']['commit']}`{' (uncommitted changes)' if meta['code']['dirty'] else ''} · "
           f"data fingerprint `{t.data.fingerprint}` · cost {t.cost * 1e4:.1f} bps per side "
           f"(slippage + half spread; Robinhood commission $0) · {t.n_trials} strategy/parameter trials", ""]
    out += ["## Method", "",
            "- **Timing:** signals from data up to day *t*'s close; trades at day *t+1*'s open. Long-only, no leverage, and no buys beyond cash.",
            "- **Prices:** Robinhood daily bars, split-adjusted. Total return (dividends reinvested) where dividends are on file; other assets are price-only (flagged).",
            "- **Idle cash** earns 0%. Strategies that go to \"cash\" buy BIL, a T-bill ETF.",
            "- **Sharpe and Sortino** are computed on returns in excess of BIL.",
            f"- **Periods** (fixed in code before any result): train {PERIODS['train'][0]}..{PERIODS['train'][1]}, "
            f"validation {PERIODS['validation'][0]}..{PERIODS['validation'][1]}, test {PERIODS['test'][0]}..end.",
            "  - Selection uses train and validation only.",
            "  - The test period is evaluated once, only for the benchmarks, the incumbent (GTAA = live Strategy C) and accepted candidates.",
            "- **Robustness:**",
            "  - every parameter in a pre-registered grid;",
            "  - 1×/2×/3× costs;",
            "  - yearly walk-forward parameter selection (2011–2021);",
            "  - a block-bootstrap Sharpe interval;",
            f"  - a deflated Sharpe ratio over all {t.n_trials} trials;",
            "  - a paired bootstrap of the Sharpe difference vs SPY.",
            f"- **Account-constrained** runs apply the real account's hard limits: {ACCOUNT_CONSTRAINTS.label}.",
            "- **Acceptance rules (all must hold):** " + "; ".join(f"`{k}` = {v}" for k, v in ACCEPTANCE.items()) + ".",
            ""]
    if t.data.problems:
        out += ["**Data checks:**", ""] + [f"- {p}" for p in t.data.problems] + [""]
    out += ["## Train + validation (selection data)", "", HEAD]
    for n, e in es.items():
        out.append(_row(n, e.selection))
    out += ["", "### By period", "", "| Strategy | Train CAGR | Train Sharpe | Train MDD | Val CAGR | Val Sharpe | Val MDD | Sharpe − SPY (95% CI) |",
            "|---|---|---|---|---|---|---|---|"]
    for n, e in es.items():
        tr, va = e.periods["train"], e.periods["validation"]
        d = e.vs_spy
        ci = "—" if n == "BENCH_SPY" or not d else f"{d[0]:+.2f} ({d[1]:+.2f} to {d[2]:+.2f})"
        out.append(f"| {n} | {_p(tr['cagr'])} | {_f(tr['sharpe'])} | {_p(tr['max_drawdown'])} | {_p(va['cagr'])} | "
                   f"{_f(va['sharpe'])} | {_p(va['max_drawdown'])} | {ci} |")
    out += ["", "### Robustness (train + validation)", "",
            "| Candidate | Grid Sharpe (default **bold**) | Sharpe 1×/2×/3× costs | Walk-forward Sharpe vs fixed default (2011–21) | Bootstrap Sharpe 95% CI | Deflated Sharpe P | Decision |",
            "|---|---|---|---|---|---|---|"]
    for n, e in es.items():
        c = e.cand
        if c.benchmark:
            continue
        grid = ", ".join((f"**{p}: {s:.2f}**" if p == c.default else f"{p}: {s:.2f}") for p, s in e.grid.items())
        costs = " / ".join(f"{e.costs[m]:.2f}" for m in sorted(e.costs))
        wf = e.walk_forward
        wf_s = f"{wf['wf']['sharpe']:.2f} vs {wf['default']['sharpe']:.2f}" if wf else "n/a"
        b = e.bootstrap
        bci = "n/a" if b.get("insufficient") else f"{b['sharpe_ci'][0]:.2f} to {b['sharpe_ci'][1]:.2f}"
        out.append(f"| {n} | {grid} | {costs} | {wf_s} | {bci} | {_f(e.dsr)} | {e.decision} |")
    out += ["", "**Failed acceptance checks:**", ""]
    for n, e in es.items():
        if not e.cand.benchmark:
            out.append(f"- {n}: " + (", ".join(e.reasons) if e.reasons else "none"))
    out += ["", "### Stress windows (return / max drawdown inside the window)", ""]
    names = [k for k in REGIMES if "(test)" not in k]
    out += ["| Strategy | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for n, e in es.items():
        out.append(f"| {n} | " + " | ".join(f"{_p(e.regimes[k]['return'], 0)} / {_p(e.regimes[k]['max_drawdown'], 0)}"
                                           for k in names) + " |")
    out += ["", "### Under the real account's limits ($1,000; train + validation)", "",
            f"Constraints: {ACCOUNT_CONSTRAINTS.label}. The $100-per-position cap means single-ETF strategies can "
            "invest only 10% of the account. Dollar figures are per year on $1,000.", "",
            "| Strategy | Train CAGR | Val CAGR | ≈ $/yr on $1,000 (val) | Val max DD | Avg exposure (val) |", "|---|---|---|---|---|---|"]
    for n, e in es.items():
        tr, va = e.account["train"], e.account["validation"]
        out.append(f"| {n} | {_p(tr['cagr'])} | {_p(va['cagr'])} | ${1000 * va['cagr']:,.0f} | {_p(va['max_drawdown'])} | "
                   f"{_p(va.get('avg_exposure'), 0)} |")
    if tested:
        prior = meta.get("prior_test_evaluations", {})
        out += ["", "## Final test (out of sample, evaluated once)", "",
                f"Evaluated for: {', '.join(tested)}. Not evaluated (remains untouched): "
                f"{', '.join(n for n in es if n not in tested)}.", ""]
        if any(prior.get(n) for n in tested):
            out += ["> ⚠ Earlier registry runs already evaluated the test period for: "
                    + ", ".join(f"{n} ({prior[n]}×)" for n in tested if prior.get(n))
                    + ". These test results are no longer fully untouched.", ""]
        out += ["> ⚠ The earlier research study (2026-10-12, outside this pipeline) viewed 2008–2026 for GTAA and SPY trend, so "
                "for those two families the test period was not untouched by the researcher.", ""]
        out += [HEAD]
        for n in tested:
            out.append(_row(n, es[n].test))
        out += ["", "| Strategy | Sharpe − SPY, test (95% CI) | Account-limited CAGR | Account-limited max DD | " +
                " | ".join(k for k in REGIMES if "(test)" in k) + " | Decision |", "|---|---|---|---|---|---|---|"]
        for n in tested:
            e = es[n]
            d = e.test_vs_spy
            ci = "—" if n == "BENCH_SPY" or not d else f"{d[0]:+.2f} ({d[1]:+.2f} to {d[2]:+.2f})"
            reg = " | ".join(f"{_p(e.regimes[k]['return'], 0)} / {_p(e.regimes[k]['max_drawdown'], 0)}"
                             for k in REGIMES if "(test)" in k)
            out.append(f"| {n} | {ci} | {_p(e.test_account.get('cagr'))} | {_p(e.test_account.get('max_drawdown'))} | {reg} | "
                       f"{e.decision or 'benchmark'} |")
        out += ["", f"Test pass rules for accepted candidates: {TEST_PASS}."]
    out += ["", "## Candidates (pre-registered)", ""]
    for n, e in es.items():
        c = e.cand
        out.append(f"- **{n}** ({c.family}). *Hypothesis:* {c.hypothesis} *Rules:* {c.rules}"
                   + (f" Default {c.default}; grid {list(c.grid)}." if c.grid else "")
                   + (f" *Note:* {c.notes}" if c.notes else ""))
    out += ["", "## Not tested, and why", "",
            "- **Fundamental quality and earnings revisions:** no point-in-time fundamentals or estimate history are available. Robinhood `preview_scan` is current-only. Testing on today's fundamentals would be look-ahead.",
            "- **News and earnings catalysts:** no point-in-time news archive with reliable timestamps. Earnings drift for large caps is weak since 2006 (Martineau 2022).",
            "- **Single-stock momentum on the S&P 500:** tested by `evaluate-scanner` on point-in-time constituents (2019–2025). It did not beat SPY, and its rank IC was ≈ 0. It is not repeated here, because today's survivors would add survivorship bias.",
            "- **Leveraged / inverse ETFs (Strategy B's TQQQ/SQQQ):** prohibited for the account. `evaluate-desk` showed a trading edge near zero per instrument, with Sharpe 95% intervals that include zero."]
    return "\n".join(out) + "\n"
