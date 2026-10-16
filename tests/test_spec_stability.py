"""Mechanical edits must preserve every pre-registered methodology input."""

from agent_trading.dashboard import spec


def test_registered_spec_hash_is_unchanged():
    assert spec.SPEC_VERSION == "2026-10-15.1"
    assert spec.SPEC_FREEZE_DATE == "2026-10-15"
    assert spec.spec_hash() == "60c10ab9b32cdcc3"


def test_current_version_has_a_new_unique_changelog_entry():
    versions = [version for version, _ in spec.SPEC_CHANGELOG]
    assert len(versions) == len(set(versions))
    assert versions[-1] == spec.SPEC_VERSION
    assert all(reason.strip() for _, reason in spec.SPEC_CHANGELOG)
    assert versions[:2] == ["2026-10-13.1", "2026-10-13.2"]
    assert versions[2:11] == [f"2026-10-14.{n}" for n in range(1, 10)]


def test_full_registration_history_is_preserved_and_runtime_reasons_are_concise():
    import hashlib
    import json

    from tests.spec_history import full_changelog

    entries = full_changelog()
    assert [version for version, _ in entries] == [version for version, _ in spec.SPEC_CHANGELOG]
    historical = entries[:12]
    digest = hashlib.sha256(json.dumps(historical, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert digest == "13c070bb5aa26468f0a6c796547237478d1f8b1092130efc9b8fb31cceea2f7c"
    assert all("\n" not in reason and len(reason) <= 160 for _, reason in spec.SPEC_CHANGELOG)
