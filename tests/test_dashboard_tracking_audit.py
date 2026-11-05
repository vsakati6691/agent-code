"""Regression tests for the 2026-11-04 tracking and coverage audit (findings from the 2026-11-03 snapshot).

1. Every 2026-11-03 pick was reported "no close on the snapshot date": ranking took the as-of bar from the
   close-verified end-of-session quote because the Cboe history file lagged, while tracking read the raw file.
2. Endpoints must be exact NYSE sessions for stocks and benchmarks; a missing bar never moves them.
3. Partial baskets and missing benchmarks stay out of completed-basket averages; versions are never pooled.
4. A skipped rerun reports "skipped", not "ok", and the snapshot keeps its own completeness.
5. Each list shows its screening funnel and the tradability gate's share.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime

import pandas as pd
import pytest

from agent_trading.dashboard import tracking
from agent_trading.dashboard.__main__ import main as cli
from agent_trading.dashboard.__main__ import update_tracking
from agent_trading.dashboard.provider_parsers import Quote
from agent_trading.dashboard.site_exclusions import excluded_summary, funnel
from agent_trading.dashboard.site_layout import freshness_banner, run_outcome, run_status_text
from agent_trading.dashboard.store import Store
from agent_trading.market_calendar import is_trading_day
from tests.conftest import make_bars
from tests.dashboard_fixtures import FakeHttp


def sessions(start: str, end: str) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([d for d in pd.bdate_range(start, end) if is_trading_day(d.date())])


def series(idx: pd.DatetimeIndex, growth: float) -> pd.Series:
    return pd.Series([100.0 * (1 + growth) ** i for i in range(len(idx))], index=idx)


IDX = sessions("2026-09-01", "2027-01-29")


def snap(as_of: str, tickers: list[str], version: str = "v1", band: str = "large") -> dict:
    return {"as_of": as_of, "spec_version": version, "bands": {band: {"candidates": [{"ticker": t} for t in tickers]}}}


# --- exact sessions and outcome states ------------------------------------------------------------------------------


def test_new_basket_is_pending_even_without_its_entry_close():
    """2026-11-03 reproduction: the history file had no 11-03 bar yet. Before the fix every horizon of the new
    basket was 'unavailable: no close on the snapshot date'; a horizon that has not matured is pending."""
    lagging = {t: series(IDX[IDX <= "2026-11-02"], 0.001) for t in ("AAA", "BBB", "SPY")}
    out = tracking.track([snap("2026-11-03", ["AAA", "BBB"])], lagging, date(2026, 11, 3))
    row = out["by_snapshot"][0]
    for h, bars in tracking.spec.TRACK_HORIZONS.items():
        x = row["horizons"][h]
        assert x["status"] == "pending" and x["unavailable"] == []
        assert x["exit_session"] == tracking.session_after(date(2026, 11, 3), bars).isoformat()
    assert tracking.session_after(date(2026, 11, 3), 21) == date(2026, 12, 3)  # Thanksgiving is not a session


def test_pending_horizon_until_the_endpoint_session_and_its_close():
    prices = {t: series(IDX, 0.001) for t in ("AAA", "SPY")}
    start = date(2026, 10, 2)
    end = tracking.session_after(start, 21)
    before = {t: s[s.index < pd.Timestamp(end)] for t, s in prices.items()}
    # the endpoint session has not passed: pending
    x = tracking.track([snap("2026-10-02", ["AAA"])], before, end - pd.Timedelta(days=1))["by_snapshot"][0]
    assert x["horizons"]["1m"]["status"] == "pending"
    # on the endpoint session, before the provider publishes its close: still pending, never 'missing'
    x = tracking.track([snap("2026-10-02", ["AAA"])], before, end)["by_snapshot"][0]
    assert x["horizons"]["1m"]["status"] == "pending" and "not yet published" in x["horizons"]["1m"]["note"]
    # once the close exists the basket is complete and uses exactly that session
    x = tracking.track([snap("2026-10-02", ["AAA"])], prices, end)["by_snapshot"][0]["horizons"]["1m"]
    assert x["status"] == "ok" and x["exit_session"] == end.isoformat() and x["measured"] == x["n"] == 1
    a = prices["AAA"]
    assert x["gross"] == pytest.approx(a.loc[str(end)] / a.loc["2026-10-02"] - 1)


def test_missing_endpoint_session_is_never_bridged_to_a_later_close():
    prices = {t: series(IDX, g) for t, g in (("AAA", 0.001), ("BBB", 0.002), ("SPY", 0.0005))}
    start = date(2026, 10, 2)
    end = tracking.session_after(start, 21)
    prices["BBB"] = prices["BBB"].drop(pd.Timestamp(end))  # the vendor skipped exactly the endpoint session
    out = tracking.track([snap("2026-10-02", ["AAA", "BBB"])], prices, date(2026, 12, 31))
    x = out["by_snapshot"][0]["horizons"]["1m"]
    assert x["status"] == "incomplete" and x["measured"] == 1 and x["n"] == 2 and x["missing_exit"] == 1
    assert x["unavailable"] == [{"ticker": "BBB", "status": f"missing exit price: no close on the {end} session"}]
    # the measured stock and the benchmark use the same two sessions
    spy = prices["SPY"]
    assert x["benchmark"] == pytest.approx(spy.loc[str(end)] / spy.loc["2026-10-02"] - 1)
    summ = out["by_version"][0]["summary"]["large"]["1m"]
    assert summ["snapshots_measured"] == 0 and summ["incomplete"] == 1 and summ["mean_excess_net"] is None


def test_missing_entry_price_is_distinguished_from_missing_exit():
    prices = {t: series(IDX, 0.001) for t in ("AAA", "CCC", "SPY")}
    prices["CCC"] = prices["CCC"][prices["CCC"].index > "2026-10-02"]  # listed after the snapshot session
    x = tracking.track([snap("2026-10-02", ["AAA", "CCC"])], prices, date(2026, 12, 31))["by_snapshot"][0]
    h = x["horizons"]["1m"]
    assert h["status"] == "incomplete" and h["missing_entry"] == 1 and h["missing_exit"] == 0
    assert h["unavailable"][0]["status"] == "missing entry price: no close on 2026-10-02"


def test_incomplete_basket_is_left_out_of_completed_averages():
    full = {t: series(IDX, g) for t, g in (("AAA", 0.002), ("BBB", 0.001), ("SPY", 0.0))}
    gone = dict(full, BBB=full["BBB"][full["BBB"].index <= "2026-10-20"])  # prices stop: possible delisting
    snaps = [snap("2026-10-02", ["AAA", "BBB"]), snap("2026-10-09", ["AAA"])]
    out = tracking.track(snaps, gone, date(2026, 12, 31))
    first, second = (r["horizons"]["1m"] for r in out["by_snapshot"])
    assert first["status"] == "incomplete" and "possible delisting" in first["unavailable"][0]["status"]
    assert first["note"] == "not counted in completed-basket averages"
    assert second["status"] == "ok"
    summ = out["by_version"][0]["summary"]["large"]["1m"]
    assert summ["snapshots_measured"] == 1 and summ["incomplete"] == 1
    assert summ["mean_excess_net"] == pytest.approx(second["excess_net"])  # the partial basket is not averaged in


def test_missing_benchmark_is_reported_and_kept_out_of_benchmark_statistics():
    prices = {"AAA": series(IDX, 0.001)}  # no SPY series at all
    out = tracking.track([snap("2026-10-02", ["AAA"])], prices, date(2026, 12, 31))
    x = out["by_snapshot"][0]["horizons"]["1m"]
    assert x["status"] == "benchmark unavailable" and x["measured"] == 1
    assert x["benchmark"] is None and x["excess_net"] is None
    assert x["benchmark_status"].startswith("missing entry price")
    assert out["by_version"][0]["summary"]["large"]["1m"]["snapshots_measured"] == 0


def test_two_spec_versions_keep_returns_turnover_and_chains_apart():
    prices = {t: series(IDX, g) for t, g in (("AAA", 0.002), ("BBB", 0.001), ("CCC", 0.003), ("SPY", 0.0))}
    snaps = [
        snap("2026-10-02", ["AAA", "BBB"], "v1"),
        snap("2026-10-09", ["AAA", "BBB"], "v1"),
        snap("2026-10-16", ["AAA", "CCC"], "v2"),
    ]
    out = tracking.track(snaps, prices, date(2026, 12, 31))
    v1, v2 = out["by_version"]
    assert (v1["spec_version"], v1["weekly_snapshots"], v2["spec_version"], v2["weekly_snapshots"]) == (
        "v1",
        2,
        "v2",
        1,
    )
    assert v1["summary"]["large"]["1m"]["snapshots_measured"] == 2
    assert v2["summary"]["large"]["1m"]["snapshots_measured"] == 1
    # turnover is measured only against the previous list of the same version: v2's first list has none
    assert v1["turnover"]["large"] == [{"as_of": "2026-10-09", "turnover": 0.0}]
    assert v2["turnover"] == {} and v2["summary"]["large"]["mean_weekly_turnover"] is None
    assert v1["weekly_chain"]["large"]["weeks"] == 2 and v2["weekly_chain"]["large"]["weeks"] == 1
    assert "never pooled" in out["evidence_note"]
    assert out["measurement_revision"]["date"] == "2026-11-04"


# --- tracking uses the ranking price path ---------------------------------------------------------------------------


class LaggingProviders:
    """The Cboe history file has not published the as-of close; the close-verified quote has (2026-11-03)."""

    history_provider = "cboe"

    def __init__(self, as_of: date, tickers: list[str]):
        self.as_of, self.http = as_of, FakeHttp()
        self.bars = {
            t: make_bars(n=400, start=100 + i, drift=0.0005, seed=40 + i, end=as_of.isoformat())
            for i, t in enumerate(tickers)
        }
        self.bars = {t: b[[is_trading_day(d.date()) for d in b.index]] for t, b in self.bars.items()}

    def history(self, symbol):
        return self.bars[symbol].iloc[:-1].copy()

    def quote(self, symbol):
        bar, prev = self.bars[symbol].iloc[-1], self.bars[symbol].iloc[-2]
        return Quote(
            symbol,
            float(bar["close"]),
            float(prev["close"]),
            datetime(self.as_of.year, self.as_of.month, self.as_of.day, 15, 59, 59),
            None,
            f"{self.as_of}T23:30:00+00:00",  # 18:30 ET: after the close
            open=float(bar["open"]),
            high=float(bar["high"]),
            low=float(bar["low"]),
            volume=float(bar["volume"]),
            change=float(bar["close"] - prev["close"]),
        )


def test_update_tracking_uses_the_validated_quote_bar_and_records_the_source(tmp_path):
    as_of = date(2026, 11, 3)
    st = Store(tmp_path)
    st.write_snapshot({**snap("2026-10-02", ["AAA", "BBB"], "2026-10-19.6"), "status": "partial"})
    st.write_snapshot({**snap("2026-11-03", ["AAA", "BBB"], "2026-10-19.6"), "status": "partial"})
    prov = LaggingProviders(as_of, ["AAA", "BBB", "SPY", "IJH", "IWM"])
    update_tracking(st, prov, as_of)
    out = st.read_json("tracking.json")
    new = next(r for r in out["by_snapshot"] if r["as_of"] == "2026-11-03")
    assert {x["status"] for x in new["horizons"].values()} == {"pending"}
    assert all(x["unavailable"] == [] for x in new["horizons"].values())
    old = next(r for r in out["by_snapshot"] if r["as_of"] == "2026-10-02")["horizons"]["1m"]
    assert old["status"] == "ok" and old["measured"] == old["n"] == 2  # matured 2026-11-02, exact session
    src = out["prices"]
    assert src["provider"] == "cboe" and src["rejected"] == {} and src["validated"] == src["symbols"] == 5
    assert sorted(src["as_of_bar_from_quote"]) == ["AAA", "BBB", "IJH", "IWM", "SPY"]


def test_update_tracking_reports_rejected_series_instead_of_dropping_them(tmp_path):
    as_of = date(2026, 11, 3)
    st = Store(tmp_path)
    st.write_snapshot({**snap("2026-10-02", ["AAA", "BAD"], "v"), "status": "ok"})
    prov = LaggingProviders(as_of, ["AAA", "BAD", "SPY", "IJH", "IWM"])
    bad = prov.bars["BAD"].copy()
    bad.iloc[-10, bad.columns.get_loc("close")] = bad.iloc[-10]["high"] * 1.5  # close far outside its range
    prov.bars["BAD"] = bad
    update_tracking(st, prov, as_of)
    out = st.read_json("tracking.json")
    assert "BAD" in out["prices"]["rejected"] and "close outside" in out["prices"]["rejected"]["BAD"]
    x = out["by_snapshot"][0]["horizons"]["1m"]
    assert x["status"] == "incomplete" and x["unavailable"][0]["ticker"] == "BAD"


# --- run status ------------------------------------------------------------------------------------------------------


def test_skipped_rerun_over_a_partial_snapshot_reports_skip_and_keeps_partial(tmp_path):
    st = Store(tmp_path)
    st.write_snapshot({**snap("2026-11-03", ["AAA"], "v"), "status": "partial"})
    before = (tmp_path / "snapshots" / "2026-11-03" / "snapshot.json").read_bytes()
    assert cli(["run", "--data", str(tmp_path), "--as-of", "2026-11-03"]) == 0
    status = st.status()
    assert status["status"] == "skipped" and status["snapshot_status"] == "partial"
    assert (tmp_path / "snapshots" / "2026-11-03" / "snapshot.json").read_bytes() == before
    stored = st.load("2026-11-03")
    text = run_status_text(stored, status)
    assert "data: partial" in text and "latest workflow run: skipped" in text and "ok" not in text
    banner = freshness_banner(stored, status, now=datetime(2026, 11, 4, 18, 0))
    assert "Partial data" in banner and "skipped" in banner


def test_legacy_status_written_by_a_skip_is_read_as_skipped():
    legacy = {
        "status": "ok",
        "message": "snapshot for 2026-11-03 already exists; kept unchanged",
        "as_of": "2026-11-03",
    }
    assert run_outcome(legacy) == "skipped"
    assert run_outcome({"status": "partial", "message": "weekly update completed with partial data"}) == "completed"
    assert run_outcome({"status": "failed", "message": "x"}) == "failed"
    assert "data: partial" in run_status_text({"as_of": "2026-11-03", "status": "partial"}, legacy)


# --- screening funnel ------------------------------------------------------------------------------------------------


def large_band() -> dict:
    """The stored 2026-11-03 large-cap counts: 490 evaluated, 48 ranked, 10 published, 323 unverified."""
    excluded = [{"ticker": f"T{i:03d}", "reason": "Robinhood tradability not yet verified"} for i in range(323)]
    excluded += [
        {"ticker": f"E{i:03d}", "reason": "too little evidence: 5 of 18 sub-metrics missing"} for i in range(104)
    ]
    excluded += [{"ticker": f"M{i:02d}", "reason": "market cap unavailable (no share count)"} for i in range(6)]
    cands = [
        {
            "rank": 1,
            "ticker": "FIX",
            "sector": "Industrials",
            "raw_composite": 90.43,
            "sector_penalty": 0.0,
            "composite": 90.43,
        },
        {
            "rank": 2,
            "ticker": "MU",
            "sector": "Information Technology",
            "raw_composite": 97.91,
            "sector_penalty": 18.0,
            "composite": 79.91,
        },
    ]
    return {"evaluated": 490, "ranked": 48, "max_results": 10, "candidates": cands, "excluded": excluded}


def test_funnel_shows_counts_and_the_tradability_gate_share():
    band = large_band()
    f = funnel(band)
    assert (f["evaluated"], f["ranked"], f["published"], f["tradability_excluded"], f["passed_other_rules"]) == (
        490,
        48,
        2,
        323,
        371,
    )
    html = excluded_summary("large", band)
    assert "490 evaluated → 48 ranked → 2 published (up to 10)" in html
    assert "323 of the 371 scored stocks that passed every other rule (87%)" in html
    assert re.search(r"Most common: .*\(323\)", html)
    # raw score, sector deduction and final score together explain why MU (highest raw) ranks second
    assert re.search(
        r"<td>MU</td><td>Information Technology</td><td class=\"num\">97.9</td>"
        r"<td class=\"num\">-18.0</td><td class=\"num\">79.9</td>",
        html,
    )


def test_funnel_degrades_for_older_snapshots_without_counts_or_breakdowns():
    band = large_band()
    for key in ("evaluated", "ranked"):
        band.pop(key)
    for c in band["candidates"]:
        c.pop("raw_composite")
    html = excluded_summary("large", band)
    assert "Screening funnel" not in html and "Why the order changed" not in html and "433 excluded" in html


# --- site built from stored data agrees with the records -------------------------------------------------------------


def test_site_history_and_lists_agree_with_tracking_and_snapshot_records(tmp_path):
    from agent_trading.dashboard.pipeline import run
    from agent_trading.dashboard.site import build_site
    from agent_trading.dashboard.tradability import Tradability
    from tests.dashboard_fixtures import AS_OF, FakeProviders, benchmarks

    p = FakeProviders()
    benchmarks(p)
    for i in range(12):
        p.add(f"S{i:02d}", 100 + i, growth=0.05 + 0.04 * i, drift=0.0004 + 0.0001 * i, shares=5e8)
    first = run(p, AS_OF, options_enabled=False, tradability=Tradability.all_tradable(list(p.listed), "2026-10-08"))
    second = copy.deepcopy(first)
    second["as_of"], second["spec_version"], second["status"] = "2026-10-16", "next-version", "partial"
    st = Store(tmp_path / "d")
    st.write_snapshot(first)
    st.write_snapshot(second)
    names = {c["ticker"] for s in (first, second) for b in s["bands"].values() for c in b["candidates"]}
    prices = {t: series(IDX, 0.0005 + 0.0001 * i) for i, t in enumerate(sorted(names | {"SPY", "IJH", "IWM"}))}
    gap = tracking.session_after(AS_OF, 21)
    dropped = first["bands"]["large"]["candidates"][-1]["ticker"]
    prices[dropped] = prices[dropped].drop(pd.Timestamp(gap))  # one first-version large-cap pick lacks its exit
    out = tracking.track([first, second], prices, date(2026, 11, 20))
    st.write_json("tracking.json", json.loads(json.dumps(out)))
    st.write_status(
        "skipped", "snapshot for 2026-10-16 already exists; kept unchanged", "2026-10-16", snapshot_status="partial"
    )
    build_site(tmp_path / "d", tmp_path / "s")
    history = (tmp_path / "s" / "history.html").read_text(encoding="utf-8")
    for v in out["by_version"]:
        assert f"Methodology {v['spec_version']}" in history
    large = next(r for r in out["by_snapshot"] if r["as_of"] == AS_OF.isoformat() and r["band"] == "large")
    one = large["horizons"]["1m"]
    assert one["status"] == "incomplete" and one["measured"] == one["n"] - 1
    assert f"{one['measured']} of {one['n']} picks measurable" in history and "1 missing exit price" in history
    s1 = out["by_version"][0]["summary"]["large"]["1m"]
    assert s1["snapshots_measured"] == 0 and s1["incomplete"] == 1
    assert "0 complete · 1 incomplete · 0 pending" in history
    from agent_trading.dashboard.fmt import pct

    done = next(r for r in out["by_snapshot"] if r["as_of"] == "2026-10-16" and r["band"] == "large")["horizons"]["1m"]
    assert done["status"] == "ok" and done["measured"] == done["n"]  # the gap is not on this basket's sessions
    assert f'{pct(done["net"], 1, True)}<div class="small muted">vs {pct(done["benchmark"], 1, True)}' in history
    assert f"{done['n']} of {done['n']} picks measurable" in history
    s2 = out["by_version"][1]["summary"]["large"]["1m"]
    assert s2["snapshots_measured"] == 1 and pct(s2["mean_excess_net"], 1, True) in history
    assert "Measurement revision 2026-11-04" in history
    growth = (tmp_path / "s" / "growth.html").read_text(encoding="utf-8")
    b = second["bands"]["large"]
    assert f"{b['evaluated']:,} evaluated → {b['ranked']:,} ranked → {len(b['candidates'])} published" in growth
    audit = (tmp_path / "s" / "audit.html").read_text(encoding="utf-8")
    assert "data: partial" in audit and "latest workflow run: skipped" in audit


def test_legacy_tracking_file_is_not_shown_as_results(tmp_path):
    from agent_trading.dashboard.site_history import tracking_section

    legacy = {"as_of": "2026-11-03", "by_snapshot": [], "summary": {}, "weekly_chain": {}, "evidence_note": "x"}
    html = tracking_section(legacy, ["2026-11-03"])
    assert "predates the 2026-11-04 measurement revision" in html and "Average excess" not in html
