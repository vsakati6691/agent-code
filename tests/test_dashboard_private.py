"""Private source ingestion retains validation and cannot enter a public build."""

import copy
import json
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from agent_trading.dashboard import massive_history, spec
from agent_trading.dashboard.__main__ import main
from agent_trading.dashboard.http import BudgetExceeded, FetchError, HttpClient, ProviderLimits, ProviderUnavailable
from agent_trading.dashboard.massive_history import SOURCE, fetch_history, parse_history
from agent_trading.dashboard.pipeline import Context, latest_bars, run
from agent_trading.dashboard.private_research import MARKER, check_publication, mark_private
from agent_trading.dashboard.providers import Providers
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.store import Store
from agent_trading.dashboard.tradability import Tradability
from agent_trading.data.validation import DataQualityError, validate_bars
from tests.conftest import make_bars
from tests.dashboard_ci import check_links
from tests.dashboard_fixtures import AS_OF, FakeProviders, benchmarks
from tests.test_dashboard_http import Resp, Session


@pytest.fixture(autouse=True)
def local_test_context(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)


def response(symbol="IJH", end="2026-10-09", n=80):
    frame = make_bars(n=n, end=end)
    fields = {"open": "o", "high": "h", "low": "l", "close": "c", "volume": "v"}
    rows = [
        {
            **{dst: float(row[src]) for src, dst in fields.items()},
            "t": int(day.tz_localize("America/New_York").timestamp() * 1000),
        }
        for day, row in frame.iterrows()
    ]
    return {"status": "OK", "ticker": symbol, "adjusted": True, "results": rows, "resultsCount": len(rows)}


def test_parser_preserves_observations_and_new_york_session_across_dst():
    raw = response(end="2026-04-10")
    before = copy.deepcopy(raw)
    frame = parse_history(raw, "IJH")
    validate_bars(frame, "IJH", date(2026, 4, 10), 0, 60)
    assert raw == before
    assert frame.attrs["price_source"] == SOURCE and frame.attrs["publication"] == "private"
    assert frame.index[-1] == pd.Timestamp("2026-04-10")
    assert frame.iloc[-1]["open"] == raw["results"][-1]["o"]


@pytest.mark.parametrize(
    "field,value", [("adjusted", False), ("ticker", "SPY"), ("next_url", "https://bad.test"), ("resultsCount", 2)]
)
def test_parser_rejects_wrong_basis_identity_or_incomplete_history(field, value):
    raw = response()
    raw[field] = value
    with pytest.raises(FetchError):
        parse_history(raw, "IJH")


@pytest.mark.parametrize("damage", ["duplicate", "reverse", "missing", "boolean", "intraday"])
def test_parser_rejects_invalid_daily_schema(damage):
    raw = response()
    rows = raw["results"]
    if damage == "duplicate":
        rows[-1]["t"] = rows[-2]["t"]
    elif damage == "reverse":
        rows.reverse()
    elif damage == "missing":
        rows[-1].pop("v")
    elif damage == "boolean":
        rows[-1]["o"] = True
    else:
        rows[-1]["t"] += 60000
    with pytest.raises(FetchError, match="malformed"):
        parse_history(raw, "IJH")


@pytest.mark.parametrize("damage", ["bad_open", "negative_volume", "nonfinite", "stale"])
def test_existing_validator_still_rejects_observed_bad_bars(damage):
    raw = response()
    if damage == "bad_open":
        raw["results"][-1]["o"] = raw["results"][-1]["h"] + 1
    elif damage == "negative_volume":
        raw["results"][-1]["v"] = -1
    elif damage == "nonfinite":
        raw["results"][-1]["v"] = float("inf")
    as_of = date(2026, 10, 12) if damage == "stale" else AS_OF
    frame = parse_history(raw, "IJH")
    with pytest.raises(DataQualityError):
        validate_bars(frame, "IJH", as_of, 0, 60)


def test_fetch_is_bounded_cached_split_adjusted_and_keeps_key_out_of_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(massive_history, "datetime", SimpleNamespace(now=lambda tz: datetime(2026, 10, 10, tzinfo=tz)))
    session = Session([Resp(body=json.dumps(response()).encode())])
    http = HttpClient(
        tmp_path, "synthetic research test@example.com", session=session, limits={"massive": ProviderLimits(13, 1)}
    )
    provider = Providers(http, massive_key="SYNTHETIC_PRIVATE_KEY", history_as_of=AS_OF)
    ctx = Context(AS_OF, provider)
    frame, why, _ = latest_bars(ctx, "IJH")
    assert why is None and len(frame) == 80
    assert provider.history("IJH").equals(frame)
    assert len(session.calls) == 1 and http.cache_hits == 1
    url, params, _ = session.calls[0]
    assert url.endswith("/IJH/range/1/day/2024-10-11/2026-10-09")
    assert params == {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": "SYNTHETIC_PRIVATE_KEY"}
    assert all("SYNTHETIC_PRIVATE_KEY" not in p.name for p in tmp_path.iterdir())
    with pytest.raises(BudgetExceeded):
        provider.history("SPY")
    assert len(session.calls) == 1


def test_history_window_uses_collection_date_instead_of_an_expired_as_of_boundary():
    session = Session([Resp(body=json.dumps(response(end="2026-10-16")).encode())])
    http = HttpClient(None, "synthetic", session=session)
    fetch_history(http, "SYNTHETIC", "IJH", date(2026, 10, 16), collected_on=date(2026, 10, 17))
    assert session.calls[0][0].endswith("/IJH/range/1/day/2024-10-18/2026-10-16")
    with pytest.raises(FetchError, match="outside the Basic history window"):
        fetch_history(http, "SYNTHETIC", "IJH", date(2020, 1, 1), collected_on=date(2026, 10, 17))
    assert len(session.calls) == 1


def test_private_request_pacing_matches_registered_basic_limit():
    clock = [0.0]
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    http = HttpClient(None, "synthetic", session=Session([Resp()] * 6), clock=lambda: clock[0], sleep=sleep)
    for i in range(6):
        http.get_json(f"https://api.massive.com/test/{i}")
    assert waits == [13.0] * 5 and clock[0] == 65
    assert http.limits["massive"].budget == spec.PRIVATE_HISTORY_RULE["limits"]["attempts"]
    assert http.limits["massive"].min_interval == spec.PRIVATE_HISTORY_RULE["limits"]["min_interval_seconds"]


def test_json_entitlement_error_stops_network_and_invalid_ticker_never_requests():
    session = Session([Resp(body=b'{"status":"NOT_AUTHORIZED"}')])
    http = HttpClient(None, "synthetic", session=session)
    provider = Providers(http, massive_key="SYNTHETIC", history_as_of=AS_OF)
    with pytest.raises(FetchError, match="unsupported"):
        provider.history("../escape?apiKey=bad")
    assert session.calls == []
    for ticker in ("IJH", "SPY"):
        with pytest.raises(ProviderUnavailable):
            provider.history(ticker)
    assert len(session.calls) == 1


def test_env_file_is_explicit_and_only_loads_dashboard_names(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("UNRELATED_ENV", raising=False)
    env = tmp_path / ".env"
    env.write_text("MASSIVE_API_KEY=SYNTHETIC_ENV_SECRET\nUNRELATED_ENV=unrelated\n")
    data = tmp_path / "data"
    assert main(["--env-file", str(env), "verify", "--data", str(data)]) == 0
    import os

    assert os.environ["MASSIVE_API_KEY"] == "SYNTHETIC_ENV_SECRET"
    assert "UNRELATED_ENV" not in os.environ
    assert "SYNTHETIC_ENV_SECRET" not in capsys.readouterr().out


def test_private_run_requires_credentials_before_requesting_data(tmp_path, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "synthetic research test@example.com")
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="MASSIVE_API_KEY must"):
        main(["run", "--private", "--data", str(tmp_path / "data")])


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_access_billing_and_quota_failures_stop_all_further_provider_requests(status):
    session = Session([Resp(status, b"do not echo provider response")])
    http = HttpClient(None, "synthetic", session=session)
    for ticker in ("IJH", "SPY"):
        with pytest.raises(ProviderUnavailable, match="stopped"):
            http.get_json(f"https://api.massive.com/{ticker}")
    assert len(session.calls) == 1
    assert http.limits["massive"].min_interval == 13


def test_private_data_never_enters_public_build_even_when_it_is_an_older_week(tmp_path):
    store = Store(tmp_path / "data")
    store.write_snapshot({"as_of": "2026-10-02", "publication": "private"})
    store.write_snapshot({"as_of": "2026-10-09"})
    out = tmp_path / "site"
    out.mkdir()
    (out / "index.html").write_text("last good site")
    with pytest.raises(ValueError, match="cannot be published"):
        build_site(store.root, out)
    assert (out / "index.html").read_text() == "last good site"
    with pytest.raises(ValueError, match="cannot be published"):
        main(["verify", "--data", str(store.root)])


def test_marker_blocks_failed_runs_and_local_modes_are_prohibited_in_actions(tmp_path, monkeypatch):
    root = tmp_path / "private"
    mark_private(root)
    assert (root / MARKER).exists()
    with pytest.raises(ValueError, match="cannot be published"):
        check_publication(Store(root))
    with pytest.raises(ValueError, match="research-data"):
        mark_private(tmp_path / "research-data")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    for action in (
        lambda: mark_private(root),
        lambda: check_publication(Store(root), True),
        lambda: Providers(HttpClient(None, "test"), massive_key="SYNTHETIC", history_as_of=AS_OF),
    ):
        with pytest.raises(ValueError, match="local only"):
            action()


def test_private_pipeline_has_source_and_no_fabricated_long_returns_and_renders_locally(tmp_path):
    provider = FakeProviders()
    provider.history_provider = "massive"
    benchmarks(provider)
    for i in range(12):
        provider.add(f"S{i:02d}", 100 + i, growth=0.1 + 0.04 * i, shares=5e8, n=500)
    for bars in provider.bars.values():
        bars.attrs.update(price_source=SOURCE, publication="private")
    snapshot = run(
        provider,
        AS_OF,
        options_enabled=False,
        tradability=Tradability.all_tradable(list(provider.listed), "2026-10-08"),
    )
    assert snapshot["publication"] == "private" and snapshot["price_history"]["provider"] == "massive"
    assert snapshot["universe"]["sp500_price_coverage"] == 1
    assert all(b["source"] == SOURCE for b in snapshot["benchmarks"].values())
    assert all(row["price_source"] == SOURCE for row in snapshot["leaders_2030_inputs"])
    candidate = snapshot["bands"]["large"]["candidates"][0]
    assert candidate["sources"]["price"] == SOURCE
    assert candidate["history"]["returns"]["3y"] is None
    store = Store(tmp_path / "data")
    store.write_snapshot(snapshot)
    assert main(["verify", "--private", "--data", str(store.root)]) == 0
    out = tmp_path / "site"
    build_site(store.root, out, private=True)
    assert check_links(out) == []
    assert json.loads((out / "build.json").read_text())["publication"] == "private"
    for page in out.rglob("*.html"):
        assert "Private personal research" in page.read_text(encoding="utf-8")
