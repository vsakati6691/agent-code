"""Spec 2026-10-19.2 data-validation fixes. Every number here is synthetic."""

import copy
from datetime import date, timedelta

import pandas as pd
import pytest

from agent_trading.dashboard import leaders, scoring
from agent_trading.dashboard.fundamentals import build, consecutive, quarter_back, ttm
from agent_trading.dashboard.pipeline_score import market_cap
from agent_trading.dashboard.site_leaders import leaders_page
from tests.dashboard_fixtures import _fact, make_facts, quarter_ends
from tests.test_dashboard_leaders import QUARTERS, company, snapshot

AS_OF = date(2026, 10, 16)
CLOSE = pd.Series([100.0] * 300)

# --- date-matched quarter windows ---------------------------------------------------------------


def gapped_quarters() -> list[str]:
    """Nine adjacent quarters to 2024-06-30, then a jump to 2021-06-30 (an issuer tag gap)."""
    q = [d.isoformat() for d in quarter_ends(28)]
    return q[:9] + q[20:]


def test_ttm_windows_match_dates_and_never_splice_across_a_gap():
    q = gapped_quarters()
    assert q[8:10] == ["2024-06-30", "2021-06-30"]
    values = [float(i + 1) for i in range(len(q))]
    assert ttm(values, 0, q) == sum(values[0:4])
    assert ttm(values, 4, q) == sum(values[4:8])  # the year-ago window is intact
    assert ttm(values, 12, q) is None  # three years back falls inside the gap
    assert ttm(values, 12) == sum(values[12:16])  # the legacy positional form would have spliced 2019-2020
    assert quarter_back(q, 0, 1) == 4 and quarter_back(q, 5, 1) is None


def test_twelve_and_sixteen_week_quarters_are_adjacent_but_a_missing_quarter_is_not():
    assert consecutive(["2026-08-30", "2026-05-10", "2026-02-15", "2025-11-23"], 0)  # 16/12/12-week steps
    assert not consecutive(["2026-05-10", "2026-02-15", "2025-11-23", "2025-05-11"], 0)  # 16-week quarter dropped
    assert not consecutive(["2026-06-30"] * 4, 0)


def test_gapped_series_has_no_three_year_cagr_and_year_over_year_uses_matching_quarters():
    facts = make_facts(quarters=24, growth=0.20)
    ends = {d.isoformat() for i, d in enumerate(quarter_ends(24)) if 9 <= i < 20}
    for node in facts["facts"]["us-gaap"].values():
        for unit, arr in node["units"].items():
            node["units"][unit] = [f for f in arr if f["end"] not in ends]
    f = build(facts, AS_OF, max_quarters=24)
    assert f.quarters[8:10] == ["2024-06-30", "2021-06-30"]
    m = scoring.compute_metrics(f, CLOSE, None, 1e10)
    assert m["revenue_cagr_3y"] is None
    assert m["revenue_growth_ttm"] == pytest.approx(0.20)
    assert m["dilution"] == pytest.approx(0.01)
    # yoy for quarters 5-7 has no year-ago quarter, so consistency is not computed from spliced pairs
    assert m["growth_consistency"] is None
    complete = scoring.compute_metrics(build(make_facts(quarters=24, growth=0.20), AS_OF, 24), CLOSE, None, 1e10)
    assert complete["revenue_cagr_3y"] == pytest.approx(0.20) and complete["growth_consistency"] == 1.0


def test_sixteen_week_fourth_quarter_is_derived_and_counted_in_ttm():
    start = date(2025, 9, 1)
    ends = [date(2025, 11, 23), date(2026, 2, 15), date(2026, 5, 10)]
    discrete = [60.0, 65.0, 70.0]
    revenue = [
        _fact(s, e, v, filed=e + timedelta(days=24))
        for s, e, v in zip(
            [start, ends[0] + timedelta(days=1), ends[1] + timedelta(days=1)], ends, discrete, strict=True
        )
    ]
    revenue += [
        _fact(start, ends[1], 125.0, filed=ends[1] + timedelta(days=24)),
        _fact(start, ends[2], 195.0, filed=ends[2] + timedelta(days=24)),
        _fact(start, date(2026, 8, 30), 285.0, form="10-K", filed=date(2026, 10, 7)),
    ]
    f = build({"cik": 9, "facts": {"us-gaap": {"Revenues": {"units": {"USD": revenue}}}, "dei": {}}}, AS_OF)
    assert f.quarters[:4] == ["2026-08-30", "2026-05-10", "2026-02-15", "2025-11-23"]
    assert f.flows["revenue"][0] == 90.0 and f.derived["revenue"][0]
    assert ttm(f.flows["revenue"], 0, f.quarters) == 285.0  # the full fiscal year, not 3 x 12 weeks + a stray quarter


# --- cover-page shares -----------------------------------------------------------------------------


def test_cover_count_comes_only_from_the_latest_statements_filing():
    facts = make_facts()
    dei = facts["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
    current = copy.deepcopy(dei)
    dei[:] = [_fact(None, date(2010, 10, 27), 1.2e7, filed=date(2010, 11, 2))]  # left behind by a per-class switch
    f = build(facts, AS_OF)
    assert f.cover_shares is None
    cap, flags = market_cap(f, 100.0)
    assert cap == pytest.approx(100.0 * f.diluted_shares[0]) and flags == ["shares from weighted-average fallback"]
    dei.extend(current)
    assert build(facts, AS_OF).cover_shares == 1e8


# --- Leaders share checks --------------------------------------------------------------------------


def only_row(record, **snap) -> dict:
    payload = leaders.build({**snapshot([record]), **snap}, [])
    rows = payload["entries"] or [{"unavailable_reason": g["reason"], "current_rank": None} for g in payload["gaps"]]
    return rows[0]


def test_thousandfold_share_count_is_unavailable():
    record = company()
    record["fundamentals"]["diluted_shares"][:2] = [9.82e10, 8.21e10]  # 2026 quarters tagged 1000x too high
    record["metrics"]["market_cap"] = 1e10
    row = only_row(record)
    assert row["current_rank"] is None
    assert row["unavailable_reason"].startswith("share bases disagree: close x diluted shares gives $9.82T")
    assert "differs more than 10x from 100,000,000 (2025-12-31)" in row["unavailable_reason"]


@pytest.mark.parametrize("cover", [True, False])
def test_split_counts_pass_with_a_matching_cover_basis_and_jumps_fail_without_one(cover):
    record = company(price=4)
    record["fundamentals"]["diluted_shares"][0] = 2.5e9  # 25-for-1 split; earlier quarters not restated
    record["metrics"].update(market_cap=1e10 if cover else None, ev_to_sales=None)
    row = only_row(record)
    if cover:
        assert row["current_market_cap_usd"] == 1e10 and row["current_rank"] == 1
    else:
        assert row["current_rank"] is None and "differs more than 10x" in row["unavailable_reason"]


@pytest.mark.parametrize(
    "metrics, shares, problem",
    [
        ({"ev_to_sales": 2.5 / 7.2}, 1e8, True),  # EV/Sales from a 2010 cover count, about 7x too low
        ({}, 100.0, True),  # issuer tags diluted shares in millions
        ({"ev_to_sales": 3.0}, 1e8, False),  # 1.2x apart: inside the registered tolerance
        ({"ev_to_sales": 3.0, "net_debt": None}, 1e8, False),  # EV = cap + (net debt or 0), as in scoring
        ({"ev_to_sales": None}, 1e8, False),  # no basis: ranked, with the missing cross-check listed
    ],
)
def test_close_times_diluted_shares_must_agree_with_the_cover_page_basis(metrics, shares, problem):
    record = company()
    record["metrics"].update(metrics)
    record["fundamentals"]["diluted_shares"] = [shares] * 16
    row = only_row(record)
    reason = row["unavailable_reason"] or ""
    assert (row["current_rank"] is None) == problem
    assert ("share bases disagree" in reason) == problem
    unchecked = "diluted share count not cross-checked: no stored cover-page basis"
    assert (unchecked in row.get("missing_inputs", [])) == (metrics.get("ev_to_sales", 1) is None)


def test_scenarios_use_ev_to_sales_from_the_rows_own_cap():
    record = company()
    record["metrics"].update(ev_to_sales=3.0, net_debt=1e9)  # stored basis 1.1e10 vs own cap 1e10
    row = only_row(record)
    own = (1e10 + 1e9) / 4e9
    assert row["scenario_assumptions"]["base"]["exit_ev_to_sales"] == pytest.approx(own * 0.75)


def test_stored_metrics_from_a_gapped_quarter_list_are_not_used():
    fallback = {"groups": {"growth": {"fields": {"revenue_cagr_3y": {"value": 0.15, "as_of": "2026-08-01"}}}}}
    record = company(growth=0.436)
    record["fundamentals"]["quarters"] = QUARTERS[:9] + ["2021-06-30", "2021-03-31", "2020-06-30"] + QUARTERS[12:]
    record["decision_research"] = fallback
    row = only_row(record)
    assert row["scenario_assumptions"]["base"]["observed_revenue_cagr_3y"] == 0.15
    assert row["scenario_assumptions"]["base"]["growth_basis"].startswith("Fiscal-year revenue CAGR")
    record = company()
    record["fundamentals"]["quarters"][3] = "2025-05-11"  # 2025-08 quarter missing from the stored TTM window
    row = only_row(record)
    assert "stored TTM revenue is not four adjacent quarters" in row["unavailable_reason"]


# --- one row per company ---------------------------------------------------------------------------


def two_classes(volumes=(None, None)):
    rows = []
    for ticker, price, volume in (("GOOGL", 100, volumes[0]), ("GOOG", 99, volumes[1])):
        record = company(ticker, price=price)
        record["cik"] = 1652044
        record["metrics"]["market_cap"] = price * 1e8
        if volume is not None:
            record["dollar_volume"] = volume
        rows.append(record)
    other = company("ZZZ", price=50)
    other["cik"] = 7
    return rows + [other]


EVALUATED_GOOGL = {
    "ticker": "GOOG",
    "reason": "another share class of the same company is evaluated instead (GOOGL, more liquid)",
}


@pytest.mark.parametrize(
    "volumes, excluded, winner",
    [
        ((1e9, 2e9), [], "GOOG"),  # stored dollar volume decides
        ((None, None), [EVALUATED_GOOGL], "GOOGL"),  # older snapshots: the large list's recorded choice
        ((None, None), [], "GOOG"),  # nothing stored: ticker order
    ],
)
def test_each_company_is_ranked_once(volumes, excluded, winner):
    snap = snapshot(two_classes(volumes))
    snap["bands"]["large"]["excluded"] = excluded
    payload = leaders.build(snap, [])
    tickers = [r["ticker"] for r in payload["entries"]]
    loser = ({"GOOGL", "GOOG"} - {winner}).pop()
    assert winner in tickers and loser not in tickers and len(tickers) == 2
    assert payload["share_classes"] == [{"ticker": loser, "ranked_as": winner}]
    assert payload["company_count"] == 2 and payload["universe_count"] == 3 and not payload["partial"]
    row = next(r for r in payload["entries"] if r["ticker"] == winner)
    assert row["other_share_classes"] == [loser] and row["current_rank"] == 1
    text = leaders_page(payload, details := {})
    assert f"also listed as {loser}" in text and f"{loser} is counted with {winner}" in text
    assert any(f"other listed classes: {loser}" in page for page in details.values())
