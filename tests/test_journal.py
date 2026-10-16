"""Trade journal (the paper broker's position ledger)."""

import sqlite3
from datetime import date

import pytest

from agent_trading.journal import Journal

D = date(2026, 10, 12)


@pytest.fixture
def journal(tmp_path):
    return Journal(tmp_path / "j.db")


def test_open_close_and_stats(journal):
    a = journal.open_trade("NVDA", 1, 100, 95, D, "trend")
    b = journal.open_trade("AMD", 2, 50, 48, D)
    assert journal.open_risk() == pytest.approx(5 + 4)
    journal.close_trade(a, 110, D, "target")
    journal.close_trade(b, 47, D, "stop")
    s = journal.summary(1000)
    assert s["closed_trades"] == 2 and s["open_trades"] == 0
    assert s["realized_pnl"] == pytest.approx(10 - 6)
    assert s["win_rate"] == 0.5
    closed = journal.closed_trades().set_index("symbol")
    assert closed.loc["NVDA", "r_multiple"] == pytest.approx(2.0)
    assert closed.loc["AMD", "r_multiple"] == pytest.approx(-1.5)


def test_schema_blocks_shorts_and_bad_stops(journal):
    with sqlite3.connect(journal.path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO trades (mode,symbol,side,quantity,entry_date,entry_price,stop_price) "
                "VALUES ('paper','X','short',1,'2026-01-01',10,11)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO trades (mode,symbol,side,quantity,entry_date,entry_price,stop_price) "
                "VALUES ('live','X','long',1,'2026-01-01',10,9)"
            )
    with pytest.raises(sqlite3.IntegrityError):
        journal.open_trade("X", 1, 10, 11, D)  # stop above entry


def test_cannot_close_twice(journal):
    t = journal.open_trade("SPY", 1, 100, 95, D)
    journal.close_trade(t, 101, D)
    with pytest.raises(ValueError):
        journal.close_trade(t, 102, D)
