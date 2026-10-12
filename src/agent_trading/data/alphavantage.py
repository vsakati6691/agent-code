"""Minimal Alpha Vantage client (daily bars + earnings calendar).

The API key is sent as a query parameter, so request URLs are never logged and
HTTP errors are re-raised without the URL.
"""
from __future__ import annotations

import io
import logging
import time
from typing import Any

import pandas as pd
import requests

from ..logging_setup import register_secret

BASE_URL = "https://www.alphavantage.co/query"
SOURCE_NAME = "Alpha Vantage"
log = logging.getLogger(__name__)


class AlphaVantageError(RuntimeError):
    """API returned an error, a rate-limit notice, or a premium-only notice."""


def parse_daily_json(data: dict[str, Any], symbol: str) -> pd.DataFrame:
    for key in ("Error Message", "Information", "Note"):
        if key in data:
            raise AlphaVantageError(f"{symbol}: {data[key]}")
    series = data.get("Time Series (Daily)")
    if not series:
        raise AlphaVantageError(f"{symbol}: response has no daily time series")
    df = pd.DataFrame.from_dict(series, orient="index")
    df = df.rename(
        columns={
            "1. open": "open",
            "2. high": "high",
            "3. low": "low",
            "4. close": "close",
            "5. volume": "volume",
        }
    )
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()


def parse_earnings_csv(text: str) -> pd.DataFrame:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        raise AlphaVantageError(f"earnings calendar: {stripped[:200]}")
    df = pd.read_csv(io.StringIO(text))
    expected = {"symbol", "reportDate", "fiscalDateEnding"}
    if not expected.issubset(df.columns):
        raise AlphaVantageError("earnings calendar: unexpected format")
    df["reportDate"] = pd.to_datetime(df["reportDate"]).dt.date
    return df


def parse_treasury_json(data: dict[str, Any]) -> pd.Series:
    """Monthly 3-month T-bill yields in percent, indexed by month start."""
    for key in ("Error Message", "Information", "Note"):
        if key in data:
            raise AlphaVantageError(f"treasury yield: {data[key]}")
    rows = [(r["date"], r["value"]) for r in data.get("data", []) if r.get("value") not in (None, "", ".")]
    if not rows:
        raise AlphaVantageError("treasury yield: no data")
    s = pd.Series({pd.Timestamp(d): float(v) for d, v in rows}).sort_index()
    s.index.name = "date"
    return s.rename("yield_pct")


class AlphaVantageClient:
    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        pause_seconds: float = 12.5,
        timeout: float = 30.0,
    ) -> None:
        register_secret(api_key)
        self._key = api_key
        self._session = session or requests.Session()
        self._pause = pause_seconds
        self._timeout = timeout
        self._last_call = 0.0
        self.calls_made = 0

    def _get(self, params: dict[str, str]) -> requests.Response:
        wait = self._pause - (time.monotonic() - self._last_call)
        if self.calls_made and wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        self.calls_made += 1
        log.info("Alpha Vantage request: function=%s symbol=%s", params.get("function"), params.get("symbol", "-"))
        try:
            resp = self._session.get(BASE_URL, params={**params, "apikey": self._key}, timeout=self._timeout)
        except requests.RequestException as exc:
            raise AlphaVantageError(f"network error ({type(exc).__name__})") from None
        if resp.status_code != 200:
            raise AlphaVantageError(f"HTTP {resp.status_code}")
        return resp

    def daily_bars(self, symbol: str, outputsize: str = "compact") -> pd.DataFrame:
        resp = self._get({"function": "TIME_SERIES_DAILY", "symbol": symbol, "outputsize": outputsize})
        try:
            data = resp.json()
        except ValueError:
            raise AlphaVantageError(f"{symbol}: response was not JSON") from None
        return parse_daily_json(data, symbol)

    def treasury_yield(self, maturity: str = "3month") -> pd.Series:
        resp = self._get({"function": "TREASURY_YIELD", "interval": "monthly", "maturity": maturity})
        try:
            data = resp.json()
        except ValueError:
            raise AlphaVantageError("treasury yield: response was not JSON") from None
        return parse_treasury_json(data)

    def earnings_calendar(self, horizon: str = "3month") -> pd.DataFrame:
        resp = self._get({"function": "EARNINGS_CALENDAR", "horizon": horizon})
        return parse_earnings_csv(resp.text)
