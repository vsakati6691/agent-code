import sqlite3
from datetime import date

import pytest

from agent_trading.cli import main
from agent_trading.data.cache import write_cache
from agent_trading.data.service import EarningsData, MarketDataService
from agent_trading.journal import Journal
from agent_trading.report import build_daily_report, build_dashboard
from agent_trading.screen import run_screen

from .conftest import make_bars

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
            conn.execute("INSERT INTO trades (mode,symbol,side,quantity,entry_date,entry_price,stop_price) "
                         "VALUES ('paper','X','short',1,'2026-01-01',10,11)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO trades (mode,symbol,side,quantity,entry_date,entry_price,stop_price) "
                         "VALUES ('live','X','long',1,'2026-01-01',10,9)")
    with pytest.raises(sqlite3.IntegrityError):
        journal.open_trade("X", 1, 10, 11, D)  # stop above entry


def test_cannot_close_twice(journal):
    t = journal.open_trade("SPY", 1, 100, 95, D)
    journal.close_trade(t, 101, D)
    with pytest.raises(ValueError):
        journal.close_trade(t, 102, D)


def test_daily_report_flags_unverified_earnings(settings, journal):
    cache = settings.resolve(settings.data.cache_dir)
    for i, sym in enumerate(["SPY", "NVDA", "XLU"]):
        write_cache(cache, sym, make_bars(seed=i, drift=0.002, volume=5e6))
    svc = MarketDataService(settings)
    loaded = svc.load(["SPY", "NVDA", "XLU", "MISSING"], D)
    text = build_daily_report(settings, loaded, run_screen(loaded.bars, settings),
                              EarningsData(None, None, None, "not available"), journal, D)
    assert "Mode: PAPER" in text
    assert "not verified" in text
    assert "MISSING" in text  # rejected symbol is disclosed
    assert "Not investment advice" in text


def test_dashboard_renders(settings, journal):
    t = journal.open_trade("NVDA", 1, 100, 95, D)
    journal.close_trade(t, 104, D, "exit")
    page = build_dashboard(settings, journal, {"kind": "test", "metrics": {"total_return": 0.1, "trades": 3}})
    assert "<title>Paper Trading Dashboard</title>" in page and "NVDA" in page


def test_cli_journal_enforces_risk(tmp_path, capsys):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    from .conftest import ROOT

    (cfg_dir / "settings.yaml").write_text((ROOT / "config" / "settings.yaml").read_text())
    cfg = str(cfg_dir / "settings.yaml")
    # 1 share risks $5 x 1.2 stop buffer = $6 > $5 cap; 0.8 share plans $4.80
    assert main(["--config", cfg, "journal", "open", "NVDA", "1", "100", "95"]) == 2
    assert main(["--config", cfg, "journal", "open", "NVDA", "0.8", "100", "95"]) == 0
    # second trade risking $15 would exceed both the per-trade and aggregate limits
    assert main(["--config", cfg, "journal", "open", "AMD", "3", "100", "95"]) == 2
    assert main(["--config", cfg, "journal", "list"]) == 0
    assert "NVDA" in capsys.readouterr().out
