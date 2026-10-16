from dataclasses import replace

import pytest

from agent_trading.config import RiskConfig
from agent_trading.risk import (
    ProposedOrder,
    RiskViolation,
    check_new_trade_risk,
    check_order,
    size_position,
)

CFG = RiskConfig()


def test_risk_per_trade_is_half_percent():
    d = size_position(equity=1000, cash=1000, entry_price=100, stop_price=95, open_risk=0, cfg=CFG)
    assert d.limited_by == "risk per trade"
    assert d.quantity == 1.0  # $5 risk / $5 per share
    assert d.risk_amount == pytest.approx(5.0)


def test_aggregate_open_risk_cap():
    d = size_position(1000, 1000, 100, 95, open_risk=12.5, cfg=CFG)  # only $2.50 of the $15 left
    assert d.limited_by == "aggregate open-risk limit"
    assert d.risk_amount == pytest.approx(2.5)
    full = size_position(1000, 1000, 100, 95, open_risk=15.0, cfg=CFG)
    assert full.quantity == 0


def test_position_and_cash_caps():
    tight = size_position(1000, 1000, 100, 99.9, 0, CFG)  # tiny stop distance would mean 50 shares
    assert tight.limited_by == "max position size"
    assert tight.notional <= 250 + 1e-9
    broke = size_position(1000, 40, 100, 95, 0, CFG)
    assert broke.limited_by == "available cash"
    assert broke.notional <= 40


def test_whole_shares_mode_rounds_down():
    d = size_position(1000, 1000, 400, 380, 0, replace(CFG, fractional_shares=False))
    assert d.quantity == 0  # $5 / $20 = 0.25 share
    f = size_position(1000, 1000, 400, 380, 0, CFG)
    assert f.quantity == 0.25


def test_dust_positions_skipped():
    # Only $0.003 of open-risk budget left: ~$0.06 position, below the $1 minimum.
    d = size_position(1000, 1000, 65, 61.83, open_risk=14.997, cfg=CFG)
    assert d.quantity == 0 and "minimum order" in d.limited_by
    ok = size_position(1000, 1000, 65, 61.83, open_risk=0, cfg=CFG)
    assert ok.notional >= CFG.min_order_notional


def test_stop_above_entry_rejected():
    with pytest.raises(RiskViolation):
        size_position(1000, 1000, 100, 101, 0, CFG)


def test_short_sale_blocked(settings):
    with pytest.raises(RiskViolation, match="short"):
        check_order(ProposedOrder("NVDA", "sell", 2, 100, held_quantity=1), settings, cash=1000)


def test_margin_blocked(settings):
    with pytest.raises(RiskViolation, match="margin"):
        check_order(ProposedOrder("NVDA", "buy", 20, 100), settings, cash=1000)


@pytest.mark.parametrize("asset", ["option", "crypto", "future"])
def test_non_equity_blocked(settings, asset):
    with pytest.raises(RiskViolation):
        check_order(ProposedOrder("X", "buy", 1, 10, asset_type=asset), settings, cash=1000)


def test_live_mode_blocked(settings):
    with pytest.raises(RiskViolation):
        check_order(ProposedOrder("SPY", "buy", 1, 10), replace(settings, mode="live"), cash=1000)


def test_manual_trade_risk_limits():
    assert check_new_trade_risk(1000, 0, 1, 100, 95, CFG) == pytest.approx(5)
    with pytest.raises(RiskViolation, match="exceeds"):
        check_new_trade_risk(1000, 0, 2, 100, 95, CFG)
    with pytest.raises(RiskViolation, match="open risk"):
        check_new_trade_risk(1000, 12, 1, 100, 95, CFG)
