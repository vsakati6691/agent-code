"""Synthetic, provider-shaped data for the research-dashboard tests (no network)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from agent_trading.dashboard.http import FetchError
from agent_trading.dashboard.providers import Quote
from tests.conftest import make_bars

AS_OF = date(2026, 10, 9)  # a Friday, NYSE open


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
    f = {
        "end": end.isoformat(),
        "val": val,
        "form": form,
        "filed": (filed or end + timedelta(days=40)).isoformat(),
        "accn": "0000000000-26-000001",
        "fy": end.year,
        "fp": "Q",
    }
    if start is not None:
        f["start"] = start.isoformat()
    return f


def make_facts(
    cik: int = 1,
    quarters: int = 16,
    rev0: float = 1e9,
    growth: float = 0.30,
    gross: float = 0.6,
    op: float = 0.2,
    fcf: float = 0.18,
    sbc: float = 0.04,
    shares: float = 1e8,
    dilution: float = 0.01,
    cash: float = 2e9,
    debt: float = 5e8,
    filed_lag: int = 40,
    omit: tuple[str, ...] = (),
    last: date = date(2026, 6, 30),
) -> dict:
    """Company facts with steady quarterly growth (`growth` per year), newest quarter ending `last`."""
    ends = quarter_ends(quarters, last)
    q = (1 + growth) ** 0.25
    tags: dict[str, list] = {
        k: []
        for k in (
            "Revenues",
            "GrossProfit",
            "OperatingIncomeLoss",
            "NetIncomeLoss",
            "NetCashProvidedByUsedInOperatingActivities",
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "ShareBasedCompensation",
            "DepreciationDepletionAndAmortization",
        )
    }
    dil = []
    for i, e in enumerate(ends):
        rev = rev0 / q**i
        s = e - timedelta(days=90)
        filed = e + timedelta(days=filed_lag)
        vals = {
            "Revenues": rev,
            "GrossProfit": rev * gross,
            "OperatingIncomeLoss": rev * op,
            "NetIncomeLoss": rev * op * 0.8,
            "NetCashProvidedByUsedInOperatingActivities": rev * (fcf + 0.03),
            "PaymentsToAcquirePropertyPlantAndEquipment": rev * 0.03,
            "ShareBasedCompensation": rev * sbc,
            "DepreciationDepletionAndAmortization": rev * 0.02,
        }
        for k, v in vals.items():
            tags[k].append(_fact(s, e, v, filed=filed))
        dil.append(_fact(s, e, shares / (1 + dilution) ** (i / 4), filed=filed))
    newest, filed0 = ends[0], ends[0] + timedelta(days=filed_lag)
    inst = {
        "CashAndCashEquivalentsAtCarryingValue": cash,
        "LongTermDebtNoncurrent": debt,
        "Assets": rev0 * 8,
        "AssetsCurrent": cash + rev0,
        "LiabilitiesCurrent": rev0 * 0.8,
        "StockholdersEquity": rev0 * 5,
    }
    gaap = {k: {"units": {"USD": v}} for k, v in tags.items() if k not in omit}
    gaap["WeightedAverageNumberOfDilutedSharesOutstanding"] = {"units": {"shares": dil}}
    for k, v in inst.items():
        if k not in omit:
            gaap[k] = {"units": {"USD": [_fact(None, newest, v, filed=filed0)]}}
    dei = {
        "EntityCommonStockSharesOutstanding": {
            "units": {"shares": [_fact(None, newest + timedelta(days=30), shares, filed=filed0)]}
        }
    }
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
        self.sp = {}  # ticker -> (cik, name, sector)
        self.listed = {}  # ticker -> (name, exchange, etf)
        self.ciks = {}  # ticker -> cik
        self.facts = {}  # cik -> facts
        self.bars = {}  # ticker -> DataFrame
        self.chains = {}  # ticker -> (under, rows)
        self.earnings = pd.DataFrame({"symbol": [], "reportDate": []})
        self.calls: list[str] = []
        self.subs: dict = {}  # cik -> submissions payload (filings), default only an SIC code
        self.fail: set[str] = set()

    def add(
        self,
        ticker,
        cik,
        sp=True,
        name=None,
        sector="Information Technology",
        drift=0.001,
        n=1300,
        seed=None,
        price=100.0,
        volume=2_000_000,
        **facts,
    ):
        name = name or f"{ticker} Inc. Common Stock"
        if sp:
            self.sp[ticker] = (cik, name, sector)
        self.listed[ticker] = (name, "Nasdaq", False)
        self.ciks[ticker] = cik
        self.facts[cik] = make_facts(cik, **facts)
        self.bars[ticker] = make_bars(
            n=n,
            start=price,
            drift=drift,
            seed=seed if seed is not None else cik,
            end=self.as_of.isoformat(),
            volume=volume,
        )

    def _check(self, what):
        self.calls.append(what)
        if what in self.fail:
            raise FetchError(f"{what}: HTTP 503 after 3 attempts")

    def sec_tickers(self):
        self._check("sec_tickers")
        return pd.DataFrame(
            [(t, cik, t, "Nasdaq") for t, cik in self.ciks.items()], columns=["ticker", "cik", "name", "exchange"]
        ).set_index("ticker")

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
        self._check(f"subs:{cik}")
        return self.subs.get(cik, {"sic": "7372"})

    def symbol_directories(self):
        self._check("dirs")
        rows = [(t, n, ex, etf, False, "") for t, (n, ex, etf) in self.listed.items()]
        return pd.DataFrame(
            rows, columns=["ticker", "name", "exchange", "etf", "test_issue", "financial_status"]
        ).set_index("ticker")

    def sp500(self):
        self._check("sp500")
        return pd.DataFrame(
            [(t, n, s, cik) for t, (cik, n, s) in self.sp.items()], columns=["ticker", "name", "sector", "cik"]
        ).set_index("ticker")

    def quote(self, symbol):
        self._check(f"quote:{symbol}")
        df = self.bars.get(symbol)
        if df is None:
            raise FetchError("cdn-api.cboe.com: HTTP 403")
        last = df.index[-1].date()
        return Quote(
            symbol,
            float(df["close"].iloc[-1]),
            float(df["close"].iloc[-2]),
            datetime(last.year, last.month, last.day, 16, 0),
            30.0,
            f"{last}T22:00:00+00:00",
        )

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


def option_row(
    under: str,
    exp: date,
    strike: float,
    bid: float,
    ask: float,
    delta=0.55,
    oi=5000,
    vol=200,
    iv=0.3,
    theta=-0.05,
    root=None,
) -> dict:
    root = root or under.replace(".", "")
    occ = f"{root}{exp:%y%m%d}C{int(strike * 1000):08d}"
    return {
        "option": occ,
        "root": root,
        "expiration": exp,
        "type": "call",
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "iv": iv,
        "open_interest": oi,
        "volume": vol,
        "delta": delta,
        "gamma": 0.01,
        "theta": theta,
        "vega": 0.3,
        "rho": 0.1,
        "last_trade_time": f"{AS_OF}T15:59:00",
        "last_price": (bid + ask) / 2,
    }


FAKE_AI_LARGE = tuple(f"AIL{i}" for i in range(7))  # market caps about $15B to $45B
FAKE_AI_MID = tuple(f"AIM{i}" for i in range(6))  # about $3B to $8B
FAKE_AI_UNIVERSE = (
    tuple((t, "Accelerators and AI chips") for t in FAKE_AI_LARGE)
    + tuple((t, "Power, cooling and electrical") for t in FAKE_AI_MID)
    + (("AIGONE", "Memory and storage"),)
)  # never listed: shows an unresolved name


def add_ai_names(p: FakeProviders, fillers: int = 10) -> None:
    """Fake AI-exposed companies with controlled market caps, plus filler S&P 500 members so that the 20th-largest
    S&P 500 market cap exists (the top-20 bar needs 20 members with data)."""
    for i in range(fillers):
        p.add(f"F{i:02d}", 200 + i, growth=0.01, drift=0.0002, shares=3e8)
    for i, t in enumerate(FAKE_AI_LARGE + FAKE_AI_MID):
        cik = 500 + i
        large = t in FAKE_AI_LARGE
        target = 15e9 + 5e9 * i if large else 3e9 + 1e9 * (i - len(FAKE_AI_LARGE))
        p.add(t, cik, sp=False, shares=1e8, drift=0.0004, growth=0.10 + 0.03 * i)
        px = float(p.bars[t]["close"].iloc[-1])
        p.facts[cik] = make_facts(cik, growth=0.10 + 0.03 * i, shares=target / px)


def demo_site(tmp_path, two_weeks: bool = True):
    """Build a complete offline site (two weekly snapshots, options, watchlist, AI lists) and return (data_dir, out_dir)."""
    from unittest import mock

    from agent_trading.dashboard import options as opt
    from agent_trading.dashboard import spec, tracking
    from agent_trading.dashboard.pipeline import run
    from agent_trading.dashboard.site import build_site
    from agent_trading.dashboard.store import Store
    from agent_trading.dashboard.tradability import Tradability
    from agent_trading.dashboard.watchlist import WatchlistConfig
    from tests.test_dashboard_v2 import chains_for

    def providers(as_of, tweak):
        p = FakeProviders(as_of)
        benchmarks(p)
        sectors = ["Information Technology", "Health Care", "Industrials"]
        for i in range(12):
            p.add(
                f"S{i:02d}",
                100 + i,
                growth=0.05 + 0.04 * i + (tweak if i % 4 == 0 else 0),
                drift=0.0004 + 0.0001 * i,
                shares=5e8,
                sector=sectors[i % 3],
            )
        p.add("MIDA", 300, sp=False, shares=4e7, drift=0.0003, growth=0.25)
        p.add("SPEC", 301, sp=False, shares=8e6, drift=0.0003, growth=0.50, cash=1e8)
        p.add("SLOW", 302, sp=False, shares=8e6, drift=0.0003, growth=0.05)
        p.add("NEWQ", 303, sp=False, shares=8e6, drift=0.0003, growth=0.30, quarters=2)
        add_ai_names(p)
        for t, name, start, drift, vol, seed in (
            ("QQQX", "Invesco QQQ Trust, Series 1", 300, 0.0004, 0.01, 77),
            ("LEVX", "ProShares UltraPro QQQ", 50, 0.0008, 0.03, 78),
            ("ODDF", "Some Unusual Strategy Fund", 20, 0.0002, 0.01, 80),
        ):
            p.listed[t] = (name, "Nasdaq", True)
            p.bars[t] = make_bars(n=1300, start=start, drift=drift, vol=vol, seed=seed, end=as_of.isoformat())
        p.bars["QQQ"] = make_bars(n=1300, start=300, drift=0.0004, seed=79, end=as_of.isoformat())
        for cik in (100 + i for i in range(12)):  # S&P names: quarterly 8-K item 2.02 earnings releases
            p.subs[cik] = {
                "sic": "7372",
                "filings": {
                    "recent": {
                        "form": ["8-K", "10-Q", "8-K", "8-K", "10-Q", "8-K", "10-K", "8-K"],
                        "filingDate": [
                            "2026-07-30",
                            "2026-07-31",
                            "2026-06-02",
                            "2026-04-29",
                            "2026-04-30",
                            "2026-01-28",
                            "2026-02-15",
                            "2025-10-29",
                        ],
                        "items": ["2.02,9.01", "", "5.07", "2.02,9.01", "", "2.02", "", "2.02,9.01"],
                    }
                },
            }
        p.earnings = __import__("pandas").DataFrame(
            {"symbol": ["S04", "S08"], "reportDate": [as_of + timedelta(days=21), as_of + timedelta(days=40)]}
        )
        return p

    data, out = tmp_path / "data", tmp_path / "site"
    store = Store(data)
    wl = WatchlistConfig(("MIDA", "QQQX", "LEVX", "NEWQ", "ODDF", "NOPE"), "2026-10-14", "fixture")
    dates = [(AS_OF - timedelta(days=7), 0.0), (AS_OF, 0.12)] if two_weeks else [(AS_OF, 0.0)]
    snaps = []
    for as_of, tweak in dates:
        p = providers(as_of, tweak)
        t = Tradability.all_tradable(list(p.listed), (as_of - timedelta(days=1)).isoformat())
        with mock.patch.object(spec, "AI_UNIVERSE", FAKE_AI_UNIVERSE):
            snap = run(p, as_of, store.latest(before=str(as_of)), options_enabled=False, tradability=t, watchlist=wl)
        snap["options"] = {"enabled": True, "status": "ok", **opt.build_horizons(chains_for(6), as_of, {})}
        from agent_trading.dashboard import speculative

        focus_chains = {}
        for ticker in speculative.targets(snap):
            rows = []
            for days in (30, 60):
                for kind in ("call", "put"):
                    item = option_row(ticker, as_of + timedelta(days=days), 100, 2.0, 2.1, delta=0.3, iv=0.4)
                    if kind == "put":
                        item.update(type="put", delta=-0.3, option=f"{ticker}{item['expiration']:%y%m%d}P00100000")
                    rows.append(item)
            focus_chains[ticker] = (
                {
                    "symbol": ticker,
                    "close": 100,
                    "last_trade_time": f"{as_of}T16:00:00",
                    "timestamp": f"{as_of} 22:00:00",
                },
                rows,
            )
        snap["speculative"] = speculative.build(
            focus_chains,
            as_of,
            {ticker: [{"date": as_of + timedelta(days=21), "event": "earnings"}] for ticker in focus_chains},
        )
        store.write_snapshot(snap, "fixture")
        snaps.append(snap)
    store.write_json("tracking.json", tracking.track(snaps, {k: v["close"] for k, v in p.bars.items()}, AS_OF))
    build_site(data, out)
    return data, out
