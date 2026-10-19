"""Spec 2026-10-19.5: companies outside the index, XBRL gap fills and visible reasons. Synthetic numbers only."""

import copy
import json
from datetime import date

import pandas as pd
import pytest

from agent_trading.dashboard import leaders, scoring, spec
from agent_trading.dashboard.fundamentals import annual_series, build
from agent_trading.dashboard.site_leaders import leaders_page, why_unavailable
from tests.dashboard_fixtures import _fact, make_facts, quarter_ends
from tests.test_dashboard_leaders import company, snapshot

AS_OF = date(2026, 10, 16)


def entry(**changes) -> dict:
    return {
        "name": "Synthetic AI Lab",
        "kind": "private",
        "ticker": None,
        "valuation_usd": 300e9,
        "valuation_date": "2026-05-01",
        "valuation_basis": "Priced round, post-money",
        "valuation_source": "Company announcement",
        "valuation_url": "https://example.com/round",
        "valuation_confirmed": True,
        "status": "Confidential draft S-1 submitted",
        "status_date": "2026-06-01",
        "status_source": "Company announcement",
        "status_url": "https://example.com/s1",
        "status_confirmed": False,
        "notes": "",
        **changes,
    }


def write(tmp_path, companies) -> str:
    path = tmp_path / "outside.json"
    path.write_text(json.dumps({"companies": companies}), encoding="utf-8")
    return path


# --- config ------------------------------------------------------------------------------------------


def test_registered_config_is_valid_sourced_and_dated():
    rows = leaders.load_outside()
    assert {r["name"] for r in rows} >= {"Anthropic", "OpenAI", "SpaceX"}
    for r in rows:
        assert r["valuation_usd"] >= spec.LEADERS_OUTSIDE_RULES["min_valuation_usd"]
        assert r["valuation_url"].startswith("https://") and r["status_url"].startswith("https://")
        assert r["valuation_date"] <= "2026-10-19" and r["status_date"] <= "2026-10-19"
    spacex = next(r for r in rows if r["name"] == "SpaceX")
    assert spacex["kind"] == "listed_non_index" and spacex["ticker"] == "SPCX"


@pytest.mark.parametrize(
    "changes",
    [
        {"ticker": "ABC"},  # a private company has no ticker
        {"kind": "listed_non_index"},  # a listed company needs one
        {"kind": "pre_ipo"},
        {"valuation_url": "http://example.com"},
        {"status_date": "2026-13-01"},
        {"valuation_usd": 0},
        {"valuation_confirmed": "yes"},
        {"status": " "},
        {"extra": 1},
    ],
)
def test_config_rejects_invalid_entries(tmp_path, changes):
    with pytest.raises(ValueError):
        leaders.load_outside(write(tmp_path, [entry(**changes)]))


def test_config_rejects_duplicates_and_unknown_root(tmp_path):
    with pytest.raises(ValueError):
        leaders.load_outside(write(tmp_path, [entry(), entry(name="synthetic ai lab")]))
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"companies": [], "other": 1}), encoding="utf-8")
    with pytest.raises(ValueError):
        leaders.load_outside(path)


# --- payload -------------------------------------------------------------------------------------------


def test_rows_are_dated_sized_and_placed_for_scale_only():
    entries = [
        entry(),
        entry(name="Later", valuation_date="2026-10-20"),  # after the snapshot
        entry(name="Stale", valuation_date="2025-09-01"),  # older than 365 days
        entry(name="Small", valuation_usd=50e9),
        entry(name="Bigger", valuation_usd=900e9),
    ]
    rows, omitted = leaders.outside_rows(entries, "2026-10-15", [1e12, 500e9, 200e9, 100e9])
    assert [(r["name"], r["would_rank"]) for r in rows] == [("Bigger", 2), ("Synthetic AI Lab", 3)]
    assert omitted == [
        "Later: dated after the snapshot (2026-10-20)",
        "Stale: valuation older than 365 days (2025-09-01)",
        "Small: valuation below $100.0B",
    ]


def test_build_carries_outside_rows_without_ranking_them():
    snap = snapshot([company()])
    before = copy.deepcopy(snap)
    payload = leaders.build(snap, [], [entry()])
    assert snap == before
    assert [r["ticker"] for r in payload["entries"]] == ["AAA"] and payload["entries"][0]["current_rank"] == 1
    assert payload["outside_index"][0]["would_rank"] == 1  # $300B against AAA's $10B
    with pytest.raises(ValueError):
        leaders.build(snap, [], [entry(kind="listed_non_index", ticker="AAA")])


def test_page_labels_sources_and_escapes():
    payload = leaders.build(
        snapshot([company()]),
        [],
        [entry(name="<b>Lab</b>", notes="note & more"), entry(name="Listed Co", kind="listed_non_index", ticker="LCO")],
    )
    text = leaders_page(payload, {})
    assert "Private and recently listed companies outside the index" in text
    assert "&lt;b&gt;Lab&lt;/b&gt;" in text and "<b>Lab</b>" not in text and "note &amp; more" in text
    assert "confirmed (company page)" in text and "unverified (press report)" in text
    assert "Listed, not in the S&amp;P 500 (LCO)" in text and "scale only" in text
    assert 'rel="noopener noreferrer"' in text
    empty = leaders_page(leaders.build(snapshot([company()]), []), {})
    assert "No companies outside the index registered for this snapshot." in empty


def test_unavailable_rows_show_their_first_reason_in_the_table():
    row = {"movement": "unavailable", "unavailable_reason": "three-year revenue CAGR unavailable; more"}
    assert why_unavailable(row) == '<div class="small muted">three-year revenue CAGR unavailable</div>'
    assert why_unavailable({"movement": "stays_in_top_20", "unavailable_reason": None}) == ""
    long = why_unavailable({"movement": "unavailable", "unavailable_reason": "x" * 200})
    assert long.endswith("…</div>") and len(long) < 160


# --- XBRL gap fills ------------------------------------------------------------------------------------


def alphabet_like(scale: float = 1.0) -> dict:
    """'Revenues' skips eleven quarters; another revenue tag, ending earlier, covers them (times `scale`)."""
    facts = make_facts(quarters=24, growth=0.20)
    gaap = facts["facts"]["us-gaap"]
    full = copy.deepcopy(gaap["Revenues"]["units"]["USD"])
    ends = [d.isoformat() for d in quarter_ends(24)]
    gap = set(ends[9:20])
    gaap["Revenues"]["units"]["USD"] = [f for f in full if f["end"] not in gap]
    # like Alphabet's second tag: no recent quarters, so "Revenues" stays the chosen tag
    other = [dict(f, val=f["val"] * scale) for f in full if f["end"] not in ends[:4]]
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = {"units": {"USD": other}}
    return facts


def test_revenue_gaps_fill_from_an_agreeing_tag_only():
    filled = build(alphabet_like(1.005), AS_OF, max_quarters=24)
    assert len(filled.quarters) == 24 and filled.quarters[8:10] == ["2024-06-30", "2024-03-31"]
    m = scoring.compute_metrics(filled, pd.Series([100.0] * 300), None, 1e10)
    assert m["revenue_cagr_3y"] == pytest.approx(0.20, abs=0.01)
    apart = build(alphabet_like(1.10), AS_OF, max_quarters=24)  # 10% apart: a different measure
    assert apart.quarters[8:10] == ["2024-06-30", "2021-06-30"]


def test_fiscal_years_fill_from_an_agreeing_tag():
    def fy(tag_years, scale=1.0):
        return [
            _fact(
                date(y, 1, 1), date(y, 12, 31), 100.0 * 1.2 ** (y - 2018) * scale, form="10-K", filed=date(y + 1, 2, 1)
            )
            for y in tag_years
        ]

    group = {
        "Revenues": {"units": {"USD": fy([2018, 2019, 2020, 2021, 2023, 2024, 2025])}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": fy(range(2018, 2025), 1.001)}},
    }
    tags = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert "2022-12-31" in annual_series(group, tags, "USD", AS_OF, fill=True)
    assert "2022-12-31" not in annual_series(group, tags, "USD", AS_OF)


@pytest.mark.parametrize("equal", [True, False])
def test_basic_count_stands_in_only_where_basic_and_diluted_eps_match(equal):
    facts = make_facts(quarters=8)
    gaap = facts["facts"]["us-gaap"]
    diluted = gaap.pop("WeightedAverageNumberOfDilutedSharesOutstanding")["units"]["shares"]
    gaap["WeightedAverageNumberOfSharesOutstandingBasic"] = {"units": {"shares": diluted}}
    eps = [dict(f, val=1.25) for f in diluted]
    gaap["EarningsPerShareDiluted"] = {"units": {"USD/shares": eps}}
    gaap["EarningsPerShareBasic"] = {"units": {"USD/shares": [dict(f, val=1.25 if equal else 1.30) for f in eps]}}
    f = build(facts, AS_OF)
    assert (f.diluted_shares[0] == pytest.approx(1e8)) if equal else f.diluted_shares[0] is None
    assert bool(f.notes) == equal
