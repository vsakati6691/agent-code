"""Per-symbol CSV cache of daily bars. New bars are merged in, so history grows."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


def cache_path(cache_dir: Path, symbol: str) -> Path:
    """A supported ticker's contained CSV path, including Windows device-name guards."""
    if (
        not isinstance(symbol, str)
        or not re.fullmatch(r"[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*", symbol)
        or len(symbol) > 32
    ):
        raise ValueError("invalid ticker for cache path")
    symbol = symbol.upper()
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if symbol.split(".")[0] in reserved:
        raise ValueError("reserved ticker for cache path")
    root = Path(cache_dir).resolve()
    path = (root / f"{symbol}.csv").resolve()
    if not path.is_relative_to(root):
        raise ValueError("ticker cache path escapes its directory")
    return path


def read_cache(cache_dir: Path, symbol: str) -> pd.DataFrame | None:
    path = cache_path(cache_dir, symbol)
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    return df[COLUMNS].sort_index()


def write_cache(cache_dir: Path, symbol: str, df: pd.DataFrame) -> Path:
    path = cache_path(cache_dir, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df[COLUMNS].sort_index()
    out.index.name = "date"
    out.to_csv(path, date_format="%Y-%m-%d")
    return path


def merge_bars(old: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    """Combine two series; on overlapping dates the newer data wins."""
    if old is None or old.empty:
        return new.sort_index()
    combined = pd.concat([old[COLUMNS], new[COLUMNS]])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


def last_cached_date(cache_dir: Path, symbol: str) -> pd.Timestamp | None:
    df = read_cache(cache_dir, symbol)
    return None if df is None or df.empty else df.index[-1]


def load_csv_file(path: Path) -> pd.DataFrame:
    """Load a user-supplied CSV with columns date,open,high,low,close,volume."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in ["date", *COLUMNS] if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    return df.set_index("date")[COLUMNS].astype(float).sort_index()
