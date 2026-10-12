"""S&P 500 constituents, discovered dynamically from the SPY fund-holdings filing.

A Claude session calls Financial Datasets `get_index_fund` (ticker SPY,
limit 1000) through MCP and saves the JSON; `universe import` validates it and
stores a dated CSV. Coverage of the scan is always measured against this list.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from ..config import Settings

TICKER_RE = re.compile(r"^[A-Z]{1,5}([.\-][A-Z])?$")
UNIVERSE_DIR = "universe"


class UniverseError(ValueError):
    """The constituent list is unusable."""


@dataclass(frozen=True)
class Universe:
    as_of: date
    source: str
    table: pd.DataFrame          # ticker, name, weight
    excluded: list[str]          # non-ticker rows (cash, placeholders) with reasons

    @property
    def tickers(self) -> list[str]:
        return list(self.table["ticker"])


_SUFFIXES = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|PLC|LTD|LIMITED|NV|N\.V|SA|AG|LP|LLC|HOLDINGS?|GROUP|"
    r"CLASS [A-Z]|CL [A-Z]|THE|COM|SHS|ORD|REIT|TRUST)\b")


def normalize_name(name: str) -> str:
    """Company name key for matching filings that omit the ticker."""
    s = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper().replace("&", " AND "))
    s = _SUFFIXES.sub(" ", s)
    return " ".join(s.split())


def _clean_ticker(t: str | None) -> str:
    return (t or "").strip().upper().replace("/", ".")


def parse_index_fund(raw: dict, settings: Settings, name_map: dict[str, str] | None = None,
                     min_count: int | None = None) -> Universe:
    """`name_map`: normalized company name -> ticker, used when a filing row has no
    ticker (N-PORT often omits them for foreign-domiciled companies).
    `min_count`: lower bound override for historical snapshots."""
    fund = raw.get("fund") or {}
    holdings = raw.get("holdings")
    if not isinstance(holdings, list) or not holdings:
        raise UniverseError("no holdings in the index-fund response")
    as_of = fund.get("as_of") or fund.get("filing_date")
    if not as_of:
        raise UniverseError("index-fund response has no as-of date")
    rows, excluded = [], []
    for h in holdings:
        t = _clean_ticker(h.get("ticker"))
        if not t and name_map:
            t = name_map.get(normalize_name(h.get("name", "")), "")
        if h.get("asset_class") != "equity":
            excluded.append(f"{t or h.get('name')}: asset class {h.get('asset_class')!r}")
        elif not TICKER_RE.match(t):
            excluded.append(f"{t or '(none)'} ({h.get('name')}): not a valid ticker")
        else:
            rows.append({"ticker": t, "name": h.get("name", ""), "weight": float(h.get("weight") or 0.0)})
    table = pd.DataFrame(rows).drop_duplicates("ticker")
    sc = settings.scanner
    lo = sc.min_constituents if min_count is None else min_count
    if not lo <= len(table) <= sc.max_constituents:
        raise UniverseError(f"{len(table)} valid constituents, expected {lo}-{sc.max_constituents}")
    source = f"Financial Datasets get_index_fund({fund.get('name', settings.scanner.index_fund)}), filing {fund.get('filing_date')}"
    return Universe(date.fromisoformat(as_of), source, table.reset_index(drop=True), excluded)


def _dir(settings: Settings) -> Path:
    return settings.resolve(settings.data.cache_dir).parent / UNIVERSE_DIR


def save_universe(settings: Settings, u: Universe) -> Path:
    d = _dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"sp500_{u.as_of.isoformat()}.csv"
    u.table.to_csv(path, index=False)
    (d / f"sp500_{u.as_of.isoformat()}.meta.json").write_text(
        json.dumps({"as_of": u.as_of.isoformat(), "source": u.source, "excluded": u.excluded}, indent=2),
        encoding="utf-8")
    return path


def import_universe(settings: Settings, source: Path) -> Universe:
    u = parse_index_fund(json.loads(Path(source).read_text(encoding="utf-8")), settings)
    save_universe(settings, u)
    return u


def import_universe_history(settings: Settings, sources: list[Path], min_count: int = 400) -> list[Universe]:
    """Import historical (point-in-time) constituent snapshots.

    Tickers missing from a filing are resolved by company name using every
    snapshot that does carry them (including the current list). Unresolved rows
    are kept in the snapshot's excluded list so coverage gaps stay visible.
    """
    raws = [json.loads(Path(p).read_text(encoding="utf-8")) for p in sources]
    name_map: dict[str, str] = {}
    current = load_universe(settings)
    if current is not None:
        for r in current.table.itertuples():
            name_map.setdefault(normalize_name(r.name), r.ticker)
    for raw in raws:
        for h in raw.get("holdings") or []:
            t = _clean_ticker(h.get("ticker"))
            if TICKER_RE.match(t):
                name_map.setdefault(normalize_name(h.get("name", "")), t)
    out = []
    for raw in raws:
        u = parse_index_fund(raw, settings, name_map, min_count)
        save_universe(settings, u)
        out.append(u)
    return out


def load_universe(settings: Settings) -> Universe | None:
    d = _dir(settings)
    files = sorted(d.glob("sp500_*.csv")) if d.exists() else []
    if not files:
        return None
    path = files[-1]
    meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    return Universe(date.fromisoformat(meta["as_of"]), meta["source"], pd.read_csv(path), meta.get("excluded", []))


def load_universe_history(settings: Settings) -> dict[date, list[str]]:
    """All stored constituent snapshots, by as-of date (for point-in-time backtests)."""
    d = _dir(settings)
    out: dict[date, list[str]] = {}
    for path in sorted(d.glob("sp500_*.csv")) if d.exists() else []:
        as_of = date.fromisoformat(path.stem.removeprefix("sp500_"))
        out[as_of] = list(pd.read_csv(path)["ticker"])
    return out


def members_on(history: dict[date, list[str]], day: date) -> list[str]:
    """Constituents from the latest snapshot on or before `day` (empty if none)."""
    past = [d for d in history if d <= day]
    return history[max(past)] if past else []


def universe_problems(u: Universe | None, settings: Settings, today: date) -> list[str]:
    if u is None:
        return ["no S&P 500 constituent list imported"]
    age = (today - u.as_of).days
    if age > settings.scanner.universe_max_age_days:
        return [f"constituent list is {age} days old (as of {u.as_of}); refresh it"]
    return []


def coverage(u: Universe, scanned: list[str], rejected: dict[str, str]) -> dict:
    expected = set(u.tickers)
    got = expected & set(scanned)
    missing = sorted(expected - got)
    return {
        "expected": len(expected),
        "scanned": len(got),
        "ratio": len(got) / len(expected) if expected else 0.0,
        "missing": {t: rejected.get(t, "no price data") for t in missing},
    }
