"""Public data providers for the research dashboard: parsers (pure) and fetchers (via http.py).

Provider choices, coverage, terms and limits are documented in docs/RESEARCH_DASHBOARD.md.
In short:
* SEC EDGAR (US government data, public): ticker/CIK/exchange map, XBRL company facts,
  shares-outstanding frames, submissions (SIC industry). Needs a User-Agent with a contact.
* Nasdaq Trader symbol directories: listing exchange, ETF and test-issue flags.
* Wikipedia "List of S&P 500 companies" (CC BY-SA 4.0): current S&P 500 members and GICS sectors.
* Cboe delayed quotes (cboe.com, undocumented public JSON; site terms allow personal, non-commercial
  use only): end-of-session stock quotes, split-adjusted daily price history, option chains with IV
  and Greeks. Publishing its data needs the owner's review of those terms.
* Alpha Vantage EARNINGS_CALENDAR (free key, 25 requests/day): upcoming earnings dates, one request.

The interactive Robinhood MCP is not used: it needs a logged-in Claude session and cannot run in CI.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser

import pandas as pd

from .http import FetchError, HttpClient

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_FRAME_URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/{period}.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
WIKI_SP500_URL = "https://en.wikipedia.org/w/api.php"
WIKI_SP500_PARAMS = {"action": "parse", "page": "List_of_S&P_500_companies", "prop": "text",
                     "format": "json", "formatversion": "2"}
CBOE_BASE = "https://cdn-api.cboe.com/api/global/delayed_quotes"
AV_URL = "https://www.alphavantage.co/query"

SOURCES = {
    "sec": "SEC EDGAR XBRL company facts and frames (data.sec.gov), public data",
    "nasdaqtrader": "Nasdaq Trader symbol directories (nasdaqlisted.txt, otherlisted.txt)",
    "wikipedia": "Wikipedia, 'List of S&P 500 companies' (CC BY-SA 4.0)",
    "cboe": "Cboe Global Markets delayed quotes (cboe.com); end-of-session, not real time",
    "alphavantage": "Alpha Vantage EARNINGS_CALENDAR",
}

OTHER_EXCHANGES = {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
NON_COMMON = re.compile(
    r"\b(warrants?|rights?|units?|preferred|depositary|debentures?|notes? due|%|subordinated|trust preferred|"
    r"etf|etn|fund|index|exchange[- ]traded|beneficial interest|limited partnership units?|acquisition corp(oration)?|"
    r"acquisition company)\b", re.I)
COMMON = re.compile(r"\b(common stock|common shares|ordinary shares|class [a-z] (common|ordinary)|"
                    r"common units|capital stock|shares of beneficial)\b", re.I)


def canonical(ticker: str) -> str:
    """One spelling for share classes everywhere: BRK.B (SEC uses BRK-B, some files BRK/B)."""
    return (ticker or "").strip().upper().replace("-", ".").replace("/", ".")


# --- SEC ------------------------------------------------------------------------------

def parse_sec_tickers(raw: dict) -> pd.DataFrame:
    fields = raw.get("fields")
    if fields != ["cik", "name", "ticker", "exchange"]:
        raise FetchError("SEC ticker file has an unexpected layout")
    df = pd.DataFrame(raw["data"], columns=fields)
    df["ticker"] = df["ticker"].map(canonical)
    df["exchange"] = df["exchange"].fillna("")
    return df.drop_duplicates("ticker").set_index("ticker")


def parse_share_frames(frames: list[dict], as_of: date) -> dict[int, tuple[float, str]]:
    """Latest cover-page share count per CIK with an end date on or before `as_of`: {cik: (shares, end)}."""
    out: dict[int, tuple[float, str]] = {}
    for fr in frames:
        for row in fr.get("data", []):
            end = row.get("end", "")
            if not end or date.fromisoformat(end) > as_of:
                continue
            cik, val = int(row["cik"]), float(row["val"])
            if val > 0 and (cik not in out or end > out[cik][1]):
                out[cik] = (val, end)
    return out


def share_frame_periods(as_of: date, n: int = 3) -> list[str]:
    """SEC instant frame names for the quarter of `as_of` and the n-1 before it (e.g. CY2026Q3I)."""
    y, q = as_of.year, (as_of.month - 1) // 3 + 1
    out = []
    for _ in range(n):
        out.append(f"CY{y}Q{q}I")
        q -= 1
        if q == 0:
            y, q = y - 1, 4
    return out


SIC_SECTORS = [  # coarse sectors from SEC SIC codes, for companies outside the S&P 500 list
    ((100, 999), "Agriculture"), ((1000, 1499), "Materials"), ((1311, 1389), "Energy"), ((1500, 1799), "Industrials"),
    ((2000, 2199), "Consumer Staples"), ((2200, 2799), "Consumer Discretionary"), ((2800, 2829), "Materials"),
    ((2830, 2836), "Health Care"), ((2840, 2899), "Materials"), ((2900, 2999), "Energy"),
    ((3000, 3569), "Industrials"), ((3570, 3579), "Information Technology"), ((3580, 3659), "Industrials"),
    ((3660, 3699), "Information Technology"), ((3700, 3799), "Industrials"), ((3800, 3839), "Industrials"),
    ((3840, 3859), "Health Care"), ((3860, 3999), "Industrials"), ((4000, 4799), "Industrials"),
    ((4800, 4899), "Communication Services"), ((4900, 4999), "Utilities"), ((5000, 5199), "Industrials"),
    ((5200, 5999), "Consumer Discretionary"), ((6000, 6499), "Financials"), ((6500, 6799), "Real Estate"),
    ((7000, 7369), "Consumer Discretionary"), ((7370, 7379), "Information Technology"),
    ((7380, 7999), "Consumer Discretionary"), ((8000, 8099), "Health Care"), ((8100, 8999), "Industrials"),
]


def sector_from_sic(sic: str | int | None) -> str:
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return "Unknown"
    best = "Unknown"
    for (lo, hi), name in SIC_SECTORS:   # later, narrower ranges override broader ones
        if lo <= code <= hi:
            best = name
    return best


def parse_earnings_8k(subs: dict | None) -> list[str]:
    """Filing dates of 8-K (or 8-K/A) reports that include item 2.02 'Results of Operations and Financial
    Condition', newest first, from an SEC submissions payload."""
    recent = ((subs or {}).get("filings") or {}).get("recent") or {}
    forms, dates, items = recent.get("form") or [], recent.get("filingDate") or [], recent.get("items") or []
    out = [d for f, d, it in zip(forms, dates, items + [""] * (len(forms) - len(items)))
           if f in ("8-K", "8-K/A") and "2.02" in {s.strip() for s in str(it).split(",")}]
    return sorted(set(out), reverse=True)


# --- Nasdaq Trader ------------------------------------------------------------------------

def _pipe_table(text: str) -> pd.DataFrame:
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
    return pd.read_csv(io.StringIO("\n".join(lines)), sep="|", dtype=str, keep_default_na=False)


def parse_symbol_directories(nasdaq_text: str, other_text: str) -> pd.DataFrame:
    """ticker -> name, exchange, etf, test_issue, financial_status (Nasdaq only)."""
    n = _pipe_table(nasdaq_text)
    o = _pipe_table(other_text)
    if "Symbol" not in n.columns or "ACT Symbol" not in o.columns:
        raise FetchError("Nasdaq Trader symbol directory has an unexpected layout")
    rows = []
    for _, r in n.iterrows():
        rows.append((canonical(r["Symbol"]), r["Security Name"], "Nasdaq", r["ETF"] == "Y", r["Test Issue"] == "Y",
                     r.get("Financial Status", "")))
    for _, r in o.iterrows():
        rows.append((canonical(r["ACT Symbol"]), r["Security Name"], OTHER_EXCHANGES.get(r["Exchange"], r["Exchange"]),
                     r["ETF"] == "Y", r["Test Issue"] == "Y", ""))
    df = pd.DataFrame(rows, columns=["ticker", "name", "exchange", "etf", "test_issue", "financial_status"])
    return df.drop_duplicates("ticker").set_index("ticker")


def common_stock_reason(name: str, etf: bool, test_issue: bool, financial_status: str) -> str | None:
    """Why a listed security is not a common stock for this dashboard (None = it is)."""
    if test_issue:
        return "test issue"
    if etf:
        return "ETF or fund"
    if "$" in name:
        return "preferred or other non-common class"
    if financial_status in ("Q", "G", "H", "J", "K"):   # Nasdaq codes involving bankruptcy
        return "bankruptcy status on Nasdaq"
    if NON_COMMON.search(name) and not re.search(r"common stock|ordinary shares", name, re.I):
        return "not common stock (warrant, right, unit, preferred, note, fund or blank-check)"
    if re.search(r"acquisition corp", name, re.I):
        return "blank-check company (SPAC)"
    if re.search(r"depositary", name, re.I):
        return "depositary shares (ADR/ADS)"
    if not COMMON.search(name):
        return "security name does not identify common stock"
    return None


# --- Wikipedia S&P 500 ------------------------------------------------------------------------

class _TableParser(HTMLParser):
    """Collect the rows of the table with id="constituents"."""

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table" and (self.depth or attrs.get("id") == "constituents"):
            self.depth += 1
        elif self.depth == 1 and tag == "tr":
            self._row = []
        elif self.depth == 1 and tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self.depth:
            self.depth -= 1
        elif self.depth == 1 and tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif self.depth == 1 and tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_sp500(raw: dict) -> pd.DataFrame:
    html = (raw.get("parse") or {}).get("text", "")
    p = _TableParser()
    p.feed(html)
    if not p.rows:
        raise FetchError("Wikipedia S&P 500 page: constituents table not found")
    head, body = p.rows[0], p.rows[1:]
    want = {"Symbol": "ticker", "Security": "name", "GICS Sector": "sector", "GICS Sub-Industry": "industry",
            "Date added": "date_added", "CIK": "cik"}
    idx = {v: head.index(k) for k, v in want.items() if k in head}
    if "ticker" not in idx or "sector" not in idx:
        raise FetchError("Wikipedia S&P 500 page: unexpected table columns")
    rows = [{k: r[i] if i < len(r) else "" for k, i in idx.items()} for r in body]
    if not rows:
        raise FetchError("Wikipedia S&P 500 page: constituents table is empty")
    df = pd.DataFrame(rows)
    df["ticker"] = df["ticker"].map(canonical)
    df["cik"] = pd.to_numeric(df.get("cik"), errors="coerce")
    df = df[df["ticker"].str.match(r"^[A-Z]{1,5}(\.[A-Z])?$")].drop_duplicates("ticker").set_index("ticker")
    if not 480 <= len(df) <= 520:
        raise FetchError(f"Wikipedia S&P 500 page: {len(df)} constituents parsed (expected about 503)")
    return df


# --- Cboe -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Quote:
    symbol: str
    close: float | None
    prev_close: float | None
    last_trade: datetime | None
    iv30: float | None
    fetched: str


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def parse_cboe_quote(raw: dict) -> Quote:
    d = raw.get("data") or {}
    if not d.get("symbol"):
        raise FetchError("Cboe quote: no data")
    lt = d.get("last_trade_time")
    return Quote(canonical(d["symbol"]), _num(d.get("close")), _num(d.get("prev_day_close")),
                 datetime.fromisoformat(lt) if lt else None, _num(d.get("iv30")), str(raw.get("timestamp", "")))


def parse_cboe_history(raw: dict) -> pd.DataFrame:
    rows = raw.get("data") or []
    if not rows:
        raise FetchError("Cboe history: no rows")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.set_index("date").sort_index()[["open", "high", "low", "close", "volume"]]
    df = df[~df.index.duplicated(keep="last")]
    # Cboe pads some rows with a zero open, and a few bars have an open or close slightly outside the
    # day's high-low range (vendor glitches). Repair them so the OHLC checks stay meaningful, and count
    # the repairs: research uses closes, and a series needing many repairs is flagged.
    valid = (df["close"] > 0) & df[["high", "low", "close"]].notna().all(axis=1)
    dropped = int((~valid).sum())
    df = df[valid].copy()
    df["volume"] = df["volume"].fillna(0.0)
    df.loc[~(df["open"] > 0), "open"] = df["close"]
    df.loc[~(df["low"] > 0), "low"] = df[["open", "close"]].min(axis=1)
    hi, lo = df[["open", "close"]].max(axis=1), df[["open", "close"]].min(axis=1)
    bad = (df["high"] < hi - 1e-9) | (df["low"] > lo + 1e-9)
    df.loc[bad, "high"] = df.loc[bad, ["high"]].join(hi[bad].rename("x")).max(axis=1)
    df.loc[bad, "low"] = df.loc[bad, ["low"]].join(lo[bad].rename("x")).min(axis=1)
    df.attrs["dropped_bars"] = dropped
    df.attrs["repaired_bars"] = int(bad.sum())
    df.attrs["repaired_recent"] = int(bad.iloc[-252:].sum())
    return df


OCC_RE = re.compile(r"^(?P<root>[A-Z0-9.]{1,6}?)(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<cp>[CP])(?P<k>\d{8})$")


def parse_occ(symbol: str) -> dict | None:
    m = OCC_RE.match(symbol.strip().upper())
    if not m:
        return None
    return {"root": m["root"], "expiration": date(2000 + int(m["y"]), int(m["m"]), int(m["d"])),
            "type": "call" if m["cp"] == "C" else "put", "strike": int(m["k"]) / 1000.0}


def parse_cboe_chain(raw: dict) -> tuple[dict, list[dict]]:
    """(underlying info, option rows). Rows keep only fields the dashboard publishes or uses."""
    d = raw.get("data") or {}
    if not d.get("symbol") or not isinstance(d.get("options"), list):
        raise FetchError("Cboe option chain: no data")
    under = {"symbol": canonical(d["symbol"]), "close": _num(d.get("close")), "price": _num(d.get("current_price")),
             "last_trade_time": d.get("last_trade_time"), "iv30": _num(d.get("iv30")),
             "timestamp": str(raw.get("timestamp", ""))}
    rows = []
    for o in d["options"]:
        occ = parse_occ(str(o.get("option", "")))
        if occ is None:
            continue
        rows.append({"option": o["option"], **occ, "bid": _num(o.get("bid")), "ask": _num(o.get("ask")),
                     "iv": _num(o.get("iv")), "open_interest": _num(o.get("open_interest")),
                     "volume": _num(o.get("volume")), "delta": _num(o.get("delta")), "gamma": _num(o.get("gamma")),
                     "theta": _num(o.get("theta")), "vega": _num(o.get("vega")), "rho": _num(o.get("rho")),
                     "last_trade_time": o.get("last_trade_time"), "last_price": _num(o.get("last_trade_price"))})
    return under, rows


# --- fetchers ------------------------------------------------------------------------------------

class Providers:
    """Thin fetch layer. Every method raises FetchError (or BudgetExceeded) on failure."""

    def __init__(self, http: HttpClient, av_key: str | None = None) -> None:
        self.http = http
        self.av_key = av_key

    def sec_tickers(self) -> pd.DataFrame:
        return parse_sec_tickers(self.http.get_json(SEC_TICKERS_URL, max_age_hours=24))

    def share_frames(self, as_of: date) -> dict[int, tuple[float, str]]:
        frames = []
        for period in share_frame_periods(as_of):
            try:
                frames.append(self.http.get_json(SEC_FRAME_URL.format(period=period), max_age_hours=24))
            except FetchError as exc:
                if "HTTP 404" not in str(exc):     # a quarter with no filings yet is normal
                    raise
        return parse_share_frames(frames, as_of)

    def company_facts(self, cik: int) -> dict:
        return self.http.get_json(SEC_FACTS_URL.format(cik=int(cik)), max_age_hours=72)

    def submissions(self, cik: int) -> dict:
        return self.http.get_json(SEC_SUBMISSIONS_URL.format(cik=int(cik)), max_age_hours=168)

    def symbol_directories(self) -> pd.DataFrame:
        return parse_symbol_directories(self.http.get_text(NASDAQ_LISTED_URL, max_age_hours=24),
                                        self.http.get_text(OTHER_LISTED_URL, max_age_hours=24))

    def sp500(self) -> pd.DataFrame:
        return parse_sp500(self.http.get_json(WIKI_SP500_URL, WIKI_SP500_PARAMS, max_age_hours=24))

    def quote(self, symbol: str) -> Quote:
        return parse_cboe_quote(self.http.get_json(f"{CBOE_BASE}/quotes/{symbol}.json", max_age_hours=12))

    def history(self, symbol: str) -> pd.DataFrame:
        return parse_cboe_history(self.http.get_json(f"{CBOE_BASE}/charts/historical/{symbol}.json", max_age_hours=12))

    def option_chain(self, symbol: str) -> tuple[dict, list[dict]]:
        return parse_cboe_chain(self.http.get_json(f"{CBOE_BASE}/options/{symbol}.json", max_age_hours=12))

    def earnings_calendar(self) -> pd.DataFrame:
        if not self.av_key:
            raise FetchError("Alpha Vantage key not configured (ALPHAVANTAGE_API_KEY)")
        from ..data.alphavantage import AlphaVantageError, parse_earnings_csv
        from ..logging_setup import register_secret

        register_secret(self.av_key)
        text = self.http.get_text(AV_URL, {"function": "EARNINGS_CALENDAR", "horizon": "12month",
                                           "apikey": self.av_key}, max_age_hours=24)
        try:
            df = parse_earnings_csv(text)
        except AlphaVantageError as exc:
            raise FetchError(str(exc)) from None
        df["symbol"] = df["symbol"].map(canonical)
        return df
