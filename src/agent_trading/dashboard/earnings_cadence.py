"""Describe the existing calendar-day cadence check without implying a verified schedule."""

import re
from datetime import date

TOLERANCE_DAYS = 21  # Existing pipeline check, not a registered eligibility or scoring rule.


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
