"""Optional FMP quarterly aggregates; never synthesize individual 13F holders."""

from __future__ import annotations

import math
from datetime import date, timedelta

from .http import FetchError

ENDPOINT = "https://financialmodelingprep.com/stable/institutional-ownership/symbol-positions-summary"


def eligible_quarter(as_of: date) -> date:
    start = date(as_of.year, ((as_of.month - 1) // 3) * 3 + 1, 1)
    end = start - timedelta(days=1)
    while (as_of - end).days < 45:
        end = date(end.year, ((end.month - 1) // 3) * 3 + 1, 1) - timedelta(days=1)
    return end


def _count(value: object) -> int:
    if isinstance(value, bool) or value is None:
        raise FetchError("FMP institutional count is missing or invalid")
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise FetchError("FMP institutional count is invalid") from None
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise FetchError("FMP institutional count is invalid")
    return int(number)


def parse(raw: object, symbol: str, quarter: date, retrieved_at: str) -> dict:
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], dict):
        raise FetchError("FMP institutional response must contain one quarterly aggregate")
    row = raw[0]
    if row.get("symbol") != symbol or row.get("date") != str(quarter):
        raise FetchError("FMP institutional symbol or quarter mismatch")
    return {
        "state": "available",
        "provider": "fmp",
        "source": ENDPOINT,
        "retrieved_at": retrieved_at,
        "report_quarter_end": str(quarter),
        "holder_count": _count(row.get("investorsHolding")),
        "reported_shares": _count(row.get("numberOf13Fshares")),
        "top_holders": [],
        "reason": "FMP aggregate fallback; individual holders and original filing timestamps unavailable. Current observation, not historical point-in-time evidence.",
    }
