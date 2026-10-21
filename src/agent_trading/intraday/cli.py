"""Local commands: python -m agent_trading.intraday --help."""

import argparse
import csv
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from ..logging_setup import setup_logging
from .backtest import load_replay, replay, walk_forward
from .calendar import NY, jobs
from .config import load_config
from .demo import demo_snapshot
from .engine import Simulator
from .longbridge_api import DataUnavailable
from .longbridge_provider import LongbridgeProvider
from .notifications import export_alerts
from .providers import FileProvider, MassiveProvider
from .reporting import performance, write_report
from .service import Service, explain_latest
from .store import Store


def provider_for(args, cfg):
    if args.provider == "longbridge":
        return LongbridgeProvider(cfg)
    if args.provider == "massive":
        return MassiveProvider(os.environ.get("MASSIVE_API_KEY", ""), cfg, args.events)
    if not args.snapshot:
        raise ValueError("--snapshot path required with file provider")
    return FileProvider(args.snapshot)


def parser():
    p = argparse.ArgumentParser(description="Local options simulator; no brokerage orders or live endpoints")
    p.add_argument("--config", default="config/intraday_options.yaml")
    p.add_argument("--db", default="data/intraday/longbridge-paper.sqlite3")
    p.add_argument("--provider", choices=["longbridge", "file", "massive"], default="longbridge")
    p.add_argument("--snapshot", help="normalized timestamped JSON; never restamped")
    p.add_argument("--events", help="sourced event-clearance JSON for Massive")
    p.add_argument("--reports", default="reports/intraday")
    p.add_argument(
        "--alert-outbox", default="data/intraday/alerts.jsonl", help="local alert delivery during scheduling"
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("scan", help="manual read-only candidate scan (also monitor existing simulated positions)")
    sub.add_parser("prepare", help="refresh membership, support/resistance and event coverage")
    sub.add_parser("tick", help="run due jobs once")
    run = sub.add_parser("run", help="foreground scheduler; Ctrl+C stops process and monitoring")
    run.add_argument("--enable-entries", action="store_true", help="enable local simulated entries")
    control = sub.add_parser("control")
    control.add_argument("action", choices=["start", "stop", "enable", "disable", "emergency"])
    sub.add_parser("status")
    sub.add_parser("report")
    sub.add_parser("explain")
    sub.add_parser("schedule")
    sub.add_parser("doctor", help="read-only Longbridge credentials, data and event access diagnostics")
    export = sub.add_parser("export")
    export.add_argument("path")
    alerts = sub.add_parser("alerts", help="append new notification events to a local JSONL integration outbox")
    alerts.add_argument("path")
    demo = sub.add_parser("demo", help="offline synthetic scenario, separate demo ledger")
    demo.add_argument("--output", default="data/intraday/demo.jsonl")
    backtest = sub.add_parser("backtest")
    backtest.add_argument("path", nargs="?")
    backtest.add_argument("--entry-time", action="append", help="research restriction, e.g. 09:50 or 13:30")
    backtest.add_argument("--walk-forward", action="store_true")
    backtest.add_argument("--train-sessions", type=int, default=20)
    backtest.add_argument("--test-sessions", type=int, default=5)
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    load_dotenv(".env", override=False)
    setup_logging(Path("logs/intraday"))
    try:
        cfg = load_config(args.config)
        now = datetime.now(UTC)
        if args.command == "doctor":
            provider = provider_for(args, cfg)
            if not isinstance(provider, LongbridgeProvider):
                raise ValueError("doctor requires --provider longbridge")
            print(json.dumps(provider.check_access(now), indent=2))
            return 0
        if args.command == "schedule":
            print(
                json.dumps(
                    [(kind, at.astimezone(NY).isoformat()) for kind, at in jobs(now.astimezone(NY).date())], indent=2
                )
            )
            return 0
        if args.command == "backtest":
            snapshots = load_replay(args.path) if args.path else []
            if args.walk_forward:
                # Candidate variants fixed before evaluation. OOS blocks never select parameters.
                variants = [type(cfg).model_validate({**cfg.model_dump(), "reward_to_risk": rr}) for rr in [1.5, 2.0]]
                result = walk_forward(snapshots, variants, args.train_sessions, args.test_sessions)
            else:
                result = replay(snapshots, cfg, set(args.entry_time) if args.entry_time else None)
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0
        if args.command == "demo":
            if args.db == "data/intraday/longbridge-paper.sqlite3":
                args.db = "data/intraday/demo.sqlite3"
            now = datetime(2026, 10, 20, 9, 50, tzinfo=NY)
        store = Store(args.db, cfg)
        try:
            engine = Simulator(store, cfg)
            if args.command == "demo":
                if store.rows("orders"):
                    raise ValueError("demo requires a new empty ledger; choose a new --db path")
                engine.controls(now, running=True, enabled=True)
                snapshots = []
                for offset, premium in [(0, 0.4), (1, 0.4), (901, 0.65), (902, 0.65)]:
                    at = now + timedelta(seconds=offset)
                    snap = demo_snapshot(at, cfg, premium=premium)
                    snapshots.append(snap)
                    if offset == 0:
                        engine.cycle(snap, at, enter=True)
                    else:
                        engine.monitor(snap, at)
                end = now.replace(hour=16, minute=10, second=0)
                snapshots.append(demo_snapshot(end, cfg))
                engine.monitor(snapshots[-1], end)
                engine.controls(end, running=False, enabled=False)
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("\n".join(s.model_dump_json() for s in snapshots) + "\n", encoding="utf-8")
                print(json.dumps(performance(store, cfg), indent=2, allow_nan=False))
                write_report(store, cfg, args.reports, now.date())
            elif args.command == "control":
                changes = {
                    "start": {"running": True},
                    "stop": {"running": False, "enabled": False},
                    "enable": {"enabled": True},
                    "disable": {"enabled": False},
                    "emergency": {"emergency": True},
                }
                engine.controls(now, **changes[args.action])
                print("Local simulator controls updated. Monitoring requires the local app/process to be running.")
            elif args.command == "status":
                print(
                    json.dumps(
                        {
                            "running": store.get("running"),
                            "enabled": store.get("enabled"),
                            "emergency_stop": store.get("killed"),
                            "heartbeat": store.get("heartbeat"),
                            "provider": json.loads(store.get("provider_status", "{}")),
                            "performance": performance(store, cfg),
                        },
                        indent=2,
                    )
                )
            elif args.command == "report":
                print(write_report(store, cfg, args.reports, now.astimezone(NY).date()))
            elif args.command == "explain":
                print(json.dumps(explain_latest(store), indent=2))
            elif args.command == "alerts":
                print(f"Exported {export_alerts(store, args.path)} alert events.")
            elif args.command == "export":
                rows = store.rows("fills")
                path = Path(args.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id", "label"])
                    writer.writeheader()
                    writer.writerows(rows)
                print(path)
            else:
                service = Service(store, cfg, provider_for(args, cfg), args.reports, alerts=args.alert_outbox)
                if args.command == "run":
                    engine.controls(now, running=True, enabled=args.enable_entries)
                    service.run()
                elif args.command == "tick":
                    service.tick()
                elif args.command == "prepare":
                    print(json.dumps(service.prepare(), indent=2))
                else:
                    print(service.manual_scan().model_dump_json(indent=2))
        finally:
            store.close()
        return 0
    except DataUnavailable as exc:
        print(str(exc))  # this adapter exposes only fixed, redacted diagnostics
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        # Avoid leaking raw third-party payloads, URLs or supplied credential values.
        print(f"Unable to complete command ({type(exc).__name__}). Check configuration, data coverage and local logs.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
