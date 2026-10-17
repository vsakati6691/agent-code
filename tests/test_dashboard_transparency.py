from agent_trading.dashboard import spec
from agent_trading.dashboard.site_methodology import history_table, progress, version_counts
from agent_trading.dashboard.site_refresh import audit_context, banner


def test_counts_are_per_version_and_distinct_week():
    records = [
        {"as_of": "2026-10-09", "spec_version": "old"},
        {"as_of": "2026-10-10", "spec_version": spec.SPEC_VERSION},
        {"as_of": "2026-10-11", "spec_version": spec.SPEC_VERSION},
        {"as_of": "2026-10-17", "spec_version": spec.SPEC_VERSION},
    ]
    counts = {r["version"]: r for r in version_counts(records)}
    assert counts["old"]["weeks"] == 1
    assert counts[spec.SPEC_VERSION]["snapshots"] == 3
    assert counts[spec.SPEC_VERSION]["weeks"] == 2
    assert counts[spec.SPEC_VERSION]["estimate"] == "2027-10-02"
    assert "2 of 52 snapshots under the current version" in progress(records)
    assert "Freeze date: 2026-10-16." in progress(records)
    assert "2027-10-02" in history_table(records)
    assert "0 of 52" in progress([])
    assert "Unavailable until first snapshot" in history_table([])


def test_conflicting_hashes_are_not_presented_as_continuous():
    records = [
        {"as_of": d, "spec_version": "old", "spec_hash": h} for d, h in (("2026-10-09", "a"), ("2026-10-16", "b"))
    ]
    assert "Unavailable: different hashes under one version" in history_table(records)


def test_partial_banner_lists_missing_datasets_reasons_and_budget():
    daily = {
        "as_of": "2026-10-16",
        "collected_at": "2026-10-16T22:00:00Z",
        "status": "partial",
        "quotes": {
            "AAA": {"status": "unavailable", "reason": "request budget exhausted"},
            "BBB": {"status": "available"},
        },
        "chain_status": {"CCC": {"status": "unavailable", "reason": "stale <quote>"}},
        "options": {"enabled": True, "events_known": False, "earnings_reason": "calendar failed"},
        "usage": {"requests": {"cboe": 2}, "budgets": {"cboe": 2}, "cache_hits": 1},
    }
    text = banner({"as_of": "2026-10-09"}, {"data": daily})
    assert 'href="audit.html#daily-context"' in text and "partial" in text
    text = audit_context({"as_of": "2026-10-09"}, {"data": daily})
    assert "Quote AAA: request budget exhausted" in text
    assert "Options chain CCC: stale &lt;quote&gt;" in text
    assert "Earnings calendar: calendar failed" in text
    assert "cboe: 2 requests / 2 budget" in text
    assert "Total cache hits: 1" in text
    assert "Quote BBB" not in text
    daily["options"]["enabled"] = False
    assert "Earnings calendar" not in audit_context({"as_of": "2026-10-09"}, {"data": daily})
    daily["status"] = "ok"
    assert "Not refreshed" not in audit_context({"as_of": "2026-10-09"}, {"data": daily})
