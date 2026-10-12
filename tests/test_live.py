"""Manual live tickets: sizing against the real account, never sending orders."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from agent_trading.account import AccountSnapshot
from agent_trading.config import ConfigError, validate
from agent_trading.live import LiveLedger, Ticket, build_tickets, prepare
from agent_trading.paper import Intent

AS_OF = date(2026, 10, 12)


def snap(total=1000.0, cash=1000.0, positions=(), orders=(), last4="8204", age_h=1.0):
    fetched = (datetime.now(timezone.utc) - timedelta(hours=age_h)).isoformat(timespec="seconds")
    return AccountSnapshot(fetched, last4, "Agent-trading", total, cash, cash, list(positions), list(orders))


@pytest.fixture
def ledger(settings):
    return LiveLedger(settings.resolve(settings.paths.journal_db))


def buy(sym="NVDA", ref=100.0, stop=95.0, strategy="B-desk"):
    return Intent(sym, "buy", ref, stop, strategy, "test", 1.0)


def run(settings, ledger, s, intents, record=False):
    res = prepare(settings, ledger, s, AS_OF, record=record)
    return build_tickets(settings, res, s, intents, {}) if res.verified else res


def test_disabled_produces_nothing(settings, ledger):
    s = replace(settings, live=replace(settings.live, enabled=False))
    res = prepare(s, ledger, snap(), AS_OF)
    assert not res.enabled and not res.verified and not res.tickets


@pytest.mark.parametrize("bad", [None, snap(last4="1234"), snap(age_h=48)])
def test_unverified_snapshot_blocks_tickets(settings, ledger, bad):
    res = prepare(settings, ledger, bad, AS_OF)
    assert res.enabled and not res.verified and res.account_note


def test_buy_sized_on_capped_equity_with_limit_and_stop(settings, ledger):
    res = run(settings, ledger, snap(total=5000, cash=5000), [buy()])
    assert res.equity == 1000 and res.cash == 1000  # capped at live.capital
    (t,) = res.tickets
    assert t.side == "buy" and t.limit_price == 100.5 and t.stop_price == 95.0
    r = settings.risk
    assert t.planned_risk <= 1000 * r.risk_per_trade_pct + 1e-9
    assert t.notional <= 1000 * r.max_position_pct + 1e-9


def test_only_live_strategies_ticketed(settings, ledger):
    res = run(settings, ledger, snap(), [buy("AAA", strategy="A-scanner")])
    assert res.tickets == []


def test_sell_only_what_is_held(settings, ledger):
    ledger.replace_tickets(date(2026, 10, 1), [Ticket("NVDA", "buy", 2, 101, 95, "B-desk", "x", 5)])
    held = snap(total=1000, cash=800, positions=[{"symbol": "NVDA", "quantity": 2.0, "average_buy_price": 100.0}],
                orders=[{"symbol": "NVDA", "side": "sell", "state": "confirmed", "quantity": "2"}])
    intents = [Intent("NVDA", "sell", 110, None, "B-desk", "below SMA50"),
               Intent("TLT", "sell", 90, None, "C-gtaa", "below average")]
    res = run(settings, ledger, held, intents)
    (t,) = res.tickets
    assert (t.symbol, t.side, t.quantity, t.limit_price) == ("NVDA", "sell", 2.0, 109.45)
    assert "cancel its open stop order first" in t.reason
    assert res.positions["NVDA"].stop == 95  # stop comes from the opening ticket


def test_unknown_position_counts_fully_as_risk(settings, ledger):
    manual = snap(total=1000, cash=800, positions=[{"symbol": "XYZ", "quantity": 4.0, "average_buy_price": 50.0}])
    res = run(settings, ledger, manual, [buy()])
    assert any("stop is unknown" in w for w in res.warnings)
    assert res.tickets == [] and "open-risk" in res.skipped[0]


def test_open_buy_order_blocks_new_buys(settings, ledger):
    pending = snap(orders=[{"symbol": "GLD", "side": "buy", "state": "queued", "quantity": "1"}])
    res = run(settings, ledger, pending, [buy()])
    assert res.tickets == [] and "open buy order" in res.skipped[0]


def test_daily_loss_limit_blocks_buys(settings, ledger):
    ledger.record_equity(date(2026, 10, 9), 1000.0)
    res = run(settings, ledger, snap(total=985, cash=985), [buy()], record=True)
    assert not res.status.new_entries_allowed and res.tickets == []
    assert "daily loss" in res.skipped[0]


def test_tickets_are_idempotent_per_day(settings, ledger):
    t = Ticket("GLD", "buy", 1, 300, 290, "C-gtaa", "x", 10)
    ledger.replace_tickets(AS_OF, [t])
    ledger.replace_tickets(AS_OF, [t])
    day, tickets = ledger.latest_tickets()
    assert day == AS_OF.isoformat() and tickets == [t]


def test_config_rejects_unknown_live_strategy(settings):
    with pytest.raises(ConfigError, match="live.strategies"):
        validate(replace(settings, live=replace(settings.live, strategies=["Z-yolo"])))
