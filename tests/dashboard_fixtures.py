"""Synthetic, provider-shaped data for the research-dashboard tests (no network)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from agent_trading.dashboard.http import FetchError
from agent_trading.dashboard.providers import Quote
from tests.conftest import make_bars

AS_OF = date(2026, 10, 9)          # a Friday, NYSE open


def quarter_ends(n: int, last: date = date(2026, 6, 30)) -> list[date]:
    out, y, m = [], last.year, last.month
    for _ in range(n):
        d = (date(y, m % 12 + 1, 1) if m < 12 else date(y + 1, 1, 1)) - timedelta(days=1)
        out.append(d)
        m -= 3
        if m <= 0:
            m += 12
            y -= 1
    return out


def _fact(start: date | None, end: date, val: float, form: str = "10-Q", filed: date | None = None) -> dict:
    f = {"end": end.isoformat(), "val": val, "form": form, "filed": (filed or end + timedelta(days=40)).isoformat(),
         "accn": "0000000000-26-000001", "fy": end.year, "fp": "Q"}
    if start is not None:
        f["start"] = start.isoformat()
    return f


def make_facts(cik: int = 1, quarters: int = 16, rev0: float = 1e9, growth: float = 0.30, gross: float = 0.6,
               op: float = 0.2, fcf: float = 0.18, sbc: float = 0.04, shares: float = 1e8, dilution: float = 0.01,
               cash: float = 2e9, debt: float = 5e8, filed_lag: int = 40, omit: tuple[str, ...] = (),
               last: date = date(2026, 6, 30)) -> dict:
    """Company facts with steady quarterly growth (`growth` per year), newest quarter ending `last`."""
    ends = quarter_ends(quarters, last)
    q = (1 + growth) ** 0.25
    tags: dict[str, list] = {k: [] for k in ("Revenues", "GrossProfit", "OperatingIncomeLoss", "NetIncomeLoss",
                                             "NetCashProvidedByUsedInOperatingActivities",
                                             "PaymentsToAcquirePropertyPlantAndEquipment", "ShareBasedCompensation",
                                             "DepreciationDepletionAndAmortization")}
    dil = []
    for i, e in enumerate(ends):
        rev = rev0 / q ** i
        s = e - timedelta(days=90)
        filed = e + timedelta(days=filed_lag)
        vals = {"Revenues": rev, "GrossProfit": rev * gross, "OperatingIncomeLoss": rev * op,
                "NetIncomeLoss": rev * op * 0.8, "NetCashProvidedByUsedInOperatingActivities": rev * (fcf + 0.03),
                "PaymentsToAcquirePropertyPlantAndEquipment": rev * 0.03, "ShareBasedCompensation": rev * sbc,
                "DepreciationDepletionAndAmortization": rev * 0.02}
        for k, v in vals.items():
            tags[k].append(_fact(s, e, v, filed=filed))
        dil.append(_fact(s, e, shares / (1 + dilution) ** (i / 4), filed=filed))
    newest, filed0 = ends[0], ends[0] + timedelta(days=filed_lag)
    inst = {"CashAndCashEquivalentsAtCarryingValue": cash, "LongTermDebtNoncurrent": debt, "Assets": rev0 * 8,
            "AssetsCurrent": cash + rev0, "LiabilitiesCurrent": rev0 * 0.8, "StockholdersEquity": rev0 * 5}
    gaap = {k: {"units": {"USD": v}} for k, v in tags.items() if k not in omit}
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = {"units": {"shares": dil}}
    for k, v in inst.items():
        if k not in omit:
            gaap[k] = {"units": {"USD": [_fact(None, newest, v, filed=filed0)]}}
    dei = {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        _fact(None, newest + timedelta(days=30), shares, filed=filed0)]}}}
    return {"cik": cik, "entityName": f"Company {cik}", "facts": {"us-gaap": gaap, "dei": dei}}


class FakeHttp:
    def __init__(self):
        self.used = {}

    def usage(self):
        return {"requests": dict(self.used), "cache_hits": 0, "budgets": {}}


class FakeProviders:
    """Implements the Providers interface from in-memory tables. Missing entries raise FetchError."""

    def __init__(self, as_of: date = AS_OF):
        self.as_of = as_of
        self.http = FakeHttp()
        self.sp = {}            # ticker -> (cik, name, sector)
        self.listed = {}        # ticker -> (name, exchange, etf)
        self.ciks = {}          # ticker -> cik
        self.facts = {}         # cik -> facts
        self.bars = {}          # ticker -> DataFrame
        self.chains = {}        # ticker -> (under, rows)
        self.earnings = pd.DataFrame({"symbol": [], "reportDate": []})
        self.calls: list[str] = []
        self.fail: set[str] = set()

    def add(self, ticker, cik, sp=True, name=None, sector="Information Technology", drift=0.001, n=1300, seed=None,
            price=100.0, volume=2_000_000, **facts):
        name = name or f"{ticker} Inc. Common Stock"
        if sp:
            self.sp[ticker] = (cik, name, sector)
        self.listed[ticker] = (name, "Nasdaq", False)
        self.ciks[ticker] = cik
        self.facts[cik] = make_facts(cik, **facts)
        self.bars[ticker] = make_bars(n=n, start=price, drift=drift, seed=seed if seed is not None else cik,
                                      end=self.as_of.isoformat(), volume=volume)

    def _check(self, what):
        self.calls.append(what)
        if what in self.fail:
            raise FetchError(f"{what}: HTTP 503 after 3 attempts")

    def sec_tickers(self):
        self._check("sec_tickers")
        return pd.DataFrame([(t, cik, t, "Nasdaq") for t, cik in self.ciks.items()],
                            columns=["ticker", "cik", "name", "exchange"]).set_index("ticker")

    def share_frames(self, as_of):
        self._check("frames")
        out = {}
        for cik, f in self.facts.items():
            sh = f["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"][0]
            out[cik] = (sh["val"], sh["end"])
        return out

    def company_facts(self, cik):
        self._check(f"facts:{cik}")
        if cik not in self.facts:
            raise FetchError("data.sec.gov: HTTP 404")
        return self.facts[cik]

    def submissions(self, cik):
        return {"sic": "7372"}

    def symbol_directories(self):
        self._check("dirs")
        rows = [(t, n, ex, etf, False, "") for t, (n, ex, etf) in self.listed.items()]
        return pd.DataFrame(rows, columns=["ticker", "name", "exchange", "etf", "test_issue", "financial_status"]).set_index("ticker")

    def sp500(self):
        self._check("sp500")
        return pd.DataFrame([(t, n, s, cik) for t, (cik, n, s) in self.sp.items()],
                            columns=["ticker", "name", "sector", "cik"]).set_index("ticker")

    def quote(self, symbol):
        self._check(f"quote:{symbol}")
        df = self.bars.get(symbol)
        if df is None:
            raise FetchError("cdn-api.cboe.com: HTTP 403")
        last = df.index[-1].date()
        return Quote(symbol, float(df["close"].iloc[-1]), float(df["close"].iloc[-2]),
                     datetime(last.year, last.month, last.day, 16, 0), 30.0, "t")

    def history(self, symbol):
        self._check(f"history:{symbol}")
        if symbol not in self.bars:
            raise FetchError("cdn-api.cboe.com: HTTP 403")
        return self.bars[symbol].copy()

    def option_chain(self, symbol):
        self._check(f"chain:{symbol}")
        if symbol not in self.chains:
            raise FetchError("cdn-api.cboe.com: HTTP 403")
        return self.chains[symbol]

    def earnings_calendar(self):
        self._check("earnings")
        return self.earnings


def benchmarks(p: FakeProviders) -> None:
    for i, b in enumerate(("SPY", "IJH", "IWM")):
        p.bars[b] = make_bars(n=1300, start=400, drift=0.0004, seed=900 + i, end=p.as_of.isoformat(), volume=5e7)


def option_row(under: str, exp: date, strike: float, bid: float, ask: float, delta=0.55, oi=5000, vol=200,
               iv=0.3, theta=-0.05, root=None) -> dict:
    root = root or under.replace(".", "")
    occ = f"{root}{exp:%y%m%d}C{int(strike * 1000):08d}"
    return {"option": occ, "root": root, "expiration": exp, "type": "call", "strike": strike, "bid": bid, "ask": ask,
            "iv": iv, "open_interest": oi, "volume": vol, "delta": delta, "gamma": 0.01, "theta": theta, "vega": 0.3,
            "rho": 0.1, "last_trade_time": f"{AS_OF}T15:59:00", "last_price": (bid + ask) / 2}
