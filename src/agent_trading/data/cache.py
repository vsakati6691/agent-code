"""Per-symbol CSV cache of daily bars. New bars are merged in, so history grows."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


def cache_path(cache_dir: Path, symbol: str) -> Path:
    return cache_dir / f"{symbol.upper()}.csv"


def read_cache(cache_dir: Path, symbol: str) -> pd.DataFrame | None:
    path = cache_path(cache_dir, symbol)
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    return df[COLUMNS].sort_index()


def write_cache(cache_dir: Path, symbol: str, df: pd.DataFrame) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(cache_dir, symbol)
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
