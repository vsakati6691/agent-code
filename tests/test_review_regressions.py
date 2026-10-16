"""Regressions for the four defects reproduced by the 2026-10-13 repository review.

1. The order gate's daily purchase and entry counters restarted at zero on
   every call, so a same-day rerun could approve a second $200 / 3 entries.
2. Any open sell order (a take-profit limit, a partial stop) silenced the
   missing-stop warning, whatever its type or quantity.
3. Execution reconciliation counted fills twice when its baseline was first
   recorded after an order had already filled.
4. Account parsing accepted positive infinity for cash and account value.
"""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from agent_trading import killswitch, order_gate
from agent_trading.account import AccountSnapshot, SnapshotError, parse_snapshot
from agent_trading.execution.ledger import OrderLedger
from agent_trading.execution.models import OrderRequest, Quote
from agent_trading.execution.service import ExecutionService
from agent_trading.execution.sim import SimulatedBroker
from agent_trading.live import LiveLedger, Ticket, build_tickets, prepare
from agent_trading.paper import Intent
from agent_trading.risk import TradingStatus

AS_OF = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 21, 0, tzinfo=UTC)
OK = TradingStatus(True, "ok", 0.0, 0.0, 1000.0)


def bars(**closes):
    idx = pd.to_datetime([AS_OF - timedelta(days=1), AS_OF])
    return {
        s: pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6}, index=idx)
        for s, c in closes.items()
    }


BARS = bars(SPY=600.0, EFA=80.0, IEF=95.0, GLD=250.0)


def snap(total=1000.0, cash=1000.0, positions=(), orders=(), fetched=NOW - timedelta(minutes=20)):
    return AccountSnapshot(
        fetched.isoformat(timespec="seconds"),
        "1234",
        "Agent-trading",
        total,
        cash,
        cash,
        list(positions),
        list(orders),
        0.0,
    )


def buy(sym, qty, limit, stop):
    return Ticket(sym, "buy", qty, limit, stop, "C-gtaa", "test")


# --- 1. daily counters persist across gate calls ---------------------------------


def test_gate_counts_tickets_already_issued_that_day(settings):
    first = order_gate.check_tickets(
        settings, [buy("SPY", 0.16, 603, 580), buy("EFA", 1.2, 80.4, 76)], snap(), AS_OF, BARS, OK, NOW
    )
    assert len(first.approved) == 2  # $192.96, 2 entries
    second = order_gate.check_tickets(
        settings,
        [buy("IEF", 1.0, 95.4, 92), buy("GLD", 0.38, 251, 240)],
        snap(),
        AS_OF,
        BARS,
        OK,
        NOW,
        issued_today=first.approved,
    )
    assert not second.approved
    assert all("remaining room" in why for _, why in second.rejected)


def test_gate_entry_counter_survives_reruns(settings):
    small = [buy("SPY", 0.05, 603, 580), buy("EFA", 0.3, 80.4, 76), buy("IEF", 0.3, 95.4, 92)]  # 3 entries, < $100
    res = order_gate.check_tickets(
        settings, [buy("GLD", 0.1, 251, 240)], snap(), AS_OF, BARS, OK, NOW, issued_today=small
    )
    assert not res.approved and "remaining room" in res.rejected[0][1]


def test_gate_rejects_a_symbol_already_ticketed_today(settings):
    res = order_gate.check_tickets(
        settings, [buy("SPY", 0.1, 603, 580)], snap(), AS_OF, BARS, OK, NOW, issued_today=[buy("SPY", 0.1, 603, 580)]
    )
    assert not res.approved and "already ticketed" in res.rejected[0][1]


def test_ledger_keeps_earlier_same_day_tickets_and_sizing_respects_them(settings):
    ledger = LiveLedger(settings.resolve(settings.paths.journal_db))
    ledger.add_tickets(AS_OF, [buy("SPY", 0.16, 603, 580), buy("EFA", 1.2, 80.4, 76)])
    ledger.add_tickets(AS_OF, [buy("SPY", 0.16, 603, 580)])  # a rerun never duplicates or deletes
    issued = ledger.tickets_on(AS_OF)
    assert [t.symbol for t in issued] == ["SPY", "EFA"]
    assert ledger.latest_buy("SPY") is not None  # the stop stays known
    s = snap(fetched=datetime.now(UTC) - timedelta(minutes=20))
    res = prepare(settings, ledger, s, AS_OF)
    assert [t.symbol for t in res.issued_today] == ["SPY", "EFA"]
    res = build_tickets(
        settings,
        res,
        s,
        [Intent("SPY", "buy", 600.0, 580.0, "C-gtaa", "t", 1.0), Intent("IEF", "buy", 50.0, 49.0, "C-gtaa", "t", 0.5)],
        {},
    )
    assert any("SPY: already ticketed today" in m for m in res.skipped)
    (ief,) = res.tickets  # only $7.04 of the $200/day is left
    assert ief.notional <= 200 - (0.16 * 603 + 1.2 * 80.4) + 1e-6


# --- 2. missing-stop warning needs a stop order that covers the position -------------


def _stop_snapshot(orders):
    raw = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "account_number": "xxxx1234",
        "nickname": "Agent-trading",
        "unsettled_funds": "0",
        "portfolio": {"total_value": "1000", "cash": "910", "buying_power": {"buying_power": "910"}},
        "positions": [{"symbol": "SPY", "quantity": "0.15", "average_buy_price": "600"}],
        "orders": orders,
    }
    return parse_snapshot(raw)


def _warnings(settings, orders):
    ledger = LiveLedger(settings.resolve(settings.paths.journal_db))
    ledger.replace_tickets(date(2026, 10, 9), [buy("SPY", 0.15, 603, 580)])
    return [w for w in prepare(settings, ledger, _stop_snapshot(orders), AS_OF).warnings if w.startswith("SPY")]


SELL = {"symbol": "SPY", "side": "sell", "state": "confirmed"}


@pytest.mark.parametrize(
    "order, fragment",
    [
        (dict(SELL, quantity="0.15", type="limit", trigger="immediate", price="700"), "no stop-loss"),  # take-profit
        (dict(SELL, quantity="0.05", type="market", trigger="stop", stop_price="580"), "cover only 0.05"),
        (dict(SELL, quantity="0.15", type="market", trigger="stop"), "no stop-loss"),  # no stop price
        (dict(SELL, quantity="0.15"), "no stop-loss"),  # type unknown
    ],
)
def test_open_sell_that_does_not_protect_the_position_still_warns(settings, order, fragment):
    (w,) = _warnings(settings, [order])
    assert fragment in w


@pytest.mark.parametrize(
    "orders",
    [
        [dict(SELL, quantity="0.15", type="market", trigger="stop", stop_price="580")],
        [
            dict(SELL, quantity="0.10", type="limit", trigger="stop", stop_price="580", price="575"),
            dict(SELL, quantity="0.05", type="market", trigger="stop", stop_price="580"),
        ],
    ],
)
def test_stop_orders_covering_the_full_position_clear_the_warning(settings, orders):
    assert _warnings(settings, orders) == []


def test_snapshot_keeps_order_type_trigger_and_stop_price():
    (o,) = _stop_snapshot([dict(SELL, quantity="0.15", type="market", trigger="stop", stop_price="580")]).open_orders
    assert (o["type"], o["trigger"], o["stop_price"]) == ("market", "stop", 580.0)


# --- 3. reconciliation baseline after a fill ---------------------------------------


def test_baseline_recorded_after_a_fill_does_not_double_count(settings, tmp_path):
    now = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    quotes = {
        s: Quote(s, px - 0.01, px + 0.01, px, now - timedelta(seconds=5)) for s, px in (("IEF", 95.0), ("EFA", 80.0))
    }
    broker = SimulatedBroker(1000.0, None, quotes, clock=lambda: now)
    svc = ExecutionService(settings, broker, OrderLedger(tmp_path / "orders.db"), "paper", clock=lambda: now)
    assert svc.execute(OrderRequest("d1", "C-gtaa", "IEF", "buy", 1, 95.05)).filled_quantity == 1
    assert svc.health_check().problems == []  # records the baseline
    assert svc.health_check().problems == []  # nothing changed since
    assert not killswitch.status(settings).engaged
    # a later fill is still counted, and a real mismatch is still caught
    assert svc.execute(OrderRequest("d2", "C-gtaa", "EFA", "buy", 1, 80.05)).filled_quantity == 1
    assert svc.health_check().problems == []
    broker.positions["IEF"] = 5
    assert any("IEF: broker holds 5, ledger expects 1" in p for p in svc.health_check().problems)


# --- 4. non-finite account numbers -----------------------------------------------


@pytest.mark.parametrize(
    "field, value",
    [("total_value", "inf"), ("cash", "Infinity"), ("buying_power", "1e999"), ("cash", "nan"), ("total_value", "-1")],
)
def test_non_finite_or_negative_account_numbers_are_rejected(field, value):
    portfolio = {"total_value": "1000", "cash": "1000", "buying_power": "1000", field: value}
    raw = {"fetched_at": NOW.isoformat(), "account_number": "xxxx1234", "portfolio": portfolio}
    with pytest.raises(SnapshotError):
        parse_snapshot(raw)


@pytest.mark.parametrize(
    "raw_pos",
    [
        {"symbol": "SPY", "quantity": "inf"},
        {"symbol": "SPY", "quantity": "1", "average_buy_price": "inf"},
        {"symbol": "SPY", "quantity": "1", "average_buy_price": "nan"},
    ],
)
def test_non_finite_position_numbers_are_rejected(raw_pos):
    raw = {
        "fetched_at": NOW.isoformat(),
        "account_number": "xxxx1234",
        "unsettled_funds": "0",
        "portfolio": {"total_value": "1000", "cash": "1000", "buying_power": "1000"},
        "positions": [raw_pos],
    }
    with pytest.raises(SnapshotError):
        parse_snapshot(raw)


def test_infinite_unsettled_funds_rejected():
    raw = {
        "fetched_at": NOW.isoformat(),
        "account_number": "xxxx1234",
        "unsettled_funds": "inf",
        "portfolio": {"total_value": "1000", "cash": "1000", "buying_power": "1000"},
    }
    with pytest.raises(SnapshotError):
        parse_snapshot(raw)
