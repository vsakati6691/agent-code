"""Exchange sessions, DST and early closes, isolated from the daily strategy calendar."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

NY = ZoneInfo("America/New_York")


def aware(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware time required")
    return now.astimezone(NY)


@lru_cache(maxsize=8)
def exchange(year: int):
    return xcals.get_calendar("XNYS", start=f"{year - 1}-01-01", end=f"{year + 1}-12-31")


@dataclass(frozen=True)
class Session:
    open: datetime
    close: datetime

    @property
    def flatten(self) -> datetime:
        return self.close - timedelta(minutes=30)

    @property
    def early(self) -> bool:
        return self.close.astimezone(NY).hour < 16


@lru_cache(maxsize=2048)
def session(day: date) -> Session | None:
    cal = exchange(day.year)
    if not cal.is_session(day.isoformat()):
        return None
    return Session(
        cal.session_open(day.isoformat()).to_pydatetime(), cal.session_close(day.isoformat()).to_pydatetime()
    )


def next_session(day: date) -> date:
    cal = exchange(day.year)
    return cal.date_to_session((day + timedelta(days=1)).isoformat(), direction="next").date()


def entry_window(now: datetime) -> bool:
    local = aware(now)
    s = session(local.date())
    if s is None or s.early:
        return False  # no new entries on short sessions
    return time(9, 45) <= local.time().replace(tzinfo=None) < time(10, 31) or time(13, 30) <= local.time().replace(
        tzinfo=None
    ) < time(13, 35)


def jobs(day: date) -> list[tuple[str, datetime]]:
    s = session(day)
    if s is None:
        return []
    result = [("prepare", datetime.combine(day, time(8, 30), NY))]
    if not s.early:
        result.extend(("scan", datetime.combine(day, time(9, 45), NY) + timedelta(minutes=5 * i)) for i in range(10))
        result.append(("scan", datetime.combine(day, time(13, 30), NY)))
    result.extend([("flatten", s.flatten), ("report", s.close + timedelta(minutes=10))])
    return result
