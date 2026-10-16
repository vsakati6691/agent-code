"""Final order gate and kill switch: hard account limits, fail-closed behaviour."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from agent_trading import killswitch, order_gate
from agent_trading.account import AccountSnapshot
from agent_trading.config import HARD_LIMITS, LEVERAGED_INVERSE_ETFS, ConfigError, validate
from agent_trading.live import Ticket
from agent_trading.risk import TradingStatus

AS_OF = date(2026, 10, 12)  # a Monday, NYSE open
NOW = datetime(2026, 10, 12, 21, 0, tzinfo=UTC)  # 5 PM ET
OK = TradingStatus(True, "ok", 0.0, 0.0, 1000.0)


def bars(**closes):
    idx = pd.to_datetime([AS_OF - timedelta(days=1), AS_OF])
    return {
        s: pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 1e6}, index=idx)
        for s, c in closes.items()
    }


def snap(total=1000.0, cash=1000.0, positions=(), orders=(), fetched=NOW - timedelta(minutes=20), unsettled=0.0):
    return AccountSnapshot(
        fetched.isoformat(timespec="seconds"),
        "8204",
        "Agent-trading",
        total,
        cash,
        cash,
        list(positions),
        list(orders),
        unsettled,
    )


def buy(sym="SPY", qty=0.15, limit=603.0, stop=580.0):
    return Ticket(sym, "buy", qty, limit, stop, "C-gtaa", "test")


def check(settings, tickets, s=None, b=None, status=OK, now=NOW, as_of=AS_OF):
    return order_gate.check_tickets(
        settings,
        tickets,
        snap() if s is None else s,
        as_of,
        bars(SPY=600.0, EFA=80.0, IEF=95.0, GLD=250.0, TQQQ=90.0, NVDA=180.0) if b is None else b,
        status,
        now,
    )


def test_valid_buy_passes(settings):
    res = check(settings, [buy()])
    assert res.approved and not res.rejected and not res.blockers


@pytest.mark.parametrize(
    "ticket, fragment",
    [
        (buy(qty=0.2), "per-order limit"),  # $120.60 > $100
        (buy("TQQQ", qty=1, limit=90.4, stop=85), "leveraged/inverse"),
        (buy("AAPL", qty=0.4, limit=200, stop=190), "live_allowed_symbols"),
        (buy(stop=None), "stop-loss"),
        (buy(stop=610.0), "stop-loss"),
        (buy(limit=640.0, qty=0.1), "from the"),  # limit 6.7% above the close
        (buy("VNQ", qty=1, limit=90, stop=85), "no verified"),  # no bar for VNQ
    ],
)
def test_bad_buys_rejected(settings, ticket, fragment):
    res = check(settings, [ticket])
    assert not res.approved and fragment in res.rejected[0][1]


def test_daily_entry_purchase_exposure_and_reserve_limits(settings):
    tickets = [buy("SPY", 0.16, 603, 580), buy("EFA", 1.2, 80.4, 76), buy("IEF", 1.0, 95.4, 92)]
    res = check(settings, tickets)
    assert [t.symbol for t in res.approved] == ["SPY", "EFA"]  # $96.48 + $96.48; IEF would pass $200/day
    assert "remaining room" in res.rejected[0][1]
    # $750 already invested: exposure cap $800 leaves $50
    held = snap(total=1000, cash=250, positions=[{"symbol": "GLD", "quantity": 3.0, "average_buy_price": 250}])
    res = check(settings, [buy("SPY", 0.1, 603, 580)], s=held)
    assert not res.approved and "remaining room" in res.rejected[0][1]
    # cash reserve: $260 settled cash keeps $200 back, so a $54.27 buy fits but $96.48 does not
    low_cash = snap(total=960, cash=260, positions=[{"symbol": "GLD", "quantity": 2.8, "average_buy_price": 250}])
    assert check(settings, [buy("SPY", 0.09, 603, 580)], s=low_cash).approved
    assert not check(settings, [buy("SPY", 0.16, 603, 580)], s=low_cash).approved


def test_one_position_per_ticker_and_no_duplicates(settings):
    held = snap(total=1000, cash=850, positions=[{"symbol": "SPY", "quantity": 0.25, "average_buy_price": 600}])
    assert "already held" in check(settings, [buy()], s=held).rejected[0][1]
    res = check(settings, [buy(qty=0.1), buy(qty=0.1)])
    assert len(res.approved) == 1 and "duplicate" in res.rejected[0][1]


def test_unsettled_cash_and_open_buy_block_buys_but_not_sells(settings):
    held = [{"symbol": "GLD", "quantity": 0.2, "average_buy_price": 250}]
    sell = Ticket("GLD", "sell", 0.2, 248.75, None, "C-gtaa", "below average")
    s = snap(total=1000, cash=950, positions=held, unsettled=None)
    res = check(settings, [sell, buy()], s=s)
    assert res.approved == [sell] and "settled cash unknown" in res.rejected[0][1]
    s = snap(total=1000, cash=950, positions=held, orders=[{"symbol": "EFA", "side": "buy", "state": "queued"}])
    res = check(settings, [sell, buy()], s=s)
    assert res.approved == [sell] and "open buy order" in res.rejected[0][1]
    # unsettled sale proceeds are not spendable
    s = snap(total=1000, cash=1000, unsettled=850)
    assert "remaining room" in check(settings, [buy()], s=s).rejected[0][1]


def test_sells_only_what_is_held(settings):
    held = snap(total=1000, cash=950, positions=[{"symbol": "GLD", "quantity": 0.2, "average_buy_price": 250}])
    res = check(
        settings,
        [Ticket("GLD", "sell", 0.3, 248, None, "C-gtaa", "x"), Ticket("TLT", "sell", 1, 88, None, "C-gtaa", "x")],
        s=held,
    )
    assert not res.approved and "exceeds" in res.rejected[0][1] and "not held" in res.rejected[1][1]


@pytest.mark.parametrize(
    "as_of, now, fetched, fragment",
    [
        (AS_OF, NOW, None, "no account snapshot"),
        (AS_OF, NOW + timedelta(hours=7), NOW, "h old"),
        (date(2026, 10, 9), NOW, NOW - timedelta(minutes=20), "not the ticket day"),
        (
            date(2026, 11, 26),
            datetime(2026, 11, 26, 21, tzinfo=UTC),
            datetime(2026, 11, 26, 20, tzinfo=UTC),
            "not an NYSE trading day",
        ),
    ],
)
def test_global_blockers_reject_everything(settings, as_of, now, fetched, fragment):
    s = None if fetched is None else snap(fetched=fetched)
    res = order_gate.check_tickets(settings, [buy()], s, as_of, bars(SPY=600.0), OK, now)
    assert not res.approved and any(fragment in b for b in res.blockers)


def test_unreconciled_account_blocks(settings):
    s = snap(total=1000, cash=900, positions=[{"symbol": "GLD", "quantity": 1.0, "average_buy_price": 250}])
    res = check(settings, [buy()], s=s)  # 900 + 250 = 1150 vs 1000
    assert any("does not reconcile" in b for b in res.blockers)
    s = snap(total=1000, cash=900, positions=[{"symbol": "XYZ", "quantity": 1.0, "average_buy_price": 100}])
    assert any("cannot reconcile" in b for b in check(settings, [buy()], s=s).blockers)


def test_loss_limits_block_buys_and_drawdown_engages_kill_switch(settings):
    day_loss = TradingStatus(True, "ok", -10.5, 10.5, 1000.0)
    assert "daily loss" in check(settings, [buy()], status=day_loss).rejected[0][1]
    dd = TradingStatus(True, "ok", -1.0, 50.0, 1000.0)
    res = check(settings, [buy()], status=dd)
    assert not res.approved and res.engage_kill_switch and "review limit" in res.engage_kill_switch
    assert "status unknown" in check(settings, [buy()], status=None).rejected[0][1]


def test_kill_switch_persists_and_needs_explicit_release(settings):
    assert not killswitch.status(settings).engaged
    killswitch.engage(settings, "manual test")
    killswitch.engage(settings, "second reason")  # idempotent: keeps the first reason
    st = killswitch.status(settings)  # a fresh read = a restart
    assert st.engaged and st.reason == "manual test"
    res = check(settings, [buy()])
    assert not res.approved and any("KILL SWITCH" in b for b in res.blockers)
    with pytest.raises(ValueError):
        killswitch.release(settings, "yes")
    assert killswitch.status(settings).engaged
    assert not killswitch.release(settings, killswitch.RELEASE_PHRASE).engaged
    assert check(settings, [buy()]).approved
    log = settings.resolve(settings.account_limits.kill_switch_file).with_name("kill_switch_log.jsonl")
    assert log.read_text(encoding="utf-8").count("\n") == 2


def test_unreadable_kill_switch_file_counts_as_engaged(settings):
    path = settings.resolve(settings.account_limits.kill_switch_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert killswitch.status(settings).engaged


def test_live_disabled_blocks(settings):
    s = replace(settings, live=replace(settings.live, enabled=False))
    assert any("disabled" in b for b in check(s, [buy()]).blockers)


def test_hard_limits_cannot_be_loosened(settings):
    assert HARD_LIMITS["max_order_notional"] == 100 and HARD_LIMITS["max_total_exposure"] == 800
    assert HARD_LIMITS["min_cash_reserve"] == 200 and HARD_LIMITS["max_daily_purchases"] == 200
    assert HARD_LIMITS["max_daily_entries"] == 3 and HARD_LIMITS["drawdown_review_pct"] == 0.05
    al = settings.account_limits
    for bad in (
        replace(al, max_order_notional=150),
        replace(al, max_total_exposure=900),
        replace(al, min_cash_reserve=100),
        replace(al, max_daily_entries=5),
        replace(al, drawdown_review_pct=0.08),
        replace(al, live_allowed_symbols=["SPY", "TQQQ"]),
    ):
        with pytest.raises(ConfigError):
            validate(replace(settings, account_limits=bad))
    validate(replace(settings, account_limits=replace(al, max_order_notional=50)))  # tightening is fine


def test_leveraged_list_covers_desk_instruments():
    assert {"TQQQ", "SQQQ"} <= LEVERAGED_INVERSE_ETFS and "IBIT" not in LEVERAGED_INVERSE_ETFS
