"""Describe the existing calendar-day cadence check without implying a verified schedule."""

import re
from datetime import date

TOLERANCE_DAYS = 21  # Existing pipeline check, not a registered eligibility or scoring rule.


def label(expected: date, scheduled: date) -> str:
    gap = (scheduled - expected).days
    difference = f"{abs(gap)} calendar days {'earlier' if gap < 0 else 'later'}" if gap else "on the expected date"
    verdict = "within" if abs(gap) <= TOLERANCE_DAYS else "outside"
    return (
        f"{difference} relative to the 8-K cadence estimate (expected about {expected}); "
        f"{verdict} the ±{TOLERANCE_DAYS}-calendar-day check; schedule remains unverified"
    )


def display(record: dict) -> str:
    stored = record.get("cadence_check") or ""
    expected = re.search(r"expected about (\d{4}-\d{2}-\d{2})", stored)
    scheduled = record.get("next_scheduled") or record.get("date")
    if expected and scheduled:
        try:
            return label(date.fromisoformat(expected[1]), date.fromisoformat(scheduled))
        except ValueError:
            pass
    return stored
