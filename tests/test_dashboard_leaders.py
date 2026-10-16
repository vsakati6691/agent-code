"""Leaders uses only stored data; all numerical fixtures here are synthetic."""

import copy
import csv
import io
import json
from datetime import date

import pytest

from agent_trading.dashboard import leaders, scenarios, spec, watchlist
from agent_trading.dashboard.pipeline_context import Context
from agent_trading.dashboard.pipeline_leaders import retained_inputs
from agent_trading.dashboard.schema import LEADER_ENTRY
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.site_downloads import leaders_csv, watchlist_csv
from agent_trading.dashboard.site_leaders import leaders_page
from agent_trading.dashboard.site_watchlist import _upside_cell
from agent_trading.dashboard.store import Store
from tests.dashboard_ci import check_links
from tests.dashboard_fixtures import FakeProviders, demo_site


def company(ticker="AAA", price=100, growth=0.10):
    return {
        "ticker": ticker,
        "name": ticker + " Company",
        "sector": "Technology",
        "price": price,
        "price_date": "2026-10-15",
        "fundamentals": {"quarters": ["2026-06-30"] * 8, "diluted_shares": [1e8] * 8, "last_filed": "2026-08-01"},
        "metrics": {
            "revenue_ttm": 4e9,
            "revenue_growth_ttm": growth,
            "ev_to_sales": price / 40,
            "net_debt": 0.0,
            "dilution": 0.02,
            "fcf_margin": 0.2,
        },
    }


def snapshot(rows, members=None):
    return {
        "as_of": "2026-10-15",
        "spec_version": "2026-10-14.9",
        "bands": {"large": {"candidates": rows}},
        "universe": {"sp500_members": members or [r["ticker"] for r in rows]},
    }


def challenger(**changes):
    return {
        "name": "Synthetic Challenger",
        "ticker": None,
        "listing_status": "private",
        "assumed_2030_market_cap_usd": 1e12,
        "assumption_source": "Synthetic test document",
        "assumption_date": "2026-10-09",
        "growth_drivers": ["2026-10-08: Synthetic driver"],
        "notes": "Fixture only",
        **changes,
    }


def test_empty_and_valid_config(tmp_path):
    assert leaders.load_challengers() == []
    path = tmp_path / "challengers.json"
    path.write_text(json.dumps({"challengers": [challenger()]}))
    assert leaders.load_challengers(path) == [challenger()]


@pytest.mark.parametrize(
    "changes",
    [
        {"extra": 3},
        {"assumption_source": " "},
        {"assumed_2030_market_cap_usd": True},
        {"assumed_2030_market_cap_usd": float("nan")},
        {"assumed_2030_market_cap_usd": -1},
        {"listing_status": "listed"},
        {"assumption_date": "2026-99-99"},
        {"growth_drivers": ["undated"]},
        {"growth_drivers": ["2026-10-10: Future evidence"]},
        {"ticker": "AAA"},
        {"listing_status": "listed_non_index", "ticker": None},
        {"notes": 1},
    ],
)
def test_config_rejects_invalid_fields(tmp_path, changes):
    path = tmp_path / "challengers.json"
    path.write_text(json.dumps({"challengers": [challenger(**changes)]}))
    with pytest.raises(ValueError):
        leaders.load_challengers(path)


def test_config_missing_source_unknown_root_and_duplicate_fail(tmp_path):
    path = tmp_path / "challengers.json"
    entry = challenger()
    del entry["assumption_source"]
    for raw in (
        {"challengers": [entry]},
        {"challengers": [], "unknown": 1},
        {"challengers": [challenger(), challenger()]},
    ):
        path.write_text(json.dumps(raw))
        with pytest.raises(ValueError):
            leaders.load_challengers(path)


def test_model_is_the_existing_function_and_cap_uses_matching_projected_shares():
    record = company()
    payload = leaders.build(snapshot([record]), [])
    row = payload["entries"][0]
    assert watchlist.company_scenarios is scenarios.company_scenarios
    assert row["current_market_cap_usd"] == 1e10
    assert row["shares_date"] == "2026-06-30"
    expected = watchlist.company_scenarios(
        100, 1e8, 4e9, 0.1, 2.5, 0, 0.02, watchlist.years_to_target(date(2026, 10, 15)), 0.2
    )
    for case in leaders.CASES:
        assert row["scenario_2030"][f"{case}_price"] == expected[case]["price"]
        assert row["scenario_2030"][f"{case}_shares"] == expected[case]["assumptions"]["shares_2030"]
        assert row["scenario_2030"][f"{case}_cap"] == pytest.approx(
            expected[case]["price"] * expected[case]["assumptions"]["shares_2030"]
        )
    assert row["current_rank"] == row["rank_2030"] == 1
    assert set(row) == set(LEADER_ENTRY["properties"])


def test_ties_candidate_union_and_curated_displacement():
    rows = [company(f"T{i:03}", 100, 0.1) for i in range(52)]
    snap = snapshot(list(reversed(rows)))
    result = leaders.build(snap, [challenger()])
    indexed = {r["ticker"]: r for r in result["entries"]}
    assert indexed["T000"]["current_rank"] == 1
    assert indexed["T000"]["rank_2030"] == 2
    assert indexed["T049"]["movement"] == "drops_out_of_top_50"
    assert "T050" not in indexed
    assert indexed[None]["rank_2030"] == 1
    assert indexed[None]["evidence_grade"] == "none"
    assert indexed[None]["scenario_2030"]["base_price"] is None
    assert indexed[None]["scenario_basis"] == "curated assumption"
    rows[-1]["metrics"]["revenue_growth_ttm"] = 0.6
    rising = leaders.build(snapshot(rows), [])
    assert next(r for r in rising["entries"] if r["ticker"] == "T051")["movement"] == "rises_into_top_50"


@pytest.mark.parametrize(
    "current,future,curated,want",
    [
        (1, 50, False, "stays_in_top_50"),
        (50, 51, False, "drops_out_of_top_50"),
        (51, 50, False, "rises_into_top_50"),
        (1, None, False, "unavailable"),
        (None, 100, True, "curated_challenger"),
    ],
)
def test_all_movement_states(current, future, curated, want):
    assert leaders.movement(current, future, curated) == want


def test_unavailable_preserves_current_rank_and_watchlist_reason():
    record = company()
    record["unavailable_reason"] = "no scenario method for this security type (fund)"
    record["metrics"]["revenue_growth_ttm"] = None
    row = leaders.build(snapshot([record]), [])["entries"][0]
    assert row["current_rank"] == 1 and row["rank_2030"] is None
    assert row["rank_delta"] is None and row["movement"] == "unavailable"
    assert row["unavailable_reason"] == record["unavailable_reason"]
    assert "revenue growth not computable" in " ".join(row["missing_inputs"])


def test_missing_inputs_are_not_guessed_and_future_assumptions_are_omitted():
    record = company()
    record["metrics"]["dilution"] = None
    before = snapshot([record], ["AAA", "MISSING"])
    original = copy.deepcopy(before)
    result = leaders.build(before, [challenger(assumption_date="2026-10-16")])
    assert before == original
    assert result["computed_count"] == 0 and result["partial"]
    assert "trailing dilution unavailable" in result["entries"][0]["unavailable_reason"]
    assert (
        result["gaps"][0]["ticker"] == "MISSING" and "dated diluted shares unavailable" in result["gaps"][0]["reason"]
    )
    assert result["omitted_challengers"]
    text = leaders_page(result, {})
    assert "future weekly collection must retain the missing inputs" in text
    assert text.count("<tr data-ticker=") == 0
    assert "trailing dilution unavailable" in text


def test_growth_drivers_are_dated_stored_evidence():
    record = company()
    record["decision_research"] = {
        "groups": {
            "growth": {
                "as_of": "2026-08-01",
                "fields": {
                    "revenue_cagr_3y": {"value": 0.2, "period": "2023-06-30 to 2026-06-30"},
                    "eps_cagr_5y": {"value": 0.5, "as_of": "2026-10-20"},
                },
            }
        },
        "business": {
            "filed": "2026-08-01",
            "url": "https://www.sec.gov/example",
            "description": "Stored issuer sentence",
        },
    }
    drivers = leaders.growth_drivers(record, "2026-10-15")
    assert len(drivers) == 2 and all(d.startswith("2026-08-01:") for d in drivers)
    assert "Stored issuer sentence" in drivers[1]


def test_csv_has_provenance_projected_shares_and_percentage_points():
    result = leaders.build(snapshot([company()]), [])
    row = next(csv.DictReader(io.StringIO(leaders_csv(result))))
    assert row["shares_basis"] == leaders.SHARE_BASIS and row["shares_date"] == "2026-06-30"
    assert row["is_scenario"] == "True" and row["bear_shares"] and row["base_cap"]
    assert row["rank_scope"] == "full stored index universe"
    entry = {
        "ticker": "AAA",
        "scenarios": {
            case: {"price": price, "change": price / 100 - 1, "annualized": 0.052}
            for case, price in zip(leaders.CASES, [75, 124, 170], strict=True)
        },
    }
    csv_row = next(csv.DictReader(io.StringIO(watchlist_csv({"watchlist": {"entries": [entry]}}))))
    assert [float(csv_row[k]) for k in ("upside_bear_pct", "upside_base_pct", "upside_bull_pct", "cagr_base_pct")] == [
        -25,
        24,
        70,
        5.2,
    ]
    html = _upside_cell(entry)
    assert "+24%" in html and "+5.2%/yr" in html and 'data-v="24"' in html
    assert "upside-zero" in html and "upside-base" in html
    unavailable = _upside_cell({"unavailable_reason": "new filer"})
    assert 'data-v=""' in unavailable and "new filer" in unavailable and "<svg" not in unavailable


def test_retention_does_not_call_providers_or_change_exclusions():
    import pandas as pd

    from agent_trading.dashboard.fundamentals import build as build_fundamentals
    from tests.conftest import make_bars
    from tests.dashboard_fixtures import make_facts

    p = FakeProviders()
    ctx = Context(date(2026, 10, 15), p)
    ctx.facts[1] = (build_fundamentals(make_facts(), ctx.as_of), None)
    ctx.histories["AAA"] = (make_bars(end="2026-10-15"), None, [])
    ref = {"sp500": pd.DataFrame([{"ticker": "AAA", "name": "AAA", "cik": 1, "sector": "Tech"}]).set_index("ticker")}
    before = copy.deepcopy(ctx.excluded)
    records = retained_inputs(ctx, ref)
    assert not p.calls and ctx.excluded == before
    assert records[0]["fundamentals"]["diluted_shares"]
    assert (
        leaders.build({**snapshot([]), "leaders_2030_inputs": records, "universe": {"sp500_members": ["AAA"]}}, [])[
            "computed_count"
        ]
        == 1
    )
    # A verified short-history close may already be cached by the watchlist.
    bars = ctx.histories.pop("AAA")
    ctx.histories["AAA"] = (None, "only 3 bars, need 60", [])
    ctx.histories[("AAA", spec.WATCHLIST_MIN_PRICE_BARS)] = bars
    assert retained_inputs(ctx, ref) == records
    assert not p.calls


def test_latest_dated_share_basis_and_non_operating_reason():
    record = company()
    record["fundamentals"]["quarters"][:3] = ["2025-12-31", "2026-06-30", "2026-12-31"]
    record["fundamentals"]["diluted_shares"][:3] = [2e8, 3e8, 9e8]
    record["asset_type"] = "fund"
    row = leaders.build(snapshot([record]), [])["entries"][0]
    assert row["shares_outstanding"] == 3e8 and row["shares_date"] == "2026-06-30"
    assert row["current_rank"] == 1 and row["rank_2030"] is None
    assert "no scenario method for this security type (fund)" in row["unavailable_reason"]


def test_build_smoke_old_snapshot_immutability_and_page_budgets(tmp_path):
    data, out = demo_site(tmp_path, two_weeks=False)
    snap = Store(data).load("2026-10-09")
    # Old snapshots have only published company detail rows; exercise that build path.
    snap.pop("leaders_2030_inputs")
    snap.pop("leaders_2030")
    old_data = tmp_path / "old-data"
    Store(old_data).write_snapshot(snap)
    hashes = {p.relative_to(old_data): p.read_bytes() for p in old_data.rglob("*") if p.is_file()}
    build_site(old_data, tmp_path / "old-site")
    assert hashes == {p.relative_to(old_data): p.read_bytes() for p in old_data.rglob("*") if p.is_file()}
    for site in (out, tmp_path / "old-site"):
        assert not check_links(site)
        for name in ("leaders.html", "watchlist.html"):
            assert (site / name).stat().st_size < 150_000
        assert (site / "downloads/2026-10-09_leaders_2030.csv").exists()
        leader_html = (site / "leaders.html").read_text(encoding="utf-8")
        assert "No curated challengers registered" in leader_html and "<tr data-ticker=" in leader_html
        assert spec.DISCLAIMER in leader_html
        watch_html = (site / "watchlist.html").read_text(encoding="utf-8")
        assert (
            watch_html.index("Latest price</th>")
            < watch_html.index("Upside to base 2030</th>")
            < watch_html.index("Bear 2030</th>")
        )


def test_full_candidate_union_fits_budget_and_no_data_config_is_validated(tmp_path, monkeypatch):
    from agent_trading.dashboard.site_layout import page

    rows = [company(f"T{i:03}", 1000 - i, -0.3 if i < 50 else 0.6) for i in range(100)]
    result = leaders.build(snapshot(rows), [])
    assert len(result["entries"]) == 100
    markup = page("Leaders", leaders_page(result, {}), "leaders.html")
    assert len(markup.encode()) < 150_000

    def invalid():
        raise ValueError("challenger missing source")

    monkeypatch.setattr(leaders, "load_challengers", invalid)
    with pytest.raises(ValueError, match="missing source"):
        build_site(tmp_path / "data", tmp_path / "site")
