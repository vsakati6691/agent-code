"""Split-adjusted public-market observations for private, local research only."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

import pandas as pd

from .http import FetchError, HttpClient, ProviderUnavailable

SOURCE = "Massive daily aggregates; split-adjusted, not dividend-adjusted; private personal use"
BASE = "https://api.massive.com/v2/aggs/ticker"


def parse_history(raw: dict, symbol: str) -> pd.DataFrame:
    """Preserve observed OHLCV; downstream validation must reject any bad bar."""
    if not isinstance(raw, dict) or raw.get("status") not in {"OK", "DELAYED"}:
        raise ProviderUnavailable("Massive history: unsuccessful response; stopped for this run")
    if raw.get("ticker") != symbol or raw.get("adjusted") is not True:
        raise FetchError("Massive history: mismatched ticker or unconfirmed split adjustment")
    rows = raw.get("results")
    if not isinstance(rows, list) or not rows:
        raise FetchError("Massive history: no daily bars in the entitled date window")
    if raw.get("next_url") or raw.get("resultsCount", len(rows)) != len(rows):
        raise FetchError("Massive history: incomplete or paginated daily response")
    fields = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
    try:
        if any(
            isinstance(row[k], bool) or not isinstance(row[k], (int, float)) for row in rows for k in (*fields, "t")
        ):
            raise ValueError
        df = pd.DataFrame(rows)
        times = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
        if times.isna().any() or (times != times.dt.normalize()).any():
            raise ValueError
        df.index = pd.DatetimeIndex(times.dt.tz_localize(None), name="date")
        df = df.rename(columns=fields)[list(fields.values())]
        if df.index.has_duplicates or not df.index.is_monotonic_increasing:
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise FetchError("Massive history: malformed, duplicate or unsorted daily bars") from None
    df.attrs["price_source"] = SOURCE
    df.attrs["publication"] = "private"
    return df


def fetch_history(
    http: HttpClient, key: str, symbol: str, as_of: date, *, collected_on: date | None = None
) -> pd.DataFrame:
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.]{0,15}", symbol):
        raise FetchError("Massive history: unsupported stock ticker")
    # Entitlements roll with collection time, not the requested as-of session.
    # One day inside 730 days also avoids an intraday entitlement-boundary rejection.
    collected_on = collected_on or datetime.now(UTC).date()
    start = max(as_of - timedelta(days=730), collected_on - timedelta(days=729))
    if start > as_of:
        raise FetchError("Massive history: as-of date is outside the Basic history window")
    raw = http.get_json(
        f"{BASE}/{symbol}/range/1/day/{start}/{as_of}",
        {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key},
        max_age_hours=12,
        cache_key_extra=f"private-daily-v1:{as_of}",
    )
    try:
        return parse_history(raw, symbol)
    except ProviderUnavailable:
        http.unavailable.add("massive")
        raise
