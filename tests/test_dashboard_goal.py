import json
import math
import re
import shutil
import subprocess
from datetime import date
from html import unescape

import pytest

from agent_trading.dashboard import assets_goal, spec
from agent_trading.dashboard.goal import ending_value, required_rate, stressed_ending, weighted_endings
from agent_trading.dashboard.site_evidence import FINAL, ROOT, TOURNAMENT, evidence_page, read_evidence
from agent_trading.dashboard.site_goal import goal_page, payload


def test_required_rate_and_contribution_timing():
    assert required_rate(10000, 20000, 0, 4) == pytest.approx(2**0.25 - 1)
    years = (date(2030, 12, 31) - date(2026, 10, 15)).days / 365.25
    rate = required_rate(10000, 20000, 100, years)
    assert ending_value(10000, 100, years, rate) == pytest.approx(20000)
    assert rate < required_rate(10000, 20000, 0, years)
    assert ending_value(10000, 100, 1, 0) == 11200
    assert ending_value(0, 100, 1, 0.12) == pytest.approx(sum(100 * 1.12 ** (1 - i / 12) for i in range(1, 13)))
    assert ending_value(10000, 100, 1.04, 0) == 11200
    assert required_rate(10000, 10000, 100, 1) < 0
    assert required_rate(10000, 50, 100, 1) is None


@pytest.mark.parametrize(
    "args",
    [(0, 100, 0, 4), (100, 0, 0, 4), (100, 200, -1, 4), (100, 200, 0, 0), (100, 200, 0, 101), (math.nan, 200, 0, 4)],
)
def test_invalid_required_inputs_fail_closed(args):
    assert required_rate(*args) is None


def test_weighted_endings_and_unavailable_propagation():
    rates = {"AAA": {"bear": -0.1, "base": 0.1, "bull": 0.2}, "Cash": {k: 0 for k in ("bear", "base", "bull")}}
    result = weighted_endings(10000, 100, 4, {"AAA": 0.5, "Cash": 0.5, "MISSING": 0}, rates)
    assert not result["reason"]
    assert result["values"]["base"] == pytest.approx(ending_value(5000, 50, 4, 0.1) + ending_value(5000, 50, 4, 0))
    missing = weighted_endings(10000, 0, 4, {"AAA": 0.5, "MISSING": 0.5}, rates)
    assert "MISSING" in missing["reason"] and all(v is None for v in missing["values"].values())
    assert weighted_endings(10000, 0, 4, {"AAA": 0.4}, rates)["reason"] == "Weights must total 100%."
    assert stressed_ending(10000, 100, 4, 0.05, 0.4) == pytest.approx(ending_value(11200 * 0.6, 100, 3, 0.05))
    assert stressed_ending(10000, 100, 0.5, 0.05, 0.4) is None


def test_javascript_arithmetic_matches_reference(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node not installed")
    cases = [
        [10000, 20000, 0, 4.2],
        [10000, 20000, 100, 4.2],
        [10000, 10000, 100, 1],
        [10000, 50, 100, 1],
        [0, 100, 0, 4],
    ]
    rates = {"AAA": {"bear": -0.1, "base": 0.1, "bull": 0.3}, "Cash": {k: 0 for k in ("bear", "base", "bull")}}
    weights = {"AAA": 0.25, "Cash": 0.75, "MISSING": 0}
    script = tmp_path / "goal.js"
    script.write_text(
        assets_goal.MATH_JS
        + "\nconsole.log(JSON.stringify({required:"
        + json.dumps(cases)
        + ".map(a=>GoalMath.required(...a)),weighted:GoalMath.weighted(10000,100,4.2,"
        + json.dumps(weights)
        + ","
        + json.dumps(rates)
        + "),stress:GoalMath.stress(10000,100,4.2,.05,.4)}));",
        encoding="utf-8",
    )
    result = json.loads(subprocess.check_output([node, str(script)]))
    for actual, args in zip(result["required"], cases, strict=True):
        expected = required_rate(*args)
        assert actual == pytest.approx(expected) if expected is not None else actual is None
    expected = weighted_endings(10000, 100, 4.2, weights, rates)
    assert result["weighted"]["values"] == pytest.approx(expected["values"])
    assert result["stress"] == pytest.approx(stressed_ending(10000, 100, 4.2, 0.05, 0.4))


def test_goal_render_and_stress_defaults_use_stored_observations():
    entry = {"ticker": "AAA", "asset_type": "ETF", "history": {"drawdowns": {"max_5y": {"value": -0.35}}}}
    snap = {"as_of": "2026-10-09", "watchlist": {"entries": [entry]}}
    data = payload(snap, date(2026, 10, 15))
    assert data["classes"][0]["drawdown"] == 0.35
    assert {a["ticker"] for a in data["assets"]} == {"AAA", "SPY", "QQQ", "Cash"}
    assert next(a for a in data["assets"] if a["ticker"] == "SPY")["rates"] == {}
    text = unescape(goal_page(snap, date(2026, 10, 15)))
    assert 'value="10000"' in text and 'value="20000"' in text
    assert 'href="evidence.html"' in text and 'id="goal-stress-ending"' in text
    assert spec.PROBABILITY_STATEMENT in text and spec.DISCLAIMER in text
    assert "fetch(" not in assets_goal.JS and "XMLHttpRequest" not in assets_goal.JS


def price_entry(ticker="AAA"):
    return {
        "ticker": ticker,
        "price": 123.45,
        "price_date": "2026-10-09",
        "scenarios": {
            case: {"price": price, "annualized": rate, "assumptions": {}}
            for case, price, rate in (("bear", 91.23, -0.05), ("base", 234.56, 0.07), ("bull", 345.67, 0.12))
        },
    }


def test_goal_prices_reuse_stored_values_without_recalculation(monkeypatch):
    monkeypatch.setattr("agent_trading.dashboard.site_goal._assumptions", lambda entry: "")
    entry = price_entry()
    snap = {"watchlist": {"entries": [entry]}}
    data = payload(snap, date(2026, 10, 15))
    assert data["assets"][0]["prices"] == {"bear": 91.23, "base": 234.56, "bull": 345.67}
    assert data["assets"][0]["price"] == 123.45
    daily = {"data": {"as_of": "2026-10-14", "quotes": {"AAA": {"status": "available", "close": 199.99}}}}
    text = goal_page(snap, date(2026, 10, 15), daily=daily)
    table = text.split('<table id="t-goal"', 1)[1].split("</table>", 1)[0]
    for label in (
        "Current price (date)",
        "2030 Bear",
        "2030 Base",
        "2030 Bull",
        "Base %/yr",
        "Required %/yr",
        "Base vs required",
    ):
        assert label in table
    for value in ("$123.45", "2026-10-09", "$91.23", "$234.56", "$345.67", "7.00%/yr"):
        assert value in table
    assert "Latest close $199.99 (2026-10-14)" in table
    assert 'data-v="123.45"' in table and 'data-v="199.99"' not in table
    assert "2030 price scenarios (conditional, not predictions)" in table
    assert "How this is calculated" in text
    # Daily prices are display context; calculator payload and stored input remain untouched.
    assert payload(snap, date(2026, 10, 15)) == data
    assert entry["price"] == 123.45
    for stamp, status, close in (
        ("2026-10-09", "available", 200),
        ("2026-10-08", "available", 200),
        ("invalid", "available", 200),
        ("2026-10-14", "unavailable", 200),
        ("2026-10-14", "available", -1),
    ):
        daily["data"].update(as_of=stamp, quotes={"AAA": {"status": status, "close": close}})
        assert "Latest close" not in goal_page(snap, daily=daily)


def test_goal_missing_rows_escape_and_keep_saved_weight_mapping(monkeypatch):
    monkeypatch.setattr("agent_trading.dashboard.site_goal._assumptions", lambda entry: "")
    missing = {"ticker": 'X<script>"', "unavailable_reason": 'No SEC <financials> "available"'}
    snap = {"watchlist": {"entries": [missing, price_entry()]}}
    text = goal_page(snap, date(2026, 10, 15))
    body = text.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    rows = re.findall(r"<tr>(.*?)</tr>", body)
    assert len(rows) == 2 and "AAA" in rows[0]
    assert all(len(re.findall(r"<td\b", row)) == 8 for row in rows)
    assert 'id="goal-rate-1"' in rows[0] and 'id="goal-rate-0"' in rows[1]
    assert 'X&lt;script&gt;&quot; weight (%) <input id="goal-weight-0"' in text
    assert 'AAA weight (%) <input id="goal-weight-1"' in text
    assert "No SEC &lt;financials&gt; &quot;available&quot;" in rows[1]
    assert "Unavailable" not in rows[1] and '<script>"' not in text
    assert payload(snap)["assets"][0]["ticker"] == missing["ticker"]


def test_plan_explains_company_etf_gap_with_stored_etf_arithmetic():
    from agent_trading.dashboard.site_goal import scenario_model_gap

    entry = price_entry("SMH")
    entry["scenarios"]["base"]["assumptions"] = {
        "total_return_assumption": 0.06,
        "assumed_fee": 0.0035,
        "assumed_distribution_yield": 0.004,
        "price_return": 0.0525,
    }
    snap = {"spec_version": "<old-version>", "watchlist": {"entries": [entry]}}
    before = json.dumps(snap, sort_keys=True)
    text = scenario_model_gap(snap)
    for value in (
        "SMH",
        "QQQ",
        "6.00%",
        "0.35%",
        "0.40%",
        "5.25%",
        "No holdings-weighted reconciliation",
        "market-cap CAGR",
        "per-share",
        "one-year",
        "three-year CAGR",
    ):
        assert value in text
    assert "&lt;old-version&gt;" in text and "<old-version>" not in text
    assert json.dumps(snap, sort_keys=True) == before


def test_evidence_reads_source_tables_and_omits_operational_columns(tmp_path):
    for name in (FINAL, TOURNAMENT):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (ROOT / name).read_text(encoding="utf-8")
        target.write_text(text.replace("+5.4%", "+5.7%"), encoding="utf-8")
    data = read_evidence(tmp_path)
    assert data["available"]
    text = unescape(evidence_page(data))
    assert "+5.7%" in text and "+5.4%" not in text
    assert "No candidate passed" in text and "Acceptance rules (all must hold)" in text
    assert "test period was not untouched" in text
    assert "Account-limited" not in text and "$1,000" not in text
    assert not read_evidence(tmp_path / "missing")["available"]
