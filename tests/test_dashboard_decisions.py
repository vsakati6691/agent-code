"""Decision research registration and calculations (external services are mocked)."""
from agent_trading.dashboard import spec


def test_decision_rules_are_registered_before_evaluation():
    assert spec.SPEC_VERSION == "2026-10-14.9"
    assert "registered before any data" in dict(spec.SPEC_CHANGELOG)[spec.SPEC_VERSION]
    assert spec.DECISION_RULES["growth_weights"] == {
        "growth": .25, "earnings": .1875, "quality": .1875, "balance": .1875, "valuation": .1875}
    assert spec.SPECULATIVE_RULES == {
        "top_per_list": 3, "per_ticker": 3, "min_dte": 30, "max_dte": 90,
        "min_delta": .25, "max_delta": .40, "open_interest_above": 500, "min_volume": 10,
        "max_spread_pct": .10, "iv_min_dte": 20, "iv_max_dte": 40, "iv_target_dte": 30,
        "iv_rank_sessions": 252, "iv_rank_days": 366, "options_cap_pct": 5, "trade_cap_pct": 1,
        "profit_exit": 1., "loss_exit": -.5, "exit_dte": 21}
