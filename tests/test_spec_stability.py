"""Mechanical edits must preserve every pre-registered methodology input."""

from agent_trading.dashboard import spec


def test_registered_spec_hash_is_unchanged():
    assert spec.SPEC_VERSION == "2026-10-19.5"
    assert spec.SPEC_FREEZE_DATE == "2026-10-16"
    assert spec.spec_hash() == "b3cb68c04141ade3"


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
    # 2026-10-19.5 adds the outside-index list and XBRL gap fills: removing both restores 2026-10-19.4
    assert previous.pop("xbrl_fill") == spec.XBRL_FILL_RULES
    assert previous["leaders_2030"].pop("outside_index") == spec.LEADERS_OUTSIDE_RULES
    previous["version"] = "2026-10-19.4"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "80ccdd1aad1d4c1e"
    # 2026-10-19.4 is a data-validation fix: undoing its windows, share checks and rule texts restores 2026-10-19.3
    assert previous.pop("quarter_windows") == spec.QUARTER_WINDOWS
    assert spec.QUARTER_WINDOWS["quarter_span_days"] == (80, 120)
    leaders_rules = previous["leaders_2030"]
    assert leaders_rules.pop("share_checks") == spec.LEADERS_SHARE_CHECKS
    for key, old in (
        ("rule", spec.LEADERS_RULE_2026_10_17_2),
        ("collection", spec.LEADERS_COLLECTION_RULE_2026_10_17_2),
    ):
        assert leaders_rules[key] != old
        leaders_rules[key] = old
    assert previous["market_cap_definition"] != spec.MARKET_CAP_DEFINITION_2026_10_13_1
    previous["market_cap_definition"] = spec.MARKET_CAP_DEFINITION_2026_10_13_1
    previous["version"] = "2026-10-19.3"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "f7fdc50c0cf51c28"
    assert previous.pop("live_gaps") == spec.LIVE_GAP_RULES
    previous["version"] = "2026-10-19.2"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "61c2dca113e02014"
    assert previous.pop("resilience_validation") == spec.RESILIENCE_VALIDATION_RULES
    previous["version"] = "2026-10-19.1"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "0e6cb19e305dffdb"
    assert previous.pop("resilience") == spec.RESILIENCE_RULES
    previous["version"] = "2026-10-18.1"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "02ed25651e9d6ed7"
    # 2026-10-18.1 adds the daily cadence and a 2-session stale warning: undoing both restores 2026-10-17.6
    cadence = previous.pop("snapshot_cadence")
    assert cadence == {"rule": spec.SNAPSHOT_CADENCE_RULE, "published_recent": 10}
    assert previous["display_rules"]["freshness"][1] == spec.FRESHNESS_STALE_SESSIONS == 2
    previous["display_rules"]["freshness"][1] = spec.FRESHNESS_STALE_SESSIONS_2026_10_14_5
    previous["version"] = "2026-10-17.6"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "e9da93a7beccbb19"
    # 2026-10-17.6 changes only the Cboe price-bar rule: restoring its 2026-10-17.4 form restores 2026-10-17.5
    bars = previous["price_bars"]
    assert bars.pop("listing_gap_days") == spec.PRICE_LISTING_GAP_DAYS == 30
    assert (bars["rule"], bars["range_check_bars"]) == (spec.PRICE_BAR_RULE, 63)
    bars["rule"], bars["range_check_bars"] = spec.PRICE_BAR_RULE_2026_10_17_4, spec.PRICE_RANGE_CHECK_BARS_2026_10_17_4
    previous["version"] = "2026-10-17.5"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "4ddb57a61a8ef6b3"
    # 2026-10-17.5 only adds the Buy/Sell desk: removing it restores 2026-10-17.4 exactly
    assert previous.pop("decision_desk")["rules"] == spec.DESK_RULES
    previous["version"] = "2026-10-17.4"
    digest = hashlib.sha256(json.dumps(previous, sort_keys=True, default=str).encode()).hexdigest()[:16]
    assert digest == "e6620b35c01e39f3"
    assert previous.pop("price_bars")["rule"] == spec.PRICE_BAR_RULE_2026_10_17_4
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
