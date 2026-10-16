from datetime import date

from agent_trading import market_calendar as mc
from agent_trading.strategies import gtaa
from agent_trading.strategies.desk import next_session


def test_known_nyse_holidays():
    expected_2026 = {
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    }
    assert mc.holidays(2026) == expected_2026
    assert date(2027, 3, 26) in mc.holidays(2027)  # Good Friday 2027
    assert date(2027, 6, 18) in mc.holidays(2027)  # Juneteenth on Saturday -> Friday
    assert date(2027, 12, 24) in mc.holidays(2027)  # Christmas on Saturday -> Friday
    assert date(2022, 12, 31) not in mc.holidays(2022)  # New Year's on Saturday: not observed
    assert date(2021, 6, 18) not in mc.holidays(2021)  # Juneteenth starts in 2022
    assert date(2025, 1, 9) in mc.holidays(2025)  # special closure


def test_trading_day_navigation():
    assert mc.next_trading_day(date(2026, 11, 25)) == date(2026, 11, 27)  # skips Thanksgiving
    assert mc.previous_trading_day(date(2026, 1, 2)) == date(2025, 12, 31)
    assert not mc.is_trading_day(date(2026, 10, 10))  # Saturday
    assert mc.is_trading_day(date(2026, 10, 12))  # Columbus Day: NYSE open


def test_month_end_rebalance_respects_holidays():
    # Memorial Day 2027 is Monday May 31, the month's last weekday: Friday May 28 is the rebalance day.
    assert mc.is_last_trading_day_of_month(date(2027, 5, 28))
    assert gtaa.is_rebalance_day([], date(2027, 5, 28))
    assert gtaa.is_rebalance_day([], date(2026, 10, 30))
    assert not gtaa.is_rebalance_day([], date(2026, 10, 29))


def test_next_session_skips_holidays():
    assert next_session(date(2026, 12, 24)) == date(2026, 12, 28)
    assert next_session(date(2026, 10, 9)) == date(2026, 10, 12)
