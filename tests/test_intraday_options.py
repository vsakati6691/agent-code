"""Adversarial safety, causal scan, execution lifecycle and scheduler integration."""

import json
from datetime import date, datetime, timedelta

import pytest
from pydantic import ValidationError

from agent_trading.intraday.backtest import replay, walk_forward_windows
from agent_trading.intraday.calendar import NY, entry_window, jobs, next_session, session
from agent_trading.intraday.config import Settings
from agent_trading.intraday.demo import demo_snapshot
from agent_trading.intraday.engine import Simulator
from agent_trading.intraday.models import Contract, Snapshot
from agent_trading.intraday.options import contract_problems, select
from agent_trading.intraday.providers import MassiveProvider, parse_contract
from agent_trading.intraday.reporting import performance
from agent_trading.intraday.scanner import scan
from agent_trading.intraday.service import Service
from agent_trading.intraday.store import Store

NOW = datetime(2026, 10, 20, 9, 50, tzinfo=NY)


@pytest.fixture(scope="module")
def cfg():
    return Settings()


@pytest.fixture(scope="module")
def snapshot(cfg):
    return demo_snapshot(NOW, cfg)


@pytest.fixture
def book(tmp_path, cfg):
    store = Store(tmp_path / "book.sqlite3", cfg)
    engine = Simulator(store, cfg)
    engine.controls(NOW, running=True, enabled=True)
    yield store, engine
    store.close()


def update(snap, now, *, premium=None, size=None, contracts=True):
    rows = []
    for c in snap.contracts:
        fields = {"quote_at": now, "underlying_at": now, "volume_at": now}
        if premium is not None:
            fields.update(ask=premium, bid=round(premium - 0.02, 2))
        if size is not None:
            fields.update(ask_size=size, bid_size=size)
        rows.append(c.model_copy(update=fields))
    return snap.model_copy(update={"observed_at": now, "contracts": rows if contracts else []})


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode", "live"),
        ("max_trade_loss", 51),
        ("daily_loss_budget", 101),
        ("max_trades", 3),
        ("max_positions", 3),
        ("initial_capital", float("nan")),
        ("minimum_delta", 0.9),
        ("max_trades", True),
        ("slippage", -0.1),
    ],
)
def test_config_cannot_loosen_or_accept_invalid(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_weights_and_unknown_keys():
    with pytest.raises(ValidationError):
        Settings(weights={"trend": 40})
    with pytest.raises(ValidationError):
        Settings(broker_url="https://example.invalid")


def test_calendar_holiday_dst_and_early_close():
    assert session(date(2026, 12, 25)) is None
    assert session(date(2025, 1, 9)) is None
    assert session(date(2026, 11, 27)).close.astimezone(NY).hour == 13
    assert not entry_window(datetime(2026, 11, 27, 9, 50, tzinfo=NY))
    assert [kind for kind, _ in jobs(date(2026, 11, 27))] == ["prepare", "flatten", "report"]
    assert next_session(date(2026, 11, 25)) == date(2026, 11, 27)
    assert session(date(2026, 3, 6)).open.hour == 14
    assert session(date(2026, 3, 9)).open.hour == 13
    assert len([x for x in jobs(NOW.date()) if x[0] == "scan"]) == 11


def test_scanner_complete_bull_and_bear(cfg, snapshot):
    bullish = scan(snapshot, NOW, cfg)
    assert bullish.coverage == 1
    assert len(bullish.top("CALL")) == 2 and not bullish.top("PUT")
    bearish = scan(demo_snapshot(NOW, cfg, bearish=True), NOW, cfg)
    assert len(bearish.top("PUT")) == 2 and not bearish.top("CALL")
    assert all(0 <= s.score <= 100 for s in bearish.signals)


def test_scanner_rvol_uses_same_time_of_day(cfg, snapshot):
    signal = scan(snapshot, NOW, cfg).top("CALL")[0]
    assert signal.factors["rvol"] == pytest.approx((15 * 200 + 5 * 300) / (20 * 100))


def test_no_lookahead_from_future_bars(cfg, snapshot):
    future = demo_snapshot(NOW + timedelta(hours=1), cfg)
    contaminated = snapshot.model_copy(update={"bars": future.bars})
    before = scan(snapshot, NOW, cfg)
    after = scan(contaminated, NOW, cfg)
    assert [s.model_dump() for s in before.signals] == [s.model_dump() for s in after.signals]


def test_missing_opening_minute_and_universe_coverage_block(cfg, snapshot):
    bars = dict(snapshot.bars)
    bars["ALFA"] = [b for b in bars["ALFA"] if b.end != NOW.replace(hour=9, minute=31)]
    result = scan(snapshot.model_copy(update={"bars": bars}), NOW, cfg)
    assert result.coverage == 0.5
    assert not result.top("CALL")
    assert "incomplete" in result.rejected["ALFA"]


@pytest.mark.parametrize("change", ["future_membership", "old_membership", "delayed", "events", "future_snapshot"])
def test_bad_context_cannot_qualify(cfg, snapshot, change):
    updates = {
        "future_membership": {"membership_at": NOW + timedelta(seconds=1)},
        "old_membership": {"membership_at": NOW - timedelta(days=2)},
        "delayed": {"feed": "delayed"},
        "events": {"events": {}},
        "future_snapshot": {"observed_at": NOW + timedelta(seconds=1)},
    }
    assert not scan(snapshot.model_copy(update=updates[change]), NOW, cfg).top("CALL")


def test_no_orb_confirmation_on_945_range_end(cfg):
    now = NOW.replace(minute=45)
    assert not scan(demo_snapshot(now, cfg), now, cfg).top("CALL")


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"ask": 1.5, "bid": 1.48}, "full-premium"),
        ({"quote_at": NOW - timedelta(seconds=31)}, "stale"),
        ({"quote_at": NOW + timedelta(seconds=1)}, "future"),
        ({"bid": 0.5}, "crossed"),
        ({"bid": 0.2}, "spread"),
        ({"delta": -0.5}, "delta"),
        ({"feed": "delayed"}, "feed"),
        ({"open_interest": 2}, "interest"),
        ({"ask_size": 0}, "size"),
        ({"multiplier": 10}, "deliverable"),
        ({"volume_at": NOW - timedelta(days=1)}, "volume"),
        ({"symbol": "O:ALFA261021C00101000"}, "identifier"),
        ({"expiry": date(2026, 10, 23)}, "next-session"),
    ],
)
def test_option_filters(cfg, snapshot, change, reason):
    c = snapshot.contracts[0].model_copy(update=change)
    assert any(reason in r for r in contract_problems(c, "ALFA", "CALL", NOW, cfg, fixture=True))


def test_no_expiration_substitution(cfg, snapshot):
    c = snapshot.contracts[0].model_copy(update={"expiry": date(2026, 10, 23)})
    selected, rejected = select([c], "ALFA", "CALL", NOW, cfg, fixture=True)
    assert selected is None and rejected


def test_missing_greeks_and_nonfinite_quote_rejected(snapshot):
    fields = snapshot.contracts[0].model_dump()
    del fields["theta"]
    with pytest.raises(ValidationError):
        Contract.model_validate(fields)
    fields = snapshot.contracts[0].model_dump()
    fields["bid"] = float("nan")
    with pytest.raises(ValidationError):
        Contract.model_validate(fields)


def test_pending_is_not_fill_and_same_quote_cannot_fill(book, snapshot):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    assert len(store.rows("orders")) == 2
    assert not store.rows("fills")
    engine.monitor(snapshot, NOW + timedelta(seconds=1))
    assert not store.rows("fills")


def test_full_lifecycle_fees_and_actual_net_pnl(book, snapshot, cfg):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    engine.monitor(update(snapshot, NOW + timedelta(seconds=1)), NOW + timedelta(seconds=1))
    assert len(store.rows("fills")) == 2
    assert all(p["quantity"] == 1 for p in store.rows("positions"))
    engine.monitor(update(snapshot, NOW + timedelta(seconds=20), premium=0.65), NOW + timedelta(seconds=20))
    assert len(store.rows("fills")) == 2  # exit submission is also not a fill
    engine.monitor(update(snapshot, NOW + timedelta(seconds=21), premium=0.65), NOW + timedelta(seconds=21))
    assert all(p["quantity"] == 0 for p in store.rows("positions"))
    report = performance(store, cfg)
    assert report["closed_trades"] == 2
    assert report["realized_net_pnl"] == pytest.approx(2 * (62 - 41 - 1.3))
    assert report["profit_factor"] is None
    assert report["equity"] == pytest.approx(10039.4)
    assert engine.cash(NOW) == 1000000 - 2 * 4165  # same-day sale proceeds not reused


def test_gap_away_from_limit_does_not_fill(book, snapshot):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    at = NOW + timedelta(seconds=1)
    engine.monitor(update(snapshot, at, premium=0.7), at)
    assert not store.rows("fills")
    at = NOW + timedelta(seconds=61)
    engine.monitor(update(snapshot, at), at)
    assert all(o["status"] == "cancelled" for o in store.rows("orders"))


def test_atomic_duplicate_prevention_across_connections(tmp_path, cfg, snapshot):
    path = tmp_path / "same.sqlite3"
    one, two = Store(path, cfg), Store(path, cfg)
    try:
        a, b = Simulator(one, cfg), Simulator(two, cfg)
        a.controls(NOW, running=True, enabled=True)
        a.cycle(snapshot, NOW, enter=True)
        b.cycle(snapshot, NOW, enter=True)
        assert len(one.rows("orders")) == 2
    finally:
        one.close()
        two.close()


def test_partial_fills_never_reuse_displayed_size_on_restart(tmp_path, cfg, snapshot):
    path = tmp_path / "partial.sqlite3"
    cheap = update(snapshot, NOW, premium=0.2)
    # Tight spread and low premium permit two contracts while keeping full-premium risk <= $50.
    cheap = cheap.model_copy(update={"contracts": [c.model_copy(update={"bid": 0.19}) for c in cheap.contracts]})
    store = Store(path, cfg)
    engine = Simulator(store, cfg)
    engine.controls(NOW, running=True, enabled=True)
    engine.cycle(cheap, NOW, enter=True)
    later = update(cheap, NOW + timedelta(seconds=1))
    engine.monitor(later, NOW + timedelta(seconds=1))
    assert all(o["status"] == "partial" and o["filled"] == 1 for o in store.rows("orders"))
    store.close()
    reopened = Store(path, cfg)
    try:
        engine = Simulator(reopened, cfg)
        engine.monitor(later, NOW + timedelta(seconds=2))
        assert len(reopened.rows("fills")) == 2
        later = update(cheap, NOW + timedelta(seconds=3))
        engine.monitor(later, NOW + timedelta(seconds=3))
        assert len(reopened.rows("fills")) == 4
        assert all(o["status"] == "filled" for o in reopened.rows("orders"))
    finally:
        reopened.close()


def test_emergency_stop_and_missing_exit_quotes_stay_unresolved(book, snapshot, cfg):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    at = NOW + timedelta(seconds=1)
    engine.monitor(update(snapshot, at), at)
    engine.controls(at, emergency=True)
    with pytest.raises(ValueError, match="latched"):
        engine.controls(at, enabled=True)
    end = NOW.replace(hour=16, minute=10)
    engine.monitor(update(snapshot, end, contracts=False), end)
    assert all(p["quantity"] == 1 for p in store.rows("positions"))
    assert store.get("killed") == "true"
    assert performance(store, cfg)["equity"] is None
    assert any(e["kind"] == "unresolved_overnight_positions" for e in store.rows("events"))


def test_configuration_cannot_reinterpret_existing_ledger(tmp_path, cfg):
    path = tmp_path / "pinned.sqlite3"
    Store(path, cfg).close()
    with pytest.raises(ValueError, match="configuration changed"):
        Store(path, Settings(reward_to_risk=2))


def test_ledger_corruption_latches_stop(book, snapshot):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    at = NOW + timedelta(seconds=1)
    engine.monitor(update(snapshot, at), at)
    store.db.execute("UPDATE positions SET quantity=99")
    engine.monitor(update(snapshot, at + timedelta(seconds=1)), at + timedelta(seconds=1))
    assert store.get("killed") == "true"
    assert store.get("enabled") == "false"


def test_daily_budget_reserves_all_pending_orders(tmp_path, snapshot):
    cfg = Settings(daily_loss_budget=50)
    store = Store(tmp_path / "budget.sqlite3", cfg)
    try:
        engine = Simulator(store, cfg)
        engine.controls(NOW, running=True, enabled=True)
        engine.cycle(snapshot, NOW, enter=True)
        assert len(store.rows("orders")) == 1
    finally:
        store.close()


def test_fake_future_snapshot_never_fills(book, snapshot):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    engine.monitor(update(snapshot, NOW + timedelta(seconds=10)), NOW + timedelta(seconds=1))
    assert not store.rows("fills")


class FakeHTTP:
    def __init__(self, pages):
        self.pages, self.calls, self.limits = iter(pages), [], {}

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.pages)


def test_provider_pagination_never_exfiltrates_key(cfg):
    http = FakeHTTP([{"status": "OK", "results": [], "next_url": "https://example.invalid/steal"}])
    provider = MassiveProvider("placeholder-test-key", cfg, http=http)
    with pytest.raises(RuntimeError, match="pagination"):
        provider.chain("ALFA", NOW)
    assert len(http.calls) == 1


def test_provider_translates_start_to_completed_minute(cfg):
    start = NOW - timedelta(minutes=1)
    http = FakeHTTP(
        [
            {
                "status": "OK",
                "results": [
                    {"t": int(start.timestamp() * 1000), "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 200, "vw": 100.2}
                ],
            }
        ]
    )
    bars = MassiveProvider("placeholder-test-key", cfg, http=http).bars("ALFA", "2026-10-20", "2026-10-20")
    assert bars[0].end == NOW
    assert http.calls[0][1]["params"]["adjusted"] == "false"


def test_contract_parser_requires_observed_quote():
    with pytest.raises(KeyError):
        parse_contract({"details": {}, "greeks": {}})


class FakeProvider:
    def __init__(self, snapshot):
        self.value, self.calls = snapshot, 0

    def snapshot(self, now, *, include_stocks=True):
        self.calls += 1
        return self.value


def test_schedule_idempotence_and_missed_jobs(book, snapshot, cfg, tmp_path):
    store, _ = book
    provider = FakeProvider(snapshot)
    service = Service(store, cfg, provider, tmp_path, clock=lambda: NOW)
    service.tick()
    service.tick()
    scans = [r for r in store.rows("runs") if r["job"].startswith("scan:")]
    assert len(scans) == 2  # 9:45 missed; 9:50 claimed exactly once
    assert {r["status"] for r in scans} == {"missed", "done"}
    assert len(store.rows("orders")) == 2


def test_provider_failure_disables_entries_and_redacts_raw_errors(book, cfg, tmp_path):
    store, _ = book

    class Broken:
        def snapshot(self, *args, **kwargs):
            raise RuntimeError("apiKey=secret-never-store")

    Service(store, cfg, Broken(), tmp_path, clock=lambda: NOW).tick()
    assert store.get("enabled") == "false"
    assert "secret-never-store" not in json.dumps(store.rows("events"))


def test_replay_requires_data_and_preserves_time(cfg, snapshot):
    assert replay([], cfg)["status"] == "missing_data"
    with pytest.raises(ValueError, match="chronological"):
        replay([snapshot, snapshot], cfg)
    result = replay([snapshot], cfg)
    assert result["status"] == "fixture_validation_only"
    assert result["missing_close_observations"] == ["2026-10-20"]
    assert result["daily_sharpe"] is None


def test_walk_forward_has_embargo_and_no_overlapping_oos():
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(20)]
    folds = list(walk_forward_windows(days, train=5, test=3))
    seen = set()
    for training, testing in folds:
        assert max(training) + timedelta(days=1) < min(testing)
        assert not seen.intersection(testing)
        seen.update(testing)


def test_normalized_snapshot_rejects_timezone_naive(cfg, snapshot):
    raw = snapshot.model_dump(mode="json")
    raw["observed_at"] = "2026-10-20T09:50:00"
    with pytest.raises(ValidationError):
        Snapshot.model_validate(raw)


def test_signal_invalidation_cancels_pending_entry(book, snapshot):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    at = NOW + timedelta(seconds=1)
    bad = update(snapshot, at).model_copy(update={"events": {}})
    engine.cycle(bad, at, enter=True)
    assert not store.rows("fills")
    assert all(o["status"] == "cancelled" for o in store.rows("orders"))


def test_maximum_hold_enqueues_exit_and_requires_next_quote(book, snapshot):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    at = NOW + timedelta(seconds=1)
    engine.monitor(update(snapshot, at), at)
    at += timedelta(minutes=60)
    engine.monitor(update(snapshot, at), at)
    assert all(p["quantity"] == 1 for p in store.rows("positions"))
    assert any(o["reason"] == "maximum holding period" for o in store.rows("orders"))
    engine.monitor(update(snapshot, at + timedelta(seconds=1)), at + timedelta(seconds=1))
    assert all(p["quantity"] == 0 for p in store.rows("positions"))


def test_stop_loss_can_exceed_threshold_and_reports_actual_loss(book, snapshot, cfg):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    at = NOW + timedelta(seconds=1)
    engine.monitor(update(snapshot, at), at)
    at += timedelta(seconds=1)
    engine.monitor(update(snapshot, at, premium=0.1), at)
    engine.monitor(update(snapshot, at + timedelta(seconds=1), premium=0.1), at + timedelta(seconds=1))
    assert performance(store, cfg)["realized_net_pnl"] == pytest.approx(2 * (7 - 41 - 1.3))
    assert all(p["quantity"] == 0 for p in store.rows("positions"))


def test_emergency_still_allows_exits(book, snapshot):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    at = NOW + timedelta(seconds=1)
    engine.monitor(update(snapshot, at), at)
    engine.controls(at, emergency=True)
    at += timedelta(seconds=1)
    engine.monitor(update(snapshot, at), at)
    engine.monitor(update(snapshot, at + timedelta(seconds=1)), at + timedelta(seconds=1))
    assert all(p["quantity"] == 0 for p in store.rows("positions"))
    assert store.get("killed") == "true"


def test_outbox_is_optional_local_and_idempotent(book, snapshot, tmp_path):
    from agent_trading.intraday.notifications import export_alerts

    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    path = tmp_path / "outbox.jsonl"
    assert export_alerts(store, path) == 4
    assert export_alerts(store, path) == 0
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len({r["id"] for r in rows}) == 4


def test_replay_complete_fixture_is_never_market_evidence(cfg, snapshot):
    at = NOW + timedelta(seconds=1)
    end = NOW.replace(hour=16, minute=10)
    snaps = [
        snapshot,
        update(snapshot, at),
        update(snapshot, at + timedelta(seconds=10), premium=0.65),
        update(snapshot, at + timedelta(seconds=11), premium=0.65),
        update(snapshot, end),
    ]
    report = replay(snaps, cfg)
    assert report["closed_trades"] == 2
    assert report["input_coverage_complete"]
    assert not report["performance_evidence_complete"]
    assert report["edge_status"].startswith("NOT ESTABLISHED")


def test_widened_spread_after_submission_cannot_fill(book, snapshot):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    at = NOW + timedelta(seconds=1)
    changed = update(snapshot, at)
    changed = changed.model_copy(update={"contracts": [c.model_copy(update={"bid": 0.01}) for c in changed.contracts]})
    engine.monitor(changed, at)
    assert not store.rows("fills")


def test_cost_basis_corruption_latches_stop(book, snapshot):
    store, engine = book
    engine.cycle(snapshot, NOW, enter=True)
    at = NOW + timedelta(seconds=1)
    engine.monitor(update(snapshot, at), at)
    store.db.execute("UPDATE positions SET cost=1")
    engine.monitor(update(snapshot, at + timedelta(seconds=1)), at + timedelta(seconds=1))
    assert store.get("killed") == "true"


def test_replay_incomplete_event_coverage_cannot_pass(cfg, snapshot):
    bad = snapshot.model_copy(update={"events": {}})
    end = NOW.replace(hour=16, minute=10)
    result = replay([bad, update(bad, end)], cfg)
    assert not result["input_coverage_complete"]
    assert "incomplete contemporaneous event coverage" in result["input_problems"]
