"""Import MCP data saved by a Claude session (the Python code cannot call MCP).

Each importer validates the payload, records the source and fetch time, and
writes a normalised CSV under data/snapshots/<kind>/. Readers return the
latest snapshot plus its age so callers can refuse stale data.

Kinds and the MCP tool that produces each:
  fundamentals  Robinhood preview_scan (columns: Market cap, Sector, P/E, Forward P/E,
                PEG, Gross margin, Operating margin, Net profit margin,
                Return on equity, EPS, Earnings date); several files may be
                merged (the scanner returns at most 200 rows per call)
  quotes        Robinhood get_equity_quotes
  news          Financial Datasets get_news (headlines only: UNVERIFIED)
  filings       Financial Datasets get_filings
  econ          Bigdata.com bigdata_events_calendar (economic_calendar)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import Settings

SNAP_DIR = "snapshots"


class SnapshotDataError(ValueError):
    """A saved MCP payload is malformed."""


@dataclass(frozen=True)
class Snapshot:
    kind: str
    table: pd.DataFrame
    fetched_at: datetime
    source: str

    def age_hours(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (now - self.fetched_at).total_seconds() / 3600


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _yyyymmdd(v) -> str | None:
    x = _num(v)
    if x is None:
        return None
    s = str(int(round(x)))
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else None


def _payload(raw: dict) -> dict:
    return raw.get("data", raw) if isinstance(raw, dict) else raw


# ---------------------------------------------------------------- parsers

def parse_fundamentals(raws: list[dict]) -> pd.DataFrame:
    rows = []
    for raw in raws:
        result = _payload(raw).get("result")
        if not isinstance(result, dict) or "results" not in result:
            raise SnapshotDataError("not a preview_scan/run_scan payload")
        for r in result["results"]:
            c = r.get("columns", {})
            rows.append({
                "ticker": str(r.get("ticker", "")).upper(),
                "market_cap": _num(c.get("Market cap")),
                "sector_code": c.get("Sector") or None,
                "pe": _num(c.get("P/E")),
                "forward_pe": _num(c.get("Forward P/E")),
                "peg": _num(c.get("PEG")),
                "gross_margin": _num(c.get("Gross margin")),
                "operating_margin": _num(c.get("Operating margin")),
                "net_margin": _num(c.get("Net profit margin")),
                "roe": _num(c.get("Return on equity")),
                "eps": _num(c.get("EPS")),
                "earnings_date": _yyyymmdd(c.get("Earnings date")),
            })
    if not rows:
        raise SnapshotDataError("no fundamentals rows")
    return pd.DataFrame(rows).drop_duplicates("ticker", keep="last")


def parse_quotes(raw: dict) -> pd.DataFrame:
    results = _payload(raw).get("results")
    if not isinstance(results, list):
        raise SnapshotDataError("not a get_equity_quotes payload")
    rows = []
    for r in results:
        q = r.get("quote", r)
        bid, ask = _num(q.get("bid_price")), _num(q.get("ask_price"))
        reg_t, ext_t = q.get("venue_last_trade_time"), q.get("venue_last_non_reg_trade_time")
        use_ext = bool(ext_t) and (not reg_t or ext_t > reg_t)
        price = _num(q.get("last_non_reg_trade_price") if use_ext else q.get("last_trade_price"))
        mid = (bid + ask) / 2 if bid and ask else None
        rows.append({
            "ticker": str(q.get("symbol", "")).upper(),
            "price": price,
            "price_time": ext_t if use_ext else reg_t,
            "session": "extended" if use_ext else "regular",
            "previous_close": _num(q.get("adjusted_previous_close") or q.get("previous_close")),
            "bid": bid, "ask": ask,
            "spread_pct": (ask - bid) / mid if mid else None,
            "state": q.get("state"),
        })
    return pd.DataFrame(rows)


def parse_news(raw) -> pd.DataFrame:
    items = raw if isinstance(raw, list) else _payload(raw).get("news", [])
    rows = [{"ticker": (i.get("ticker") or "MARKET").upper(), "date": i.get("date"), "title": i.get("title"),
             "source": i.get("source"), "url": i.get("url"), "verified": False} for i in items]
    return pd.DataFrame(rows, columns=["ticker", "date", "title", "source", "url", "verified"])


def parse_filings(raw) -> pd.DataFrame:
    items = raw if isinstance(raw, list) else _payload(raw).get("filings", [])
    rows = [{"ticker": (i.get("ticker") or "").upper(), "filing_type": i.get("filing_type"),
             "filing_date": i.get("filing_date"), "report_date": i.get("report_date"), "url": i.get("url")}
            for i in items]
    return pd.DataFrame(rows, columns=["ticker", "filing_type", "filing_date", "report_date", "url"])


def parse_econ(raw: dict) -> pd.DataFrame:
    events = _payload(raw).get("events")
    if not isinstance(events, list):
        raise SnapshotDataError("not an economic-calendar payload")
    rows = [{"time": e.get("date"), "country": e.get("country"), "name": e.get("name"),
             "impact": e.get("impact"), "category": e.get("category"),
             "consensus": e.get("consensus"), "previous": e.get("previous"), "actual": e.get("actual")}
            for e in events]
    df = pd.DataFrame(rows, columns=["time", "country", "name", "impact", "category", "consensus", "previous", "actual"])
    df["date"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/New_York").dt.date
    return df


PARSERS = {"quotes": parse_quotes, "news": parse_news, "filings": parse_filings, "econ": parse_econ}
SOURCES = {
    "fundamentals": "Robinhood MCP preview_scan",
    "quotes": "Robinhood MCP get_equity_quotes",
    "news": "Financial Datasets MCP get_news (headlines, unverified)",
    "filings": "Financial Datasets MCP get_filings (SEC EDGAR)",
    "econ": "Bigdata.com MCP economic calendar",
}


# ---------------------------------------------------------------- storage

def _dir(settings: Settings, kind: str) -> Path:
    return settings.resolve(settings.data.cache_dir).parent / SNAP_DIR / kind


def import_snapshot_files(settings: Settings, kind: str, paths: list[Path],
                          fetched_at: datetime | None = None, merge: bool = False) -> Snapshot:
    """Parse saved MCP payload(s) of one kind and store the normalised snapshot.

    merge=True appends to today's snapshot of the same kind (e.g. news for
    several tickers); otherwise the new snapshot replaces it.
    """
    raws = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    if kind == "fundamentals":
        table = parse_fundamentals(raws)
    elif kind in PARSERS:
        table = pd.concat([PARSERS[kind](r) for r in raws], ignore_index=True)
    else:
        raise SnapshotDataError(f"unknown snapshot kind {kind!r}")
    fetched_at = fetched_at or datetime.now(timezone.utc)
    if merge:
        prev = load_snapshot(settings, kind)
        if prev is not None and prev.fetched_at.date() == fetched_at.date():
            table = pd.concat([prev.table, table], ignore_index=True).drop_duplicates()
    d = _dir(settings, kind)
    d.mkdir(parents=True, exist_ok=True)
    table.to_csv(d / "latest.csv", index=False)
    (d / "latest.meta.json").write_text(json.dumps(
        {"fetched_at": fetched_at.isoformat(timespec="seconds"), "source": SOURCES[kind], "rows": len(table)}),
        encoding="utf-8")
    return Snapshot(kind, table, fetched_at, SOURCES[kind])


def load_snapshot(settings: Settings, kind: str) -> Snapshot | None:
    d = _dir(settings, kind)
    if not (d / "latest.csv").exists():
        return None
    meta = json.loads((d / "latest.meta.json").read_text(encoding="utf-8"))
    try:
        table = pd.read_csv(d / "latest.csv")
    except pd.errors.EmptyDataError:
        table = pd.DataFrame()
    if kind == "econ" and not table.empty:
        table["date"] = pd.to_datetime(table["date"]).dt.date
    return Snapshot(kind, table, datetime.fromisoformat(meta["fetched_at"]), meta["source"])


def high_impact_events(econ: Snapshot | None, start: date, days: int, country: str = "US",
                       max_age_hours: float = 36, now: datetime | None = None) -> pd.DataFrame | None:
    """High-impact releases from `start` through `start + days`.

    Returns None when the calendar is missing or stale, so callers can fail safe.
    """
    if econ is None or econ.age_hours(now) > max_age_hours:
        return None
    t = econ.table
    if t.empty:
        return t
    mask = (t["impact"] == "HIGH") & (t["country"] == country) & (t["date"] >= start) & \
           (t["date"] <= start + pd.Timedelta(days=days).to_pytimedelta())
    return t[mask]
