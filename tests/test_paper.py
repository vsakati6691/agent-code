"""Paper-execution tests: fills, stops, timing, idempotency, fail-safes."""

from dataclasses import replace
from datetime import UTC, date

import pandas as pd
import pytest

from agent_trading.account import SnapshotError, parse_snapshot, verify_snapshot
from agent_trading.indicators import atr
from agent_trading.journal import Journal
from agent_trading.paper import Intent, PaperBroker
from agent_trading.risk import RiskViolation

from .conftest import make_bars


def uptrend(n=200, end="2026-10-09", seed=1):
    return make_bars(n=n, end=end, seed=seed, drift=0.003, vol=0.004, volume=5e6, start=100)


@pytest.fixture
def broker(settings, tmp_path):
    return PaperBroker(settings, Journal(tmp_path / "paper.db"))


def window(bars, end):
    return {s: df.loc[:end] for s, df in bars.items()}


def buys(bars, settings):
    """A buy intent per symbol at the last close with a 2.5 x ATR stop, so broker
    mechanics are tested independently of the strategy rules."""
    out = []
    for sym, df in bars.items():
        close = float(df["close"].iloc[-1])
        stop = close - settings.risk.atr_stop_multiple * float(atr(df, 14).iloc[-1])
        out.append(Intent(sym, "buy", close, stop, "test", "test entry"))
    return out


def sells(bars):
    return [Intent(sym, "sell", float(df["close"].iloc[-1]), None, "test", "test exit") for sym, df in bars.items()]


def test_signal_then_fill_at_next_open(settings, broker):
    bars = {"UPA": uptrend(seed=1), "UPB": uptrend(seed=2)}
    d1 = pd.Timestamp("2026-10-08")
    b1 = window(bars, d1)
    broker.run(b1, d1.date(), buys(b1, settings))
    queued = broker.orders("pending")
    assert len(queued) >= 1 and set(queued["side"]) == {"buy"}
    assert broker.journal.open_trades().empty  # nothing filled on the signal day

    d2 = pd.Timestamp("2026-10-09")
    broker.run(bars, d2.date(), [])
    trades = broker.journal.open_trades()
    assert not trades.empty
    for t in trades.itertuples():
        expected = bars[t.symbol].loc[d2, "open"] * (1 + settings.costs.per_side)
        assert t.entry_price == pytest.approx(expected)
        assert t.entry_date == "2026-10-09"
        assert t.stop_price < t.entry_price


def test_rerun_same_day_is_idempotent(settings, broker):
    bars = {"UPA": uptrend()}
    d = date(2026, 10, 9)
    broker.run(bars, d, buys(bars, settings))
    n = len(broker.orders())
    r = broker.run(bars, d, buys(bars, settings))
    assert len(broker.orders()) == n
    assert any("already generated" in w for w in r.warnings)


def test_stop_hit_closes_trade_with_gap_fill(settings, broker):
    df = uptrend(n=150)
    j = broker.journal
    entry_day = df.index[-3]
    j.open_trade("UPA", 0.5, 100.0, 95.0, entry_day.date())
    broker._set_meta("last_processed_date", entry_day.date().isoformat())
    crash = df.copy()
    day = df.index[-2]
    crash.loc[day, ["open", "high", "low", "close"]] = [90.0, 91.0, 89.0, 90.5]  # gaps below the stop
    broker.run({"UPA": crash}, df.index[-1].date(), [])
    closed = j.closed_trades()
    assert len(closed) == 1
    row = closed.iloc[0]
    assert row["exit_reason"] == "stop"
    assert row["exit_price"] == pytest.approx(90.0 * (1 - settings.costs.per_side))  # gap => open, not stop


def test_buy_cancelled_when_open_gaps_below_stop(settings, broker):
    bars = {"UPA": uptrend()}
    d1 = bars["UPA"].index[-2]
    b1 = window(bars, d1)
    broker.run(b1, d1.date(), buys(b1, settings))
    order = broker.orders("pending").iloc[0]
    crashed = bars["UPA"].copy()
    last = crashed.index[-1]
    crashed.loc[last, ["open", "low"]] = order["stop_price"] * 0.9
    crashed.loc[last, "close"] = crashed.loc[last, "open"]
    crashed.loc[last, "high"] = max(crashed.loc[last, "high"], crashed.loc[last, "open"])
    broker.run({"UPA": crashed}, last.date(), [])
    assert broker.journal.open_trades().empty
    assert "below stop" in broker.orders("cancelled").iloc[0]["note"]


def test_exit_signal_sells_next_open(settings, broker):
    df = uptrend(n=200)
    j = broker.journal
    tid = j.open_trade("UPA", 0.5, 100.0, 50.0, df.index[-5].date())
    falling = df.copy()
    falling.iloc[-3:, :4] = falling.iloc[-3:, :4].values * 0.6  # close far below the 50-day SMA, above stop
    falling.iloc[-3:, falling.columns.get_loc("high")] = falling.iloc[-3:][["open", "close", "high"]].max(axis=1)
    d1 = falling.index[-2]
    broker._set_meta("last_processed_date", falling.index[-3].date().isoformat())
    b1 = {"UPA": falling.loc[:d1]}
    broker.run(b1, d1.date(), sells(b1))
    assert (broker.orders("pending")["side"] == "sell").any()
    broker.run({"UPA": falling}, falling.index[-1].date(), [])
    closed = j.closed_trades()
    assert len(closed) == 1 and closed.iloc[0]["id"] == tid
    assert closed.iloc[0]["exit_price"] == pytest.approx(falling["open"].iloc[-1] * (1 - settings.costs.per_side))


def test_entries_respect_risk_limits(settings, broker):
    bars = {f"S{i}": uptrend(seed=i) for i in range(8)}
    d1 = bars["S0"].index[-2]
    b1 = window(bars, d1)
    broker.run(b1, d1.date(), buys(b1, settings))
    pending = broker.orders("pending")
    buffer = settings.risk.stop_risk_buffer
    risk = (pending["quantity"] * (pending["ref_price"] - pending["stop_price"]) * (1 + buffer)).sum()
    assert risk <= settings.paper_starting_equity * settings.risk.max_open_risk_pct + 1e-6
    assert (pending["quantity"] * pending["ref_price"]).max() <= 250 + 1e-6


def test_sell_intent_without_position_is_ignored(settings, broker):
    bars = {"UPA": uptrend()}
    r = broker.run(bars, date(2026, 10, 9), sells(bars))
    assert broker.orders("pending").empty
    assert any("short selling is not allowed" in w for w in r.warnings)


def test_missing_data_for_held_position_warns(settings, broker):
    broker.journal.open_trade("GONE", 1, 10, 9, date(2026, 10, 1))
    bars = {"UPA": uptrend()}
    r = broker.run(bars, date(2026, 10, 9), buys(bars, settings))
    assert any("GONE" in w for w in r.warnings)


def test_paper_broker_refuses_live_mode(settings, tmp_path):
    with pytest.raises(RiskViolation):
        PaperBroker(replace(settings, mode="live"), Journal(tmp_path / "x.db"))


# ---------------------------------------------------------------- account snapshot

RAW = {
    "fetched_at": "2026-10-12T04:00:00+00:00",
    "account_number": "000000001234",
    "nickname": "Agent-trading",
    "portfolio": {"total_value": "1000", "cash": "1000", "buying_power": {"buying_power": "1000.0000"}},
    "positions": [],
    "orders": [
        {"symbol": "SPY", "side": "buy", "state": "filled", "quantity": "1"},
        {"symbol": "QQQ", "side": "buy", "state": "queued", "quantity": "1"},
    ],
}


def test_snapshot_masks_account_and_keeps_open_orders_only():
    snap = parse_snapshot(RAW)
    assert snap.account_last4 == "1234"
    assert "000000001234" not in repr(snap)
    assert [o["symbol"] for o in snap.open_orders] == ["QQQ"]


def test_snapshot_verification(settings):
    from datetime import datetime

    snap = parse_snapshot(RAW)
    assert verify_snapshot(snap, settings, datetime(2026, 10, 12, 10, tzinfo=UTC)) == []
    stale = verify_snapshot(snap, settings, datetime(2026, 10, 14, tzinfo=UTC))
    assert any("hours old" in p for p in stale)
    wrong = parse_snapshot({**RAW, "account_number": "1111"})
    assert any(
        "not the configured" in p for p in verify_snapshot(wrong, settings, datetime(2026, 10, 12, 5, tzinfo=UTC))
    )


@pytest.mark.parametrize(
    "bad",
    [
        {k: v for k, v in RAW.items() if k != "fetched_at"},
        {**RAW, "fetched_at": "2026-10-12T04:00:00"},  # no timezone
        {**RAW, "portfolio": {"cash": "1000"}},  # missing total value
        {**RAW, "portfolio": {**RAW["portfolio"], "cash": "-5"}},
    ],
)
def test_malformed_snapshot_rejected(bad):
    with pytest.raises(SnapshotError):
        parse_snapshot(bad)
