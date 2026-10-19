"""Spec 2026-10-14.7: the AI page (two top-5 lists, top-20 market-cap scenario test, curated universe, private
companies), plus the page-weight, sortable-header and saved-view changes that shipped with it."""

from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd
import pytest

from agent_trading.dashboard import ai, spec
from agent_trading.dashboard.pipeline import run
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.store import Store
from agent_trading.dashboard.tradability import Tradability
from tests.dashboard_fixtures import (
    AS_OF,
    FAKE_AI_LARGE,
    FAKE_AI_MID,
    FAKE_AI_UNIVERSE,
    FakeProviders,
    add_ai_names,
    benchmarks,
    demo_site,
)
from tests.spec_history import historical_reason
from tests.test_dashboard_site import visible_text

# --- registration: a new, dated methodology version; nothing else moves ---------------------------------------------


def test_ai_lists_are_a_new_spec_version_with_the_existing_rules_untouched():
    assert spec.SPEC_VERSION == "2026-10-19.1"
    # The explorer is registered after AI; retain the exact original AI registration and every rule assertion.
    reason = historical_reason("2026-10-14.7")
    assert "AI" in reason and "registered before any snapshot" in reason
    assert "No probability" in reason and "unchanged" in reason
    bands = {b.key: b for b in spec.BANDS}
    assert list(bands) == ["large", "mid", "small", "multibagger", "ai_large", "ai_mid"]
    assert (
        bands["large"].max_results,
        bands["mid"].min_cap,
        bands["mid"].max_cap,
        bands["small"].min_cap,
        bands["multibagger"].max_results,
    ) == (10, 2e9, 10e9, 300e6, 5)
    big, mid = bands["ai_large"], bands["ai_mid"]
    assert (big.universe, big.min_cap, big.max_cap, big.max_results, big.profile) == ("ai", 10e9, None, 5, "standard")
    assert (mid.universe, mid.min_cap, mid.max_cap, mid.max_results, mid.profile) == ("ai", 2e9, 10e9, 5, "standard")
    assert big.gates == () and mid.gates == () and big.min_revenue_growth is None  # same scoring, no extra gate
    assert {k: v[0] for k, v in spec.OPTION_RANKING.items()} == {
        "liquidity": 0.45,
        "breakeven": 0.35,
        "time_decay": 0.20,
    }
    assert spec.spec_dict()["ai"]["universe"] and "AI" in spec.spec_dict()["bands"][4]["title"]


def test_the_ai_universe_is_unique_unleveraged_and_documented():
    tickers = [t for t, _ in spec.AI_UNIVERSE]
    assert len(tickers) == len(set(tickers)) >= 40
    assert {r for _, r in spec.AI_UNIVERSE} <= set(spec.AI_ROLES)
    assert not {"TQQQ", "SQQQ", "QQQ", "SMH", "SOXL", "BITX", "IBIT"} & set(tickers)  # stocks only
    assert {"NVDA", "MU", "MSFT", "PLTR", "CRWV", "VRT"} <= set(tickers)
    for text in (spec.AI_UNIVERSE_DEFINITION, spec.AI_TOP20_RULE, spec.AI_PRIVATE_RULE, spec.AI_PROBABILITY_NOTE):
        assert not re.search(r"\b[A-Z]{2,}_[A-Z_]{3,}\b", text), text  # no internal constant names on a public page
    assert "not a claim" in spec.AI_UNIVERSE_DEFINITION and "No probability" in spec.AI_PROBABILITY_NOTE


# --- universe resolution -------------------------------------------------------------------------------------------


def _dirs(rows):
    return pd.DataFrame(
        rows, columns=["ticker", "name", "exchange", "etf", "test_issue", "financial_status"]
    ).set_index("ticker")


def test_universe_resolution_uses_the_listing_and_registrant_checks(monkeypatch):
    monkeypatch.setattr(
        spec,
        "AI_UNIVERSE",
        (
            ("AAA", "Memory and storage"),
            ("ADR", "Accelerators and AI chips"),
            ("ETFX", "Cloud and platforms"),
            ("GONE", "Memory and storage"),
            ("NOSEC", "Cloud and platforms"),
            ("OTCX", "Cloud and platforms"),
        ),
    )
    dirs = _dirs(
        [
            ("AAA", "AAA Inc. Common Stock", "Nasdaq", False, False, ""),
            ("ADR", "ADR Holdings plc American Depositary Shares", "Nasdaq", False, False, ""),
            ("ETFX", "Some AI ETF", "NYSE Arca", True, False, ""),
            ("NOSEC", "NoSec Corp. Common Stock", "NYSE", False, False, ""),
            ("OTCX", "Otc Corp. Common Stock", "OTC", False, False, ""),
        ]
    )
    sec = pd.DataFrame([("AAA", 11, "AAA", "Nasdaq")], columns=["ticker", "cik", "name", "exchange"]).set_index(
        "ticker"
    )
    sp = pd.DataFrame([("AAA", "Information Technology")], columns=["ticker", "sector"]).set_index("ticker")
    rows, rejects = ai.resolve_universe(sec, dirs, sp)
    assert rows == [("AAA", 11, "AAA Inc. Common Stock", "Information Technology")]
    assert rejects["ADR"].startswith("not common stock") and rejects["ETFX"] == "ETF or fund"
    assert "not in the current exchange listings" in rejects["GONE"]
    assert rejects["NOSEC"] == "not in the SEC ticker file (no SEC registrant match)"
    assert "not an eligible exchange" in rejects["OTCX"]


# --- the top-20 market-cap bar and the scenario test ---------------------------------------------------------------

CAPS = {f"T{i}": (100 - i) * 1e9 for i in range(25)}  # T0 = $100B ... T24 = $76B


def test_size_ladder_finds_the_twentieth_largest_and_says_when_it_cannot():
    lad = ai.size_ladder(CAPS)
    assert (
        lad["available"] and lad["threshold"] == 81e9 and lad["threshold_ticker"] == "T19" and lad["n_with_cap"] == 25
    )
    assert [m["ticker"] for m in lad["members"][:3]] == ["T0", "T1", "T2"] and len(lad["members"]) == 25
    junk = {**CAPS, "NAN": float("nan"), "NEG": -5.0, "NONE": None, "ZERO": 0.0}
    assert ai.size_ladder(junk)["n_with_cap"] == 25  # non-finite, negative, zero and missing are ignored
    few = ai.size_ladder({"A": 1e9, "B": 2e9})
    assert not few["available"] and few["threshold"] is None and "fewer than 20" in few["reason"]
    assert len(ai.size_ladder({f"X{i}": 1e9 + i for i in range(60)})["members"]) == ai.LADDER_SIZE


def _cand(cap=20e9, shares=1e8):
    def yrs(v5, v10):
        return {"5": {"value_per_share": v5, "shares": shares}, "10": {"value_per_share": v10, "shares": shares}}

    return {
        "market_cap": cap,
        "scenarios": {
            "bear": {"years": yrs(100, 90)},
            "base": {"years": yrs(300, 500)},
            "bull": {"years": yrs(600, 1500)},
        },
    }


def test_top20_test_compares_scenario_market_caps_with_todays_bar():
    t = ai.top20_test(_cand(), ai.size_ladder(CAPS))
    assert t["status"] == "ok" and t["threshold"] == 81e9 and t["current_vs_threshold"] == pytest.approx(20e9 / 81e9)
    rows = {(r["case"], r["year"]): r for r in t["rows"]}
    assert len(rows) == 6
    assert rows[("bear", 5)]["market_cap"] == pytest.approx(10e9) and not rows[("bear", 5)]["above_today_bar"]
    assert rows[("base", 10)]["market_cap"] == pytest.approx(50e9) and rows[("base", 10)][
        "multiple_of_threshold"
    ] == pytest.approx(50 / 81)
    assert rows[("bull", 10)]["market_cap"] == pytest.approx(150e9) and rows[("bull", 10)]["above_today_bar"]
    assert "probab" not in json.dumps(t).lower()  # a scenario comparison, never a probability
    assert ai.top20_test({"market_cap": 1e9, "scenarios": None, "scenario_note": "no EV"}, ai.size_ladder(CAPS)) == {
        **ai.top20_test({"market_cap": 1e9, "scenarios": None}, ai.size_ladder(CAPS)),
        "reason": "no EV",
    }
    none = ai.top20_test(_cand(), ai.size_ladder({"A": 1e9}))
    assert none["status"] == "unavailable" and none["threshold"] is None and "fewer than 20" in none["reason"]


def test_private_valuation_placement_is_in_words_and_only_for_dollars():
    lad = ai.size_ladder(CAPS)
    usd = lambda v: {"valuation": v, "currency": "USD"}  # noqa: E731
    assert ai.place_in_ladder(usd(852), lad) == "above the largest S&P 500 member today (T0)"
    assert ai.place_in_ladder(usd(90), lad) == "between #10 (T9) and #11 (T10) among today's largest S&P 500 members"
    assert ai.place_in_ladder(usd(5), lad) == "below the 25th-largest S&P 500 member by market cap"
    assert ai.place_in_ladder({"valuation": 21, "currency": "EUR"}, lad) is None  # no exchange rate is collected
    assert ai.place_in_ladder({"valuation": None, "currency": None}, lad) is None
    assert ai.place_in_ladder(usd(90), {"members": []}) is None


# --- private companies: nothing without a source ---------------------------------------------------------------------


def test_the_shipped_private_company_file_is_fully_sourced():
    p = ai.load_private()
    names = [c["name"] for c in p["companies"]]
    assert {"OpenAI", "Anthropic (Claude)", "Databricks", "Mistral AI"} <= set(names)
    priced = [c for c in p["companies"] if c["valuation"] is not None]
    assert len(priced) >= 4
    for c in priced:
        assert c["source_url"].startswith("https://") and c["source_label"] and c["valuation_date"] and c["basis"]
        assert c["currency"] in ai.CURRENCIES and c["valuation"] > 0
    for c in p["companies"]:
        if c["valuation"] is None:
            assert c["no_valuation_reason"]
        if c.get("status_note"):
            assert c["status_source_url"].startswith("https://")
    assert "unverified" in p["note"] and "not a market capitalization" in p["note"]
    assert "probab" not in json.dumps(p).lower()


@pytest.mark.parametrize(
    "record, message",
    [
        (
            {"valuation": 10, "currency": "USD", "basis": "round", "valuation_date": "2026-01", "source_label": "X"},
            "needs source_url",
        ),
        (
            {
                "valuation": 10,
                "currency": "USD",
                "basis": "round",
                "valuation_date": "2026-01",
                "source_label": "X",
                "source_url": "http://example.com/a",
            },
            "https link",
        ),
        (
            {
                "valuation": 10,
                "currency": "JPY",
                "basis": "round",
                "valuation_date": "2026-01",
                "source_label": "X",
                "source_url": "https://example.com/a",
            },
            "currency",
        ),
        (
            {
                "valuation": -3,
                "currency": "USD",
                "basis": "r",
                "valuation_date": "2026-01",
                "source_label": "X",
                "source_url": "https://example.com/a",
            },
            "positive number",
        ),
        (
            {
                "valuation": 10,
                "currency": "USD",
                "basis": "r",
                "source_label": "X",
                "source_url": "https://example.com/a",
            },
            "needs valuation_date",
        ),
        ({"valuation": None}, "no_valuation_reason"),
        ({"valuation": None, "no_valuation_reason": "none", "status_note": "IPO filed"}, "status note needs"),
    ],
)
def test_a_private_valuation_without_a_source_and_date_is_rejected(tmp_path, record, message):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"companies": [{"name": "Acme AI", "what": "Makes things", **record}]}), encoding="utf-8")
    with pytest.raises(ai.PrivateConfigError, match=message):
        ai.load_private(f)


def test_private_file_refuses_account_like_fields_and_missing_files_are_empty(tmp_path):
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"companies": [], "positions": [1]}), encoding="utf-8")
    with pytest.raises(ai.PrivateConfigError, match="private-looking"):
        ai.load_private(f)
    assert ai.load_private(tmp_path / "missing.json")["companies"] == []


# --- the weekly run ------------------------------------------------------------------------------------------------------


@pytest.fixture
def prov():
    p = FakeProviders()
    benchmarks(p)
    for i in range(12):
        p.add(f"S{i:02d}", 100 + i, growth=0.05 + 0.04 * i, drift=0.0004 + 0.0001 * i, shares=5e8)
    return p


def _all_tradable(p):
    return Tradability.all_tradable(list(p.listed), "2026-10-08")


def test_run_lists_the_top_five_ai_stocks_per_band_with_roles_and_the_scenario_test(prov, monkeypatch):
    monkeypatch.setattr(spec, "AI_UNIVERSE", FAKE_AI_UNIVERSE)
    add_ai_names(prov)
    snap = run(prov, AS_OF, options_enabled=False, tradability=_all_tradable(prov))
    big, mid = snap["bands"]["ai_large"], snap["bands"]["ai_mid"]
    assert len(big["candidates"]) == 5 and len(mid["candidates"]) == 5
    assert all(c["market_cap"] >= 10e9 and c["band"] == "ai_large" for c in big["candidates"])
    assert all(2e9 <= c["market_cap"] < 10e9 and c["band"] == "ai_mid" for c in mid["candidates"])
    assert {c["ticker"] for c in big["candidates"]} <= set(FAKE_AI_LARGE) and {
        c["ticker"] for c in mid["candidates"]
    } <= set(FAKE_AI_MID)
    assert [c["rank"] for c in big["candidates"]] == [1, 2, 3, 4, 5]
    assert big["benchmark"] == "SPY" and mid["benchmark"] == "IJH" and big["profile"] == mid["profile"] == "standard"
    assert big["scenario_years"] == [1, 3, 5, 10]
    assert all(c["ai_role"] == "Accelerators and AI chips" for c in big["candidates"])
    ex = {x["ticker"]: x["reason"] for x in big["excluded"]}
    assert "not in the current exchange listings" in ex["AIGONE"] and "outside the band" in ex["AIM0"]
    ai_block = snap["ai"]
    assert ai_block["universe"]["defined"] == len(FAKE_AI_UNIVERSE) and "AIGONE" in ai_block["universe"]["unresolved"]
    assert ai_block["ladder"]["available"] and ai_block["ladder"]["n_with_cap"] == 22  # 12 members + 10 fillers
    assert ai_block["private"]["companies"] and "probab" not in json.dumps(ai_block["private"]).lower()
    for c in big["candidates"] + mid["candidates"]:
        t = c["top20_test"]
        assert t["status"] == "ok" and t["threshold"] == ai_block["ladder"]["threshold"] and len(t["rows"]) == 6
        for r in t["rows"]:
            assert r["above_today_bar"] == (r["market_cap"] >= t["threshold"])
    assert "probab" not in json.dumps({"big": big["candidates"][0]["top20_test"], "ladder": ai_block["ladder"]}).lower()


def test_without_twenty_sp500_members_the_bar_is_unavailable_and_says_why(prov, monkeypatch):
    monkeypatch.setattr(spec, "AI_UNIVERSE", FAKE_AI_UNIVERSE)
    add_ai_names(prov, fillers=0)  # only 12 S&P 500 members
    snap = run(prov, AS_OF, options_enabled=False, tradability=_all_tradable(prov))
    assert not snap["ai"]["ladder"]["available"] and snap["ai"]["ladder"]["threshold"] is None
    t = snap["bands"]["ai_large"]["candidates"][0]["top20_test"]
    assert t["status"] == "unavailable" and "fewer than 20" in t["reason"] and t["rows"] == []


def test_unverified_ai_stocks_are_excluded_and_queued_for_a_read_only_check(prov, monkeypatch):
    monkeypatch.setattr(spec, "AI_UNIVERSE", FAKE_AI_UNIVERSE)
    add_ai_names(prov)
    verified = [s for s in prov.listed if s not in ("AIL1", "AIL2")]
    todo: list = []
    snap = run(
        prov, AS_OF, options_enabled=False, tradability=Tradability.all_tradable(verified, "2026-10-08"), todo_out=todo
    )
    ex = {x["ticker"]: x["reason"] for x in snap["bands"]["ai_large"]["excluded"]}
    assert (
        ex["AIL1"] == "Robinhood tradability not yet verified"
        and ex["AIL2"] == "Robinhood tradability not yet verified"
    )
    assert {"AIL1", "AIL2"} <= {t["ticker"] for t in todo if t["band"] == "ai_large"}
    assert "AIL1" not in [c["ticker"] for c in snap["bands"]["ai_large"]["candidates"]]


def test_a_stock_on_two_lists_appears_once_in_the_earnings_panel(prov, monkeypatch):
    monkeypatch.setattr(spec, "AI_UNIVERSE", (("S11", "Cloud and platforms"), ("S10", "Cloud and platforms")))
    prov.earnings = pd.DataFrame({"symbol": ["S11"], "reportDate": [date(2026, 10, 30)]})
    snap = run(prov, AS_OF, options_enabled=False, tradability=_all_tradable(prov))
    assert "S11" in [c["ticker"] for c in snap["bands"]["large"]["candidates"]]
    assert "S11" in [c["ticker"] for c in snap["bands"]["ai_large"]["candidates"]]
    items = [i for i in snap["events"]["items"] if i["ticker"] == "S11"]
    assert len(items) == 1 and "large" in items[0]["list"] and "ai_large" in items[0]["list"]


def test_a_rejected_private_file_degrades_to_a_visible_problem_not_a_crash(prov, monkeypatch):
    monkeypatch.setattr(spec, "AI_UNIVERSE", FAKE_AI_UNIVERSE)
    add_ai_names(prov)
    monkeypatch.setattr(
        ai, "load_private", lambda *a, **k: (_ for _ in ()).throw(ai.PrivateConfigError("no source for X"))
    )
    snap = run(prov, AS_OF, options_enabled=False, tradability=_all_tradable(prov))
    assert snap["ai"]["private"]["companies"] == [] and snap["status"] == "partial"
    assert any("private-company file was rejected" in p and "no source for X" in p for p in snap["problems"])


# --- the site ----------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    return demo_site(tmp_path_factory.mktemp("ai"))


@pytest.fixture(scope="module")
def site(built):
    return built[1]


def test_the_ai_page_has_both_lists_the_scenario_test_the_universe_and_private_companies(site):
    page = (site / "ai.html").read_text(encoding="utf-8")
    assert page.count("<h1") == 1 and "aria-current=page>AI stocks<" in page
    for heading in (
        "AI large cap ($10B+): top 5",
        "AI mid cap ($2B-$10B): top 5",
        "Could they reach the top 20?",
        "The AI-exposed universe, by role",
        "Private AI companies, for context",
    ):
        assert heading in page.replace("&amp;", "&").replace("&#x27;", "'"), heading
    assert 'id="t-ai_large"' in page and 'id="t-ai_mid"' in page and "AI role: Accelerators and AI chips" in page
    text = visible_text(page)
    assert "Probability not established" in text and "not a forecast and not advice" in text
    assert not re.search(r"probab\w*[^.]{0,60}\d+\s?%", text, re.I)  # no probability percentage anywhere
    assert "20th-largest S&amp;P 500 member" in page and 'href="excluded-ai_large.html"' in page
    for t in FAKE_AI_LARGE[:1] + FAKE_AI_MID[:1] + ("AIGONE",):
        assert t in text
    assert (site / "excluded-ai_large.html").exists() and (site / "excluded-ai_mid.html").exists()
    assert (site / "downloads" / f"{AS_OF}_ai_large.csv").exists()


def test_private_companies_show_sources_dates_and_the_unverified_label(site):
    page = (site / "ai.html").read_text(encoding="utf-8")
    priced = [c for c in ai.load_private()["companies"] if c["valuation"] is not None]
    for c in priced:
        assert f'href="{c["source_url"]}" rel="noopener"' in page, c["name"]
        assert c["valuation_date"] in page
    assert page.count("reported, unverified") == len(priced)
    assert "Also watched: no corroborated valuation" in page and "Perplexity" in page
    assert "not compared: reported in EUR and no exchange rate is collected" in page  # Mistral
    assert "above the largest S&amp;P 500 member today" in page or "between #" in page  # a USD valuation is placed
    private = page[page.index('id="private"') :]
    assert "$" not in re.sub(
        r"\$\d[\d.,]*B|\$[\d.]+ billion", "", private.split("Also watched")[1]
    )  # no prices for unlisted names


def test_the_ai_lists_have_their_own_page_not_a_growth_tab(site):
    index = (site / "index.html").read_text(encoding="utf-8")
    growth = (site / "growth.html").read_text(encoding="utf-8")
    assert 'data-tab="ai_large"' not in growth and 'data-tab="ai_mid"' not in growth
    assert 'data-list="ai_large"' not in growth and 'data-list="ai_mid"' not in growth
    assert 'href="../ai.html#ai_large"' in (site / "stock" / "ai_large-AIL6.html").read_text(encoding="utf-8")
    assert 'id="ai_large"' in (site / "ai.html").read_text(encoding="utf-8")
    assert 'id="ai-stocks"' in index and 'href="ai.html"' in index and 'href="stock/ai_large-AIL6.html"' in index
    nav = re.search(r"<nav\b[^>]*>(.*?)</nav>", index, re.S).group(1)
    assert nav.index("AI stocks") < nav.index("Options")
    detail = (site / "stock" / "ai_large-AIL6.html").read_text(encoding="utf-8")
    assert "Top-20 market-cap scenario test" in detail and "Today's bar" in detail
    assert "Top-20 market-cap scenario test" not in (site / "stock" / "large-S11.html").read_text(encoding="utf-8")
    assert "AI large cap" in (site / "symbol" / "AIL6.html").read_text(encoding="utf-8")
    assert "ai_large" in (site / "data" / "schema.json").read_text(encoding="utf-8")
    snap = json.loads((site / "data" / "latest.json").read_text())
    assert set(snap) <= set(json.loads((site / "data" / "schema.json").read_text())["properties"])


def test_methodology_registers_the_ai_universe_and_rules(site):
    page = (site / "methodology.html").read_text(encoding="utf-8")
    assert 'id="ai"' in page and "2026-10-14.7" in page and "Registered AI universe" in page
    assert "AMD, AVGO" in page.replace("NVDA, ", "") or "NVDA, AMD, AVGO" in page


def test_a_snapshot_from_before_the_ai_lists_renders_an_explanation_not_an_error(built, tmp_path):
    data, _ = built
    store = Store(data)
    snap = store.load(store.dates()[-1])
    for key in ("ai_large", "ai_mid"):
        snap["bands"].pop(key)
    snap["ai"], snap["spec_version"] = None, "2026-10-14.6"
    old = Store(tmp_path / "old")
    old.write_snapshot(snap, "test")
    out = tmp_path / "site"
    build_site(tmp_path / "old", out)
    page = (out / "ai.html").read_text(encoding="utf-8")
    assert (
        "No AI lists in this snapshot" in page and "2026-10-14.6" in page and "The AI-exposed universe, by role" in page
    )
    index = (out / "index.html").read_text(encoding="utf-8")
    assert 'id="ai-stocks"' not in index and 'href="ai.html"' in index  # linked from the menu only
    assert not (out / "excluded-ai_large.html").exists()


# --- page weight: evidence rows load on demand ------------------------------------------------------------------------------


def test_list_pages_carry_placeholders_and_each_evidence_block_is_a_small_file(site):
    for name, _keys in (("growth.html", ("large", "mid", "small")), ("ai.html", ("ai_large", "ai_mid"))):
        page = (site / name).read_text(encoding="utf-8")
        assert 'class="evidence"' not in page, name  # the evidence moved out of the page
        sources = re.findall(r'class="lazy" data-src="([^"]+)"\s+data-page="([^"]+)"', page)
        assert len(sources) >= 10, name
        for src, link in sources:
            assert (site / src).exists() and (site / link).exists(), (src, link)
            body = json.loads((site / src).read_text(encoding="utf-8"))
            assert set(body) == {"html"} and 'class="evidence"' in body["html"] and link in body["html"]
            assert (site / src).stat().st_size < 12_000
    names = {p.stem for p in (site / "fragments").glob("*.json")}
    assert {"large-S11", "ai_large-AIL6", "ai_mid-AIM5"} <= names and not any(
        n.startswith("multibagger") for n in names
    )


def test_evidence_fragments_obey_the_same_output_guards_as_pages(site):
    forbidden = [
        (r"\d[eE][-+]\d", "scientific notation"),
        (r"\bnan\b", "nan"),
        (r"\bNaN\b", "NaN"),
        (r"\bNone\b", "None"),
        (r"(?<![\w-])-?inf\b", "inf"),
    ]
    problems = []
    for p in (site / "fragments").glob("*.json"):
        body = visible_text(json.loads(p.read_text(encoding="utf-8"))["html"])
        problems += [f"{p.name}: {label}" for pattern, label in forbidden if re.search(pattern, body)]
    assert not problems, problems[:10]


def test_the_overview_is_far_lighter_than_with_inline_evidence(site):
    from agent_trading.dashboard.site_overview import evidence_fragments

    snap = json.loads((site / "data" / "latest.json").read_text())
    inline = sum(
        len(json.loads(v)["html"].encode())
        for v in evidence_fragments({k: b for k, b in snap["bands"].items() if k in ("large", "mid", "small")}).values()
    )
    now = (site / "index.html").stat().st_size
    assert inline > 30_000 and now < 150_000
    assert now + inline > now * 1.25  # the page used to carry that weight itself


# --- sortable headers and saved views (browser script contracts; behaviour was checked in a browser) -----------------------


def test_sortable_headers_are_buttons_that_announce_and_saved_views_are_visible_and_resettable():
    from agent_trading.dashboard.assets import CSS, JS

    assert "document.createElement('button')" in JS and "btn.className = 'sortbtn'" in JS
    assert (
        "setAttribute('aria-sort', dir > 0 ? 'ascending' : 'descending')" in JS
        and "th.removeAttribute('tabindex')" not in JS
    )
    assert "setAttribute('role', 'status')" in JS and "'Sorted by ' + view.label" in JS
    assert "th.setAttribute('tabindex', '0')" not in JS  # the th is no longer the control
    assert "'view:' + location.pathname + ':' + table.id" in JS and "reset.textContent = 'Reset view'" in JS
    assert "Saved view restored for this table" in JS and "remember(key, isDefault() ? null : view)" in JS
    assert "try { if (value === null) localStorage.removeItem(key)" in JS and "catch (e) {}" in JS
    assert (
        "localStorage.getItem('matrix'" not in JS and "localStorage.getItem('tab:" not in JS
    )  # tabs are still not restored
    assert "lazy[data-src]" in JS and "fetch(box.dataset.src" in JS and "Open the full research page" in JS
    assert (
        "th[data-sort] .sortbtn" in CSS
        and 'th[aria-sort="descending"] .sortbtn::after' in CSS
        and ".sortbtn:focus-visible" in CSS
    )


def test_the_merged_table_script_keeps_both_the_scanner_features_and_the_saved_views():
    """The daily scan (PR #20: filter selects, empty state, Reset filters, pinned tickers, missing numbers last) and the
    saved views (PR #21) share one table script; losing either half would break the other page."""
    from agent_trading.dashboard.assets import JS

    assert JS.count("document.querySelectorAll('table[data-table]')") == 1  # one script, not two competing ones
    # from the scan: filters, empty message, its own reset button, the pins event, missing numbers sort last
    assert (
        "[data-filter=\"' + table.id" in JS
        and "[data-empty=\"' + table.id" in JS
        and "[data-reset=\"' + table.id" in JS
    )
    assert "document.addEventListener('pinschange', filter)" in JS and "if (isNaN(x)) return isNaN(y) ? 0 : 1;" in JS
    assert "empty.hidden = shown > 0" in JS and "f.value = ''" in JS
    # from the saved views: filter values are saved and restored only when the option still exists, and a table that
    # has its own reset button does not also get a second "Reset view" link
    assert "view.f[f.dataset.field] = f.value" in JS and "saved.f[f.dataset.field]" in JS
    assert "var reset = ownReset;" in JS and "if (!ownReset) reset.hidden = isDefault();" in JS
    assert "<<<<<<<" not in JS and ">>>>>>>" not in JS and "research-pins-v1" in JS
