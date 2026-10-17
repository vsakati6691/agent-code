"""Robinhood earnings-calendar verdicts (owner check, display only): parsing, freshness, labels, build and CLI.

All data is synthetic; nothing touches the network or a broker."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pytest

from agent_trading.dashboard import earnings_verdicts as ev
from agent_trading.dashboard import evidence
from agent_trading.dashboard.__main__ import main as cli
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.store import Store
from tests.dashboard_fixtures import demo_site

TODAY = date(2026, 10, 16)
ROW = {
    "symbol": "FIX",
    "year": 2026,
    "quarter": 3,
    "eps": {"estimate": "12.730000", "actual": None},
    "report": {"date": "2026-10-30", "timing": "pm", "verified": True},
}
ITEMS = [
    {"ticker": "FIX", "date": "2026-10-22", "list": "large"},
    {"ticker": "CORZ", "date": "2026-10-23", "list": "ai_mid"},
    {"ticker": "NVDA", "date": "2026-11-18", "list": "large"},
]


def row(symbol: str, day: str, confirmed: bool = True) -> dict:
    return dict(ROW, symbol=symbol, report={"date": day, "timing": "pm", "verified": confirmed})


def payload(*rows: dict) -> dict:
    return {"data": {"results": list(rows)}, "guide": "Each entry is one company's report event within the window."}


# --- parsing and storage --------------------------------------------------------------------------------------


def test_parse_keeps_symbols_dates_and_the_broker_flag_only():
    symbols, window = ev.parse_calendar(payload(ROW, row("coco", "2026-10-22", confirmed=False)), "2026-10-16")
    assert symbols["FIX"] == {
        "reports": [{"date": "2026-10-30", "timing": "pm", "confirmed": True}],
        "checked_at": "2026-10-16",
    }
    assert symbols["COCO"]["reports"][0]["confirmed"] is False
    assert window == {
        "start": "2026-10-22",
        "end": "2026-10-30",
        "filter": "high_market_cap",
        "rows": 2,
        "checked_at": "2026-10-16",
    }
    text = json.dumps(symbols)
    assert "eps" not in text and "12.73" not in text


def test_parse_rejects_account_fields_other_payloads_and_empty_responses_without_a_window():
    with pytest.raises(ev.EarningsVerdictError, match="account"):
        ev.parse_calendar({"account_number": "123456789", "data": {"results": [ROW]}}, "2026-10-16")
    with pytest.raises(ev.EarningsVerdictError, match="get_earnings_calendar"):
        ev.parse_calendar({"data": {"results": [{"symbol": "AAA", "tradeable": True}]}}, "2026-10-16")
    with pytest.raises(ev.EarningsVerdictError, match="results"):
        ev.parse_calendar({"data": {"items": []}}, "2026-10-16")
    with pytest.raises(ev.EarningsVerdictError, match="empty"):
        ev.parse_calendar(payload(), "2026-10-16")
    _, window = ev.parse_calendar(payload(), "2026-10-16", start="2026-11-16", days=15, calendar_filter="all")
    assert (window["start"], window["end"], window["rows"], window["filter"]) == ("2026-11-16", "2026-11-30", 0, "all")


def test_merge_keeps_newer_checks_adds_same_day_windows_and_round_trips(tmp_path):
    v = ev.EarningsVerdicts()
    assert v.stored is False and v.newest_check() is None
    assert v.merge(*ev.parse_calendar(payload(ROW), "2026-10-10", start="2026-10-10", days=31)) == 1
    assert v.merge(*ev.parse_calendar(payload(row("FIX", "2026-10-29")), "2026-10-09")) == 0  # older: ignored
    assert v.symbols["FIX"]["reports"][0]["date"] == "2026-10-30"
    same_day = payload(row("FIX", "2026-10-30"), row("NVDA", "2026-11-17"))
    assert v.merge(*ev.parse_calendar(same_day, "2026-10-10")) == 1  # NVDA is new, FIX unchanged
    assert v.merge(*ev.parse_calendar(payload(row("FIX", "2026-10-22")), "2026-10-16")) == 1  # newer check replaces
    assert v.symbols["FIX"]["reports"] == [{"date": "2026-10-22", "timing": "pm", "confirmed": True}]
    assert len(v.windows) == 4 and v.newest_check() == "2026-10-16"
    v.save(tmp_path)
    again = ev.EarningsVerdicts.load(tmp_path)
    assert again.symbols == v.symbols and again.windows == v.windows
    saved = json.loads((tmp_path / ev.FILE).read_text(encoding="utf-8"))
    assert saved["source"].startswith("Robinhood MCP get_earnings_calendar (read-only)")
    assert saved["max_age_days"] == ev.MAX_AGE_DAYS


# --- verdicts -------------------------------------------------------------------------------------------------


def test_check_covers_verified_differs_not_listed_stale_and_unknown():
    v = ev.EarningsVerdicts()
    first = payload(ROW, row("JOE", "2026-10-28", confirmed=False))
    v.merge(*ev.parse_calendar(first, "2026-10-16", start="2026-10-16", days=31))
    ok = v.check("FIX", "2026-10-30", TODAY)
    assert ok["status"] == "verified" and ok["confirmed"] is True
    assert ev.label(ok) == "verified (broker calendar, checked 2026-10-16)"
    assert "tentative" in ev.label(v.check("JOE", "2026-10-28", TODAY))
    diff = v.check("FIX", "2026-10-22", TODAY)
    assert diff["status"] == "differs" and diff["broker_dates"] == ["2026-10-30"]
    assert ev.label(diff) == "differs from the broker calendar, which lists 2026-10-30 (checked 2026-10-16)"
    missing = v.check("CORZ", "2026-10-23", TODAY)
    assert missing["status"] == "not_listed"
    assert "2026-10-16 to 2026-11-15" in ev.label(missing) and "high-market-cap" in ev.label(missing)
    assert v.check("CORZ", "2026-12-01", TODAY) == {
        "status": "unverified",
        "reason": "no broker calendar check covers this date",
    }
    later = TODAY + timedelta(days=ev.MAX_AGE_DAYS + 1)
    stale = v.check("FIX", "2026-10-30", later)
    assert stale["status"] == "unverified" and stale["stale"] is True and "15 days old" in ev.label(stale)
    assert v.check("CORZ", "2026-10-23", later)["status"] == "unverified"  # the window is stale too
    assert ev.label(None) == "not independently verified"


def test_fetch_windows_split_the_horizon_into_calls_of_at_most_31_days():
    calls = ev.fetch_windows(TODAY, TODAY + timedelta(days=44))
    assert [(c["start_date"], c["days"], c["filter"]) for c in calls] == [
        ("2026-10-16", 31, "high_market_cap"),
        ("2026-11-16", 14, "high_market_cap"),
    ]
    assert ev.fetch_windows(TODAY, TODAY) == [{"start_date": "2026-10-16", "days": 1, "filter": "high_market_cap"}]
    assert ev.fetch_windows(TODAY, TODAY - timedelta(days=1)) == []


# --- build-time overlay and the audit dataset state -----------------------------------------------------------


def _snap(items: list[dict]) -> dict:
    return {
        "as_of": "2026-10-15",
        "run_finished": "2026-10-15T16:52:09+00:00",
        "sources": {},
        "universe": {},
        "problems": [],
        "events": {"items": items, "status": "ok", "window_days": 45},
        "tradability": {
            "verdicts_stored": 1,
            "to_check": 0,
            "oldest_check": "2026-10-14",
            "newest_check": "2026-10-14",
            "max_age_days": 35,
        },
        "bands": {
            "large": {
                "candidates": [
                    {"ticker": "FIX", "next_earnings": "2026-10-22"},
                    {"ticker": "DELL", "next_earnings": "2026-11-24"},
                ],
                "excluded": [],
            }
        },
    }


def _record(snap: dict) -> dict:
    return next(r for r in evidence.datasets(snap) if r["dataset"] == "Broker earnings calendar")


def test_attach_summarises_the_event_items_and_drives_the_audit_dataset_state():
    snap = _snap(ITEMS)
    assert not any(r["dataset"] == "Broker earnings calendar" for r in evidence.datasets(snap))  # not built yet
    ev.attach(snap, ev.EarningsVerdicts(), TODAY)
    assert snap[ev.BUILD_KEY]["stored"] is False and _record(snap)["state"] == "missing"
    assert "No Robinhood calendar check is stored" in ev.summary_text(snap)
    assert ev.without_overlay(snap) == _snap(ITEMS)
    v = ev.EarningsVerdicts()
    v.merge(*ev.parse_calendar(payload(ROW), "2026-10-16", start="2026-10-16", days=31))
    bc = ev.attach(snap, v, TODAY)
    assert bc["summary"] == {"total": 3, "verified": 0, "differs": 1, "not_listed": 1, "unchecked": 1, "stale": 0}
    assert ev.verdict_for(snap, "DELL", "2026-11-24")["status"] == "unverified"  # candidates beyond the panel too
    assert ev.verdict_for(snap, "FIX", None) is None and ev.verdict_for(None, "FIX", "2026-10-22") is None
    r = _record(snap)
    assert r["state"] == "partial" and r["coverage"] == "1 of 3" and r["retrieved_at"] == "2026-10-16"
    assert "0 agree, 1 differ" in r["detail"] and "1 not listed" in r["detail"]
    assert "0 of 3 dates verified, 1 differ (both dates shown), 1 not listed" in ev.summary_text(snap)
    v.merge(*ev.parse_calendar(payload(row("CORZ", "2026-10-23"), row("NVDA", "2026-11-18")), "2026-10-16"))
    ev.attach(snap, v, TODAY)
    r = _record(snap)
    assert (
        r["state"] == "available" and "2 of 3 scheduled date(s) agree with the broker calendar; 1 differ" in r["detail"]
    )
    ev.attach(snap, v, TODAY + timedelta(days=ev.MAX_AGE_DAYS + 1))
    assert _record(snap)["state"] == "stale"
    empty = _snap([])
    ev.attach(empty, v, TODAY)
    assert _record(empty)["state"] == "available" and "no scheduled report dates" in _record(empty)["detail"]


def test_site_labels_dates_from_the_stored_check_and_leaves_stored_data_untouched(tmp_path):
    data, out = demo_site(tmp_path, two_weeks=False)  # Alpha Vantage dates in the fixture: S04 10-30, S08 11-18
    audit = (out / "audit.html").read_text(encoding="utf-8")
    assert "Broker earnings calendar" in audit and "no stored read-only Robinhood calendar check" in audit
    assert "No Robinhood calendar check is stored" in (out / "index.html").read_text(encoding="utf-8")

    def digest() -> dict:
        return {p.relative_to(data): hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob("*") if p.is_file()}

    v = ev.EarningsVerdicts()
    v.merge(*ev.parse_calendar(payload(row("S04", "2026-10-30"), row("S08", "2026-11-17")), "2026-10-16"))
    v.save(data)
    before = digest()
    out2 = tmp_path / "site2"
    build_site(data, out2, today=TODAY)
    assert digest() == before  # the build reads the verdicts; it never writes to the data directory
    index = (out2 / "index.html").read_text(encoding="utf-8")
    assert "verified (broker calendar, checked 2026-10-16)" in index
    assert "differs from the broker calendar, which lists 2026-11-17 (checked 2026-10-16)" in index
    assert "1 of 2 dates verified, 1 differ (both dates shown)" in index
    assert "schedule verified against the broker calendar" in index  # the 8-K cadence sentence follows the verdict
    assert "schedule remains unverified" in index  # ... and still says so for the date that differs
    stock = next((out2 / "stock").glob("*-S04.html")).read_text(encoding="utf-8")
    assert "next: scheduled, Alpha Vantage, verified (broker calendar, checked 2026-10-16)" in stock
    assert "schedule verified against the broker calendar" in stock and "schedule remains unverified" not in stock
    assert ">verified (broker calendar)<" in stock  # the research panel's event status pill
    stock8 = next((out2 / "stock").glob("*-S08.html")).read_text(encoding="utf-8")
    assert "differs from the broker calendar, which lists 2026-11-17" in stock8 and ">unverified<" in stock8
    audit = (out2 / "audit.html").read_text(encoding="utf-8")
    assert "1 of 2 scheduled date(s) agree with the broker calendar; 1 differ" in audit
    store = Store(data)
    latest = json.loads((out2 / "data" / "latest.json").read_text(encoding="utf-8"))
    assert ev.BUILD_KEY not in latest
    for d in store.dates():
        published = json.loads((out2 / "data" / f"{d}.json").read_text(encoding="utf-8"))
        assert published == json.loads(json.dumps(store.load(d), default=str))


# --- owner CLI --------------------------------------------------------------------------------------------------


def test_cli_import_rejects_bad_payloads_and_todo_prints_verdicts_and_the_calls_to_make(tmp_path, capsys):
    store = Store(tmp_path)
    snap = {"as_of": "2026-10-15", "status": "ok", "bands": {}, "events": {"items": ITEMS, "status": "ok"}}
    store.write_snapshot(snap, "fixture")
    good = tmp_path / "cal.json"
    good.write_text(json.dumps(payload(ROW)), encoding="utf-8")
    args = ["earnings-calendar", "import", "--data", str(tmp_path), "--checked-at", "2026-10-16"]
    assert cli(args + ["--start", "2026-10-16", "--days", "31", str(good)]) == 0
    saved = json.loads((tmp_path / ev.FILE).read_text(encoding="utf-8"))
    assert saved["symbols"]["FIX"]["reports"] == [{"date": "2026-10-30", "timing": "pm", "confirmed": True}]
    assert saved["windows"] == [
        {"start": "2026-10-16", "end": "2026-11-15", "filter": "high_market_cap", "rows": 1, "checked_at": "2026-10-16"}
    ]
    assert "eps" not in (tmp_path / ev.FILE).read_text(encoding="utf-8")
    assert store.audit_log()[-1]["event"] == "earnings_calendar_imported"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"account_number": "1", "data": {"results": [ROW]}}), encoding="utf-8")
    assert cli(args + [str(bad)]) == 1
    assert "account_number" not in (tmp_path / ev.FILE).read_text(encoding="utf-8")
    assert cli(args + ["--start", "2026-10-16", "--days", "31", str(good), str(good)]) == 1  # one window, one file
    assert cli(args) == 1  # nothing to import
    capsys.readouterr()
    assert cli(["earnings-calendar", "todo", "--data", str(tmp_path), "--today", "2026-10-16"]) == 0
    text = capsys.readouterr().out
    assert "3 scheduled date(s) as of 2026-10-16: 0 verified, 1 differ, 1 not listed, 1 unchecked" in text
    assert "FIX    2026-10-22  differs from the broker calendar, which lists 2026-10-30" in text
    assert "CORZ   2026-10-23  not listed in the broker calendar" in text
    assert 'get_earnings_calendar(start_date="2026-10-16", days=31, filter="high_market_cap")' in text
    assert 'get_earnings_calendar(start_date="2026-11-16", days=3, filter="high_market_cap")' in text
    assert "earnings-calendar import --data" in text


def test_cli_todo_reads_a_crlf_converted_snapshot_unverified_with_a_warning(tmp_path, capsys):
    store = Store(tmp_path)
    snap = {"as_of": "2026-10-15", "status": "ok", "bands": {}, "events": {"items": ITEMS[:1], "status": "ok"}}
    store.write_snapshot(snap, "fixture")
    p = tmp_path / "snapshots" / "2026-10-15" / "snapshot.json"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))  # what a core.autocrlf checkout does on Windows
    assert cli(["earnings-calendar", "todo", "--data", str(tmp_path), "--today", "2026-10-16"]) == 0
    captured = capsys.readouterr()
    assert "does not match its manifest hash" in captured.err and "FIX    2026-10-22" in captured.out
