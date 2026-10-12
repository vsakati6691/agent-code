"""Strategy A (S&P 500 scanner), Strategy B (desk), new risk limits, and the daily cycle.

All external services are mocked with saved-payload fixtures."""
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from agent_trading.data.cache import write_cache
from agent_trading.data.snapshots import (
    SnapshotDataError,
    high_impact_events,
    import_snapshot_files,
    load_snapshot,
    parse_fundamentals,
    parse_quotes,
)
from agent_trading.data.universe import UniverseError, coverage, import_universe, parse_index_fund, universe_problems
from agent_trading.journal import Journal
from agent_trading.paper import Intent, PaperBroker
from agent_trading.risk import Holding, PortfolioState, RiskEngine, trading_status
from agent_trading.strategies.desk import Position, leveraged_blockers, qqq_regime, run_desk
from agent_trading.strategies.scanner import run_scan, score

from .conftest import make_bars

AS_OF = date(2026, 10, 12)


def small_settings(settings, n_min=3):
    return replace(settings, scanner=replace(settings.scanner, min_constituents=n_min, max_constituents=600,
                                             min_avg_dollar_volume=1e6))


def fund_payload(tickers, as_of="2026-10-08"):
    holdings = [{"ticker": t, "name": t, "weight": 1.0, "asset_class": "equity"} for t in tickers]
    holdings += [{"ticker": None, "name": "US DOLLAR", "weight": 0.2, "asset_class": "other"},
                 {"ticker": "2602335D", "name": "TPG INC", "weight": 0.0, "asset_class": "equity"}]
    return {"ticker": "SPY", "fund": {"name": "SPDR S&P 500", "as_of": as_of, "filing_date": as_of}, "holdings": holdings}


# ---------------------------------------------------------------- universe

def test_universe_parsing_filters_non_tickers(settings):
    u = parse_index_fund(fund_payload(["AAA", "BRK.B", "CCC"]), small_settings(settings))
    assert u.tickers == ["AAA", "BRK.B", "CCC"]
    assert any("US DOLLAR" in e for e in u.excluded) and any("2602335D" in e for e in u.excluded)


def test_universe_count_out_of_range_rejected(settings):
    with pytest.raises(UniverseError, match="expected"):
        parse_index_fund(fund_payload(["AAA", "BBB"]), settings)  # default expects ~500


def test_stale_universe_flagged(settings, tmp_path):
    s = small_settings(settings)
    p = tmp_path / "f.json"
    p.write_text(json.dumps(fund_payload(["AAA", "BBB", "CCC"], "2026-08-01")))
    u = import_universe(s, p)
    assert universe_problems(u, s, AS_OF) and "old" in universe_problems(u, s, AS_OF)[0]
    assert universe_problems(None, s, AS_OF) == ["no S&P 500 constituent list imported"]


def test_coverage_reports_missing_constituents(settings):
    u = parse_index_fund(fund_payload(["AAA", "BBB", "CCC", "DDD"]), small_settings(settings))
    c = coverage(u, ["AAA", "BBB", "CCC"], {"DDD": "DDD: stale"})
    assert c["scanned"] == 3 and c["expected"] == 4 and c["missing"] == {"DDD": "DDD: stale"}


# ---------------------------------------------------------------- snapshots

SCAN = {"data": {"result": {"total_items": 2, "results": [
    {"ticker": "AAA", "columns": {"Market cap": "1e11", "Sector": "311", "Forward P/E": "20", "Operating margin": "0.3",
                                  "Return on equity": "0.25", "Earnings date": "2.0261103e+07"}},
    {"ticker": "BBB", "columns": {"Market cap": "5e10", "Sector": "311", "Forward P/E": "", "Operating margin": "",
                                  "Return on equity": "0.1", "Earnings date": ""}}]}}}

QUOTES = {"data": {"results": [{"quote": {"symbol": "AAA", "last_trade_price": "100", "venue_last_trade_time": "2026-10-09T19:59:59Z",
                                          "last_non_reg_trade_price": "101", "venue_last_non_reg_trade_time": "2026-10-12T13:00:00Z",
                                          "bid_price": "100.9", "ask_price": "101.1", "adjusted_previous_close": "100", "state": "active"}}]}}


def test_fundamentals_and_quotes_parsing():
    f = parse_fundamentals([SCAN]).set_index("ticker")
    assert f.loc["AAA", "earnings_date"] == "2026-11-03" and f.loc["AAA", "forward_pe"] == 20
    assert pd.isna(f.loc["BBB", "forward_pe"]) and pd.isna(f.loc["BBB", "earnings_date"])
    q = parse_quotes(QUOTES).iloc[0]
    assert q["price"] == 101 and q["session"] == "extended"
    assert q["spread_pct"] == pytest.approx(0.2 / 101)


def test_malformed_payloads_rejected(settings, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"error": "rate limit"}))
    for kind in ("fundamentals", "quotes", "econ"):
        with pytest.raises(SnapshotDataError):
            import_snapshot_files(settings, kind, [p])


def test_econ_calendar_staleness_fails_safe(settings, tmp_path):
    p = tmp_path / "econ.json"
    p.write_text(json.dumps({"events": [{"date": "2026-10-14T12:30:00Z", "country": "US", "name": "CPI", "impact": "HIGH"}]}))
    old = datetime(2026, 10, 1, tzinfo=timezone.utc)
    import_snapshot_files(settings, "econ", [p], fetched_at=old)
    snap = load_snapshot(settings, "econ")
    assert high_impact_events(snap, date(2026, 10, 13), 1, now=datetime(2026, 10, 13, tzinfo=timezone.utc)) is None
    fresh = high_impact_events(snap, date(2026, 10, 13), 1, now=old + timedelta(hours=1))
    assert list(fresh["name"]) == ["CPI"]


# ---------------------------------------------------------------- risk limits

def test_exclusive_group_and_symbol_risk(settings):
    engine = RiskEngine(settings)
    state = PortfolioState(1000, 900, (Holding("TQQQ", 0.2, 80, 70),))
    assert "cannot hold SQQQ together with TQQQ" in engine.evaluate_entry("SQQQ", 33, 30, state).reason
    d = engine.evaluate_entry("TQQQ", 80, 70, PortfolioState(1000, 1000))
    assert d.approved and d.risk_amount <= 2.5 + 1e-9  # $2.50, tighter than the normal $5


def test_trading_status_daily_loss_and_drawdown(settings):
    cfg = settings.risk
    hist = pd.Series([1000.0, 1010.0], index=pd.to_datetime(["2026-10-08", "2026-10-09"]))
    assert trading_status(hist, 1005, cfg, pd.Timestamp("2026-10-12")).new_entries_allowed
    day = trading_status(hist, 999.0, cfg, pd.Timestamp("2026-10-12"))
    assert not day.new_entries_allowed and "daily loss" in day.reason
    hist2 = pd.Series([1000.0, 1100.0, 1030.0], index=pd.to_datetime(["2026-10-07", "2026-10-08", "2026-10-09"]))
    dd = trading_status(hist2, 1010.0, cfg, pd.Timestamp("2026-10-12"))
    assert not dd.new_entries_allowed and "SHUTDOWN" in dd.reason
    assert not trading_status(hist, float("nan"), cfg).new_entries_allowed


# ---------------------------------------------------------------- Strategy A

def universe_bars(n_up=4, n_flat=3, n_down=3):
    """Letter-only tickers (real ones never contain digits): UPA.., FLA.., DNA.."""
    bars = {}
    for i in range(n_up):
        bars[f"UP{chr(65 + i)}"] = make_bars(n=320, seed=i, drift=0.0015, vol=0.012, volume=3e6, start=50 + i)
    for i in range(n_flat):
        bars[f"FL{chr(65 + i)}"] = make_bars(n=320, seed=50 + i, drift=0.0, vol=0.01, volume=3e6, start=60)
    for i in range(n_down):
        bars[f"DN{chr(65 + i)}"] = make_bars(n=320, seed=90 + i, drift=-0.0015, vol=0.012, volume=3e6, start=80)
    return bars


def test_scanner_ranks_and_reweights_missing_factors(settings):
    bars = universe_bars()
    spy = make_bars(n=320, seed=7, drift=0.0004, vol=0.008, volume=8e7, start=400)
    res = run_scan(bars, settings, AS_OF, bench=spy)
    t = res.table
    assert len(t) == 10 and len(res.research) == 10
    assert t["composite"].notna().all()
    assert (t["missing_factors"].str.contains("quality")).all()  # no fundamentals supplied
    best = t.index[0]
    assert t.loc[best, "price_strength"] >= t["price_strength"].median()
    assert all(s.setup != "bullish" for s in res.research if s.ticker.startswith("DN"))


def test_scanner_unknown_earnings_blocks_actionable(settings):
    bars = universe_bars()
    spy = make_bars(n=320, seed=7, drift=0.0004, vol=0.008, start=400)
    res = run_scan(bars, settings, AS_OF, bench=spy)
    assert res.actionable == []
    assert any("earnings date unverified" in " ".join(r) for r in res.rejected.values())


def test_scanner_actionable_respects_filters(settings):
    bars = universe_bars()
    spy = make_bars(n=320, seed=7, drift=0.0004, vol=0.008, start=400)
    fund = pd.DataFrame([{"ticker": t, "operating_margin": 0.2 + i * 0.01, "roe": 0.2, "forward_pe": 20 + i,
                          "sector_code": "311", "earnings_date": "2026-12-15"} for i, t in enumerate(bars)])
    quotes = pd.DataFrame([{"ticker": "UPA", "spread_pct": 0.01}])
    res = run_scan(bars, settings, AS_OF, fund, quotes, bench=spy)
    assert len(res.actionable) <= settings.scanner.top_actionable
    for s in res.actionable:
        assert s.setup == "bullish" and s.stop < s.entry_ref < s.target
        assert s.ticker != "UPA"  # UPA's 1% spread exceeds the 0.25% limit
    if "UPA" in res.rejected:
        assert any("spread" in r for r in res.rejected["UPA"])


def test_price_strength_is_a_single_factor(settings):
    t = pd.DataFrame({"mom_12_1": [0.1, 0.2], "rs_63": [0.0, 0.1], "dist_200": [0.05, 0.1], "updown_volume": [1, 1],
                      "vol_63": [0.2, 0.2], "uptrend": [True, True], "downtrend": [False, False]}, index=["A", "B"])
    out = score(t, None, settings.scanner.weights)
    assert set(["price_strength", "volume", "quality", "valuation", "risk"]) <= set(out.columns)
    assert out.loc["B", "price_strength"] == 1.0  # three correlated inputs averaged into one factor


# ---------------------------------------------------------------- Strategy B

def desk_bars(qqq_drift=0.002):
    return {
        "QQQ": make_bars(n=320, seed=3, drift=qqq_drift, vol=0.006, volume=5e7, start=400),
        "TQQQ": make_bars(n=320, seed=4, drift=3 * qqq_drift, vol=0.018, volume=5e7, start=40),
        "SQQQ": make_bars(n=320, seed=5, drift=-3 * qqq_drift, vol=0.018, volume=5e7, start=40),
        "NVDA": make_bars(n=320, seed=6, drift=0.002, vol=0.015, volume=5e7, start=100),
        "SMH": make_bars(n=320, seed=8, drift=0.001, vol=0.01, volume=5e6, start=200),
        "IBIT": make_bars(n=320, seed=9, drift=0.001, vol=0.02, volume=5e7, start=40),
    }


def no_earnings(sym):
    return None, True


def by_symbol(decisions):
    return {d.symbol: d for d in decisions}


def test_desk_uptrend_buys_tqqq_not_sqqq(settings):
    reg, ds = run_desk(desk_bars(), settings, AS_OF, {}, pd.DataFrame(columns=["name", "date"]), no_earnings)
    d = by_symbol(ds)
    assert reg["trend"] == "up"
    assert d["TQQQ"].action in ("BUY", "WAIT")  # WAIT only if QQQ dipped below its 20-day SMA
    assert d["SQQQ"].action == "NO TRADE"


def test_desk_blackout_and_missing_calendar_block_leveraged(settings):
    _, ds = run_desk(desk_bars(), settings, AS_OF, {}, None, no_earnings)
    assert by_symbol(ds)["TQQQ"].action in ("WAIT", "NO TRADE")
    assert any("unavailable" in r for r in by_symbol(ds)["TQQQ"].reasons) or by_symbol(ds)["TQQQ"].action == "NO TRADE"
    blockers = leveraged_blockers(pd.DataFrame([{"name": "CPI", "date": AS_OF}]), {"NVDA": AS_OF}, AS_OF, 1)
    assert len(blockers) == 2


def test_blackout_measured_from_fill_day(settings, tmp_path):
    """Signal Monday, fill Tuesday, CPI Wednesday: inside the 1-day blackout."""
    from agent_trading.strategies.desk import next_session

    assert next_session(date(2026, 10, 12)) == date(2026, 10, 13)
    assert next_session(date(2026, 10, 9)) == date(2026, 10, 12)  # Friday -> Monday
    p = tmp_path / "econ.json"
    p.write_text(json.dumps({"events": [{"date": "2026-10-14T12:30:00Z", "country": "US", "name": "CPI", "impact": "HIGH"}]}))
    import_snapshot_files(settings, "econ", [p])
    ev = high_impact_events(load_snapshot(settings, "econ"), next_session(AS_OF), settings.desk.event_blackout_days)
    _, ds = run_desk(desk_bars(), settings, AS_OF, {}, ev, no_earnings)
    t = by_symbol(ds)["TQQQ"]
    assert t.action != "BUY" and any("CPI" in r for r in t.reasons)


def test_desk_downtrend_considers_sqqq(settings):
    reg, ds = run_desk(desk_bars(qqq_drift=-0.002), settings, AS_OF, {}, pd.DataFrame(columns=["name", "date"]), no_earnings)
    assert reg["trend"] == "down"
    assert by_symbol(ds)["TQQQ"].action == "NO TRADE"
    assert by_symbol(ds)["SQQQ"].action in ("BUY", "WAIT", "NO TRADE")


def test_desk_time_exit_and_never_both(settings):
    pos = {"TQQQ": Position(0.2, 40, 30, date(2026, 10, 1))}  # 7 business days before AS_OF
    _, ds = run_desk(desk_bars(), settings, AS_OF, pos, pd.DataFrame(columns=["name", "date"]), no_earnings)
    d = by_symbol(ds)
    assert d["TQQQ"].action == "SELL/REDUCE" and "limit" in d["TQQQ"].reasons[0]
    assert d["SQQQ"].action == "NO TRADE"


def test_desk_nvda_earnings_blackout_and_unknown(settings):
    soon = lambda s: (AS_OF + timedelta(days=2), True) if s == "NVDA" else (None, True)
    unknown = lambda s: (None, False)
    _, ds = run_desk(desk_bars(), settings, AS_OF, {}, pd.DataFrame(columns=["name", "date"]), soon)
    assert by_symbol(ds)["NVDA"].action in ("WAIT", "NO TRADE")
    _, ds2 = run_desk(desk_bars(), settings, AS_OF, {}, pd.DataFrame(columns=["name", "date"]), unknown)
    nv = by_symbol(ds2)["NVDA"]
    assert nv.action in ("WAIT", "NO TRADE")
    if nv.action == "WAIT":
        assert any("unverified" in r for r in nv.reasons)


def test_desk_missing_qqq_data_no_trade(settings):
    b = desk_bars()
    del b["QQQ"]
    _, ds = run_desk(b, settings, AS_OF, {}, None, no_earnings)
    assert by_symbol(ds)["TQQQ"].action == "NO TRADE" and by_symbol(ds)["SQQQ"].action == "NO TRADE"


# ---------------------------------------------------------------- paper broker with intents

@pytest.fixture
def broker(settings, tmp_path):
    return PaperBroker(settings, Journal(tmp_path / "p.db"))


def test_intents_dedupe_no_short_and_exclusive(settings, broker):
    bars = desk_bars()
    d = bars["TQQQ"].index[-2].date()
    b1 = {s: df.loc[:str(d)] for s, df in bars.items()}
    close = float(b1["TQQQ"]["close"].iloc[-1])
    intents = [Intent("TQQQ", "buy", close, close * 0.9, "B-desk", "test", 1),
               Intent("TQQQ", "buy", close, close * 0.9, "B-desk", "dup", 1),
               Intent("SQQQ", "buy", 30, 27, "B-desk", "other side", 0.5),
               Intent("NVDA", "sell", 100, None, "B-desk", "no position")]
    r = broker.run(b1, None, None, d, intents=intents)
    pending = broker.orders("pending")
    assert list(pending["symbol"]) == ["TQQQ"]
    reasons = {p.symbol + str(i): p.reason for i, p in enumerate(r.new_orders)}
    assert any("duplicate" in v for v in reasons.values())
    assert any("cannot hold SQQQ" in v for v in reasons.values())
    assert any("short selling is not allowed" in w for w in r.warnings)
    assert pending.iloc[0]["strategy"] == "B-desk"


def test_fill_reduced_when_open_gaps_up(settings, broker):
    """'Partial fill': a higher open shrinks the paper size, never grows it."""
    bars = desk_bars()
    days = bars["NVDA"].index
    d1 = days[-2]
    b1 = {s: df.loc[:d1] for s, df in bars.items()}
    close = float(b1["NVDA"]["close"].iloc[-1])
    broker.run(b1, None, None, d1.date(), intents=[Intent("NVDA", "buy", close, close - 2, "B-desk", "t", 1)])
    order = broker.orders("pending").iloc[0]
    gapped = {s: df.copy() for s, df in bars.items()}
    g = gapped["NVDA"]
    g.loc[days[-1], ["open", "high"]] = [close * 1.01, max(close * 1.02, g.loc[days[-1], "high"])]
    broker.run(gapped, None, None, days[-1].date(), intents=[])
    t = broker.journal.open_trades().iloc[0]
    assert t["quantity"] <= order["quantity"] and t["strategy"] == "B-desk"


def test_time_exit_queued_for_leveraged(settings, broker):
    bars = desk_bars()
    broker.journal.open_trade("TQQQ", 0.1, 40, 30, date(2026, 9, 28), strategy="B-desk")
    broker.run(bars, None, None, bars["TQQQ"].index[-1].date(), intents=[])
    sells = broker.orders("pending")
    assert (sells["side"] == "sell").any() and "max holding" in sells.iloc[0]["reason"]


def test_loss_limit_blocks_new_entries(settings, broker):
    bars = desk_bars()
    d = bars["NVDA"].index[-1].date()
    broker._record_equity(d - timedelta(days=1), 1100.0)  # pretend yesterday's equity was $1,100
    close = float(bars["NVDA"]["close"].iloc[-1])
    r = broker.run(bars, None, None, d, intents=[Intent("NVDA", "buy", close, close - 2, "B-desk", "t")])
    assert broker.orders("pending").empty
    assert any("blocked" in w for w in r.warnings)


# ---------------------------------------------------------------- Strategy B historical backtest

def test_desk_backtest_respects_leveraged_rules(settings):
    from agent_trading.backtest.desk_backtest import run_desk_backtest

    bars = desk_bars()
    res = run_desk_backtest(bars, settings, ["TQQQ", "SQQQ"])
    for t in res.trades:
        if t.symbol in ("TQQQ", "SQQQ") and t.exit_reason != "end of test":
            held = int(np.busday_count(t.entry_date, t.exit_date))
            assert held <= settings.risk.max_holding_days[t.symbol] + 1  # exit queued at the limit, filled next open
        assert t.quantity * (t.entry_price - t.stop) * (1 + settings.risk.stop_risk_buffer) <= 2.5 * 1.1
    # never both at once
    spans = [(t.symbol, t.entry_date, t.exit_date) for t in res.trades]
    for s1, a1, b1 in spans:
        for s2, a2, b2 in spans:
            if s1 != s2:
                assert b1 <= a2 or b2 <= a1


# ---------------------------------------------------------------- end-to-end daily cycle (all inputs mocked)

def test_daily_cycle_end_to_end(settings, tmp_path):
    from agent_trading.daily import run_daily

    s = small_settings(settings)
    cache = s.resolve(s.data.cache_dir)
    end = "2026-10-09"
    uni = universe_bars()
    for t, df in uni.items():
        write_cache(cache, t, df)
    for t, df in desk_bars().items():
        write_cache(cache, t, df)
    write_cache(cache, "SPY", make_bars(n=320, seed=7, drift=0.0004, vol=0.008, volume=8e7, start=400, end=end))
    fp = tmp_path / "spy.json"
    fp.write_text(json.dumps(fund_payload([*uni, "MISSX"])))
    import_universe(s, fp)
    ep = tmp_path / "econ.json"
    ep.write_text(json.dumps({"events": [{"date": "2026-10-14T12:30:00Z", "country": "US", "name": "CPI", "impact": "HIGH"}]}))
    import_snapshot_files(s, "econ", [ep])

    text, ctx = run_daily(s, AS_OF)
    assert ctx.coverage["expected"] == 11 and ctx.coverage["scanned"] == 10
    assert "MISSX" in ctx.coverage["missing"]
    for section in ["Section A: S&P 500 scanner", "Section B: Focused desk", "Section C: Account and portfolio risk",
                    "Section D: Actions", "Orders awaiting your authorization:** none"]:
        assert section in text
    assert "incomplete scan" in text  # 10/11 < 95%
    assert {d.symbol for d in ctx.desk} == {"TQQQ", "SQQQ", "IBIT", "NVDA"}
    assert "CPI" in text
