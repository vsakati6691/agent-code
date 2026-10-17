"""Offline regressions for data provenance, exports, paths and persisted diagnostics."""

import csv
import io
import json
import logging
from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from agent_trading.dashboard import pipeline_collect, providers
from agent_trading.dashboard.fmt import csv_value
from agent_trading.dashboard.pipeline_context import Context
from agent_trading.dashboard.providers import Quote
from agent_trading.dashboard.store import Store
from agent_trading.data.cache import cache_path, write_cache
from agent_trading.data.dividends import save_dividends
from agent_trading.logging_setup import protect_log_handlers, register_secret
from tests.conftest import make_bars

AS_OF = date(2026, 10, 12)  # Monday; a lagging Cboe history file still ends Friday 2026-10-09


def session_quote(frame, **changes):
    """A post-close Cboe quote for the as-of session that links to the history file's last close."""
    last = float(frame["close"].iloc[-1])
    values = {
        "symbol": "SYN",
        "close": last * 1.01,
        "prev_close": last,
        "last_trade": datetime(2026, 10, 12, 15, 59, 59),
        "iv30": 20.0,
        "fetched": "2026-10-13 00:05:25",  # UTC, as Cboe stamps it: 20:05 ET on the as-of session
        "open": last * 1.002,
        "high": last * 1.015,
        "low": last * 0.995,
        "volume": 1_234_567.0,
        "change": last * 0.01,
    }
    return Quote(**(values | changes))


def lagging_bars(frame, quote):
    context = Context(AS_OF, SimpleNamespace(history=lambda _: frame, quote=lambda _: quote))
    return pipeline_collect.latest_bars(context, "SYN")


def test_close_only_quote_cannot_supply_missing_daily_bar():
    frame = make_bars(n=80, end="2026-10-09")
    before = frame.copy(deep=True)
    quote = session_quote(frame, open=None, high=None, low=None, volume=None)
    result, reason, flags = lagging_bars(frame, quote)
    assert result is None and "stale" in reason
    assert any("close-only" in flag for flag in flags)
    assert frame.equals(before)


@pytest.mark.parametrize("rolled", [False, True])
def test_lagging_history_takes_as_of_bar_from_post_close_quote(rolled):
    frame = make_bars(n=80, end="2026-10-09")
    before = frame.copy(deep=True)
    quote = session_quote(frame)
    if rolled:  # after hours Cboe can set prev_close to the session's own close; close - change still links
        quote = replace(quote, prev_close=quote.close)
    result, reason, flags = lagging_bars(frame, quote)
    assert reason is None and result.index[-1].date() == AS_OF
    observed = {"open": quote.open, "high": quote.high, "low": quote.low, "close": quote.close, "volume": quote.volume}
    assert result.iloc[-1].to_dict() == observed
    pd.testing.assert_frame_equal(result.iloc[:-1], frame, check_dtype=False, check_freq=False)
    assert frame.equals(before)
    assert any("end-of-session Cboe quote" in flag for flag in flags)


@pytest.mark.parametrize(
    "change, history_end, flag",
    [
        (lambda q: {"change": None}, "2026-10-09", "close less its change does not match"),
        (lambda q: {"change": q.change + 0.01}, "2026-10-09", "close less its change does not match"),
        (lambda q: {"last_trade": datetime(2026, 10, 9, 15, 59, 59)}, "2026-10-09", "last trade is not in the as-of"),
        (lambda q: {"close": q.high * 1.01}, "2026-10-09", "outside its own high-low range"),
        (lambda q: {"volume": None}, "2026-10-09", "close-only"),
        (lambda q: {}, "2026-10-08", "before the preceding session"),
        (lambda q: {"fetched": "2026-10-12 19:30:00"}, "2026-10-09", None),  # 15:30 ET: pre-close, quote rejected
    ],
)
def test_quote_cannot_supply_as_of_bar_unless_verified_and_linked(change, history_end, flag):
    frame = make_bars(n=80, end=history_end)
    quote = session_quote(frame)
    result, reason, flags = lagging_bars(frame, replace(quote, **change(quote)))
    assert result is None and "stale" in reason
    if flag is None:
        assert flags == []
    else:
        assert any(flag in f for f in flags)


def test_cboe_open_outside_range_is_kept_but_recent_close_break_rejects():
    frame = make_bars(n=300, end=AS_OF.isoformat())
    open_col, close_col = frame.columns.get_loc("open"), frame.columns.get_loc("close")
    frame.iloc[-1, open_col] = frame.iloc[-1]["high"] * 1.002  # Cboe convention, seen on most series
    frame.iloc[10, close_col] = frame.iloc[10]["high"] * 1.001  # older than the 252-session window
    before = frame.copy(deep=True)
    result, reason, flags = pipeline_collect.latest_bars(
        Context(AS_OF, SimpleNamespace(history=lambda _: frame)), "SYN"
    )
    assert reason is None and result.equals(before)  # used exactly as published
    assert any(flag.startswith("1 close(s) before the last 252 sessions") for flag in flags)

    recent = before.copy()
    recent.iloc[-5, close_col] = recent.iloc[-5]["high"] * 1.001
    result, reason, _ = pipeline_collect.latest_bars(Context(AS_OF, SimpleNamespace(history=lambda _: recent)), "SYN")
    assert result is None and reason == "price data rejected: SYN: close outside high/low range"


def test_parser_preserves_unknown_volume():
    result = providers.parse_cboe_history(
        {"data": [{"date": "2026-10-12", "open": 10, "high": 11, "low": 9, "close": 10, "volume": None}]}
    )
    assert result["volume"].isna().all()


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r", "\n"])
def test_untrusted_csv_text_is_not_a_formula(prefix):
    value = prefix + 'SUM(1,2)\n"more"'
    buf = io.StringIO()
    csv.writer(buf).writerow([csv_value(value), csv_value(-1.5), csv_value(-2), csv_value("ordinary")])
    assert next(csv.reader(io.StringIO(buf.getvalue()))) == ["'" + value, "-1.5", "-2", "ordinary"]


@pytest.mark.parametrize(
    "symbol", ["../escape", "..\\escape", "C:\\escape", "/escape", "A/B", "A:B", "CON", "NUL.x", "LPT1", "X\n", ""]
)
def test_symbol_paths_reject_traversal_and_devices(tmp_path, settings, symbol):
    with pytest.raises(ValueError):
        write_cache(tmp_path / "cache", symbol, make_bars(n=2))
    with pytest.raises(ValueError):
        save_dividends(settings, symbol, make_bars(n=2)["close"])
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize("symbol", ["SPY", "brk.b", "BRK-B", "ABC1"])
def test_supported_tickers_stay_in_cache(tmp_path, symbol):
    path = cache_path(tmp_path, symbol)
    assert path.parent == tmp_path.resolve() and path.name == symbol.upper() + ".csv"


def test_audit_and_status_redact_nested_secrets_without_rewriting_history(tmp_path):
    marker = "SYNTHETIC_AUDIT_SECRET_MARKER"
    register_secret(marker)
    store = Store(tmp_path)
    store.audit("old_event", count=2)
    before = (tmp_path / "audit.jsonl").read_bytes()
    store.audit("failure", diagnostic={"error": [RuntimeError(marker)], "token": "synthetic"})
    store.write_status("failed", marker, detail={"error": marker})
    assert (tmp_path / "audit.jsonl").read_bytes().startswith(before)
    assert marker not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert marker not in (tmp_path / "status.json").read_text(encoding="utf-8")
    assert store.audit_log()[-1]["diagnostic"]["token"] == "***"
    assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["message"] == "***"


def test_console_handlers_redact_exception_text():
    marker = "SYNTHETIC_CONSOLE_SECRET_MARKER"
    register_secret(marker)
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        protect_log_handlers()
        root.error("failure %s", marker)
    finally:
        root.removeHandler(handler)
    assert marker not in out.getvalue() and "***" in out.getvalue()


def test_data_verification_refuses_secret_before_publication(tmp_path, monkeypatch, capsys):
    from agent_trading.dashboard.__main__ import main

    marker = "SYNTHETIC_VERIFY_SECRET_MARKER"
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", marker)
    (tmp_path / "diagnostic.json").write_text(json.dumps({"error": marker}), encoding="utf-8")
    assert main(["verify", "--data", str(tmp_path)]) == 1
    assert marker not in capsys.readouterr().out
