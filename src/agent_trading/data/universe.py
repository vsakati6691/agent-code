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


def parse_index_fund(raw: dict, settings: Settings) -> Universe:
    fund = raw.get("fund") or {}
    holdings = raw.get("holdings")
    if not isinstance(holdings, list) or not holdings:
        raise UniverseError("no holdings in the index-fund response")
    as_of = fund.get("as_of") or fund.get("filing_date")
    if not as_of:
        raise UniverseError("index-fund response has no as-of date")
    rows, excluded = [], []
    for h in holdings:
        t = (h.get("ticker") or "").strip().upper()
        if h.get("asset_class") != "equity":
            excluded.append(f"{t or h.get('name')}: asset class {h.get('asset_class')!r}")
        elif not TICKER_RE.match(t):
            excluded.append(f"{t or '(none)'} ({h.get('name')}): not a valid ticker")
        else:
            rows.append({"ticker": t, "name": h.get("name", ""), "weight": float(h.get("weight") or 0.0)})
    table = pd.DataFrame(rows).drop_duplicates("ticker")
    sc = settings.scanner
    if not sc.min_constituents <= len(table) <= sc.max_constituents:
        raise UniverseError(f"{len(table)} valid constituents, expected {sc.min_constituents}-{sc.max_constituents}")
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


def load_universe(settings: Settings) -> Universe | None:
    d = _dir(settings)
    files = sorted(d.glob("sp500_*.csv")) if d.exists() else []
    if not files:
        return None
    path = files[-1]
    meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    return Universe(date.fromisoformat(meta["as_of"]), meta["source"], pd.read_csv(path), meta.get("excluded", []))


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
