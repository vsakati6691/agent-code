"""Describe the existing calendar-day cadence check without implying a verified schedule."""

import re
from datetime import date

from ..calendar_dates import calendar_day
from . import spec

TOLERANCE_DAYS = spec.RESILIENCE_RULES["earnings_tolerance_days"]
OUTLIER = "Review Required: Outlier"


def validate(scheduled: str | None, expected: str | None, as_of: date, manual: dict | None = None) -> dict:
    """Validate calendar dates before using them in automated events; keep raw evidence."""
    day = calendar_day(scheduled)
    result = {
        "expected_date": expected,
        "deviation_days": None,
        "outlier": False,
        "validation_status": "Unverified: cadence unavailable",
        "event_eligible": day is not None,
    }
    if scheduled is None or (isinstance(scheduled, str) and not scheduled.strip()):
        return {**result, "validation_status": "No scheduled date", "event_eligible": False}
    if day is None:
        return {**result, "validation_status": "Review Required: Invalid date", "event_eligible": False}
    if day <= as_of:
        return {**result, "validation_status": "Past or current reporting date", "event_eligible": False}
    expected_day = calendar_day(expected)
    if expected_day is None:
        return result
    result["expected_date"] = expected_day.isoformat()
    gap = (day - expected_day).days
    outlier = abs(gap) > TOLERANCE_DAYS
    verified = False
    if isinstance(manual, dict) and manual.get("status") == "verified" and manual.get("confirmed") is True:
        checked = calendar_day(manual.get("checked_at"))
        dates = manual.get("broker_dates")
        verified = bool(
            checked
            and 0 <= (as_of - checked).days <= 14
            and isinstance(dates, list)
            and day in {calendar_day(d) for d in dates}
        )
    return {
        **result,
        "deviation_days": gap,
        "outlier": outlier,
        "validation_status": "Manually verified"
        if verified
        else OUTLIER
        if outlier
        else "Within cadence tolerance (unverified)",
        "event_eligible": not outlier or verified,
    }


def event_eligible(record: dict | None) -> bool:
    """Legacy records remain compatible; new quarantines require explicit release."""
    return (record or {}).get("event_eligible", True) is True


def future_schedule(calendar, as_of: date, symbols: set[str] | None = None) -> dict[str, str]:
    """Normalize provider rows once; an unreadable calendar is unknown, not an empty schedule."""
    from .http import FetchError
    from .provider_parsers import canonical

    if not hasattr(calendar, "columns") or not {"symbol", "reportDate"}.issubset(calendar.columns):
        raise FetchError("earnings calendar columns missing")
    result: dict[str, str] = {}
    for symbol, value in calendar[["symbol", "reportDate"]].itertuples(index=False, name=None):
        if not isinstance(symbol, str) or not symbol.strip():
            raise FetchError("earnings calendar symbol missing")
        symbol = canonical(symbol)
        if symbols is not None and symbol not in symbols:
            continue
        day = calendar_day(value)
        if day is None:
            raise FetchError("earnings calendar date unreadable")
        if day > as_of:
            result[symbol] = min(result.get(symbol, day.isoformat()), day.isoformat())
    return result


UNVERIFIED_NOTE = "schedule remains unverified"
BROKER_NOTE = "schedule verified against the broker calendar"  # the owner's stored Robinhood calendar check agrees


def label(expected: date, scheduled: date, schedule_note: str = UNVERIFIED_NOTE) -> str:
    gap = (scheduled - expected).days
    difference = f"{abs(gap)} calendar days {'earlier' if gap < 0 else 'later'}" if gap else "on the expected date"
    verdict = "within" if abs(gap) <= TOLERANCE_DAYS else "outside"
    return (
        f"{difference} relative to the 8-K cadence estimate (expected about {expected}); "
        f"{verdict} the ±{TOLERANCE_DAYS}-calendar-day check; {schedule_note}"
    )


def display(record: dict, schedule_note: str = UNVERIFIED_NOTE) -> str:
    stored = record.get("cadence_check") or ""
    expected = re.search(r"expected about (\d{4}-\d{2}-\d{2})", stored)
    scheduled = record.get("next_scheduled") or record.get("date")
    if expected and scheduled:
        expected_day, scheduled_day = calendar_day(expected[1]), calendar_day(scheduled)
        if expected_day and scheduled_day:
            return label(expected_day, scheduled_day, schedule_note)
    return stored


def schedule_note(verdict: dict | None) -> str:
    """The cadence sentence's closing note, given the broker-calendar verdict for the same date (or None)."""
    return BROKER_NOTE if (verdict or {}).get("status") == "verified" else UNVERIFIED_NOTE
