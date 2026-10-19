"""Explorer registration, deterministic selection, calculator mirror and public-site contract."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from collections import Counter
from datetime import timedelta

import pytest

from agent_trading.dashboard import assets_bets, bets, options, spec
from agent_trading.dashboard.refresh import run
from agent_trading.dashboard.refresh_store import MAX_DAY_BYTES
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.site_bets import bets_page
from tests.dashboard_fixtures import AS_OF, demo_site, option_row
from tests.spec_history import historical_reason
from tests.test_dashboard_refresh import NOW, RefreshProviders, weekly
from tests.test_dashboard_site import visible_text


def chain_rows(per_group=15):
    rows = []
    for _tier, delta in (("Core", 0.5), ("Long-shot", 0.2)):
        for kind in ("call", "put"):
            for days in (90, 180, 365):
                for ask in (0.5, 1.5, 3.5, 7.5, 15.0):
                    for i in range(per_group):
                        strike = 50 + len(rows) / 10
                        row = option_row(
                            "AAA",
                            AS_OF + timedelta(days=days),
                            strike,
                            ask * 0.98,
                            ask,
                            delta=delta if kind == "call" else -delta,
                            oi=1000 + i,
                            theta=-0.001,
                        )
                        row["type"] = kind
                        row["option"] = (
                            f"AAA{row['expiration']:%y%m%d}{'C' if kind == 'call' else 'P'}{int(strike * 1000):08d}"
                        )
                        rows.append(row)
    return rows


def under(symbol="AAA"):
    return {"symbol": symbol, "close": 100.0, "last_trade_time": f"{AS_OF}T16:00:00", "timestamp": f"{AS_OF} 22:17:00"}


def test_explorer_registration_has_fixed_rules_and_preserves_weekly_rules():
    assert spec.SPEC_VERSION == "2026-10-19.5"
    entry = historical_reason("2026-10-14.8")
    assert "registered before any explorer data" in entry
    assert spec.EXPLORER_BANDS == ("large", "ai_large", "ai_mid")
    assert spec.EXPLORER_LONG_RULES == {
        "min_delta": 0.10,
        "max_delta_exclusive": 0.30,
        "min_open_interest": 200,
        "min_volume": 10,
        "max_spread_pct": 0.20,
        "standard_multiplier": 100,
        "require_theta": True,
    }
    assert spec.EXPLORER_PER_BAND == 12
    assert spec.OPTION_RULES == {
        "max_per_type_per_horizon": 5,
        "max_per_underlying_per_horizon": 2,
        "min_open_interest": 500,
        "min_volume": 10,
        "max_spread_pct": 0.10,
        "min_delta": 0.30,
        "max_delta": 0.70,
        "standard_multiplier": 100,
        "max_quote_age_business_days": 0,
        "require_theta": True,
    }
    assert {k: v[0] for k, v in spec.OPTION_RANKING.items()} == {
        "liquidity": 0.45,
        "breakeven": 0.35,
        "time_decay": 0.20,
    }
    assert spec.spec_dict()["explorer"]["long_shot"] == spec.EXPLORER_LONG_RULES


@pytest.mark.parametrize(
    "delta,core,long",
    [
        (0.099, False, False),
        (0.10, False, True),
        (0.2999, False, True),
        (0.30, True, False),
        (0.70, True, False),
        (0.701, False, False),
    ],
)
@pytest.mark.parametrize("kind", ["call", "put"])
def test_tiers_are_disjoint_with_exact_delta_boundaries(delta, core, long, kind):
    row = option_row("AAA", AS_OF + timedelta(days=90), 100, 0.99, 1, delta=delta if kind == "call" else -delta)
    row["type"] = kind
    assert bets.eligible(row, "AAA", AS_OF, "Core")[0] == core
    assert bets.eligible(row, "AAA", AS_OF, "Long-shot")[0] == long


@pytest.mark.parametrize(
    "changes",
    [
        {"open_interest": 199},
        {"volume": 9},
        {"bid": 0},
        {"ask": 0.5},
        {"bid": 0.5},
        {"theta": None},
        {"theta": 0},
        {"theta": float("inf")},
        {"iv": 0},
        {"delta": -0.2},
        {"root": "AAA1"},
        {"expiration": AS_OF + timedelta(days=1)},
    ],
)
def test_long_shot_rejects_bad_markets_inputs_adjustments_and_short_dated(changes):
    row = option_row("AAA", AS_OF + timedelta(days=90), 110, 0.9, 1, delta=0.2, oi=200, vol=10)
    assert bets.eligible(row, "AAA", AS_OF, "Long-shot")[0]
    assert not bets.eligible({**row, **changes}, "AAA", AS_OF, "Long-shot")[0]


@pytest.mark.parametrize(
    "premium,band",
    [
        (99.99, "under100"),
        (100, "100to250"),
        (249.99, "100to250"),
        (250, "250to500"),
        (499.99, "250to500"),
        (500, "500to1000"),
        (1000, "500to1000"),
        (1000.01, "over1000"),
    ],
)
def test_premium_band_boundaries(premium, band):
    assert bets.premium_band(premium) == band


def test_720_contract_selection_is_deterministic_scored_and_fits_daily_budget(tmp_path):
    rows = chain_rows()
    chains = {"AAA": (under(), rows)}
    before = copy.deepcopy(chains)
    explorer = bets.build(chains, AS_OF, {})
    selected = bets.unpack(explorer)
    assert len(selected) == 720 and explorer["eligible_count"] == 900
    assert set(Counter((r["tier"], r["type"], r["horizon"], r["premium_band"]) for r in selected).values()) == {12}
    assert explorer == bets.build({"AAA": (under(), list(reversed(rows)))}, AS_OF, {})
    assert chains == before and len({r["option"] for r in selected}) == 720
    for key in {(r["tier"], r["type"], r["horizon"], r["premium_band"]) for r in selected}:
        group = [r for r in selected if (r["tier"], r["type"], r["horizon"], r["premium_band"]) == key]
        assert group == sorted(
            group, key=lambda r: (-r["score"], r["underlying"], r["expiration"], r["strike"], r["option"])
        )
    weekly(tmp_path)
    p = RefreshProviders()
    p.chains["AAA"] = chains["AAA"]
    out = run(tmp_path, p, AS_OF, now=NOW)
    assert out["status"] == "ok" and out["explorer"]["selected_count"] == 720
    folder = tmp_path / "daily" / str(AS_OF)
    assert sum(f.stat().st_size for f in folder.iterdir()) < MAX_DAY_BYTES
    assert len(bets_page({"as_of": str(AS_OF)}, {"data": out}).encode()) < 300_000


def test_explorer_math_matches_existing_research_rows_for_both_types():
    for raw in chain_rows(per_group=1):
        tier = "Core" if abs(raw["delta"]) >= 0.3 else "Long-shot"
        a = bets.research_row(raw, "AAA", 100, AS_OF, tier, [], False, options.quote_info(under(), AS_OF))
        b = options.research_row(raw, 100, AS_OF, "AAA", [], events_known=False)
        for key, old in [
            ("premium", "premium_per_contract_ask"),
            ("breakeven", "breakeven"),
            ("required_move", "required_move"),
            ("implied_move", "implied_move_1sd"),
        ]:
            assert a[key] == pytest.approx(b[old])
        assert a["score"] == options.rank_score(b)["total"] and a["events_status"] == "unknown"


def test_duplicate_occ_contracts_appear_once_and_failed_chains_add_nothing():
    row = chain_rows(per_group=1)[0]
    result = bets.build({"AAA": (under(), [row, row]), "FAIL": "budget spent"}, AS_OF, {})
    assert result["selected_count"] == 1


@pytest.mark.parametrize(
    "premium,budget,n",
    [(50, "200", 4), (100, "99.99", 0), (100, "100.00", 1), (33.33, "99.99", 3), (50.001, "100", 1), (0.1, "0.30", 3)],
)
def test_budget_filter_and_sizing(premium, budget, n):
    out = bets.size(premium, budget)
    assert out["contracts"] == n and out["max_loss_cents"] <= bets.budget_cents(budget)
    assert bets.within_budget(premium, budget) == (n > 0)


@pytest.mark.parametrize("budget", ["", "-1", "nan", "Infinity", "1e3", "12.345", "1000000000", "<script>"])
def test_invalid_budgets_do_not_become_zero_or_infinite_contracts(budget):
    assert bets.budget_cents(budget) is None
    assert bets.size(1, budget)["status"] == "invalid" and not bets.within_budget(1, budget)


def test_slip_total_adds_entire_premiums_before_fees():
    entries = [{"cost_cents": 5000, "quantity": 2}, {"cost_cents": 12500, "quantity": 1}]
    assert bets.slip_total(entries, "200") == {"status": "ok", "max_loss_cents": 22500, "over_budget": True}
    assert bets.slip_total(entries, "225")["over_budget"] is False
    assert bets.slip_total([], "100")["max_loss_cents"] == 0
    assert bets.slip_total([{"cost_cents": 10, "quantity": -1}], "100")["status"] == "invalid"


def test_browser_math_mirrors_python_reference(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed; Python reference and browser QA still cover arithmetic")
    cases = [
        [50, "200"],
        [33.33, "99.99"],
        [50.001, "100"],
        [1, ""],
        [1, "1e3"],
        [1, "12.345"],
        [1, "0"],
        [1, "1000000000"],
        [1, "１２"],
    ]
    entries = [{"cost_cents": 5000, "quantity": 2}, {"cost_cents": 12500, "quantity": 1}]
    code = (
        assets_bets.MATH_JS
        + "\nconsole.log(JSON.stringify({sizes:"
        + json.dumps(cases)
        + ".map(x=>BetMath.size(x[0],x[1])),slip:BetMath.slipTotal("
        + json.dumps(entries)
        + ',"200")}));'
    )
    path = tmp_path / "mirror.js"
    path.write_text(code)
    result = json.loads(subprocess.check_output([node, str(path)]))
    assert result == {"sizes": [bets.size(*args) for args in cases], "slip": bets.slip_total(entries, "200")}


@pytest.mark.parametrize("blocked,action", [(False, "save"), (True, "save"), (True, "clear")])
def test_storage_failure_is_not_reported_as_a_success(tmp_path, blocked, action):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed")
    payload = bets.build({"AAA": (under(), chain_rows(1)[:1])}, AS_OF, {})
    # Exercise the complete script's storage boundary; a tiny DOM stands in for the browser.
    setup = r"""
class Element {
  constructor() { this.dataset = {}; this.listeners = {}; this.children = []; this.value = ''; this.textContent = ''; }
  appendChild(child) { this.children.push(child); return child; }
  setAttribute() {}
  addEventListener(name,fn) { this.listeners[name] = fn; }
  dispatchEvent() {}
}
var elements = {};
var document = {
  getElementById: id => elements[id] || (elements[id] = new Element()),
  createElement: () => new Element(), createDocumentFragment: () => new Element()
};
document.getElementById('bets-table').tBodies = [new Element()];
document.getElementById('bet-quantity').value = '1';
var localStorage = {
  getItem: () => '[]',
  setItem: () => { if (blocked) throw Error('storage blocked'); },
  removeItem: () => { if (blocked) throw Error('storage blocked'); }
};
"""
    data = {"as_of": str(AS_OF), "columns": payload["columns"], "rows": payload["rows"]}
    code = "var blocked = " + json.dumps(blocked) + ";\n" + setup
    code += '\ndocument.getElementById("bets-data").textContent = ' + json.dumps(json.dumps(data)) + ";\n"
    code += assets_bets.JS
    code += '\nelements["bet-contract"].value = "0";\n'
    code += f'elements["bet-{action}"].listeners.click();\n'
    code += 'console.log(JSON.stringify(elements["bet-notice"].textContent));'
    path = tmp_path / "storage.js"
    path.write_text(code, encoding="utf-8")
    notice = json.loads(subprocess.check_output([node, str(path)]))
    if blocked:
        assert "could not be updated" in notice and "previously saved entries may return" in notice
        assert "Saved on this device" not in notice and "Local slip cleared" not in notice
    else:
        assert notice == "Saved on this device only. No order was sent."


def test_bets_page_has_labels_local_storage_warning_and_no_probability_estimate():
    explorer = bets.build({"AAA": (under(), chain_rows(1))}, AS_OF, {})
    data = {
        "as_of": str(AS_OF),
        "weekly_as_of": str(AS_OF),
        "status": "ok",
        "collected_at": f"{AS_OF}T22:17:00+00:00",
        "explorer": explorer,
    }
    page = bets_page({"as_of": str(AS_OF)}, {"data": data})
    text = visible_text(page)
    for phrase in (
        "Most I can lose on one bet",
        "Maximum loss",
        "Delta · not a probability",
        "Probability not established",
        "Nothing is uploaded",
        "betslip-v1",
        "Clear local slip",
        "Daily:",
        "Refresh details",
    ):
        assert phrase in text, phrase
    assert "most contracts" not in text and "chance of profit" not in text
    assert 'href="audit.html#daily-context"' in page
    assert '<tbody><tr><td data-label="Contract">AAA call' in page
    assert "first 25 contracts by premium" in page
    assert not re.search(r"Probability[^<]{0,80}\d+(?:\.\d+)?%", page)
    for field in ("bet-budget", "bet-contract", "bet-quantity"):
        assert f'for="{field}"' in page and f'id="{field}"' in page
    assert page.count('aria-live="polite"') >= 3 and 'data-sort="num"' in page
    for forbidden in ("fetch(", "XMLHttpRequest", "sendBeacon", "innerHTML"):
        assert forbidden not in assets_bets.JS
    assert "If every bet expires worthless you lose " in assets_bets.JS
    assert "td::before" in assets_bets.CSS and "data-label" in assets_bets.JS


def test_old_or_missing_daily_records_explain_explorer_unavailable():
    for context in (
        None,
        {},
        {"data": {"as_of": str(AS_OF), "status": "ok", "collected_at": f"{AS_OF}T22:17:00+00:00"}},
    ):
        page = bets_page({"as_of": str(AS_OF)}, context)
        assert "Explorer data unavailable" in page and "bets-data" not in page


def test_explorer_page_linked_and_older_snapshot_builds(tmp_path):
    data, out = demo_site(tmp_path, two_weeks=False)
    assert "Explorer data unavailable" in (out / "bets.html").read_text(encoding="utf-8")
    assert "small-bet-rules" in (out / "methodology.html").read_text(encoding="utf-8")
    assert all('href="bets.html"' in p.read_text(encoding="utf-8") for p in out.glob("*.html"))
    empty = tmp_path / "empty"
    build_site(empty, tmp_path / "empty-site")
    assert (tmp_path / "empty-site/bets.html").exists()
