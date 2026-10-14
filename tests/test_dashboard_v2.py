"""Spec 2026-10-14.2: calls AND puts, list limits, watchlist 2030 scenarios, exports, old-snapshot compatibility."""
from __future__ import annotations

import csv
import io
import json
import math
from datetime import date, timedelta

import pandas as pd
import pytest

from agent_trading.dashboard import options as opt
from agent_trading.dashboard import spec
from agent_trading.dashboard import watchlist as wl
from agent_trading.dashboard.pipeline import run
from agent_trading.dashboard.site import build_site, options_csv
from agent_trading.dashboard.site_options import lists_of
from agent_trading.dashboard.store import Store
from agent_trading.dashboard.tracking import track
from agent_trading.dashboard.tradability import Tradability
from agent_trading.dashboard.watchlist import WatchlistConfig
from tests.dashboard_fixtures import AS_OF, FakeProviders, benchmarks, option_row

EXP = {"3m": AS_OF + timedelta(days=90), "6m": AS_OF + timedelta(days=180), "12m": AS_OF + timedelta(days=365)}


def put_row(under, exp, strike, bid, ask, delta=-0.5, **kw):
    r = option_row(under, exp, strike, bid, ask, delta=delta, **kw)
    r["type"] = "put"
    r["option"] = r["option"][:-9] + "P" + r["option"][-8:]                    # OCC symbol: C -> P
    return r


def chains_for(n_under: int, per_side: int = 4):
    """n_under underlyings, each with `per_side` liquid calls and puts in every horizon window."""
    out = {}
    for u in range(n_under):
        sym = f"U{chr(65 + u)}"
        rows = []
        for exp in EXP.values():
            for i in range(per_side):
                k = 100 + 5 * i
                rows.append(option_row(sym, exp, k, 6.0 - i, 6.1 - i, delta=0.65 - 0.08 * i, oi=1000 + 500 * u))
                rows.append(put_row(sym, exp, k, 4.0 + i, 4.1 + i, delta=-0.35 - 0.08 * i, oi=1000 + 500 * u))
        out[sym] = ({"symbol": sym, "close": 105.0, "last_trade_time": f"{AS_OF}T16:00:00"}, rows)
    return out


# --- options: both types x three horizons ----------------------------------------------------------------

def test_six_lists_with_limits_per_type_and_underlying():
    out = opt.build_horizons(chains_for(8), AS_OF, {})
    for h in spec.HORIZONS:
        for kind in ("calls", "puts"):
            lst = out[h.key][kind]
            rows = lst["rows"]
            assert len(rows) == spec.OPTION_RULES["max_per_type_per_horizon"] == 10
            assert all(r["type"] == kind[:-1] for r in rows)
            per = pd.Series([r["underlying"] for r in rows]).value_counts()
            assert per.max() <= spec.OPTION_RULES["max_per_underlying_per_horizon"]
            assert [r["rank"] for r in rows] == list(range(1, 11))
            scores = [r["rank_components"]["total"] for r in rows]
            assert scores == sorted(scores, reverse=True)
            assert lst["rejections"]["list limit (ranked below the cutoff)"] == 6       # 16 eligible after per-underlying cap
            dte = [r["dte"] for r in rows]
            assert all(h.min_dte <= d <= h.max_dte for d in dte)


def test_fewer_than_ten_shows_actual_count_and_reasons_without_padding():
    ch = chains_for(2, per_side=4)
    out = opt.build_horizons(ch, AS_OF, {})
    calls = out["3m"]["calls"]
    assert calls["count"] == 4 and len(calls["rows"]) == 4                 # 2 underlyings x 2 per underlying
    assert calls["rejections"]["per-underlying limit"] == 4


def test_put_math_breakeven_payoff_required_move_and_max_loss():
    r = opt.research_row(put_row("ABC", EXP["3m"], 100, 4.9, 5.1), 102.0, AS_OF, "ABC", [])
    assert r["breakeven"] == pytest.approx(94.9)                             # strike - ask
    assert r["required_move"] == pytest.approx(1 - 94.9 / 102)               # downward move needed
    assert r["breakeven_move"] < 0 and r["max_loss_per_contract"] == pytest.approx(510)
    p = {round(x["move"], 2): x["pl_per_contract"] for x in r["payoffs"]}
    assert p[0.0] == pytest.approx(-510)                                      # stock at 102 > strike: premium lost
    assert p[-0.30] == pytest.approx((100 - 102 * 0.7 - 5.1) * 100)
    assert min(x["pl_per_contract"] for x in r["payoffs"]) == pytest.approx(-510)
    assert r["premium_basis"] == "ask" and r["type"] == "put"


def test_black_scholes_put_call_parity_and_put_sensitivity():
    s, k, t, v, rf = 100, 95, 0.5, 0.3, spec.RISK_FREE_RATE
    assert opt.bs_call(s, k, t, v) - opt.bs_put(s, k, t, v) == pytest.approx(s - k * math.exp(-rf * t), abs=1e-9)
    assert opt.bs_put(80, 100, 0, 0.2) == 20
    sens = opt.sensitivity(100, 100, 0.5, 0.3, 8.0, "put")
    down, flat, up = (row[1]["model_value"] for row in sens["grid"])        # price -10% / 0 / +10% at unchanged IV
    assert down > flat > up                                                  # puts gain when the stock falls


@pytest.mark.parametrize("delta, ok", [(-0.5, True), (-0.25, False), (-0.75, False), (0.5, False), (None, False)])
def test_put_delta_band_uses_absolute_value(delta, ok):
    r = put_row("ABC", EXP["3m"], 100, 4.9, 5.1, delta=delta)
    assert opt.eligible(r, "ABC", AS_OF, "put")[0] is ok


def test_call_with_negative_delta_is_rejected():
    r = option_row("ABC", EXP["3m"], 100, 4.9, 5.1, delta=-0.5)
    assert not opt.eligible(r, "ABC", AS_OF, "call")[0]


def test_puts_are_not_reversed_growth_rankings():
    """Puts are ranked on contract characteristics for the same underlyings, independent of call order."""
    out = opt.build_horizons(chains_for(3), AS_OF, {})
    assert set(r["underlying"] for r in out["3m"]["puts"]["rows"]) <= set(out["underlyings"])
    assert "not reversing" in spec.OPTION_RANKING_NOTE or "not by reversing" in spec.OPTION_RANKING_NOTE


def test_stale_chain_gives_unavailable_calls_and_puts():
    ch = chains_for(1)
    sym = next(iter(ch))
    ch[sym][0]["last_trade_time"] = f"{AS_OF - timedelta(days=4)}T16:00:00"
    out = opt.build_horizons(ch, AS_OF, {})
    for h in spec.HORIZONS:
        assert out[h.key]["calls"]["rows"] == [] and out[h.key]["puts"]["rows"] == []
        assert out[h.key]["puts"]["status"].startswith("unavailable")


def test_option_csv_export_has_type_premium_basis_and_required_move():
    rows = opt.build_horizons(chains_for(2), AS_OF, {})["6m"]["puts"]["rows"]
    table = list(csv.DictReader(io.StringIO(options_csv(rows))))
    assert len(table) == len(rows) and {r["type"] for r in table} == {"put"}
    assert {"premium_basis", "required_move", "breakeven", "max_loss_per_contract"} <= set(table[0])


# --- watchlist -------------------------------------------------------------------------------------------

def dirs_sec():
    dirs = pd.DataFrame([
        ("COMP", "Comp Inc. Common Stock", "Nasdaq", False, False, ""),
        ("BIGF", "Invesco QQQ Trust, Series 1", "Nasdaq", True, False, ""),
        ("SEMI", "VanEck Semiconductor ETF", "Nasdaq", True, False, ""),
        ("LEV3", "ProShares UltraPro QQQ", "Nasdaq", True, False, ""),
        ("INV3", "ProShares UltraPro Short QQQ", "Nasdaq", True, False, ""),
        ("ODDF", "Some Unusual Strategy Fund", "NYSE Arca", True, False, ""),
    ], columns=["ticker", "name", "exchange", "etf", "test_issue", "financial_status"]).set_index("ticker")
    sec = pd.DataFrame([("COMP", 9001, "Comp Inc", "Nasdaq"), ("OTCX", 9002, "Otc Co", "OTC")],
                       columns=["ticker", "cik", "name", "exchange"]).set_index("ticker")
    return dirs, sec


@pytest.mark.parametrize("ticker, kind, status", [
    ("COMP", "operating company (common stock)", "listed"),
    ("BIGF", "ETF", "listed"),
    ("LEV3", "leveraged/inverse ETF", "listed"),
    ("OTCX", "SEC registrant", "OTC or not exchange-listed"),
    ("ZZZZ", None, "unresolved"),
])
def test_symbol_resolution_never_guesses(ticker, kind, status):
    d, s = dirs_sec()
    r = wl.resolve(ticker, d, s)
    assert r["asset_type"] == kind and r["status"].startswith(status)
    if ticker == "ZZZZ":
        assert r["name"] is None and "no substitute" in r["status"]


def test_leverage_parsing():
    assert wl.leverage_of("ProShares UltraPro QQQ") == 3
    assert wl.leverage_of("ProShares UltraPro Short QQQ") == -3
    assert wl.leverage_of("Direxion Daily Semiconductor Bull 3X Shares") == 3
    assert wl.leverage_of("Invesco QQQ Trust, Series 1") is None


def test_years_to_target_uses_actual_dates():
    assert wl.years_to_target(date(2026, 12, 31)) == pytest.approx(4 * 365.25 / 365.25, abs=0.01)
    assert wl.years_to_target(date(2026, 10, 9)) == pytest.approx((date(2030, 12, 31) - date(2026, 10, 9)).days / 365.25)


def test_etf_scenario_is_price_return_net_of_fee_and_yield():
    rule = spec.ETF_EXPOSURE_RULES[0]
    sc = wl.etf_scenarios(100.0, rule, 4.0)
    base = sc["base"]
    r_price = (1 + rule[3][1]) / (1 + rule[4]) / (1 + rule[5]) - 1
    assert base["price"] == pytest.approx(100 * (1 + r_price) ** 4)
    assert base["annualized"] < rule[3][1]                                  # below the total-return assumption
    assert sc["bear"]["price"] < sc["base"]["price"] < sc["bull"]["price"]


def test_leveraged_scenario_has_volatility_drag_not_naive_multiplication():
    rule = spec.ETF_EXPOSURE_RULES[0]
    sc = wl.leveraged_scenarios(100.0, 3, rule, 0.25, 4.0)
    naive = 100 * (1 + rule[3][1]) ** (3 * 4)                                 # what NOT to do
    assert sc["base"]["price"] < naive
    a = sc["base"]["assumptions"]
    assert a["volatility_drag"] == pytest.approx(9 * 0.25 ** 2 / 2)
    assert a["financing_cost"] == pytest.approx(2 * spec.LEVERAGED_FINANCING_RATE)


def test_company_scenario_reaches_the_fractional_target_date():
    sc = wl.company_scenarios(10.0, 100.0, 100.0, 0.30, 5.0, 50.0, 0.0, 4.25)
    base = sc["base"]
    path = base["assumptions"]["growth_path"]
    assert len(path) == 5                                                    # 4 full years + a partial year
    assert base["price"] == pytest.approx((base["assumptions"]["revenue_2030"] * 5.0 * 0.75 + 50.0) / 100.0)
    with pytest.raises(ValueError):
        wl.company_scenarios(10.0, 100.0, 0.0, 0.3, 5.0, 0.0, 0.0, 4.0)


def test_watchlist_config_rejects_account_fields(tmp_path):
    p = tmp_path / "w.json"
    p.write_text(json.dumps({"imported_at": "2026-10-14", "tickers": ["AAA"], "quantity": 3}))
    with pytest.raises(ValueError):
        WatchlistConfig.load(p)
    p.write_text(json.dumps({"imported_at": "2026-10-14", "tickers": ["aaa", "AAA", "brk-b"]}))
    assert WatchlistConfig.load(p).tickers == ("AAA", "BRK.B")


def test_repo_watchlist_config_is_tickers_only():
    cfg = WatchlistConfig.load()
    assert cfg is not None and "TQQQ" in cfg.tickers and cfg.imported_at == "2026-10-14"


@pytest.fixture
def prov():
    p = FakeProviders()
    benchmarks(p)
    for i in range(12):
        p.add(f"S{i:02d}", 100 + i, growth=0.05 + 0.04 * i, drift=0.0004 + 0.0001 * i, shares=5e8)
    p.add("MIDA", 300, sp=False, shares=4e7, drift=0.0003, growth=0.25)
    p.add("SPEC", 301, sp=False, shares=8e6, drift=0.0003, growth=0.50, cash=1e8)
    from tests.conftest import make_bars
    p.listed["QQQX"] = ("Invesco QQQ Trust, Series 1", "Nasdaq", True)
    p.bars["QQQX"] = make_bars(n=1300, start=300, drift=0.0004, seed=77, end=AS_OF.isoformat())
    p.listed["LEVX"] = ("ProShares UltraPro QQQ", "Nasdaq", True)
    p.bars["LEVX"] = make_bars(n=1300, start=50, drift=0.0008, vol=0.03, seed=78, end=AS_OF.isoformat())
    p.bars["QQQ"] = make_bars(n=1300, start=300, drift=0.0004, seed=79, end=AS_OF.isoformat())
    return p


def test_watchlist_is_separate_from_ranked_lists_and_covers_every_type(prov):
    t = Tradability.all_tradable(list(prov.listed), "2026-10-08")
    base = run(prov, AS_OF, options_enabled=False, tradability=t)
    cfg = WatchlistConfig(("MIDA", "QQQX", "LEVX", "NOPE"), "2026-10-14", "test")
    snap = run(prov, AS_OF, options_enabled=False, tradability=t, watchlist=cfg)
    for k in base["bands"]:                                                   # rankings unchanged by the watchlist
        assert [c["ticker"] for c in base["bands"][k]["candidates"]] == [c["ticker"] for c in snap["bands"][k]["candidates"]]
    w = {e["ticker"]: e for e in snap["watchlist"]["entries"]}
    assert w["MIDA"]["scenarios"] and w["MIDA"]["method"].startswith("company")
    assert w["QQQX"]["scenarios"] and w["QQQX"]["method"].startswith("ETF")
    assert w["LEVX"]["scenarios"] and "volatility" in w["LEVX"]["assumptions_note"]
    assert w["NOPE"]["scenarios"] is None and "unresolved" in w["NOPE"]["unavailable_reason"]
    assert snap["watchlist"]["imported_at"] == "2026-10-14" and snap["watchlist"]["target_date"] == "2030-12-31"
    for e in w.values():
        if e["scenarios"]:
            assert e["price_date"] and e["evidence_quality"] in ("low", "medium", "medium-high")


# --- site: compact overview, options toggle, watchlist page, exports, old snapshots -------------------

def _store_snapshot(root, payload):
    st = Store(root)
    st.write_snapshot(payload)
    return st


def test_new_site_pages_panels_toggle_and_downloads(tmp_path, prov):
    t = Tradability.all_tradable(list(prov.listed), "2026-10-08")
    snap = run(prov, AS_OF, options_enabled=False, tradability=t,
               watchlist=WatchlistConfig(("MIDA", "QQQX", "LEVX", "NOPE"), "2026-10-14", "test"))
    snap["options"] = {"enabled": True, "status": "ok", **opt.build_horizons(chains_for(3), AS_OF, {})}
    _store_snapshot(tmp_path / "d", snap)
    build_site(tmp_path / "d", tmp_path / "s")
    out = tmp_path / "s"
    index = (out / "index.html").read_text(encoding="utf-8")
    for text in ("Upcoming earnings", "What changed since the previous snapshot?", "Concentration and downside flags", "Performance vs benchmarks",
                 "Data coverage and freshness", "S&amp;P 500 members only", "Speculative multibagger research candidates",
                 "5-10 year research horizon", "rowtoggle", "vs bench"):
        assert text in index, text
    opts = (out / "options.html").read_text(encoding="utf-8")
    assert 'data-dim="type" data-val="put"' in opts and opts.count("data-hz=") == 6
    assert "Premium assumption" in opts and "not predict profitability" in opts
    watch = (out / "watchlist.html").read_text(encoding="utf-8")
    assert "Conditional 2030 price scenarios" in watch and "not synchronized" in watch and "Scenario unavailable" in watch
    for f in ("2026-10-09_options_3m_calls.csv", "2026-10-09_options_12m_puts.csv", "2026-10-09_watchlist_2030.csv",
              "2026-10-09_small.csv", "2026-10-09_multibagger.csv"):
        assert (out / "downloads" / f).exists(), f
    w = list(csv.DictReader(io.StringIO((out / "downloads" / "2026-10-09_watchlist_2030.csv").read_text())))
    assert {r["ticker"] for r in w} == {"MIDA", "QQQX", "LEVX", "NOPE"}


def test_old_snapshot_still_renders_and_tracks(tmp_path):
    """A snapshot from spec 2026-10-14.1 or earlier: 'spec' list, calls-only options, no watchlist or events."""
    cand = {"ticker": "OLD", "name": "Old Co", "sector": "Energy", "rank": 1, "composite": 50.0, "components": {"growth": 0.5},
            "sub_scores": {}, "metrics": {}, "missing": [], "confidence": 0.9, "confidence_label": "high", "flags": [],
            "counterargument": "x", "thesis": "t", "bear_case": "b", "risks": [], "invalidation": [], "price": 10.0,
            "price_date": "2026-10-09", "market_cap": 1e9, "cik": 1, "band": "spec", "benchmark": "IWM",
            "sources": {"price": "p", "fundamentals": "f"}, "data_timestamp": "t",
            "history": {"returns": {}, "drawdowns": {"max_5y": {"value": -0.2, "peak": "a", "trough": "b"},
                                                     "from_52w_high": -0.1}, "first_date": "2020-01-01"},
            "chart": {}, "scenarios": None, "scenario_note": "n/a", "not_scored": {}, "probability": "p",
            "fundamentals": {"quarters": [], "revenue": [], "gross_profit": [], "operating_income": [], "net_income": [],
                             "ocf": [], "capex": [], "sbc": [], "derived_revenue": [], "last_form": "10-Q", "last_filed": "x"}}
    old_call = opt.research_row(option_row("OLD", EXP["3m"], 10, 1.0, 1.05), 10.0, AS_OF, "OLD", [])
    old_call.pop("type")
    old_call["rank"], old_call["rank_components"] = 1, {"total": 50, "liquidity": 1, "breakeven": 0, "time_decay": 0}
    old = {"as_of": "2026-10-09", "status": "ok", "spec_version": "2026-10-13.2", "run_finished": "2026-10-10T15:00:00+00:00",
           "universe": {"sp500_count": 503, "sp500_price_coverage": 1.0, "broad_eligible": 1, "broad_prescreen": 1,
                        "broad_exclusion_counts": {}},
           "benchmarks": {"IWM": {"close": 200.0}}, "problems": [], "notes": [],
           "bands": {"spec": {"title": "Speculative potential multibagger research candidates", "benchmark": "IWM",
                              "benchmark_name": "IWM", "max_results": 10, "candidates": [cand], "excluded": [],
                              "ranked": 1, "evaluated": 1, "rank_changes": [], "concentration": []}},
           "options": {"enabled": True, "status": "ok", "underlyings": ["OLD"],
                       "3m": {"rows": [old_call], "considered": 1, "rejections": {}, "status": "ok"},
                       "6m": {"rows": [], "status": "no contract met the liquidity and delta rules"},
                       "12m": {"rows": [], "status": "no contract"}}}
    _store_snapshot(tmp_path / "d", old)
    build_site(tmp_path / "d", tmp_path / "s")
    out = tmp_path / "s"
    assert "retired" in (out / "index.html").read_text(encoding="utf-8") or "Speculative" in (out / "index.html").read_text(encoding="utf-8")
    opts = (out / "options.html").read_text(encoding="utf-8")
    assert "OLD" in opts and "puts were not collected in this snapshot" in opts
    assert "Watchlist not available" in (out / "watchlist.html").read_text(encoding="utf-8")
    assert (out / "stock" / "spec-OLD.html").exists() and (out / "downloads" / "2026-10-09_options_3m_calls.csv").exists()
    assert lists_of(old["options"]["3m"])["calls"]["rows"][0]["option"] == old_call["option"]
    idx = pd.bdate_range("2026-10-09", periods=40)
    prices = {t: pd.Series([100 + i for i in range(40)], index=idx, dtype=float) for t in ("OLD", "IWM")}
    tr = track([old], prices, idx[-1].date())
    assert tr["by_snapshot"][0]["band"] == "spec" and tr["by_snapshot"][0]["horizons"]["1m"]["status"] == "ok"


def test_company_scenarios_link_margins_without_changing_prices():
    """Spec 2026-10-14.3: FCF-margin path and implied 2030 EV/FCF cross-check; prices unchanged."""
    plain = wl.company_scenarios(10.0, 100.0, 100.0, 0.30, 5.0, 50.0, 0.0, 4.25)
    sc = wl.company_scenarios(10.0, 100.0, 100.0, 0.30, 5.0, 50.0, 0.0, 4.25, margin=0.20)
    for k, shift in (("bear", -0.05), ("base", 0.0), ("bull", 0.05)):
        a = sc[k]["assumptions"]
        assert sc[k]["price"] == pytest.approx(plain[k]["price"])
        assert a["margin_2030"] == pytest.approx(0.20 + shift)
        assert a["fcf_2030"] == pytest.approx(a["revenue_2030"] * a["margin_2030"])
        assert a["implied_ev_to_fcf"] == pytest.approx(a["ev_2030"] / a["fcf_2030"])
    assert sc["base"]["assumptions"]["cash_support"].startswith("consistent")
    thin = wl.company_scenarios(10.0, 100.0, 100.0, 0.30, 5.0, 0.0, 0.0, 4.25, margin=0.03)
    assert thin["bear"]["assumptions"]["cash_support"].startswith("not supported")     # 3% - 5 points < 0
    assert thin["base"]["assumptions"]["cash_support"].startswith("stretched")         # EV/FCF far above 60x
    assert plain["base"]["assumptions"]["cash_support"] == "not checked: no margin data"
