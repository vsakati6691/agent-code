"""Daily scan: faithful snapshot summaries, empty states, and sortable row alignment."""
from copy import deepcopy
from html.parser import HTMLParser

import pytest

from agent_trading.dashboard.site_scan import benchmark_return, candidate_scan, market_context, scan_header
from agent_trading.dashboard.site_watchlist import _scen_cells, watchlist_page


def snapshot():
    c = {"ticker": "ABC", "name": "Example <Company>", "rank": 1, "price": 20.0, "price_date": "2026-10-13",
         "composite": 65.0, "confidence_label": "high", "sector": "Technology", "missing": ["dilution"],
         "history": {"returns": {"1y": {"benchmark": 0.1, "stock": 0.3, "end": "2026-10-13"}}},
         "counterargument": "Valuation < growth"}
    return {"as_of": "2026-10-13", "bands": {"large": {"benchmark": "SPY", "candidates": [c]}},
            "benchmarks": {"SPY": {"date": "2026-10-13", "close": 500.0}}}


def test_benchmark_return_uses_stored_return_not_candidate_performance():
    s = snapshot()
    assert benchmark_return(s, "SPY", "1y") == 0.1
    assert benchmark_return(s, "IWM", "1y") is None
    page = market_context(s)
    assert "$500.00" in page and "+10.0%" in page and "+30.0%" not in page
    assert page.count("Unavailable") == 2


@pytest.mark.parametrize("change", ["conflicting", "wrong_date", "missing", "nonfinite"])
def test_benchmark_returns_never_guess(change):
    s = snapshot()
    c = s["bands"]["large"]["candidates"][0]
    r = c["history"]["returns"]["1y"]
    if change == "conflicting":
        other = deepcopy(c)
        other["history"]["returns"]["1y"]["benchmark"] = 0.2
        s["bands"]["large"]["candidates"].append(other)
    elif change == "wrong_date":
        r["end"] = "2026-10-12"
    elif change == "missing":
        r.pop("benchmark")
    else:
        r["benchmark"] = float("nan")
    assert benchmark_return(s, "SPY", "1y") is None


def test_legacy_returns_require_a_matching_verified_price_date():
    s = snapshot()
    c = s["bands"]["large"]["candidates"][0]
    del c["history"]["returns"]["1y"]["end"]
    assert benchmark_return(s, "SPY", "1y") == 0.1
    c["price_date"] = "2026-10-12"
    assert benchmark_return(s, "SPY", "1y") is None
    s["benchmarks"]["SPY"]["date"] = "2026-10-12"
    page = market_context(s)
    assert "$500.00" not in page and "+10.0%" not in page


def test_scan_summary_deduplicates_tickers_and_preserves_unknown_calendar():
    s = snapshot()
    s["bands"]["mid"] = deepcopy(s["bands"]["large"])
    page = scan_header(s, None)
    assert '<strong>1</strong><small>Across 2 research lists' in page
    assert '<strong>1</strong><small>Review evidence' in page
    assert "Unknown" in page and "Calendar data unavailable" in page
    assert "First stored snapshot" in page
    s["events"] = {"items": [], "status": "ok"}
    page = scan_header(s, None)
    assert "Unknown" not in page and "Next 45 days from snapshot" in page


def test_scanner_preserves_list_membership_escapes_text_and_does_not_mutate_snapshot():
    s = snapshot()
    s["bands"]["mid"] = deepcopy(s["bands"]["large"])
    before = deepcopy(s)
    page = candidate_scan(s)
    assert s == before
    assert page.count('data-ticker="ABC"') == 2
    assert "Example &lt;Company&gt;" in page and "Valuation &lt; growth" in page
    assert 'href="stock/large-ABC.html"' in page and 'href="stock/mid-ABC.html"' in page
    assert 'data-gaps="yes"' in page and 'data-quality="high"' in page
    assert 'data-sort="num">Score' not in page  # no cross-list score ranking


class Cells(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = []

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self.cells.append(dict(attrs))


def test_missing_scenarios_keep_sort_columns_aligned():
    parser = Cells()
    parser.feed(_scen_cells({}))
    assert len(parser.cells) == 3
    assert all(c.get("data-v") == "" and "colspan" not in c for c in parser.cells)


def test_empty_and_legacy_pages_remain_explanatory():
    page = candidate_scan({})
    assert "No candidates match" in page and "0 list entries" in page
    assert "Watchlist not available" in watchlist_page({})


def test_watchlist_counts_and_filters_are_based_on_stored_availability():
    s = snapshot()
    s["watchlist"] = {"status": "ok", "entries": [{"ticker": "EMPTY", "price": None}],
                      "statement": "Conditional only", "separation": "Independent list", "imported_at": "2026-10-13",
                      "target_date": "2030-12-31", "years_to_target": 4.2}
    page = watchlist_page(s)
    assert 'data-scenario="unavailable"' in page and 'data-ticker="EMPTY"' in page
    assert 'Scenarios unavailable</span><strong>1</strong>' in page
    assert page.index('id="t-watch"') < page.index("Compare all 2030 scenario ranges")
