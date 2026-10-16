"""Mechanical edits must preserve every pre-registered methodology input."""

from agent_trading.dashboard import spec


def test_registered_spec_hash_is_unchanged():
    assert spec.SPEC_VERSION == "2026-10-15.1"
    assert spec.spec_hash() == "60c10ab9b32cdcc3"


def test_current_version_has_a_new_unique_changelog_entry():
    versions = [version for version, _ in spec.SPEC_CHANGELOG]
    assert len(versions) == len(set(versions))
    assert versions[-1] == spec.SPEC_VERSION
    assert all(reason.strip() for _, reason in spec.SPEC_CHANGELOG)
    assert versions[:2] == ["2026-10-13.1", "2026-10-13.2"]
    assert versions[2:11] == [f"2026-10-14.{n}" for n in range(1, 10)]
