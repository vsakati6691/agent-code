"""Mechanical edits must preserve every pre-registered methodology input."""

from agent_trading.dashboard import spec


def test_registered_spec_hash_is_unchanged():
    assert spec.SPEC_VERSION == "2026-10-14.9"
    assert spec.spec_hash() == "13c2a70787a83822"
