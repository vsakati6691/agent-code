"""Pre-registered tournament candidates.

Each candidate states its hypothesis, rules and parameter grid BEFORE any
result is seen. `default` is the published or conventional parameter value;
the grid is only for sensitivity tests and walk-forward selection, never for
picking the best point. Weight functions use data up to each decision day's
close only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

GTAA7 = ["SPY", "EFA", "IEF", "DBC", "VNQ", "TLT", "GLD"]
RS_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ", "DBC", "GLD", "IEF", "TLT"]
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB"]
CASH = "BIL"


@dataclass
class Market:
    opens: pd.DataFrame
    closes: pd.DataFrame
    total_return: set[str]                     # symbols adjusted for dividends; the rest are price-only

    @property
    def month_end(self) -> pd.Series:
        idx = self.closes.index
        nxt = pd.Series(idx[1:].tolist() + [pd.NaT], index=idx)
        return pd.Series([n is pd.NaT or n.month != d.month for d, n in nxt.items()], index=idx)

    @property
    def week_end(self) -> pd.Series:
        idx = self.closes.index
        nxt = pd.Series(idx[1:].tolist() + [pd.NaT], index=idx)
        return pd.Series([n is pd.NaT or n.isocalendar()[1] != d.isocalendar()[1] for d, n in nxt.items()], index=idx)

    def monthly(self, cols: list[str]) -> pd.DataFrame:
        """Month-end closes (one row per month, indexed by the actual last trading day)."""
        return self.closes.loc[self.month_end.values, cols]


WeightFn = Callable[[Market, object], pd.DataFrame]


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str
    hypothesis: str
    rules: str
    fn: WeightFn
    default: object
    grid: tuple = ()
    assets: tuple[str, ...] = ()
    benchmark: bool = False
    version: str = "1"
    notes: str = ""

    def weights(self, mkt: Market, param=None) -> pd.DataFrame:
        return self.fn(mkt, self.default if param is None else param)


def _frame(mkt: Market, cols: list[str], rows: dict) -> pd.DataFrame:
    out = pd.DataFrame(np.nan, index=mkt.closes.index, columns=cols)
    for d, w in rows.items():
        out.loc[d] = [w.get(c, 0.0) for c in cols]
    return out


# ---------------------------------------------------------------- benchmarks

def buy_hold(symbol: str) -> WeightFn:
    def fn(mkt: Market, _):
        first = mkt.closes[symbol].first_valid_index()
        return _frame(mkt, [symbol], {first: {symbol: 1.0}})
    return fn


def fixed_mix(mix: dict[str, float]) -> WeightFn:
    def fn(mkt: Market, _):
        cols = list(mix)
        return _frame(mkt, cols, {d: mix for d in mkt.monthly(cols).index})
    return fn


# ---------------------------------------------------------------- candidates

def gtaa(mkt: Market, months: int) -> pd.DataFrame:
    """Faber: each asset 1/n while its month-end close is above its N-month SMA, else T-bills (BIL)."""
    m = mkt.monthly(GTAA7 + [CASH])
    sma = m[GTAA7].rolling(months).mean()
    rows = {}
    for d in m.index[months - 1:]:
        above = (m.loc[d, GTAA7] > sma.loc[d]).fillna(False)
        w = {a: 1 / len(GTAA7) for a in GTAA7 if above[a]}
        w[CASH] = 1 - sum(w.values())
        rows[d] = w
    return _frame(mkt, GTAA7 + [CASH], rows)


def spy_trend(mkt: Market, months: int) -> pd.DataFrame:
    """SPY while its month-end close is above its N-month SMA, else BIL."""
    m = mkt.monthly(["SPY", CASH])
    sma = m["SPY"].rolling(months).mean()
    rows = {d: ({"SPY": 1.0} if m.loc[d, "SPY"] > sma.loc[d] else {CASH: 1.0}) for d in m.index[months - 1:]}
    return _frame(mkt, ["SPY", CASH], rows)


def dual_momentum(mkt: Market, months: int) -> pd.DataFrame:
    """Antonacci GEM: best of SPY/EFA by N-month return if it beats BIL, else IEF."""
    m = mkt.monthly(["SPY", "EFA", "IEF", CASH])
    ret = m / m.shift(months) - 1
    rows = {}
    for d in m.index[months:]:
        best = "SPY" if ret.loc[d, "SPY"] >= ret.loc[d, "EFA"] else "EFA"
        rows[d] = {best: 1.0} if ret.loc[d, best] > ret.loc[d, CASH] else {"IEF": 1.0}
    return _frame(mkt, ["SPY", "EFA", "IEF", CASH], rows)


def relative_strength(universe: list[str], top: int) -> WeightFn:
    def fn(mkt: Market, months: int) -> pd.DataFrame:
        """Top-k by N-month return among assets that beat BIL; empty slots in BIL."""
        cols = [c for c in universe if c in mkt.closes]
        m = mkt.monthly(cols + [CASH])
        ret = m / m.shift(months) - 1
        rows = {}
        for d in m.index[months:]:
            r = ret.loc[d, cols].dropna()
            winners = [a for a in r.sort_values(ascending=False).index[:top] if r[a] > ret.loc[d, CASH]]
            w = {a: 1 / top for a in winners}
            w[CASH] = 1 - sum(w.values())
            rows[d] = w
        return _frame(mkt, cols + [CASH], rows)
    return fn


def vol_target_trend(mkt: Market, target: float) -> pd.DataFrame:
    """SPY 10-month trend filter, sized weekly to target annual volatility (20-day realised), max 100%."""
    c = mkt.closes["SPY"]
    vol = c.pct_change().rolling(20).std() * np.sqrt(252)
    me = mkt.month_end
    monthly = c[me.values]
    above = (monthly > monthly.rolling(10).mean()).reindex(c.index).ffill()
    rows = {}
    for d in c.index[mkt.week_end.values]:
        if pd.isna(above.get(d)) or pd.isna(vol.get(d)) or vol[d] <= 0:
            continue
        w = min(1.0, target / vol[d]) if above[d] else 0.0
        rows[d] = {"SPY": w, CASH: 1 - w}
    return _frame(mkt, ["SPY", CASH], rows)


def rsi2_reversion(mkt: Market, threshold: float) -> pd.DataFrame:
    """Connors RSI(2): buy SPY when RSI2 < threshold and close > 200-day SMA; exit when close > 5-day SMA."""
    c = mkt.closes["SPY"]
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 2, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 2, adjust=False).mean()
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    sma200, sma5 = c.rolling(200).mean(), c.rolling(5).mean()
    rows, inside = {}, False
    for d in c.index[200:]:
        if not inside and rsi[d] < threshold and c[d] > sma200[d]:
            inside = True
            rows[d] = {"SPY": 1.0}
        elif inside and c[d] > sma5[d]:
            inside = False
            rows[d] = {CASH: 1.0}
    return _frame(mkt, ["SPY", CASH], rows)


def combo(mkt: Market, months: int) -> pd.DataFrame:
    """Half GTAA, half SPY trend (two independently tested signals, same N)."""
    a, b = gtaa(mkt, months), spy_trend(mkt, months)
    cols = list(dict.fromkeys([*a.columns, *b.columns]))
    a, b = a.reindex(columns=cols), b.reindex(columns=cols)
    both = a.notna().any(axis=1) | b.notna().any(axis=1)
    a, b = a.ffill().fillna(0.0), b.ffill().fillna(0.0)
    out = (0.5 * a + 0.5 * b).where(both)
    # only once both sleeves have started
    started = (a.sum(axis=1) > 0) & (b.sum(axis=1) > 0)
    return out.where(started)


def candidates() -> list[Candidate]:
    return [
        Candidate("BENCH_SPY", "benchmark", "Broad US equity buy-and-hold.", "Buy SPY once; hold.",
                  buy_hold("SPY"), None, benchmark=True, assets=("SPY",)),
        Candidate("BENCH_CASH", "benchmark", "T-bill ETF buy-and-hold (investable cash).", "Buy BIL once; hold.",
                  buy_hold(CASH), None, benchmark=True, assets=(CASH,)),
        Candidate("BENCH_6040", "benchmark", "Classic balanced portfolio.", "60% SPY / 40% IEF, rebalanced monthly.",
                  fixed_mix({"SPY": 0.6, "IEF": 0.4}), None, benchmark=True, assets=("SPY", "IEF")),
        Candidate("BENCH_EW7", "benchmark", "The GTAA assets without timing (isolates the value of the trend rule).",
                  "1/7 each of the 7 GTAA ETFs, rebalanced monthly.",
                  fixed_mix({a: 1 / 7 for a in GTAA7}), None, benchmark=True, assets=tuple(GTAA7)),
        Candidate("GTAA", "trend (multi-asset)",
                  "Asset-class trend timing cuts drawdowns with a modest return cost (Faber 2007).",
                  "Month-end: hold each of SPY, EFA, IEF, DBC, VNQ, TLT, GLD at 1/7 while above its N-month SMA; rest in BIL.",
                  gtaa, 10, (6, 8, 10, 12), tuple(GTAA7 + [CASH])),
        Candidate("SPY_TREND", "trend (single index)",
                  "A 10-month SMA filter on US equities avoids the worst of bear markets.",
                  "Month-end: SPY if above its N-month SMA, else BIL.",
                  spy_trend, 10, (6, 8, 10, 12), ("SPY", CASH)),
        Candidate("DUAL_MOM", "momentum (absolute + relative)",
                  "Global equity momentum: own the stronger of US/international equities only when it beats T-bills (Antonacci).",
                  "Month-end: best of SPY/EFA by N-month return if it beats BIL, else IEF.",
                  dual_momentum, 12, (6, 9, 12), ("SPY", "EFA", "IEF", CASH)),
        Candidate("RS_TOP3", "momentum (cross-asset relative strength)",
                  "Assets with the strongest recent returns keep outperforming over the next month (time-series + cross-sectional momentum).",
                  "Month-end: top 3 of 10 ETFs by N-month return, each 1/3 if it beats BIL; empty slots in BIL.",
                  relative_strength(RS_UNIVERSE, 3), 6, (3, 6, 9, 12), tuple(RS_UNIVERSE + [CASH]),
                  notes="QQQ, IWM, EEM, VNQ, DBC, GLD, IEF, TLT, SPY, EFA. EEM, DBC and GLD price-only where no dividends are on file."),
        Candidate("SECTOR_RS", "momentum (sector rotation)",
                  "Sector momentum: the strongest sectors keep leading for a month.",
                  "Month-end: top 3 of 9 sector SPDRs by N-month return, each 1/3 if it beats BIL; empty slots in BIL.",
                  relative_strength(SECTORS, 3), 6, (3, 6, 9, 12), tuple(SECTORS + [CASH]),
                  notes="PRICE-ONLY sector data (no dividends on file): understates returns by roughly 1.5-2.5%/yr."),
        Candidate("VOL_TREND", "trend + volatility targeting",
                  "Scaling equity exposure to a volatility target improves risk-adjusted returns (Moreira-Muir; disputed by Cederburg et al.).",
                  "Weekly: SPY weight = min(1, target / 20-day realised vol) while SPY is above its 10-month SMA, else 0; rest in BIL.",
                  vol_target_trend, 0.10, (0.08, 0.10, 0.12, 0.15), ("SPY", CASH)),
        Candidate("RSI2_MR", "mean reversion",
                  "Short-term oversold pullbacks in an uptrend revert within days (Connors RSI-2).",
                  "Daily: buy SPY when RSI(2) < threshold and close > 200-day SMA; sell when close > 5-day SMA; otherwise BIL.",
                  rsi2_reversion, 10.0, (5.0, 10.0, 15.0, 20.0), ("SPY", CASH)),
        Candidate("COMBO_GTAA_TREND", "combination",
                  "Two independently tested trend signals combined diversify each other's whipsaws.",
                  "50% GTAA(N) + 50% SPY_TREND(N), rebalanced at month-end.",
                  combo, 10, (8, 10, 12), tuple(GTAA7 + [CASH])),
    ]
