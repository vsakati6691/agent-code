"""GTAA (Strategy C), point-in-time universe history, and the scanner backtest."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from agent_trading.backtest.portfolio import run_allocation
from agent_trading.backtest.scanner_backtest import run_signal_backtest, summarize
from agent_trading.data.universe import members_on, normalize_name, parse_index_fund
from agent_trading.strategies import gtaa

from .conftest import make_bars


def test_gtaa_signals_and_weights():
    up = make_bars(n=400, drift=0.002, vol=0.005, start=100)
    down = make_bars(n=400, drift=-0.002, vol=0.005, start=100, seed=3)
    hist = {"UP": up, "DOWN": down}
    day = up.index[-1]
    sig = gtaa.signals(hist, day, ["UP", "DOWN", "NONE"], 10)
    assert sig["UP"]["above"] is True and sig["DOWN"]["above"] is False
    assert sig["NONE"]["above"] is None and sig["NONE"]["reason"] == "no data"
    assert gtaa.weights(hist, day, ["UP", "DOWN"], 10) == {"UP": 0.5}


def test_gtaa_needs_enough_months():
    short = make_bars(n=120)
    s = gtaa.signals({"X": short}, short.index[-1], ["X"], 10)["X"]
    assert s["above"] is None and "months" in s["reason"]


def test_gtaa_uses_only_past_data():
    df = make_bars(n=400, drift=0.001)
    day = df.index[300]
    base = gtaa.signals({"X": df}, day, ["X"], 10)["X"]
    shocked = df.copy()
    shocked.iloc[301:, :4] *= 0.3
    assert gtaa.signals({"X": shocked}, day, ["X"], 10)["X"] == base


def test_rebalance_day_detection():
    days = list(pd.bdate_range("2026-09-24", "2026-10-02"))
    assert gtaa.is_rebalance_day(days, date(2026, 9, 30))
    assert not gtaa.is_rebalance_day(days, date(2026, 9, 29))
    assert gtaa.is_rebalance_day([], date(2026, 10, 30))  # Friday before a new month
    assert not gtaa.is_rebalance_day([], date(2026, 10, 12))


def test_gtaa_allocation_without_stops_reaches_target_weights(settings):
    from dataclasses import replace

    up = {f"A{c}": make_bars(n=400, drift=0.001, vol=0.006, seed=i, start=50) for i, c in enumerate("BC")}
    relaxed = replace(
        settings,
        risk=replace(
            settings.risk,
            risk_per_trade_pct=1.0,
            max_open_risk_pct=1.0,
            max_correlated_risk_pct=1.0,
            max_position_pct=0.5 + 1e-9,
            stop_risk_buffer=0.0,
        ),
    )
    res = run_allocation(up, relaxed, lambda d, h: gtaa.weights(h, d, list(up), 10), use_stops=False)
    assert res.trades and max(t.quantity * t.entry_price for t in res.trades) > 300  # ~1/2 of equity each
    assert all(t.exit_reason != "stop" for t in res.trades)


def test_name_resolution_for_filings_without_tickers(settings):
    from dataclasses import replace

    s = replace(settings, scanner=replace(settings.scanner, min_constituents=2))
    raw = {
        "fund": {"as_of": "2021-06-30"},
        "holdings": [
            {"ticker": None, "name": "Accenture PLC", "weight": 1, "asset_class": "equity"},
            {"ticker": "BRK/B", "name": "Berkshire Hathaway Inc", "weight": 1, "asset_class": "equity"},
            {"ticker": "MSFT", "name": "Microsoft Corp", "weight": 1, "asset_class": "equity"},
        ],
    }
    u = parse_index_fund(raw, s, name_map={normalize_name("ACCENTURE PLC-CL A"): "ACN"})
    assert set(u.tickers) == {"ACN", "BRK.B", "MSFT"}
    assert normalize_name("Accenture PLC") == normalize_name("ACCENTURE PLC CLASS A")


def test_members_on_uses_latest_snapshot_before_date():
    hist = {date(2020, 3, 31): ["A", "B"], date(2020, 6, 30): ["A", "C"]}
    assert members_on(hist, date(2020, 5, 1)) == ["A", "B"]
    assert members_on(hist, date(2020, 7, 1)) == ["A", "C"]
    assert members_on(hist, date(2020, 1, 1)) == []


def test_scanner_backtest_uses_point_in_time_members(settings):
    from dataclasses import replace

    s = replace(settings, scanner=replace(settings.scanner, min_avg_dollar_volume=1e6))
    end = "2026-09-30"
    bars = {
        f"S{c}": make_bars(n=420, seed=i, drift=0.0008 * (i % 3), vol=0.012, volume=4e6, start=40 + i, end=end)
        for i, c in enumerate("ABCDEFGHIJKL")
    }
    spy = make_bars(n=420, seed=99, drift=0.0004, vol=0.008, volume=8e7, start=300, end=end)
    early = list(bars)[:6]
    late = list(bars)[6:]
    switch = spy.index[350].date()
    hist = {spy.index[280].date(): early, switch: late}
    bt = run_signal_backtest(bars, spy, hist, s, top_n=3)
    f = bt.frame()
    assert len(f) >= 3
    for m in bt.months:
        allowed = set(early) if m.signal_date < switch else set(late)
        assert set(m.picks) <= allowed
    summary = summarize(f)
    assert {"top", "spy", "universe", "ic_mean"} <= set(summary)


def test_ablation_variants_share_months_and_full_matches_production(settings):
    from dataclasses import replace

    from agent_trading.backtest.scanner_backtest import VARIANTS, run_ablation, with_cost_multiplier

    s = replace(settings, scanner=replace(settings.scanner, min_avg_dollar_volume=1e6))
    end = "2026-09-30"
    bars = {
        f"S{c}": make_bars(n=420, seed=i, drift=0.0008 * (i % 3), vol=0.012, volume=4e6, start=40 + i, end=end)
        for i, c in enumerate("ABCDEFGH")
    }
    spy = make_bars(n=420, seed=99, drift=0.0004, vol=0.008, volume=8e7, start=300, end=end)
    hist = {spy.index[280].date(): list(bars)}
    ab = run_ablation(bars, spy, hist, s, top_n=3)
    assert set(ab) == set(VARIANTS)
    dates = [m.signal_date for m in ab["full"].months]
    assert all([m.signal_date for m in ab[v].months] == dates for v in ab)
    assert [m.picks for m in run_signal_backtest(bars, spy, hist, s, top_n=3).months] == [
        m.picks for m in ab["full"].months
    ]
    for m in ab["momentum"].months:  # momentum baseline picks are the top 12-1 momentum names
        assert len(m.picks) <= 3
    f = ab["momentum"].frame()
    cost = s.costs.per_side
    assert np.allclose(f["top_return"], f["gross_return"] - 2 * cost * f["turnover"])
    f3 = with_cost_multiplier(f, cost, 3)
    assert (f3["top_return"] <= f["top_return"] + 1e-12).all()


def test_variant_scores_add_one_factor_at_a_time(settings):
    from agent_trading.backtest.scanner_backtest import variant_scores

    t = pd.DataFrame(
        {
            "close": [50.0] * 4,
            "avg_dollar_volume": [1e9] * 4,
            "mom_12_1": [0.4, 0.3, 0.2, 0.1],
            "dist_200": [0.1, -0.05, 0.1, 0.1],
            "updown_volume": [0.5, 1.0, 3.0, 2.0],
            "vol_63": [0.6, 0.2, 0.2, 0.1],
            "composite": [0.9, 0.8, 0.7, 0.6],
            "setup": ["bullish"] * 4,
            "rsi": [50.0] * 4,
        },
        index=["A", "B", "C", "D"],
    )
    _, mom = variant_scores(t, "momentum", settings)
    assert list(mom.index) == ["A", "B", "C", "D"]
    _, trend = variant_scores(t, "momentum+trend", settings)
    assert "B" not in trend.index and list(trend.index) == ["A", "C", "D"]
    _, vol = variant_scores(t, "momentum+trend+volume", settings)
    assert vol["C"] > trend["C"] and vol["A"] < trend["A"]  # best up/down volume lifts C, weak A falls
    _, low = variant_scores(t, "momentum+trend+lowvol", settings)
    assert low["A"] < trend["A"] and low["D"] > trend["D"]  # high-vol A penalised, low-vol D rewarded
    with pytest.raises(ValueError):
        variant_scores(t, "made-up", settings)


def test_total_return_adjustment_scales_history_before_ex_date():
    from agent_trading.data.dividends import total_return_bars

    idx = pd.bdate_range("2024-01-01", periods=5)
    df = pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}, index=idx)
    divs = pd.Series([2.0], index=pd.DatetimeIndex([idx[3]], name="ex_date"), name="amount")
    out = total_return_bars(df, divs)
    assert out["close"].iloc[:3].tolist() == pytest.approx([98.0] * 3)  # x (1 - 2/100)
    assert out["close"].iloc[3:].tolist() == [100.0, 100.0]
    assert out["volume"].tolist() == df["volume"].tolist()
    assert total_return_bars(df, None).equals(df)
    huge = pd.Series([80.0], index=pd.DatetimeIndex([idx[3]]))  # implausible: skipped
    assert total_return_bars(df, huge).equals(df)


def test_dividend_import_handles_bom_and_empty(settings, tmp_path):
    from agent_trading.data.dividends import import_dividends_file, load_dividends

    p = tmp_path / "gld.json"
    p.write_text('\ufeff{"symbol":"GLD","data":[]}', encoding="utf-8")
    assert import_dividends_file(settings, "GLD", p).empty
    assert load_dividends(settings, "GLD") is not None
    c = tmp_path / "x.csv"
    c.write_text("\ufeffex_date,amount\n2024-03-01,0.5\n2024-06-03,0.6\n", encoding="utf-8")
    s = import_dividends_file(settings, "XYZ", c)
    assert s.tolist() == [0.5, 0.6]


def test_path_stats_drawdown_duration_and_years():
    from agent_trading.backtest.metrics import path_stats

    idx = pd.to_datetime(["2023-12-29", "2024-01-31", "2024-02-29", "2024-03-29", "2025-01-31"])
    eq = pd.Series([1000.0, 900.0, 950.0, 1100.0, 1210.0], index=idx)
    st = path_stats(eq, 1000.0)
    assert st["max_dd_duration_days"] == (idx[3] - idx[1]).days
    assert st["worst_month"] == pytest.approx(-0.1)
    assert st["calendar_years"][2023] == pytest.approx(0.0)
    assert st["calendar_years"][2024] == pytest.approx(0.1)
    assert st["calendar_years"][2025] == pytest.approx(0.1)


def test_vol_managed_weights_scale_down_never_up():
    calm = make_bars(n=400, drift=0.002, vol=0.002, start=100)
    wild = make_bars(n=400, drift=0.004, vol=0.04, start=100, seed=5)
    day = calm.index[-1]
    base_calm = gtaa.weights({"C": calm}, day, ["C"], 10)
    assert gtaa.vol_managed_weights({"C": calm}, day, ["C"], 10, 0.10) == base_calm  # capped at 1x
    if gtaa.weights({"W": wild}, day, ["W"], 10):
        w = gtaa.vol_managed_weights({"W": wild}, day, ["W"], 10, 0.10)["W"]
        assert 0 < w < 1.0
