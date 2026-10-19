"""Command line for the weekly research dashboard.

    python -m agent_trading.dashboard run    --data research-data --cache .cache/http [--as-of YYYY-MM-DD]
    python -m agent_trading.dashboard build  --data research-data --out site
    python -m agent_trading.dashboard verify --data research-data
    python -m agent_trading.dashboard tradability todo   --data research-data
    python -m agent_trading.dashboard tradability import --data research-data <saved MCP JSON files>
    python -m agent_trading.dashboard earnings-calendar todo   --data research-data
    python -m agent_trading.dashboard earnings-calendar import --data research-data <saved MCP JSON files>

`run` exits 0 on success (status ok or partial), 2 when the run failed and the
previous snapshot must stay up (status.json says why), 1 on a usage error.
Environment: SEC_USER_AGENT (required, e.g. "agent-code research you@example.com"),
ALPHAVANTAGE_API_KEY (optional; earnings dates). Values are never printed.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from ..logging_setup import protect_log_handlers, register_secret
from . import earnings_verdicts, spec, tracking
from .http import FetchError, HttpClient
from .pipeline import RunFailed, as_of_for, run
from .providers import Providers
from .site import build_site, scan_for_secrets
from .store import IntegrityError, SnapshotExists, Store
from .tradability import Tradability, TradabilityError, parse_results, read_todo, write_todo
from .watchlist import WatchlistConfig

log = logging.getLogger("agent_trading.dashboard")
SECRET_ENV = ("ALPHAVANTAGE_API_KEY", "SEC_USER_AGENT", "FRED_API_KEY", "MASSIVE_API_KEY", "FMP_API_KEY")


def _providers(cache: Path | None, *, private_as_of: date | None = None) -> Providers:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in ua or len(ua) < 8:
        raise SystemExit("SEC_USER_AGENT must be set to a name and contact email (SEC fair-access policy)")
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip() or None
    if key:
        register_secret(key)
    register_secret(ua)
    massive_key = os.environ.get("MASSIVE_API_KEY", "").strip() if private_as_of else None
    if private_as_of and not massive_key:
        raise SystemExit("MASSIVE_API_KEY must be set in .env for private research")
    return Providers(
        HttpClient(cache, ua),
        key,
        os.environ.get("FRED_API_KEY", "").strip() or None,
        massive_key=massive_key,
        history_as_of=private_as_of,
        fmp_key=os.environ.get("FMP_API_KEY", "").strip() or None,
    )


def cmd_run(args) -> int:
    if args.private:
        from .private_research import mark_private

        mark_private(Path(args.data))
        if args.cache:
            mark_private(Path(args.cache))
    store = Store(Path(args.data))
    as_of = date.fromisoformat(args.as_of) if args.as_of else as_of_for(datetime.now(UTC))
    if str(as_of) in store.dates():
        store.audit("run_skipped", as_of=as_of, reason="snapshot already exists (immutable)")
        store.write_status("ok", f"snapshot for {as_of} already exists; kept unchanged", str(as_of))
        print(f"snapshot for {as_of} already exists; nothing to do")
        return 0
    store.audit("run_started", as_of=as_of, commit=args.commit, limit=args.limit, options=not args.no_options)
    cache = Path(args.cache) if args.cache else None
    providers = _providers(cache, private_as_of=as_of) if args.private else _providers(cache)
    if hasattr(providers.http, "limits"):
        providers.http.limits["alphavantage"].budget = spec.DECISION_RULES["weekly_av_attempts"]
    previous = store.latest(before=str(as_of))
    trad = Tradability.load(store.root)
    todo: list[dict] = []
    try:
        try:
            from .refresh_store import RefreshStore
            from .speculative import stored_history

            iv_history = stored_history(RefreshStore(store.root), as_of) if not args.no_options else {}
            payload = run(
                providers,
                as_of,
                previous,
                options_enabled=not args.no_options,
                limit=args.limit,
                tradability=trad,
                todo_out=todo,
                watchlist=WatchlistConfig.load(),
                iv_history=iv_history,
                aggregate_store=store,
                earnings_verdicts=earnings_verdicts.EarningsVerdicts.load(store.root),
            )
        finally:
            write_todo(store.root, todo, as_of)  # symbols the next Claude session should check on Robinhood
    except RunFailed as exc:
        store.audit("run_failed", as_of=as_of, reason=str(exc), usage=providers.http.usage())
        store.write_status("failed", str(exc), str(as_of))
        print(f"run failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - any crash must leave the last good dashboard up
        store.audit("run_crashed", as_of=as_of, error=f"{type(exc).__name__}: {exc}"[:500])
        store.write_status("failed", f"unexpected error ({type(exc).__name__})", str(as_of))
        log.exception("dashboard run crashed")
        return 2
    try:
        store.write_snapshot(payload, args.commit or "")
    except SnapshotExists as exc:
        store.audit("run_skipped", as_of=as_of, reason=str(exc))
    # From here on the snapshot is stored. The workflow commits the data branch only when this command exits 0
    # or 2, so a failure in the derived tracking file must be recorded, not raised: raising would discard the
    # week's snapshot and audit lines along with it. tracking.json is recomputed from the snapshots next run.
    status, problems = payload["status"], list(payload["problems"])
    try:
        update_tracking(store, providers, as_of)
    except Exception as exc:  # noqa: BLE001 - the snapshot must survive a tracking failure
        err = f"{type(exc).__name__}: {exc}"[:500]
        store.audit("tracking_failed", as_of=as_of, error=err)
        log.exception("tracking update failed; the %s snapshot is kept and tracking.json is unchanged", as_of)
        status = "partial"
        problems.append(
            f"tracking not updated ({type(exc).__name__}); the snapshot is stored and tracking is "
            "recomputed on the next run"
        )
    store.write_status(
        status,
        "weekly update completed" if status == "ok" else "weekly update completed with partial data",
        str(as_of),
        problems=problems[:10],
    )
    store.audit("run_finished", as_of=as_of, status=status, usage=providers.http.usage())
    print(f"snapshot {as_of}: status {status}; requests {providers.http.usage()['requests']}")
    usage = providers.http.usage()
    print(
        f"provider budgets {usage.get('budgets', {})}; dataset requests {usage.get('dataset_requests', {})}; dataset budgets {usage.get('dataset_budgets', {})}"
    )
    print("new datasets: " + json.dumps(payload.get("external_datasets", {}), sort_keys=True))
    return 0


def update_tracking(store: Store, providers: Providers, as_of: date) -> None:
    snaps = [store.load(d) for d in tracking.weekly_sample(store.manifests())]  # spec SNAPSHOT_CADENCE_RULE
    tickers = {c["ticker"] for s in snaps for b in s.get("bands", {}).values() for c in b.get("candidates", [])}
    tickers |= {b.benchmark for b in spec.BANDS}
    prices = {}
    from .pipeline_collect import latest_bars
    from .pipeline_context import Context

    private = getattr(providers, "history_provider", "cboe") == "massive"
    ctx = Context(as_of, providers)
    for t in sorted(tickers):
        if private:
            df, _, _ = latest_bars(ctx, t)
            if df is not None:
                prices[t] = df["close"]
            continue
        try:
            df = providers.history(t)
        except FetchError:  # reported by tracking as unavailable, never dropped silently
            continue
        prices[t] = df["close"][df.index <= str(as_of)]
    store.write_json("tracking.json", tracking.track(snaps, prices, as_of))


def cmd_tradability(args) -> int:
    data = Path(args.data)
    if args.action == "todo":
        todo = read_todo(data)
        for i in range(0, len(todo), 10):  # get_equity_tradability takes at most 10 symbols
            print(" ".join(todo[i : i + 10]))
        print(f"{len(todo)} symbol(s) to check", file=sys.stderr)
        return 0
    trad = Tradability.load(data)
    checked_at = args.checked_at or datetime.now(UTC).date().isoformat()
    changed = 0
    for f in args.files:
        try:
            changed += trad.merge(parse_results(json.loads(Path(f).read_text(encoding="utf-8")), checked_at))
        except (TradabilityError, ValueError, KeyError) as exc:
            print(f"{f}: rejected ({exc})", file=sys.stderr)
            return 1
    trad.save(data)
    Store(data).audit("tradability_imported", files=len(args.files), symbols_updated=changed, checked_at=checked_at)
    print(f"{changed} verdict(s) stored; {len(trad.symbols)} symbol(s) in total")
    return 0


def cmd_earnings_calendar(args) -> int:
    """Owner step: compare scheduled (Alpha Vantage) dates with saved read-only Robinhood calendar responses."""
    data = Path(args.data)
    today = date.fromisoformat(args.today) if args.today else datetime.now(UTC).date()
    verdicts = earnings_verdicts.EarningsVerdicts.load(data)
    if args.action == "todo":
        store = Store(data)
        try:
            snap = store.latest()
        except IntegrityError:  # a CRLF checkout changes the hash; this list is read-only and CI verifies the branch
            print(
                "warning: the latest snapshot does not match its manifest hash (line endings?); read unverified",
                file=sys.stderr,
            )
            snap = store.load(store.dates()[-1], verify=False)
        if snap is None:
            print("no weekly snapshot is stored, so there are no scheduled dates to check", file=sys.stderr)
            return 1
        summary = earnings_verdicts.attach(snap, verdicts, today)["summary"]  # in memory only; nothing is written
        items = (snap.get("events") or {}).get("items") or []
        print(
            f"{snap['as_of']} snapshot, {summary['total']} scheduled date(s) as of {today}: {summary['verified']} "
            f"verified, {summary['differs']} differ, {summary['not_listed']} not listed, {summary['unchecked']} unchecked"
        )
        for i in items:
            v = earnings_verdicts.verdict_for(snap, i["ticker"], i["date"])
            print(f"  {i['ticker']:<6} {i['date']}  {earnings_verdicts.label(v)}")
        last = max((date.fromisoformat(i["date"]) for i in items), default=None)
        if last is not None and last >= today:
            print("Read-only Robinhood calls that cover these dates (save each JSON response, then import):")
            for w in earnings_verdicts.fetch_windows(today, last):
                print(
                    f'  get_earnings_calendar(start_date="{w["start_date"]}", days={w["days"]}, filter="{w["filter"]}")'
                )
            print(f"  python -m agent_trading.dashboard earnings-calendar import --data {args.data} <files>")
        return 0
    if not args.files:
        print("nothing to import: pass the saved get_earnings_calendar JSON file(s)", file=sys.stderr)
        return 1
    if (args.start or args.days) and len(args.files) != 1:
        print("--start/--days describe one response; import one file at a time with them", file=sys.stderr)
        return 1
    checked_at = args.checked_at or today.isoformat()
    changed, windows = 0, []
    for f in args.files:
        try:
            symbols, window = earnings_verdicts.parse_calendar(
                json.loads(Path(f).read_text(encoding="utf-8")),
                checked_at,
                start=args.start,
                days=args.days,
                calendar_filter=args.filter,
            )
        except (earnings_verdicts.EarningsVerdictError, ValueError, KeyError, TypeError) as exc:
            print(f"{f}: rejected ({exc})", file=sys.stderr)
            return 1
        changed += verdicts.merge(symbols, window)
        windows.append(f"{window['start']}..{window['end']}")
    verdicts.save(data)
    Store(data).audit(
        "earnings_calendar_imported",
        files=len(args.files),
        symbols_updated=changed,
        checked_at=checked_at,
        windows=windows,
    )
    print(
        f"{changed} symbol(s) updated; {len(verdicts.symbols)} symbol(s) and {len(verdicts.windows)} window(s) stored"
    )
    return 0


def cmd_build(args) -> int:
    info = build_site(
        Path(args.data),
        Path(args.out),
        SECRET_ENV,
        code_commit=args.commit,
        data_commit=args.data_commit,
        private=args.private,
        edition=args.edition,
    )
    print(f"site built: {info}")
    return 0


def cmd_verify(args) -> int:
    from .refresh_store import RefreshStore
    from .short_term_store import ShortTermStore

    problems = (
        Store(Path(args.data)).verify_all()
        + RefreshStore(Path(args.data)).verify_all()
        + ShortTermStore(Path(args.data)).verify_all()
    )
    if not problems:
        from .private_research import check_publication

        check_publication(Store(Path(args.data)), args.private)
    problems += [
        f"credential value found in data file: {path}" for path in scan_for_secrets(Path(args.data), SECRET_ENV)
    ]
    for p in problems:
        print(p)
    return 1 if problems else 0


def cmd_refresh(args) -> int:
    from .refresh import run as refresh_run

    # No SEC calls are made; reuse the optional existing User-Agent secret without requiring it.
    ua = os.environ.get("SEC_USER_AGENT", "agent-code public research dashboard")
    key = os.environ.get("ALPHAVANTAGE_API_KEY") or None
    register_secret(ua)
    if key:
        register_secret(key)
    providers = Providers(
        HttpClient(Path(args.cache) if args.cache else None, ua), key, fmp_key=os.environ.get("FMP_API_KEY") or None
    )
    result = refresh_run(
        Path(args.data),
        providers,
        date.fromisoformat(args.as_of) if args.as_of else None,
        options_enabled=not args.no_options,
        commit=args.commit,
    )
    print(f"daily refresh: {result['status']}")
    return 2 if result["status"] == "failed" else 0


def cmd_short_term(args) -> int:
    from . import short_term
    from .short_term_store import ShortTermStore

    http = HttpClient(
        Path(args.cache) if args.cache else None, "agent-code public research dashboard", timeout=10, fresh_only=True
    )
    http.limits["cboe"].budget = 12
    http.deadline = http.clock() + 120
    providers = Providers(http)
    store = Store(Path(args.data))
    payload = short_term.collect(providers)
    ShortTermStore(Path(args.data)).write(payload, args.commit)
    store.audit(
        "short_term_finished", status=payload["status"], collected_at=payload["collected_at"], usage=http.usage()
    )
    print(f"short-term scan: {payload['status']}; requests {http.usage()['requests']}")
    for record in payload["symbols"]:
        print(
            f"{record['symbol']}: {record['state']}; {len(record['rows'])} displayed rows; {record.get('reason') or ''}"
        )
    return 2 if payload["status"] == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="python -m agent_trading.dashboard")
    p.add_argument("--env-file", type=Path, help="load dashboard credentials from a local .env file (never printed)")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="collect data, score, and store this week's immutable snapshot")
    r.add_argument("--data", required=True)
    r.add_argument("--cache", default=None)
    r.add_argument("--as-of", default=None)
    r.add_argument("--no-options", action="store_true")
    r.add_argument("--limit", type=int, default=None, help="process only N stocks per universe (smoke tests)")
    r.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    r.add_argument("--private", action="store_true", help="local personal research using Massive price history")
    r.set_defaults(func=cmd_run)
    f = sub.add_parser("refresh", help="refresh delayed prices without changing weekly snapshots or tracking")
    f.add_argument("--data", required=True)
    f.add_argument("--cache", default=None)
    f.add_argument("--as-of", default=None)
    f.add_argument("--no-options", action="store_true")
    f.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    f.set_defaults(func=cmd_refresh)
    st = sub.add_parser(
        "short-term", help="collect delayed 0DTE, 1DTE and next-listed-expiry research during the regular session"
    )
    st.add_argument("--data", required=True)
    st.add_argument("--cache", default=None)
    st.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""))
    st.set_defaults(func=cmd_short_term)
    b = sub.add_parser("build", help="render the static site from stored snapshots (no network)")
    b.add_argument("--data", required=True)
    b.add_argument("--out", required=True)
    b.add_argument(
        "--commit", default=os.environ.get("GITHUB_SHA", ""), help="full site code commit for build metadata"
    )
    b.add_argument("--data-commit", default="", help="full stored-data commit for build metadata")
    b.add_argument("--private", action="store_true", help="allow local rendering of private personal-use data")
    b.add_argument(
        "--edition",
        choices=("full", "customer"),
        default=os.environ.get("DASHBOARD_EDITION") or "full",
        help="customer: leave out options, the Buy/Sell desk, the watchlist and broker-derived data",
    )
    b.set_defaults(func=cmd_build)
    t = sub.add_parser("tradability", help="Robinhood tradability verdicts (checked in a read-only Claude session)")
    t.add_argument("action", choices=["todo", "import"])
    t.add_argument("--data", required=True)
    t.add_argument("--checked-at", default=None, help="date of the check (default today, UTC)")
    t.add_argument("files", nargs="*")
    t.set_defaults(func=cmd_tradability)
    ec = sub.add_parser(
        "earnings-calendar", help="Robinhood earnings-calendar verdicts for scheduled dates (read-only Claude session)"
    )
    ec.add_argument("action", choices=["todo", "import"])
    ec.add_argument("--data", required=True)
    ec.add_argument("--today", default=None, help="comparison date (default today, UTC)")
    ec.add_argument("--checked-at", default=None, help="date of the calendar check (default today, UTC)")
    ec.add_argument("--start", default=None, help="start_date of the saved call (with --days; one file at a time)")
    ec.add_argument("--days", type=int, default=None, help="days of the saved call (positive = forward window)")
    ec.add_argument(
        "--filter", default=earnings_verdicts.DEFAULT_FILTER, help="the call's filter: high_market_cap (default) or all"
    )
    ec.add_argument("files", nargs="*")
    ec.set_defaults(func=cmd_earnings_calendar)
    v = sub.add_parser("verify", help="check every snapshot against its manifest hash")
    v.add_argument("--data", required=True)
    v.add_argument("--private", action="store_true", help="verify local personal-use data without publication")
    v.set_defaults(func=cmd_verify)
    args = p.parse_args(argv)
    if args.env_file:
        from dotenv import dotenv_values

        if args.env_file.name != ".env" or not args.env_file.is_file():
            p.error("--env-file must name an existing .env file")
        values = dotenv_values(args.env_file)
        for name in SECRET_ENV:
            if values.get(name):
                os.environ.setdefault(name, values[name])
    for name in SECRET_ENV:
        register_secret(os.environ.get(name, ""))
    protect_log_handlers()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
