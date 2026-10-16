"""Regular-session clock for order submission (New York time).

Orders go out only inside the regular session, minus a buffer after the open
and before the close. NYSE early closes (1 PM) are modelled for the recurring
cases: the day after Thanksgiving, Christmas Eve and July 3. An unlisted early
close is the residual risk; the close buffer and day-only orders limit it.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..market_calendar import holidays, is_trading_day

ET = ZoneInfo("America/New_York")
OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)


def is_early_close(d: date) -> bool:
    if not is_trading_day(d):
        return False
    thanksgiving = next(h for h in holidays(d.year) if h.month == 11)
    if d == thanksgiving + timedelta(days=1):
        return True
    return (d.month, d.day) in {(12, 24), (7, 3)}


def session_close(d: date) -> time:
    return EARLY_CLOSE if is_early_close(d) else CLOSE


def submission_window_open(now: datetime, open_buffer_min: int = 5, close_buffer_min: int = 10) -> tuple[bool, str]:
    """(ok, reason). `now` must be timezone-aware."""
    if now.tzinfo is None:
        return False, "clock is not timezone-aware"
    local = now.astimezone(ET)
    d = local.date()
    if not is_trading_day(d):
        return False, f"{d} is not an NYSE trading day"
    start = datetime.combine(d, OPEN, ET) + timedelta(minutes=open_buffer_min)
    end = datetime.combine(d, session_close(d), ET) - timedelta(minutes=close_buffer_min)
    if not start <= local <= end:
        return False, f"outside the submission window {start:%H:%M}-{end:%H:%M} ET (now {local:%H:%M} ET)"
    return True, ""
