"""Decision research registration and calculations (external services are mocked)."""
from agent_trading.dashboard import spec
from agent_trading.dashboard import decisions as d
from agent_trading.dashboard import decision_sources as sources
from agent_trading.dashboard.fundamentals import build, annual_series
from tests.dashboard_fixtures import make_facts, AS_OF
from datetime import date
from copy import deepcopy
import pytest


def test_decision_rules_are_registered_before_evaluation():
    assert spec.SPEC_VERSION == "2026-10-14.9"
    assert "registered before any data" in dict(spec.SPEC_CHANGELOG)[spec.SPEC_VERSION]
    assert spec.DECISION_RULES["growth_weights"] == {
        "growth": .25, "earnings": .1875, "quality": .1875, "balance": .1875, "valuation": .1875}
    assert spec.SPECULATIVE_RULES == {
        "top_per_list": 3, "per_ticker": 3, "min_dte": 30, "max_dte": 90,
        "min_delta": .25, "max_delta": .40, "open_interest_above": 500, "min_volume": 10,
        "max_spread_pct": .10, "iv_min_dte": 20, "iv_max_dte": 40, "iv_target_dte": 30,
        "iv_rank_sessions": 252, "iv_rank_days": 366, "options_cap_pct": 5, "trade_cap_pct": 1,
        "profit_exit": 1., "loss_exit": -.5, "exit_dte": 21}


@pytest.mark.parametrize("years", [3, 5])
def test_annual_cagr_positive_endpoints_and_year_matching(years):
    series = {"2025-12-31": 100 * 1.2 ** years, f"{2025-years}-12-31": 100}
    assert d.cagr(series, years)["value"] == pytest.approx(.2)
    for bad in (0, -1, float("nan"), None):
        series[f"{2025-years}-12-31"] = bad
        assert d.cagr(series, years)["value"] is None
    assert d.cagr({}, years)["reason"]
    assert d.cagr({"2025-12-31": 100, "2024-12-31": 90}, years)["value"] is None


def test_annual_facts_exclude_future_and_interim_and_use_available_restatement():
    facts = [{"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "form": "10-K", "val": 10},
             {"start": "2024-01-01", "end": "2024-12-31", "filed": "2025-03-01", "form": "10-K/A", "val": 11},
             {"start": "2024-01-01", "end": "2024-12-31", "filed": "2027-03-01", "form": "10-K/A", "val": 99},
             {"start": "2025-01-01", "end": "2025-03-31", "filed": "2025-05-01", "form": "10-Q", "val": 3}]
    group = {"EPS": {"units": {"USD/shares": facts, "USD": facts}}}
    assert annual_series(group, ["EPS"], "USD/shares", AS_OF) == {"2024-12-31": 11}


@pytest.mark.parametrize("delta,expected", [(.02001, "accelerating"), (.02, "stable"), (-.02, "stable"), (-.021, "decelerating"), (None, None)])
def test_growth_trend_boundaries(delta, expected):
    assert d.trend(delta, .02) == expected


def fixture_research():
    f = build(make_facts(), AS_OF)
    f.flows.update(revenue=[200]*4+[100]*4, gross_profit=[120]*4+[50]*4,
                   operating_income=[40]*4+[10]*4, ocf=[60]*4+[20]*4, capex=[10]*8,
                   interest_expense=[5]*8, dna=[10]*8, net_income=[20]*8)
    f.instants.update(cash_equivalents=300, debt_total=100)
    f.diluted_shares = [110]*4+[100]*4
    f.quarterly_eps = [2]*4+[1]*4
    return f


def test_all_financial_decision_calculations_and_signed_net_cash():
    f = fixture_research()
    research = d.build(f, {"market_cap": 1000}, [100]*252+[260], [280]*253, AS_OF, "2026-11-01", "observed")
    values = {k: v["value"] for g in research["groups"].values() for k, v in g["fields"].items()}
    expected = {"pe": 12.5, "ev_sales": 1, "fcf_yield": .2, "revenue_yoy": 1, "eps_yoy": 1,
                "gross_margin": .6, "gross_margin_change": .1, "operating_margin": .2,
                "operating_margin_change": .1, "fcf_margin": .25, "fcf_margin_change": .15,
                "net_debt_ebitda": -1, "corporate_cash": 300, "debt": 100, "interest_coverage": 8,
                "share_change": .1, "below_high": 1-260/280, "return_1y": 1.6}
    for key, expected_value in expected.items():
        assert values[key] == pytest.approx(expected_value), key
    assert values["extended"] == "extended" and values["growth_trend"] == "stable"
    assert values["next_earnings"] == "2026-11-01"
    assert len(research["spark"]) == 253
    assert all("as_of" in g for g in research["groups"].values())
    assert d.build(f, {}, [100]*252+[250], [250]*253, AS_OF, None, "x")["groups"]["timing"]["fields"]["extended"]["value"] == "not extended"


def test_each_group_missing_inputs_remain_na_with_reasons():
    f = fixture_research()
    f.flows = {}; f.instants = {}; f.diluted_shares = []; f.quarterly_eps = []
    research = d.build(f, {}, [], [], AS_OF, None, "x")
    assert not research["spark"]
    for group in research["groups"].values():
        for value in group["fields"].values():
            assert value["value"] is None
            assert value["reason"]


def test_partial_debt_and_nonpositive_coverage_not_assumed_zero():
    f = fixture_research(); f.instants.pop("debt_total")
    f.flows["interest_expense"] = [0]*8
    result = d.build(f, {"market_cap":1000}, [], [], AS_OF, None, "x")
    b = result["groups"]["balance"]["fields"]
    assert b["debt"]["value"] is None and b["interest_coverage"]["value"] is None
    assert result["groups"]["valuation"]["fields"]["ev_sales"]["value"] is None
    assert d.margin_change([1,None,1,1], [10]*8) == (None, None)
    assert d.ratio(1,0) is None and d.ratio(None,1) is None


def test_percentiles_exclude_missing_average_ties_and_need_peers():
    peers = [10,20,20,40,None,float("nan")]
    assert d.percentile(10, peers)["value"] == 0
    assert d.percentile(20, peers)["value"] == 50
    assert d.percentile(40, peers)["value"] == 100
    assert d.percentile(10, [10,10])["value"] == 50
    assert d.percentile(10, [10])["value"] is None
    assert d.percentile(None, peers)["value"] is None
    cs = [{"decision_research":{"groups":{"valuation":{"fields":{"pe":d.field(v)}}}}} for v in [10,20]]
    d.add_percentiles(cs)
    assert cs[1]["decision_research"]["groups"]["valuation"]["fields"]["pe"]["percentile"]["value"] == 100


def test_quality_score_invariant_to_momentum_and_old_profiles_preserved():
    metrics = {key: (scale.lo+scale.hi)/2 for comp in spec.COMPONENTS for key,scale in comp.metrics.items()}
    before = d.score_split(metrics)
    for key in ("return_12_1","excess_6m","excess_12m"): metrics[key] = 50
    after = d.score_split(metrics)
    assert before["quality"] == after["quality"]
    assert after["momentum"]["value"] > before["momentum"]["value"]
    assert d.score_split({})["quality"]["value"] is None
    assert all(b.profile=="fundamental_growth" for b in spec.BANDS if b.key in ("large","mid","small"))
    assert all(b.profile=="standard" for b in spec.BANDS if b.key.startswith("ai_"))


def test_estimates_and_rating_counts_never_fill_missing_categories():
    raw = {"ForwardPE":"30", "PEGRatio":"1.4", "AnalystTargetPrice":"200", **{
        "AnalystRating"+k:"2" for k in ("StrongBuy","Buy","Hold","Sell","StrongSell")}}
    result = sources.estimates(raw, "now")
    assert [result[k]["value"] for k in ("forward_pe","peg","analyst_target","rating_count")] == [30,1.4,200,10]
    assert all(x["as_of"]=="now" for x in result.values())
    raw.pop("AnalystRatingBuy"); raw["ForwardPE"]="None"
    assert sources.estimates(raw,"now")["rating_count"]["value"] is None
    assert sources.estimates(raw,"now")["forward_pe"]["value"] is None
    assert all(x["value"] is None for x in sources.estimates({},"now").values())


def test_insider_market_transactions_are_not_acquisitions_and_disposals():
    raw = {"data":[{"transaction_date":"2026-10-01","shares":"100","acquisition_or_disposal":"A"}]}
    assert sources.insider_net(raw,AS_OF,"now")["value"] is None
    raw["data"][0]["transaction_code"]="P"
    raw["data"].append({"transaction_date":"2026-05-01","shares":"40","transaction_code":"S"})
    raw["data"].append({"transaction_date":"2026-10-10","shares":"999","transaction_code":"S"})
    assert sources.insider_net(raw,AS_OF,"now")["value"] == 60
    assert sources.insider_net({},AS_OF,"now")["value"] is None
    assert sources.six_months_before(date(2026,8,31)) == date(2026,2,28)


def test_filing_text_excerpts_skip_toc_and_hidden_content():
    business = 'We develop software and provide customers with subscription services across multiple markets. '
    grow = 'Our opportunities to grow depend on continued demand for these software services across the world. '
    risk = 'Our business could suffer if competitors reduce prices and customers reduce their spending on services. '
    markup = '<div>Item 1. Business 1 Item 1A. Risk Factors 2 Item 2. Properties</div>'
    markup += '<script>We grow by magic.</script><p>Item 1. Business</p>' + business*3+grow
    markup += '<p>Item 1A. Risk Factors</p>'+risk*4+'<p>Item 1B. Unresolved Staff Comments</p>'
    result=sources.filing_excerpts(markup,"https://www.sec.gov/Archives/edgar/data/1/x/a.htm","2026-01-01")
    assert result["description"] == business.strip()
    assert result["growth"] == grow.strip() and result["risk"] == risk.strip()
    assert sources.filing_excerpts('no sections','url','date')["description"] is None


def test_filing_url_is_bounded_and_point_in_time():
    recent={"form":["10-K"],"filingDate":["2026-01-01"],"accessionNumber":["0000000001-26-000001"],"primaryDocument":["report.htm"]}
    sub={"filings":{"recent":recent}}
    assert sources.latest_10k(sub,1,AS_OF)[0].startswith('https://www.sec.gov/Archives/edgar/data/1/')
    recent["primaryDocument"]=["../secret.htm"]
    assert sources.latest_10k(sub,1,AS_OF) is None
