"""Adversarial inputs from the October 17 audit; all accounts and prices are synthetic."""

import json
from dataclasses import asdict, replace

import pytest

from agent_trading.account import SnapshotError, load_saved_snapshot, parse_snapshot, save_snapshot
from agent_trading.config import ConfigError, validate
from agent_trading.data.validation import DataQualityError, validate_bars
from agent_trading.live import Ticket
from agent_trading.risk import ProposedOrder, RiskViolation, check_order
from tests.conftest import make_bars
from tests.test_order_gate import AS_OF, NOW, buy, check, snap


def raw_snapshot():
    return {
        "fetched_at": NOW.isoformat(),
        "account_number": "1234",
        "portfolio": {"total_value": 1000, "cash": 1000, "buying_power": 1000},
        "positions": [],
        "orders": [],
        "unsettled_funds": 0,
    }


@pytest.mark.parametrize("name", ["positions", "orders"])
@pytest.mark.parametrize("bad", [None, {}, "", "missing", [None]])
def test_missing_or_malformed_collections_rejected(name, bad):
    raw = raw_snapshot()
    if bad == "missing":
        del raw[name]
    else:
        raw[name] = bad
    with pytest.raises(SnapshotError):
        parse_snapshot(raw)


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "unknown"},
        {"side": "unknown"},
        {"quantity": float("nan")},
        {"quantity": True},
        {"quantity": 0},
        {"symbol": ""},
    ],
)
def test_order_records_validated_before_filtering(changes):
    raw = raw_snapshot()
    raw["orders"] = [{"symbol": "SPY", "side": "buy", "state": "filled", "quantity": 1, **changes}]
    with pytest.raises(SnapshotError):
        parse_snapshot(raw)


def test_snapshot_round_trip_and_legacy_reimport(settings):
    original = parse_snapshot(raw_snapshot())
    path = save_snapshot(settings, original)
    assert load_saved_snapshot(settings) == original
    saved = asdict(original)
    del saved["collections_complete"]
    path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(SnapshotError, match="reimport"):
        load_saved_snapshot(settings)
    saved["collections_complete"] = True
    saved["cash"] = float("nan")
    path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(SnapshotError):
        load_saved_snapshot(settings)


def test_gate_rejects_unverified_completeness_and_bad_in_memory_snapshot(settings):
    for invalid in (replace(snap(), collections_complete=False), replace(snap(), cash=float("nan"))):
        result = check(settings, [buy()], s=invalid)
        assert not result.approved and result.blockers


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "200"])
@pytest.mark.parametrize(
    "section,field",
    [
        ("account_limits", "min_cash_reserve"),
        ("account_limits", "max_daily_entries"),
        ("live", "capital"),
        ("costs", "commission_per_order"),
        ("risk", "min_order_notional"),
        ("broker", "snapshot_max_age_hours"),
        ("data", "daily_request_budget"),
    ],
)
def test_config_rejects_malformed_numbers(settings, value, section, field):
    malformed = replace(settings, **{section: replace(getattr(settings, section), **{field: value})})
    with pytest.raises(ConfigError):
        validate(malformed)


def test_nan_reserve_cannot_approve_a_ticket_even_without_config_loader(settings):
    invalid = replace(settings, account_limits=replace(settings.account_limits, min_cash_reserve=float("nan")))
    assert not check(invalid, [buy()]).approved


@pytest.mark.parametrize("value", [-1, 0, float("nan"), float("inf"), True, "1"])
@pytest.mark.parametrize("side", ["buy", "sell"])
def test_gate_rejects_bad_quantity_on_both_sides(settings, value, side):
    held = snap(cash=750, positions=[{"symbol": "GLD", "quantity": 1, "average_buy_price": 250}])
    result = check(settings, [Ticket("GLD", side, value, 250, 240, "C-gtaa", "test")], s=held)
    assert not result.approved and "quantity" in result.rejected[0][1]


@pytest.mark.parametrize("field", ["quantity", "price", "held_quantity", "cash"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_public_order_check_rejects_nonfinite(settings, field, value):
    order = ProposedOrder("SPY", "buy", 1, 1)
    cash = value if field == "cash" else 1000
    if field != "cash":
        order = replace(order, **{field: value})
    with pytest.raises(RiskViolation):
        check_order(order, settings, cash)


@pytest.mark.parametrize("column", ["open", "high", "low", "close", "volume"])
@pytest.mark.parametrize("value", [float("inf"), -float("inf")])
def test_nonfinite_bars_rejected(column, value):
    frame = make_bars(n=80, end=AS_OF.isoformat()).astype(float)
    frame.loc[frame.index[-1], column] = value
    with pytest.raises(DataQualityError, match="finite"):
        validate_bars(frame, "SYN", AS_OF, 0, 60)
