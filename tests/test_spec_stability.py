"""Mechanical edits must preserve every pre-registered methodology input."""

from agent_trading.dashboard import spec


def test_registered_spec_hash_is_unchanged():
    assert spec.SPEC_VERSION == "2026-10-17.4"
    assert spec.SPEC_FREEZE_DATE == "2026-10-16"
    assert spec.spec_hash() == "e6620b35c01e39f3"


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


def test_addition_preserves_every_prior_registered_rule():
    import hashlib
    import json

    previous = spec.spec_dict()
    assert previous.pop("price_bars")["rule"] == spec.PRICE_BAR_RULE
    previous["display_rules"]["watchlist_price"][0] = spec.WATCHLIST_PRICE_RULE_2026_10_14_5
    previous["version"] = "2026-10-17.3"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "83cd7ee1753cd7b1"
    assert previous.pop("private_history") == spec.PRIVATE_HISTORY_RULE
    previous["version"] = "2026-10-17.2"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "48a72cddda547a92"
    assert previous["leaders_2030"].pop("scenario") == spec.LEADERS_SCENARIO_RULES
    previous["leaders_2030"]["rule"] = spec.LEADERS_RULE_2026_10_17_1
    previous["leaders_2030"]["collection"] = spec.LEADERS_COLLECTION_RULE_2026_10_17_1
    previous["version"] = "2026-10-17.1"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "7878076b25e6eecd"
    assert previous["leaders_2030"]["top_n"] == 20
    assert previous["leaders_2030"].pop("collection") == spec.LEADERS_COLLECTION_RULE_2026_10_17_1
    previous["leaders_2030"]["top_n"] = 50
    previous["leaders_2030"]["rule"] = spec.LEADERS_RULE_2026_10_16
    previous["version"] = "2026-10-16.2"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "ed13539391c855db"
    previous.pop("external_datasets")
    previous["version"] = "2026-10-16.1"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "74b9e488a738c3ed"
    previous.pop("leaders_2030")
    previous["version"] = "2026-10-15.1"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "60c10ab9b32cdcc3"
