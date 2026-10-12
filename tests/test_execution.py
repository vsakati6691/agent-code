"""Execution service: validation, idempotency, ambiguous outcomes, reconciliation, halt.

Everything runs against SimulatedBroker; nothing here can reach a real broker.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from agent_trading import killswitch
from agent_trading.execution.ledger import OrderLedger
from agent_trading.execution.models import (BLOCKED, CANCELLED, DRY_RUN, FILLED, NOT_SENT, PARTIALLY_FILLED,
                                            REJECTED, UNKNOWN, OrderRequest, Quote)
from agent_trading.execution.service import (OWNER_NOT_PLACED_PHRASE, ExecutionService, ModeError,
                                             verify_mode)
from agent_trading.execution.session import is_early_close, submission_window_open
from agent_trading.execution.sim import SimulatedBroker

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)     # Tuesday 11:00 ET


def quote(sym, px, now=NOW, spread=0.02):
    return Quote(sym, px - spread / 2, px + spread / 2, px, now - timedelta(seconds=5))


def make(settings, tmp_path, mode="paper", cash=1000.0, positions=None, now=NOW):
    broker = SimulatedBroker(cash, positions, {"IEF": quote("IEF", 95.0, now), "EFA": quote("EFA", 80.0, now),
                                               "SPY": quote("SPY", 600.0, now), "TQQQ": quote("TQQQ", 90.0, now)},
                             clock=lambda: now)
    svc = ExecutionService(settings, broker, OrderLedger(tmp_path / "orders.db"), mode, clock=lambda: now)
    svc.health_check()          # records the reconciliation baseline
    return svc, broker


def buy(sym="IEF", qty=1, limit=95.05, decision="d1"):
    return OrderRequest(decision, "C-gtaa", sym, "buy", qty, limit)


def test_valid_paper_buy_fills_and_is_recorded(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    res = svc.execute(buy())
    assert res.state == FILLED and res.filled_quantity == 1 and res.broker_id
    row = svc.ledger.get(res.ref_id)
    assert row["state"] == FILLED and row["mode"] == "paper"
    events = [e["event"] for e in svc.ledger.events(res.ref_id)]
    assert events[0] == "created"            # persisted before submission
    assert broker.positions["IEF"] == 1


def test_same_decision_is_never_sent_twice(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    svc.execute(buy())
    again = svc.execute(buy())
    assert "duplicate decision" in again.reasons[0]
    assert broker.submit_calls == 1


def test_dry_run_never_calls_submit(settings, tmp_path):
    svc, broker = make(settings, tmp_path, mode="dry_run")
    res = svc.execute(buy())
    assert res.state == DRY_RUN and broker.submit_calls == 0


@pytest.mark.parametrize("req, fragment", [
    (buy(qty=2, limit=95.05), "per order"),                              # $190 > $100
    (buy("TQQQ", limit=90.05), "leveraged/inverse"),
    (buy("AAPL", limit=200.0), "allowlist"),
    (buy(limit=99.0), "above the ask"),
    (buy("SPY", limit=600.0), "per order"),
    (OrderRequest("d1", "C-gtaa", "IEF", "buy", 0, 95.0), "whole number"),
    (OrderRequest("d1", "C-gtaa", "IEF", "buy", 1, 95.0, "gtc"), "gfd"),
    (OrderRequest("d1", "C-gtaa", "IEF", "sell", 1, 94.9), "no short selling"),
])
def test_validator_refusals_are_recorded_and_not_sent(settings, tmp_path, req, fragment):
    svc, broker = make(settings, tmp_path)
    res = svc.execute(req)
    assert res.state == BLOCKED and any(fragment in r for r in res.reasons), res.reasons
    assert broker.submit_calls == 0


def test_cash_reserve_and_settled_cash(settings, tmp_path):
    svc, _ = make(settings, tmp_path, cash=290.0)
    res = svc.execute(buy())                                             # 290 - 95 < 200 reserve
    assert res.state == BLOCKED and any("reserve" in r for r in res.reasons)


def test_unsettled_sale_proceeds_cannot_fund_buys(settings, tmp_path):
    svc, broker = make(settings, tmp_path, cash=200.0, positions={"EFA": 2})
    assert svc.execute(OrderRequest("s1", "C-gtaa", "EFA", "sell", 2, 79.95)).state == FILLED
    res = svc.execute(buy(decision="b1"))                                # cash 360, settled 200
    assert res.state == BLOCKED and any("reserve" in r for r in res.reasons)
    broker.settle()
    assert svc.execute(buy(decision="b2")).state == FILLED


def test_stale_quote_market_closed_and_wide_spread_block(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    broker.set_quote(Quote("IEF", 94.99, 95.01, 95.0, NOW - timedelta(minutes=5)))
    assert any("quote is" in r for r in svc.execute(buy(decision="a")).reasons)
    broker.set_quote(Quote("IEF", 94.0, 96.0, 95.0, NOW))
    assert any("spread" in r for r in svc.execute(buy(decision="b", limit=96.0)).reasons)
    sat = datetime(2026, 10, 17, 15, 0, tzinfo=timezone.utc)
    assert not submission_window_open(sat)[0]
    assert not submission_window_open(datetime(2026, 10, 13, 13, 31, tzinfo=timezone.utc))[0]   # 9:31 ET
    assert not submission_window_open(datetime(2026, 11, 27, 17, 55, tzinfo=timezone.utc))[0]   # 12:55 ET, early close
    assert submission_window_open(datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc))[0]
    assert is_early_close(date(2026, 12, 24)) and not is_early_close(date(2026, 12, 23))


def test_daily_entry_and_purchase_limits(settings, tmp_path):
    svc, broker = make(settings, tmp_path, cash=1000.0)
    assert svc.execute(buy("IEF", decision="1")).state == FILLED
    assert svc.execute(buy("EFA", limit=80.05, decision="2")).state == FILLED
    broker.set_quote(quote("GLD", 30.0))
    res = svc.execute(OrderRequest("3", "C-gtaa", "GLD", "buy", 1, 30.01))      # $175 + $30 > $200/day
    assert res.state == BLOCKED and any("daily purchases" in r for r in res.reasons)
    broker.set_quote(quote("VNQ", 20.0))
    assert svc.execute(OrderRequest("4", "C-gtaa", "VNQ", "buy", 1, 20.01)).state == FILLED   # 3rd entry
    broker.set_quote(quote("DBC", 2.0))
    res = svc.execute(OrderRequest("5", "C-gtaa", "DBC", "buy", 1, 2.01))
    assert res.state == BLOCKED and any("entry limit" in r for r in res.reasons)


def test_timeout_after_accept_is_resolved_by_lookup_not_resubmission(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    broker.inject("timeout_after_accept")
    res = svc.execute(buy())
    # The service looked the order up by ref_id right after the timeout.
    assert res.state == FILLED and broker.submit_calls == 1
    assert len(broker.orders) == 1


def test_timeout_before_accept_stays_unknown_blocks_symbol_and_is_never_retried(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    broker.inject("timeout_before_accept")
    res = svc.execute(buy())
    assert res.state == UNKNOWN and broker.submit_calls == 1
    again = svc.execute(buy(decision="d2"))                       # a new decision, same symbol
    assert again.state == BLOCKED and any("unresolved" in r for r in again.reasons)
    assert broker.submit_calls == 1
    report = svc.health_check()
    assert not report.ok and report.stale_unresolved
    with pytest.raises(ValueError):
        svc.owner_mark_not_placed(res.ref_id, "yes")
    svc.owner_mark_not_placed(res.ref_id, OWNER_NOT_PLACED_PHRASE)
    assert svc.execute(buy(decision="d3")).state == FILLED


def test_rejection_and_not_sent_are_terminal(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    broker.inject("reject")
    assert svc.execute(buy(decision="a")).state == REJECTED
    broker.inject("not_sent")
    assert svc.execute(buy(decision="b")).state == NOT_SENT
    assert svc.execute(buy(decision="c")).state == FILLED


def test_partial_fill_then_completion_on_later_run(settings, tmp_path):
    svc, broker = make(settings, tmp_path, cash=1000.0)
    broker.set_quote(quote("EFA", 40.0))
    broker.inject("partial")
    res = svc.execute(OrderRequest("p", "C-gtaa", "EFA", "buy", 2, 40.05))
    assert res.state == PARTIALLY_FILLED and res.filled_quantity == 1
    broker.fill_open_orders()
    assert any("-> filled" in line for line in svc.resolve_unresolved())


def test_broker_outage_blocks_and_restart_recovers_from_disk(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    broker.down = True
    res = svc.execute(buy(decision="o"))
    assert res.state == BLOCKED and any("broker unavailable" in r for r in res.reasons)
    broker.down = False
    # Crash after the broker accepted the order but before the ledger saw the reply.
    req = buy(decision="r")
    ref = svc.ledger.create(req, "paper")
    broker.submit(req, ref)
    restarted = ExecutionService(settings, broker, OrderLedger(tmp_path / "orders.db"), "paper", clock=lambda: NOW)
    assert restarted.health_check().ok
    assert restarted.ledger.get(ref)["state"] == FILLED
    assert broker.submit_calls == 1 and len(broker.orders) == 1


def test_crash_after_persist_before_submit_is_unknown_on_restart(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    ref = svc.ledger.create(buy(decision="crash"), "paper")            # PENDING, never submitted
    restarted = ExecutionService(settings, broker, OrderLedger(tmp_path / "orders.db"), "paper", clock=lambda: NOW)
    report = restarted.health_check()
    assert restarted.ledger.get(ref)["state"] == UNKNOWN and not report.ok
    assert broker.submit_calls == 0


def test_unexpected_position_fails_reconciliation_and_engages_kill_switch(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    broker.positions["SPY"] = 1                                        # appeared outside the ledger
    report = svc.health_check()
    assert not report.ok and any("SPY" in p for p in report.problems)
    assert killswitch.status(settings).engaged
    assert svc.execute(buy()).state == BLOCKED


def test_halt_engages_kill_switch_and_cancels_open_orders(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    res = svc.execute(buy(limit=94.0))                                 # below the ask: rests open
    assert svc.ledger.get(res.ref_id)["state"] == "open"
    lines = svc.halt("owner test")
    assert killswitch.status(settings).engaged
    assert svc.ledger.get(res.ref_id)["state"] == CANCELLED and lines
    assert svc.execute(buy(decision="after")).state == BLOCKED


def test_daily_loss_halts_buys_and_drawdown_engages_kill_switch(settings, tmp_path):
    svc, broker = make(settings, tmp_path)
    svc.execute(buy("EFA", limit=80.05, decision="e"))                 # value is now ~$1,000
    broker.set_quote(quote("EFA", 60.0))                               # -$20: 2% down on the day
    res = svc.execute(buy(decision="x"))
    assert res.state == BLOCKED and any("daily loss" in r for r in res.reasons)
    broker.set_quote(quote("EFA", 20.0))                               # -$60 from high-water: >5%
    svc.execute(buy(decision="y"))
    assert killswitch.status(settings).engaged


def test_sells_allowed_while_buys_halted(settings, tmp_path):
    svc, broker = make(settings, tmp_path, positions={"EFA": 1})
    svc.execute(buy(decision="warm"))                                  # sets the day's start value
    broker.set_quote(quote("EFA", 55.0))
    res = svc.execute(OrderRequest("s", "C-gtaa", "EFA", "sell", 1, 54.95))
    assert res.state == FILLED


def test_mode_verification():
    sim = SimulatedBroker(1000.0)

    class FakeLive(SimulatedBroker):
        is_live = True
        name = "fake-live"

    with pytest.raises(ModeError):
        verify_mode("live", sim)
    with pytest.raises(ModeError):
        verify_mode("paper", FakeLive(1000.0))
    with pytest.raises(ModeError):
        verify_mode("dry_run", FakeLive(1000.0))
    with pytest.raises(ModeError):
        verify_mode("papr", sim)
    verify_mode("paper", sim)
