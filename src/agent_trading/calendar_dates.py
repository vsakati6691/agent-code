"""Calendar dates for US market events; timestamps are interpreted in New York."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def calendar_day(value: object) -> date | None:
    """Accept ISO dates/timestamps and date objects; invalid or missing values stay missing.

    Date-only and naive timestamps already denote a New York calendar date.
    Aware timestamps are converted before extracting their date, including DST.
    """
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.strip())
        if isinstance(value, datetime):
            value = (value.astimezone(NY) if value.tzinfo else value).date()
        # pandas NaT is a datetime subclass whose .date() still returns NaT.
        return value if isinstance(value, date) and not isinstance(value, datetime) else None
    except (TypeError, ValueError, OverflowError):
        return None
