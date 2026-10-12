"""Refresh the local cache within the daily request budget, then load validated data."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import Settings
from .alphavantage import SOURCE_NAME, AlphaVantageClient, AlphaVantageError
from .cache import cache_path, last_cached_date, merge_bars, read_cache, write_cache
from .validation import DataQualityError, trim_bad_history, validate_bars

log = logging.getLogger(__name__)
EARNINGS_FILE = "earnings_calendar.csv"
EARNINGS_META = "earnings_calendar.meta.json"


@dataclass
class LoadResult:
    bars: dict[str, pd.DataFrame] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)


@dataclass
class EarningsData:
    table: pd.DataFrame | None
    source: str | None
    fetched_at: str | None
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.table is not None and self.error is None


class MarketDataService:
    def __init__(self, settings: Settings, client: AlphaVantageClient | None = None) -> None:
        self.settings = settings
        self.client = client
        self.cache_dir = settings.resolve(settings.data.cache_dir)

    @property
    def _budget_left(self) -> int:
        used = self.client.calls_made if self.client else 0
        return self.settings.data.daily_request_budget - used

    def refresh(self, symbols: list[str], as_of: date) -> dict[str, str]:
        """Fetch the stalest symbols first until the request budget runs out."""
        if self.client is None:
            raise RuntimeError("No data client configured")
        as_of_ts = pd.Timestamp(as_of)

        def staleness(sym: str) -> pd.Timestamp:
            last = last_cached_date(self.cache_dir, sym)
            return last if last is not None else pd.Timestamp.min

        status: dict[str, str] = {}
        for sym in sorted(symbols, key=staleness):
            last = last_cached_date(self.cache_dir, sym)
            path = cache_path(self.cache_dir, sym)
            fetched_today = path.exists() and date.fromtimestamp(path.stat().st_mtime) >= as_of
            if last is not None and (last >= as_of_ts or fetched_today):
                status[sym] = "up to date"
                continue
            if self._budget_left <= 1:  # keep one call for the earnings calendar
                status[sym] = "skipped (request budget exhausted)"
                continue
            try:
                new = self.client.daily_bars(sym, self.settings.data.outputsize)
            except AlphaVantageError as exc:
                log.warning("Fetch failed: %s", exc)
                status[sym] = f"fetch failed: {exc}"
                continue
            merged = merge_bars(read_cache(self.cache_dir, sym), new)
            write_cache(self.cache_dir, sym, merged)
            status[sym] = f"updated ({len(new)} bars fetched, {len(merged)} cached)"
        return status

    def load(self, symbols: list[str], as_of: date) -> LoadResult:
        result = LoadResult()
        d = self.settings.data
        for sym in symbols:
            try:
                df = read_cache(self.cache_dir, sym)
                if df is not None and not df.empty:
                    df, _ = trim_bad_history(df, sym)  # old anomalies trimmed; recent ones raise
                result.bars[sym] = validate_bars(df, sym, as_of, d.max_staleness_days, d.min_history_bars)
            except DataQualityError as exc:
                result.rejected[sym] = str(exc)
            except (ValueError, KeyError) as exc:
                result.rejected[sym] = f"{sym}: unreadable cache ({exc})"
        return result

    # --- earnings calendar -------------------------------------------------

    def refresh_earnings(self, as_of: date) -> None:
        meta = self._earnings_meta()
        if meta and meta.get("fetched_date") == as_of.isoformat():
            return
        if self.client is None or self._budget_left <= 0:
            log.warning("Earnings calendar not refreshed (no client or budget)")
            return
        try:
            table = self.client.earnings_calendar("3month")
        except AlphaVantageError as exc:
            log.warning("Earnings calendar fetch failed: %s", exc)
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        table.to_csv(self.cache_dir / EARNINGS_FILE, index=False)
        (self.cache_dir / EARNINGS_META).write_text(
            json.dumps(
                {
                    "source": f"{SOURCE_NAME} EARNINGS_CALENDAR",
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "fetched_date": as_of.isoformat(),
                }
            ),
            encoding="utf-8",
        )

    def _earnings_meta(self) -> dict | None:
        path = self.cache_dir / EARNINGS_META
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def earnings(self, as_of: date, max_age_days: int = 3) -> EarningsData:
        meta = self._earnings_meta()
        path = self.cache_dir / EARNINGS_FILE
        if not meta or not path.exists():
            return EarningsData(None, None, None, "earnings calendar not available")
        fetched = date.fromisoformat(meta["fetched_date"])
        if (as_of - fetched).days > max_age_days:
            return EarningsData(None, meta["source"], meta["fetched_at"], f"earnings calendar is stale (fetched {fetched})")
        table = pd.read_csv(path)
        table["reportDate"] = pd.to_datetime(table["reportDate"]).dt.date
        return EarningsData(table, meta["source"], meta["fetched_at"])


def import_robinhood(settings: Settings, json_path: Path) -> dict[str, int]:
    """Merge saved Robinhood MCP historicals into the cache. Returns bars cached per symbol."""
    from .robinhood import load_historicals_file

    cache_dir = settings.resolve(settings.data.cache_dir)
    counts = {}
    for sym, new in load_historicals_file(json_path).items():
        merged = merge_bars(read_cache(cache_dir, sym), new)
        write_cache(cache_dir, sym, merged)
        counts[sym] = len(merged)
    return counts


def import_csv(settings: Settings, symbol: str, csv_path: Path) -> int:
    """Merge a user-supplied CSV of daily bars into the cache (e.g. longer history)."""
    from .cache import load_csv_file

    cache_dir = settings.resolve(settings.data.cache_dir)
    new = load_csv_file(csv_path)
    merged = merge_bars(read_cache(cache_dir, symbol), new)
    write_cache(cache_dir, symbol, merged)
    return len(merged)
