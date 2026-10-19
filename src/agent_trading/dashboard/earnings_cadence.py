"""Describe the existing calendar-day cadence check without implying a verified schedule."""

import re
from datetime import date

from . import spec

TOLERANCE_DAYS = spec.RESILIENCE_RULES["earnings_tolerance_days"]
OUTLIER = "Review Required: Outlier"


def validate(scheduled: str | None, expected: str | None, as_of: date, manual: dict | None = None) -> dict:
    """Validate calendar dates before using them in automated events; keep raw evidence."""
    result = {
        "expected_date": expected,
        "deviation_days": None,
        "outlier": False,
        "validation_status": "Unverified: cadence unavailable",
        "event_eligible": bool(scheduled),
    }
    if not scheduled:
        return {**result, "validation_status": "No scheduled date", "event_eligible": False}
    try:
        day = date.fromisoformat(scheduled)
    except (ValueError, TypeError):
        return {**result, "validation_status": "Review Required: Invalid date", "event_eligible": False}
    if day <= as_of:
        return {**result, "validation_status": "Past or current reporting date", "event_eligible": False}
    if not expected:
        return result
    try:
        gap = (day - date.fromisoformat(expected)).days
    except (ValueError, TypeError):
        return result
    outlier = abs(gap) > TOLERANCE_DAYS
    verified = False
    if manual and manual.get("status") == "verified" and manual.get("confirmed") is True:
        try:
            age = (as_of - date.fromisoformat(str(manual["checked_at"])[:10])).days
            verified = 0 <= age <= 14 and scheduled in manual.get("broker_dates", [])
        except (KeyError, TypeError, ValueError):
            pass
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
        try:
            return label(date.fromisoformat(expected[1]), date.fromisoformat(scheduled), schedule_note)
        except ValueError:
            pass
    return stored


def schedule_note(verdict: dict | None) -> str:
    """The cadence sentence's closing note, given the broker-calendar verdict for the same date (or None)."""
    return BROKER_NOTE if (verdict or {}).get("status") == "verified" else UNVERIFIED_NOTE
