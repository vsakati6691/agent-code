"""NYSE trading calendar (full-day closures only; early closes are ordinary sessions).

Rule-based, so it needs no data feed. It covers the regular NYSE holidays:
New Year's Day, MLK Day, Presidents' Day, Good Friday, Memorial Day,
Juneteenth (from 2022), Independence Day, Labor Day, Thanksgiving and
Christmas, with the NYSE weekend rules:
- a Sunday holiday is observed on Monday;
- a Saturday holiday is observed on Friday, except New Year's Day, which is
  then not observed.

One-off closures (e.g. national days of mourning) are not predictable. They
are listed in SPECIAL_CLOSURES when known; an unlisted one simply looks like a
day with no new bar, which the freshness checks already reject.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import cache

SPECIAL_CLOSURES = {
    date(2012, 10, 29),
    date(2012, 10, 30),  # Hurricane Sandy
    date(2018, 12, 5),  # President G.H.W. Bush
    date(2025, 1, 9),  # President Carter
}


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    offset = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * offset) // 451
    month = (h + offset - 7 * m + 114) // 31
    day = (h + offset - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date, saturday_rule: bool = True) -> date | None:
    if d.weekday() == 6:
        return d + timedelta(days=1)
    if d.weekday() == 5:
        return d - timedelta(days=1) if saturday_rule else None
    return d


@cache
def holidays(year: int) -> frozenset[date]:
    days = [
        _observed(date(year, 1, 1), saturday_rule=False),
        _nth_weekday(year, 1, 0, 3),  # MLK Day
        _nth_weekday(year, 2, 0, 3),  # Presidents' Day
        _easter(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 6, 19)) if year >= 2022 else None,
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),
    ]
    return frozenset(d for d in days if d is not None) | {d for d in SPECIAL_CLOSURES if d.year == year}


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def is_last_trading_day_of_month(d: date) -> bool:
    return is_trading_day(d) and next_trading_day(d).month != d.month
