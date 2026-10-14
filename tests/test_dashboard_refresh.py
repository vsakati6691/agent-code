"""Daily collection is bounded, immutable and separate from weekly research. No network."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from agent_trading.dashboard import options, spec
from agent_trading.dashboard.http import BudgetExceeded, HttpClient
from agent_trading.dashboard.refresh import CBOE_BUDGET, collect, constrain, run
from agent_trading.dashboard.refresh_store import MAX_DAY_BYTES, RefreshStore
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.site_refresh import load_context, price
from agent_trading.dashboard.store import Store
from tests.dashboard_fixtures import AS_OF, FakeProviders, benchmarks, demo_site, option_row
from tests.test_dashboard_site import visible_text

NOW = datetime(2026, 10, 9, 22, 30, tzinfo=timezone.utc)


class RefreshProviders(FakeProviders):
    def __init__(self):
        super().__init__()
        self.http = HttpClient(None, "offline test")
        benchmarks(self)
        for i, symbol in enumerate(("AAA", "AIA", "AIM")):
            self.add(symbol, i + 1)
            self.chains[symbol] = ({"symbol": symbol, "close": 100, "last_trade_time": f"{AS_OF}T16:00:00",
                                    "timestamp": f"{AS_OF} 22:00:00"},
                                   [option_row(symbol, AS_OF + timedelta(days=90), 100, 4.9, 5.1)])

    def _check(self, what):
        provider = "alphavantage" if what == "earnings" else "cboe"
        if self.http.budget_left(provider) <= 0:
            raise BudgetExceeded("test budget spent")
        self.http.used[provider] = self.http.used.get(provider, 0) + 1
        super()._check(what)


def weekly(data):
    snap = {"as_of": str(AS_OF), "spec_version": spec.SPEC_VERSION, "status": "ok",
            "bands": {k: {"candidates": [{"ticker": t}]} for k, t in
                      (("large", "AAA"), ("ai_large", "AIA"), ("ai_mid", "AIM"))}}
    store = Store(data)
    store.write_snapshot(snap, "test")
    store.write_json("tracking.json", {"sentinel": "weekly only"})
    return snap


def file_hashes(data):
    return {p.relative_to(data).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in data.rglob("*") if p.is_file() and p.name != "audit.jsonl"}


def test_refresh_writes_only_daily_preserves_weekly_and_tracking_and_appends_audit(tmp_path):
    snap = weekly(tmp_path)
    before, audit = file_hashes(tmp_path), (tmp_path / "audit.jsonl").read_bytes()
    p = RefreshProviders()
    out = run(tmp_path, p, AS_OF, now=NOW)
    assert out["status"] == "ok"
    after = file_hashes(tmp_path)
    assert all(after[k] == value for k, value in before.items())
    assert all(k.startswith("daily/") for k in after.keys() - before.keys())
    assert (tmp_path / "audit.jsonl").read_bytes().startswith(audit)
    assert [e["event"] for e in Store(tmp_path).audit_log()][-2:] == ["refresh_started", "refresh_finished"]
    assert set(out["quotes"]) == {"AAA", "AIA", "AIM", "SPY", "IJH", "IWM"}
    assert {c for c in p.calls if c.startswith("chain:")} == {"chain:AAA"}
    assert p.calls.count("earnings") == 1
    assert all(c.startswith(("quote:", "chain:")) or c == "earnings" for c in p.calls)
    expected = options.build_horizons({"AAA": p.chains["AAA"]}, AS_OF, {})
    row = out["options"]["3m"]["calls"]["rows"][0]
    assert row["option"] == expected["3m"]["calls"]["rows"][0]["option"]
    assert row["rank_components"] == expected["3m"]["calls"]["rows"][0]["rank_components"]
    assert "payoffs" not in row and "sensitivity" not in row and "raw_chains" not in out
    assert Store(tmp_path).load(str(AS_OF)) == snap
    assert RefreshStore(tmp_path).verify_all() == []
    assert sum(p.stat().st_size for p in (tmp_path / "daily" / str(AS_OF)).iterdir()) < MAX_DAY_BYTES


def test_same_session_keeps_first_without_any_network(tmp_path):
    weekly(tmp_path)
    p = RefreshProviders()
    run(tmp_path, p, AS_OF, now=NOW)
    first, n = file_hashes(tmp_path), len(p.calls)
    assert run(tmp_path, p, AS_OF, now=NOW)["status"] == "skipped"
    assert first == file_hashes(tmp_path) and len(p.calls) == n
    assert Store(tmp_path).audit_log()[-1]["event"] == "refresh_skipped"


@pytest.mark.parametrize("session,now", [(date(2026, 12, 25), datetime(2026, 12, 25, 23, tzinfo=timezone.utc)),
                                          (date(2026, 10, 10), NOW), (AS_OF, NOW.replace(hour=19))])
def test_holidays_weekends_and_unfinished_session_skip(tmp_path, session, now):
    weekly(tmp_path)
    p = RefreshProviders()
    assert run(tmp_path, p, session, now=now)["status"] == "skipped"
    assert not p.calls and not (tmp_path / "daily").exists()
    assert Store(tmp_path).audit_log()[-1]["event"] == "refresh_skipped"


def test_stale_failed_quotes_and_missing_calendar_are_unavailable(tmp_path):
    weekly(tmp_path)
    p = RefreshProviders()
    original = p.quote
    p.quote = lambda symbol: replace(original(symbol), last_trade=datetime(2026, 10, 8, 16)) if symbol == "AAA" else original(symbol)
    p.fail.update({"quote:SPY", "chain:AAA", "earnings"})
    out = run(tmp_path, p, AS_OF, now=NOW)
    assert out["status"] == "partial"
    for ticker in ("AAA", "SPY"):
        assert out["quotes"][ticker]["status"] == "unavailable" and out["quotes"][ticker]["close"] is None
    assert "stale" in out["quotes"]["AAA"]["reason"]
    assert out["options"]["events_known"] is False and out["chain_status"]["AAA"]["status"] == "unavailable"


@pytest.mark.parametrize("change", [{"timestamp": "2026-10-08 21:00:00"}, {"symbol": "OTHER"},
                                    {"last_trade_time": "2026-10-08T16:00:00"}, {"close": float("nan")}])
def test_invalid_chain_rejected_without_contracts(tmp_path, change):
    weekly(tmp_path)
    p = RefreshProviders()
    under, rows = p.chains["AAA"]
    p.chains["AAA"] = ({**under, **change}, rows)
    out = run(tmp_path, p, AS_OF, now=NOW)
    assert out["options"]["3m"]["calls"]["rows"] == []
    assert out["chain_status"]["AAA"]["status"] == "unavailable"


def test_budget_exhaustion_records_every_unavailable_item(tmp_path):
    weekly(tmp_path)
    p = RefreshProviders()
    p.http.limits["cboe"].budget = 2
    out = run(tmp_path, p, AS_OF, now=NOW)
    assert out["status"] == "partial" and out["usage"]["requests"]["cboe"] == 2
    assert len(out["quotes"]) == 6 and "budget" in out["quotes"]["SPY"]["reason"]


def test_http_refresh_limits_fresh_cache_and_deadline(tmp_path):
    now = [0.0]
    response = Mock(status_code=200, content=b'{"fresh":true}')
    client = HttpClient(tmp_path, "offline", session=Mock(), clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    client.session.get.return_value = response
    url = "https://cdn-api.cboe.com/test"
    client._write_cache(client._key(url, None, ""), b'{"stale":true}')
    constrain(client)
    assert client.get_json(url, max_age_hours=12) == {"fresh": True}
    assert client.limits["cboe"].budget == CBOE_BUDGET == 80
    assert client.limits["alphavantage"].budget == 1 and client.limits["sec"].budget == 0
    client.session.get.return_value = Mock(status_code=429, headers={"Retry-After": "99999"})
    with pytest.raises(BudgetExceeded, match="time budget"):
        client.get_json(url)
    assert now[0] < 840
    client.deadline = now[0]
    with pytest.raises(BudgetExceeded):
        client.get_json(url)


def test_actual_http_counts_retries_in_80_and_one_av_budgets():
    client = HttpClient(None, "offline", session=Mock(), sleep=lambda _: None)
    constrain(client)
    client.session.get.return_value = Mock(status_code=503, headers={})
    for _ in range(81):
        try:
            client.get_json("https://cdn-api.cboe.com/test")
        except Exception:
            pass
    assert client.used["cboe"] == 80
    with pytest.raises(Exception):
        client.get_text("https://www.alphavantage.co/test")
    assert client.used["alphavantage"] == 1


def test_failed_integrity_and_size_are_fail_closed(tmp_path):
    weekly(tmp_path)
    p = RefreshProviders()
    payload = run(tmp_path, p, AS_OF, now=NOW)
    folder = tmp_path / "daily" / str(AS_OF)
    (folder / "refresh.json").write_text("{}")
    first = file_hashes(tmp_path)
    assert run(tmp_path, p, AS_OF, now=NOW)["status"] == "failed"
    assert file_hashes(tmp_path) == first
    assert Store(tmp_path).audit_log()[-1]["event"] == "refresh_failed"
    assert RefreshStore(tmp_path).verify_all()
    with pytest.raises(ValueError, match="400 KB"):
        RefreshStore(tmp_path / "large").write({**payload, "padding": "x" * MAX_DAY_BYTES})
    with pytest.raises(ValueError, match="private"):
        RefreshStore(tmp_path / "private").write({**payload, "api_key": "synthetic"})


@pytest.fixture(scope="module")
def built_refresh(tmp_path_factory):
    data, out = demo_site(tmp_path_factory.mktemp("refresh-site"), two_weeks=False)
    snap = Store(data).latest()
    p = RefreshProviders()
    # All other synthetic candidates remain visibly unavailable; never add invented quote values.
    payload = run(data, p, AS_OF, now=NOW)
    assert payload["status"] == "partial"
    build_site(data, out)
    return data, out, snap


def test_site_daily_labels_fallbacks_weekly_scores_links_and_size(built_refresh, tmp_path):
    data, out, snap = built_refresh
    for name in ("index", "growth", "options"):
        page = (out / f"{name}.html").read_text(encoding="utf-8")
        assert "Daily refresh," in page and "UTC, delayed, not live" in page and f"weekly snapshot {AS_OF}" in page
        assert "None" not in visible_text(page) and "NaN" not in visible_text(page)
    assert "Daily view" in (out / "options.html").read_text(encoding="utf-8")
    assert "Daily unavailable" in (out / "growth.html").read_text(encoding="utf-8")
    assert Store(data).latest() == snap
    assert all(p.stat().st_size < 300_000 for p in out.rglob("*.html"))
    ctx = load_context(tmp_path / "missing", snap, tmp_path / "empty-out")
    assert ctx["data"] is None and "missing" in ctx["reason"]
    assert price("ABC", 10, ctx) == (10, "Weekly close")
    newer = {**snap, "as_of": "2026-10-12"}
    ctx = load_context(data, newer, tmp_path / "older-out")
    assert ctx["data"] is None and "older" in ctx["reason"]


def test_site_publishes_only_last_30_daily_files_and_keeps_source(tmp_path):
    store = RefreshStore(tmp_path / "data")
    for n in range(35):
        day = (AS_OF - timedelta(days=n)).isoformat()
        store.write({"as_of": day, "weekly_as_of": "2026-09-01", "spec_version": spec.SPEC_VERSION})
    load_context(tmp_path / "data", {"as_of": "2026-09-01"}, tmp_path / "out")
    assert len(list((tmp_path / "out").rglob("refresh.json"))) == 30
    assert len(store.dates()) == 35


def test_workflow_is_guarded_pinned_and_serialized_with_weekly():
    root = Path(__file__).resolve().parents[1]
    daily = yaml.safe_load((root / ".github/workflows/research-dashboard-daily.yml").read_text())
    weekly = yaml.safe_load((root / ".github/workflows/research-dashboard.yml").read_text())
    assert daily["concurrency"] == weekly["concurrency"] == {"group": "research-dashboard", "cancel-in-progress": False}
    assert "vars.DASHBOARD_DAILY == 'true'" in daily["jobs"]["update"]["if"]
    assert daily["permissions"] == {"contents": "read"}
    assert daily["jobs"]["update"]["permissions"] == {"contents": "write"}
    for job in daily["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                assert len(step["uses"].split("@")[1]) == 40
