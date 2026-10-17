"""Offline regressions for data provenance, exports, paths and persisted diagnostics."""

import csv
import io
import json
import logging
from datetime import date
from types import SimpleNamespace

import pytest

from agent_trading.dashboard import pipeline_collect, providers
from agent_trading.dashboard.fmt import csv_value
from agent_trading.dashboard.pipeline_context import Context
from agent_trading.dashboard.store import Store
from agent_trading.data.cache import cache_path, write_cache
from agent_trading.data.dividends import save_dividends
from agent_trading.logging_setup import protect_log_handlers, register_secret
from tests.conftest import make_bars


def test_close_only_quote_cannot_supply_missing_daily_bar(monkeypatch):
    frame = make_bars(n=80, end="2026-10-09")
    before = frame.copy(deep=True)
    context = Context(date(2026, 10, 12), SimpleNamespace(history=lambda _: frame))
    monkeypatch.setattr(pipeline_collect, "_quote", lambda *_: (SimpleNamespace(close=123.0), None))
    result, reason, flags = pipeline_collect.latest_bars(context, "SYN")
    assert result is None and "stale" in reason
    assert any("close-only" in flag for flag in flags)
    assert frame.equals(before)


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
