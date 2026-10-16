"""Regressions from the immutable October 2026 dashboard snapshots. No network."""

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from agent_trading.dashboard.site_briefing import panels

FIXTURES = Path(__file__).parent / "fixtures" / "dashboard_factcheck"


def test_overview_names_methodology_change_on_real_nvda_rank_move():
    previous, current = json.loads((FIXTURES / "rank-changes.json").read_text(encoding="utf-8"))["snapshots"]
    before = json.dumps(current, sort_keys=True)
    page = panels(current, None, [previous["as_of"], current["as_of"]], previous)
    assert "NVDA up 7 to #3" in page
    assert "methodology version changed (2026-10-14.8 → 2026-10-14.9)" in page
    assert "score +9.2; component scores unchanged" in page
    assert json.dumps(current, sort_keys=True) == before

    previous["spec_version"], previous["spec_hash"] = current["spec_version"], current["spec_hash"]
    assert "methodology version changed" not in panels(current, None, [], previous)


def preclose_fixture():
    return json.loads((FIXTURES / "preclose.json").read_text(encoding="utf-8"))


def test_real_stx_and_pays_events_are_counted_once_across_lists():
    from agent_trading.dashboard.changes import summary

    previous, current = json.loads((FIXTURES / "changes.json").read_text(encoding="utf-8"))["snapshots"]
    before = json.dumps(current, sort_keys=True)
    result = summary(current, previous)
    for ticker, bands in (("STX", {"large", "ai_large"}), ("PAYS", {"small", "multibagger"})):
        rows = [r for r in result["rows"] if r["ticker"] == ticker and r["kind"] == "thesis"]
        assert len(rows) == 1
        assert set(rows[0]["bands"]) == bands
    assert result["counts"]["thesis"] == 2
    assert json.dumps(current, sort_keys=True) == before


def test_real_earnings_cadence_labels_name_the_gap_and_tolerance():
    from agent_trading.dashboard.site_briefing import _last_results
    from agent_trading.dashboard.site_company import _earnings_check

    events = json.loads((FIXTURES / "earnings.json").read_text(encoding="utf-8"))["events"]["items"]
    for ticker, gap in (("WDC", "14 calendar days earlier"), ("COCO", "13 calendar days later")):
        row = next(r for r in events if r["ticker"] == ticker)
        original = dict(row)
        for markup in (_last_results(row), _earnings_check({"earnings_check": {**row, "next_scheduled": row["date"]}})):
            assert gap in markup
            assert "21-calendar-day" in markup and "remains unverified" in markup
            assert "consistent with" not in markup
        assert row == original


def test_all_real_scheduled_earnings_remain_available_in_the_overview():
    from agent_trading.dashboard.site_scan import scan_header

    events = json.loads((FIXTURES / "earnings.json").read_text(encoding="utf-8"))["events"]
    snap = {**preclose_fixture()["snapshot"], "bands": {}, "universe": {}, "events": events}
    before = json.dumps(snap, sort_keys=True)
    page = scan_header(snap, None) + panels(snap, None)
    panel = re.search(r"<h3>Upcoming earnings \(45 days\)</h3>(.*?)</section>", page, re.S).group(1)
    assert "Scheduled earnings</span><strong>32</strong>" in page
    assert panel.count("<li>") == 32
    assert "<summary>27 more</summary>" in panel
    for item in events["items"]:
        assert f"<strong>{item['ticker']}</strong> {item['date']}" in panel
    assert json.dumps(snap, sort_keys=True) == before


def test_weekly_run_rejects_real_preclose_collection_before_any_network():
    from agent_trading.dashboard.pipeline import RunFailed, run

    snap = preclose_fixture()["snapshot"]
    providers = Mock()
    with pytest.raises(RunFailed, match="as-of close is not yet available"):
        run(providers, date.fromisoformat(snap["as_of"]), now=datetime.fromisoformat(snap["run_started"]))
    assert providers.mock_calls == []


def test_quote_fallback_rejects_real_intraday_nvda_timestamp():
    from agent_trading.dashboard.pipeline_collect import _quote
    from agent_trading.dashboard.pipeline_context import Context
    from agent_trading.dashboard.providers import Quote

    row = preclose_fixture()["option"]
    providers = Mock()
    providers.quote.return_value = Quote(
        row["underlying"],
        row["spot"],
        None,
        datetime.fromisoformat(row["underlying_last_trade"]),
        None,
        row["quote_time_utc"],
    )
    ctx = Context(date.fromisoformat(row["quote_date_ny"]), providers)
    result, reason = _quote(ctx, "NVDA")
    assert result is None and reason == "quote snapshot predates the as-of close"
    assert _quote(ctx, "NVDA") == (result, reason)
    providers.quote.assert_called_once()


def test_price_cache_changes_when_the_completed_session_advances(monkeypatch):
    from agent_trading.dashboard import providers

    class Clock:
        now_value = datetime(2026, 10, 15, 14, 37, 46, tzinfo=UTC)

        @classmethod
        def now(cls, _tz):
            return cls.now_value

    monkeypatch.setattr(providers, "datetime", Clock)
    http = Mock()
    p = providers.Providers(http)
    p._price_json("https://cdn-api.cboe.com/test")
    before = http.get_json.call_args.kwargs["cache_key_extra"]
    Clock.now_value = datetime(2026, 10, 15, 22, tzinfo=UTC)
    p._price_json("https://cdn-api.cboe.com/test")
    after = http.get_json.call_args.kwargs["cache_key_extra"]
    assert before.endswith("2026-10-14") and after.endswith("2026-10-15")


def test_real_preclose_snapshot_has_dated_notes_without_rewriting_values():
    from agent_trading.dashboard.price_integrity import correction, record_note
    from agent_trading.dashboard.site_layout import freshness_banner
    from agent_trading.dashboard.site_refresh import price

    fixture = preclose_fixture()
    snap, c = fixture["snapshot"], fixture["candidate"]
    before = json.dumps(fixture, sort_keys=True)
    text = freshness_banner(snap, None, datetime(2026, 10, 16, 18, 22, tzinfo=UTC))
    assert "Correction 2026-10-16" in text and "not verified closes" in text
    assert "Quotes are end-of-session" not in text
    assert record_note(c) == "Intraday input · correction 2026-10-16"
    assert record_note(fixture["option"]) == "Intraday input · correction 2026-10-16"
    assert not record_note(
        {**fixture["option"], "quote_time_utc": "2026-10-17T14:17:00+00:00", "quote_date_ny": "2026-10-17"}
    )
    value, label = price("NVDA", c["price"], {"data": fixture["daily"], "weekly_preclose": True})
    assert value == 217.23 and "vs stored intraday input" in label and "since weekly" not in label
    assert c["price"] == 216.97 and json.dumps(fixture, sort_keys=True) == before
    assert not correction({**snap, "run_finished": "2026-10-16T22:00:00+00:00"})
