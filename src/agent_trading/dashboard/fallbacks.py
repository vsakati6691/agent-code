"""Strict parsers for optional quote/profile fallbacks; all I/O stays in http.py."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from .http import FetchError
from .provider_parsers import Quote, _num, canonical

FMP_BASE = "https://financialmodelingprep.com/stable"
FMP_SOURCE = "Financial Modeling Prep company profile; current observation, not point-in-time history"


def fmp_row(raw: object, symbol: str) -> dict:
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        raise FetchError("FMP response missing a single company record")
    row = raw[0]
    if canonical(str(row.get("symbol", ""))) != canonical(symbol):
        raise FetchError("FMP symbol missing or mismatched")
    return row


def profile(raw: object, symbol: str, observed_at: str) -> dict:
    row = fmp_row(raw, symbol)
    cap = _num(row.get("marketCap"))
    if not isinstance(row.get("companyName"), str) or not row["companyName"].strip() or cap is None or cap <= 0:
        raise FetchError("FMP basic company fundamentals incomplete")
    return {
        "Symbol": canonical(symbol),
        "Name": row["companyName"],
        "MarketCapitalization": cap,
        "Sector": row.get("sector"),
        "Industry": row.get("industry"),
        "Description": row.get("description"),
        "Beta": _num(row.get("beta")),
        "_source": FMP_SOURCE,
        "_observed_at": observed_at,
    }


def daily_quote(raw: dict | list, symbol: str, as_of: date, observed_at: str, provider: str) -> Quote:
    try:
        if provider == "alphavantage":
            row = raw.get("Global Quote") or {}
            name = row.get("01. symbol", "")
            day = date.fromisoformat(row["07. latest trading day"])
            last = datetime.combine(day, time.min, ZoneInfo("America/New_York"))
            close, previous = _num(row.get("05. price")), _num(row.get("08. previous close"))
            source = "Alpha Vantage GLOBAL_QUOTE (daily; trade date only)"
        else:
            row = fmp_row(raw, symbol)
            name = row.get("symbol", "")
            last = datetime.fromtimestamp(float(row["timestamp"]), UTC).astimezone(ZoneInfo("America/New_York"))
            if last.hour < 16:
                raise ValueError("intraday quote")
            day = last.date()
            close, previous = _num(row.get("price")), _num(row.get("previousClose"))
            source = "Financial Modeling Prep stock quote"
        if canonical(name) != canonical(symbol) or day != as_of or close is None or close <= 0:
            raise ValueError("invalid quote")
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, OSError):
        raise FetchError(f"{provider}: quote symbol, completed session or price invalid") from None
    # Close-only fallback: do not splice a different provider's OHLCV into Cboe history.
    return Quote(canonical(symbol), close, previous, last, None, observed_at, source=source)
