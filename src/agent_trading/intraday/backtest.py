"""Event replay from real historical contracts or explicitly synthetic fixtures."""

from datetime import date
from pathlib import Path

from .calendar import NY, entry_window, exchange, session
from .config import Settings
from .engine import Simulator
from .models import Snapshot
from .reporting import performance
from .store import Store


def load_replay(path: str | Path) -> list[Snapshot]:
    return [
        Snapshot.model_validate_json(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def replay(snapshots: list[Snapshot], cfg: Settings, entry_times: set[str] | None = None) -> dict:
    if not snapshots:
        return {
            "status": "missing_data",
            "edge_status": "NOT ESTABLISHED",
            "missing": ["historical minute bars, option bid/ask/size/Greeks, point-in-time membership and events"],
        }
    times = [s.observed_at for s in snapshots]
    if any(b <= a for a, b in zip(times, times[1:], strict=False)):
        raise ValueError("replay snapshots must be strictly chronological and unique")
    feeds = {s.feed for s in snapshots}
    if len(feeds) != 1:
        raise ValueError("cannot mix fixture, real-time and delayed datasets")
    store = Store(":memory:", cfg)
    try:
        engine = Simulator(store, cfg)
        engine.controls(times[0], running=True, enabled=True)
        scan_minutes = set()
        scan_problems = set()
        for snap in snapshots:
            now = snap.observed_at.astimezone(NY)
            minute = now.replace(second=0, microsecond=0)
            eligible_minute = now.minute % 5 == 0 and (entry_times is None or now.strftime("%H:%M") in entry_times)
            do_scan = eligible_minute and minute not in scan_minutes and entry_window(now)
            if do_scan:
                result = engine.cycle(snap, now, enter=True)
                scan_problems.update(result.problems)
                for symbol in snap.universe.keys() | {"MARKET"}:
                    e = snap.events.get(symbol)
                    if not e or e.status == "unknown" or not e.observed_at <= now <= e.valid_until:
                        scan_problems.add("incomplete contemporaneous event coverage")
                scan_minutes.add(minute)
            else:
                engine.monitor(snap, now)
        result = performance(store, cfg)
        days = {t.astimezone(NY).date() for t in times}
        expected = set()
        for year in range(min(days).year, max(days).year + 1):
            first, last = max(min(days), date(year, 1, 1)), min(max(days), date(year, 12, 31))
            expected.update(d.date() for d in exchange(year).sessions_in_range(first.isoformat(), last.isoformat()))
        gaps = sorted(expected - days)
        missing_eod = [
            d.isoformat()
            for d in days
            if session(d) and max(t for t in times if t.astimezone(NY).date() == d) < session(d).close
        ]
        missing_contracts = not any(s.contracts for s in snapshots)
        input_problems = sorted({p for s in snapshots for p in s.problems} | scan_problems)
        if not scan_minutes:
            input_problems.append("no entry-window observations")
        result.update(
            {
                "status": "fixture_validation_only" if feeds == {"fixture"} else "historical_replay",
                "missing_sessions": [d.isoformat() for d in gaps],
                "missing_close_observations": sorted(missing_eod),
                "missing_historical_contracts": missing_contracts,
                "input_problems": input_problems,
                "entry_times": sorted(entry_times) if entry_times else "configured production windows",
                "input_coverage_complete": not (
                    gaps
                    or missing_eod
                    or missing_contracts
                    or input_problems
                    or result["open_positions"]
                    or not result["valuation_complete"]
                ),
                "performance_evidence_complete": feeds == {"realtime"}
                and not (
                    gaps
                    or missing_eod
                    or missing_contracts
                    or input_problems
                    or result["open_positions"]
                    or not result["valuation_complete"]
                ),
                "limitations": [
                    "displayed-size fills are a model; queue position/market impact are unobserved",
                    "historical membership must be supplied as known then; current lists cannot establish survivorship-free coverage",
                    "no 0DTE comparison or market-regime profitability claim without a suitable dataset",
                ],
            }
        )
        if gaps or missing_eod:
            result["daily_sharpe"] = None
            result["average_observed_daily_return"] = None
        return result
    finally:
        store.close()


def walk_forward_windows(days: list[date], train: int = 20, test: int = 5, embargo: int = 1):
    if train < 2 or test < 1 or embargo < 1:
        raise ValueError("require >=2 training sessions, >=1 test session and >=1 embargo session")
    days = sorted(set(days))
    for stop in range(train, len(days) - embargo - test + 1, test):
        yield days[stop - train : stop], days[stop + embargo : stop + embargo + test]


def walk_forward(
    snapshots: list[Snapshot],
    variants: list[Settings],
    train: int = 20,
    test: int = 5,
    minimum_training_trades: int = 20,
) -> list[dict]:
    """Choose on training only, freeze on the next unseen block; never modify production config."""
    days = [s.observed_at.astimezone(NY).date() for s in snapshots]
    results = []
    for training, testing in walk_forward_windows(days, train, test):
        sample = [s for s in snapshots if s.observed_at.astimezone(NY).date() in training]
        scores = [(cfg, replay(sample, cfg)) for cfg in variants]
        eligible = [
            (cfg, r)
            for cfg, r in scores
            if r["performance_evidence_complete"] and r["closed_trades"] >= minimum_training_trades
        ]
        if not eligible:
            results.append(
                {
                    "training": list(map(str, training)),
                    "testing": list(map(str, testing)),
                    "status": "insufficient_training_evidence",
                }
            )
            continue
        chosen, _ = max(eligible, key=lambda pair: pair[1]["realized_net_pnl"])
        holdout = [s for s in snapshots if s.observed_at.astimezone(NY).date() in testing]
        results.append(
            {
                "training": list(map(str, training)),
                "testing": list(map(str, testing)),
                "configuration": chosen.model_dump(),
                "out_of_sample": replay(holdout, chosen),
                "promotion": "explicit review required; no automatic production changes",
            }
        )
    return results
