"""Shared CLI data loaders, journal access and historical input validation."""

from __future__ import annotations

import logging

from .config import Settings, get_api_key

log = logging.getLogger("agent_trading")


def _service(settings: Settings, with_client: bool):
    from .data.alphavantage import AlphaVantageClient
    from .data.service import MarketDataService

    client = None
    if with_client:
        client = AlphaVantageClient(get_api_key(), pause_seconds=settings.data.request_pause_seconds)
    return MarketDataService(settings, client)


def _journal(settings: Settings):
    from .journal import Journal

    return Journal(settings.resolve(settings.paths.journal_db))


def _symbols(settings: Settings, arg: list[str] | None) -> list[str]:
    return [s.upper() for s in arg] if arg else settings.symbols


def _load(settings: Settings, args):
    svc = _service(settings, with_client=False)
    loaded = svc.load(_symbols(settings, getattr(args, "symbols", None)), args.as_of)
    for reason in loaded.rejected.values():
        log.warning("Rejected: %s", reason)
    return svc, loaded


def _account(settings: Settings):
    from .account import load_saved_snapshot, verify_snapshot

    snap = load_saved_snapshot(settings)
    return None if snap is None else (snap, verify_snapshot(snap, settings))


def _backtest_bars(settings: Settings, args) -> dict:
    """Backtests validate completeness but not freshness (history may be older).

    Old frozen stretches (pre-merger shells, thin pre-listing trading) are
    trimmed off; a recent freeze excludes the symbol.
    """
    from .data.cache import read_cache
    from .data.validation import DataQualityError, trim_frozen_history, validate_bars

    cache_dir = settings.resolve(settings.data.cache_dir)
    since = getattr(args, "since", None)
    bars = {}
    for sym in _symbols(settings, args.symbols):
        df = read_cache(cache_dir, sym)
        try:
            if df is None or df.empty:
                raise DataQualityError(f"{sym}: no data")
            if since is not None:
                df = df.loc[str(since) :]
            df, note = trim_frozen_history(df, sym)
            if note:
                log.warning("%s", note)
            bars[sym] = validate_bars(df, sym, df.index[-1].date(), 0, settings.data.min_history_bars)
        except DataQualityError as exc:
            log.warning("Excluded from backtest: %s", exc)
    return bars
