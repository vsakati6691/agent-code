"""Commands for collecting and importing research inputs."""

from __future__ import annotations

from pathlib import Path

from .cli_common import _service, _symbols
from .config import Settings


def cmd_fetch(settings: Settings, args) -> int:
    from .data.rates import refresh_rates

    svc = _service(settings, with_client=True)
    status = svc.refresh(_symbols(settings, args.symbols), args.as_of)
    svc.refresh_earnings(args.as_of)
    if refresh_rates(settings, svc.client, args.as_of):
        print("T-bill rates updated")
    for sym, msg in status.items():
        print(f"{sym:<6} {msg}")
    print(f"API calls used this run: {svc.client.calls_made}")
    return 0


def cmd_import_csv(settings: Settings, args) -> int:
    from .data.service import import_csv

    n = import_csv(settings, args.symbol.upper(), Path(args.path))
    print(f"{args.symbol.upper()}: cache now holds {n} bars")
    return 0


def cmd_import_robinhood(settings: Settings, args) -> int:
    from .data.service import import_robinhood

    for path in args.paths:
        for sym, n in import_robinhood(settings, Path(path)).items():
            print(f"{sym:<6} cache now holds {n} bars")
    return 0


def cmd_universe(settings: Settings, args) -> int:
    from .data.universe import UniverseError, import_universe, load_universe, universe_problems

    if args.action == "import-history":
        from .data.universe import import_universe_history

        try:
            for h in sorted(import_universe_history(settings, [Path(p) for p in args.paths]), key=lambda x: x.as_of):
                print(f"{h.as_of}: {len(h.tickers)} constituents; unresolved {len(h.excluded)}")
        except (UniverseError, ValueError, KeyError) as exc:
            print(f"Historical list rejected: {exc}")
            return 2
        return 0
    if args.action == "import":
        try:
            u = import_universe(settings, Path(args.path))
        except (UniverseError, ValueError, KeyError) as exc:
            print(f"Constituent list rejected: {exc}")
            return 2
    else:
        u = load_universe(settings)
        if u is None:
            print("No constituent list imported.")
            return 1
    print(f"{len(u.tickers)} constituents as of {u.as_of} ({u.source})")
    if u.excluded:
        print("Excluded rows: " + "; ".join(u.excluded))
    problems = universe_problems(u, settings, args.as_of)
    for p in problems:
        print(f"WARNING: {p}")
    if args.action == "symbols":
        print(" ".join(u.tickers))
    return 0 if not problems else 2


def cmd_snapshot(settings: Settings, args) -> int:
    from .data.snapshots import SnapshotDataError, import_snapshot_files

    try:
        snap = import_snapshot_files(settings, args.kind, [Path(p) for p in args.paths], merge=args.merge)
    except (SnapshotDataError, ValueError, KeyError) as exc:
        print(f"Snapshot rejected: {exc}")
        return 2
    print(f"{args.kind}: {len(snap.table)} rows stored ({snap.source})")
    return 0


def cmd_dividends(settings: Settings, args) -> int:
    from .data.dividends import import_dividends_file

    s = import_dividends_file(settings, args.symbol.upper(), Path(args.path))
    span = f"{s.index.min().date()} to {s.index.max().date()}" if len(s) else "none"
    print(f"{args.symbol.upper()}: {len(s)} dividends ({span})")
    return 0
