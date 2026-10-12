"""Point-in-time test of the Strategy A ranking model.

Each month-end, the universe is the S&P 500 list from the latest stored
snapshot on or before that date (not today's list). Only price-based factors
are scored: fundamentals are not available point-in-time, so quality and
valuation are absent and their weight is redistributed (exactly as the live
scanner does for missing factors).

Two views:
  * signal research: equal-weight the top N eligible names from the next open
    to the next month-end close, net of turnover costs; compared with SPY and
    with an equal-weight portfolio of all eligible members; plus the monthly
    rank information coefficient (IC) of the score against forward returns.
  * account view: the same ranking traded through the allocation engine under
    the real RiskEngine limits (trading P&L only).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from ..config import Settings
from ..data.universe import members_on
from ..strategies.scanner import features, score
from .portfolio import month_end_flags, run_allocation

LOOKBACK_BARS = 300  # enough for 12-1 momentum and the 200-day SMA


@dataclass
class MonthResult:
    signal_date: date
    members: int
    scored: int
    eligible: int
    picks: list[str]
    top_return: float
    universe_return: float
    spy_return: float
    turnover: float
    ic: float


@dataclass
class ScannerBacktest:
    months: list[MonthResult] = field(default_factory=list)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame([m.__dict__ for m in self.months]).set_index("signal_date")


def _rank_month(bars: dict[str, pd.DataFrame], spy: pd.DataFrame, members: list[str], d: pd.Timestamp,
                settings: Settings) -> pd.DataFrame:
    rows = {}
    bench = spy.loc[:d].iloc[-LOOKBACK_BARS:]
    for t in members:
        df = bars.get(t)
        if df is None:
            continue
        hist = df.loc[:d]
        if len(hist) < 260 or hist.index[-1] != d:  # must trade on the signal day
            continue
        f = features(hist.iloc[-LOOKBACK_BARS:], bench)
        if f is not None and not math.isnan(f["mom_12_1"]):
            rows[t] = f
    if not rows:
        return pd.DataFrame()
    return score(pd.DataFrame.from_dict(rows, orient="index"), None, settings.scanner.weights)


def _eligible(table: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    sc = settings.scanner
    return table[(table["setup"] == "bullish") & (table["close"] >= sc.min_price)
                 & (table["avg_dollar_volume"] >= sc.min_avg_dollar_volume) & (table["rsi"] < 75)]


def _fwd(df: pd.DataFrame, entry_day: pd.Timestamp, exit_day: pd.Timestamp) -> float | None:
    try:
        o = df.loc[entry_day, "open"]
        c = df.loc[:exit_day, "close"].iloc[-1]
    except KeyError:
        return None
    return float(c / o - 1) if o > 0 else None


def run_signal_backtest(bars: dict[str, pd.DataFrame], spy: pd.DataFrame, history: dict[date, list[str]],
                        settings: Settings, top_n: int = 10, start: date | None = None) -> ScannerBacktest:
    days = list(spy.index)
    flags = month_end_flags(days)
    month_ends = [d for d, f in zip(days, flags) if f]
    first_snap = min(history)
    out = ScannerBacktest()
    prev: set[str] = set()
    cost = settings.costs.per_side
    for i, d in enumerate(month_ends[:-1]):
        if d.date() < max(first_snap, start or first_snap):
            continue
        entry = days[days.index(d) + 1]
        exit_ = month_ends[i + 1]
        members = members_on(history, d.date())
        table = _rank_month(bars, spy, members, d, settings)
        if table.empty:
            continue
        elig = _eligible(table, settings)
        picks = list(elig.index[:top_n])
        fwd = {t: _fwd(bars[t], entry, exit_) for t in table.index}
        fwd = {t: r for t, r in fwd.items() if r is not None}
        top = [fwd[t] for t in picks if t in fwd]
        univ = [fwd[t] for t in elig.index if t in fwd]
        turnover = len(set(picks) - prev) / max(len(picks), 1) if picks else 0.0
        top_ret = (float(np.mean(top)) if top else 0.0) - 2 * cost * turnover
        both = pd.DataFrame({"s": table["composite"], "r": pd.Series(fwd)}).dropna()
        ic = float(both["s"].rank().corr(both["r"].rank())) if len(both) > 20 else float("nan")
        out.months.append(MonthResult(d.date(), len(members), len(table), len(elig), picks, top_ret,
                                      float(np.mean(univ)) if univ else 0.0,
                                      _fwd(spy, entry, exit_) or 0.0, turnover, ic))
        prev = set(picks)
    return out


def summarize(frame: pd.DataFrame) -> dict:
    def stats(r: pd.Series) -> dict:
        n = len(r)
        growth = float((1 + r).prod())
        sd = r.std()
        return {"months": n, "total": growth - 1,
                "cagr": growth ** (12 / n) - 1 if n and growth > 0 else float("nan"),
                "sharpe": float(math.sqrt(12) * r.mean() / sd) if sd and sd > 0 else float("nan"),
                "max_dd": float(((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min())}
    ic = frame["ic"].dropna()
    excess = frame["top_return"] - frame["spy_return"]
    return {
        "top": stats(frame["top_return"]),
        "universe": stats(frame["universe_return"]),
        "spy": stats(frame["spy_return"]),
        "excess_vs_spy_mean_monthly": float(excess.mean()),
        "excess_t_stat": float(excess.mean() / (excess.std() / math.sqrt(len(excess)))) if len(excess) > 2 and excess.std() > 0 else float("nan"),
        "hit_rate_vs_spy": float((excess > 0).mean()),
        "ic_mean": float(ic.mean()) if len(ic) else float("nan"),
        "ic_t_stat": float(ic.mean() / (ic.std() / math.sqrt(len(ic)))) if len(ic) > 2 and ic.std() > 0 else float("nan"),
        "avg_members": float(frame["members"].mean()),
        "avg_scored": float(frame["scored"].mean()),
        "avg_eligible": float(frame["eligible"].mean()),
        "avg_turnover": float(frame["turnover"].mean()),
    }


def run_account_backtest(bars: dict[str, pd.DataFrame], spy: pd.DataFrame, history: dict[date, list[str]],
                         settings: Settings, start, end, top_n: int = 10):
    """The same monthly ranking traded under the real RiskEngine limits (trading P&L only)."""
    def weights(d: pd.Timestamp, hist: dict[str, pd.DataFrame]) -> dict[str, float]:
        table = _rank_month(bars, spy, members_on(history, d.date()), d, settings)
        if table.empty:
            return {}
        picks = list(_eligible(table, settings).index[:top_n])
        return {t: 1.0 / top_n for t in picks}

    traded = {t: df for t, df in bars.items() if t != settings.scanner.benchmark}
    return run_allocation(traded, settings, weights, start, end, name="A-scanner (price factors)")
