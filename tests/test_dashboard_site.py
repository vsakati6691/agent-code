"""Presentation and output guards for the built site (review of 2026-10-14)."""
from __future__ import annotations

import pytest

from agent_trading.dashboard import scoring
from agent_trading.dashboard.scenarios import implied_growth_text


# --- item 1: implied growth wording -----------------------------------------------------------

def test_implied_growth_reads_in_one_pass():
    assert implied_growth_text(1.35, 0.49) == "Price implies about 135%/yr revenue growth for 5 years vs 49% trailing"
    neg = implied_growth_text(-0.12, 0.08)
    assert neg.startswith("The price implies shrinking revenue") and "-" not in neg and "12%" in neg
    assert "could not be computed" in implied_growth_text(None, 0.1)
    assert implied_growth_text(0.2, None) == "Price implies about 20%/yr revenue growth for 5 years"


def test_counterargument_uses_the_plain_wording():
    m = {"implied_revenue_cagr": 1.35, "revenue_growth_ttm": 0.49, "implied_growth_gap": -0.86}
    sub = {k: 1.0 for c in scoring.spec.COMPONENTS for k in c.metrics}
    sub["implied_growth_gap"] = 0.0
    text = scoring.counterargument(sub, m, [])
    assert text == "Weakest evidence: Price implies about 135%/yr revenue growth for 5 years vs 49% trailing."
    assert "away from recent results" not in text


def test_bear_case_does_not_repeat_the_implied_growth_sentence():
    from agent_trading.dashboard.scenarios import bear_case
    m = {"implied_revenue_cagr": 1.35, "revenue_growth_ttm": 0.49, "implied_growth_gap": -0.86}
    counter = "Weakest evidence: " + implied_growth_text(1.35, 0.49) + "."
    assert bear_case(m, counter).count("Price implies") == 1
    assert bear_case(m, "Weakest evidence: leverage.").count("Price implies") == 1


# --- item 2 / item 12: output guards over the whole built site ----------------------------------

import re  # noqa: E402

from tests.dashboard_fixtures import demo_site  # noqa: E402

FORBIDDEN = [(r"\d[eE][-+]\d", "scientific notation"), (r"\bnan\b", "nan"), (r"\bNaN\b", "NaN"), (r"\bNone\b", "None"),
             (r"(?<![\w-])-?inf\b", "inf"), (r"\{", "brace")]


def visible_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return html


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    return demo_site(tmp_path_factory.mktemp("demo"))[1]


def test_no_raw_numbers_or_python_values_leak_into_pages_or_csv(site):
    problems = []
    for p in list(site.rglob("*.html")) + list(site.rglob("*.csv")):
        text = p.read_text(encoding="utf-8")
        body = visible_text(text) if p.suffix == ".html" else text
        for pattern, label in FORBIDDEN:
            m = re.search(pattern, body)
            if m:
                problems.append(f"{p.relative_to(site)}: {label}: ...{body[max(0, m.start() - 40):m.end() + 40]!r}")
    assert not problems, "\n".join(problems[:15])


def test_detail_page_inputs_are_rounded_percentages():
    from agent_trading.dashboard.fmt import metric
    assert metric("fcf_margin_change", 8.33e-17) == "+0.0%"
    assert metric("gross_margin", 0.53212) == "53.2%"
    assert metric("net_debt_to_ebitda", 0.123456) == "0.1235x"
    assert metric("fcf_growth_ttm", -1.0) == "not meaningful (negative base)"
    assert metric("log_market_cap", 9.6).endswith("market cap")


def test_net_debt_or_net_cash_never_both():
    from agent_trading.dashboard.fmt import net_position
    assert net_position(1.5e9) == "Net debt $1.5B" and net_position(-1.5e9) == "Net cash $1.5B"
    assert net_position(-2e8, False) == "net cash $200M" and net_position(None) == "Net debt n/a"


def test_pages_never_say_net_debt_net_cash(site):
    for p in site.rglob("*.html"):
        text = p.read_text(encoding="utf-8").lower()
        assert "net debt net cash" not in text and "net cash held -" not in text, p.name


def test_detail_page_keeps_list_title_casing(site):
    page = (site / "stock" / "large-S11.html").read_text(encoding="utf-8")
    assert "in the Large cap (S&amp;P 500 members) list" in page and "s&amp;p 500 members" not in page


def test_chart_ticks_are_round_numbers():
    from agent_trading.dashboard.site import nice_ticks
    assert nice_ticks(22, 1040) == [0, 250, 500, 750, 1000, 1250]
    assert nice_ticks(95, 140) == [90, 100, 110, 120, 130, 140]
    assert nice_ticks(70, 180) == [50, 75, 100, 125, 150, 175, 200]
    t = nice_ticks(22, 5040)
    assert t[0] <= 22 and t[-1] >= 5040 and all(v % 500 == 0 for v in t) and len(t) <= 7


def test_price_chart_axis_labels_are_round(site):
    page = (site / "stock" / "large-S11.html").read_text(encoding="utf-8")
    labels = [int(x) for x in re.findall(r'text-anchor="end" font-size="11" fill="var\(--text-muted\)">(-?\d+)</text>', page)]
    assert labels and all(v % 10 == 0 for v in labels)


@pytest.mark.parametrize("kind, signed, text", [
    ("call", 0.052, "+5.2% (stock must rise)"),
    ("call", -0.031, "already past breakeven (breakeven 3.1% below the stock)"),
    ("put", -0.052, "-5.2% (stock must fall)"),
    ("put", 0.020, "already past breakeven (breakeven 2.0% above the stock)"),
    ("put", 0.0, "already past breakeven (breakeven 0.0% above the stock)"),
])
def test_distance_to_breakeven_wording(kind, signed, text):
    from agent_trading.dashboard.site_options import distance_text
    assert distance_text(kind, signed) == text


def test_options_page_never_says_zero_move(site):
    page = (site / "options.html").read_text(encoding="utf-8")
    assert "0.0% down" not in page and "0.0% up" not in page and "Distance to breakeven" in page


def test_no_backslash_escapes_inside_html_attributes(site):
    for p in site.rglob("*.html"):
        assert "\\'" not in p.read_text(encoding="utf-8"), p.name     # a backslash before a quote


def test_tabs_are_not_silently_restored_and_follow_the_hash():
    from agent_trading.dashboard.assets import CSS, JS
    assert "localStorage.getItem('matrix'" not in JS and "localStorage.getItem('tab:" not in JS
    assert "history.replaceState(null, '', '#' + state.type + '-' + state.hz)" in JS
    assert 'aria-selected="true"] { background: var(--series-1)' in CSS and "underline" in CSS


def test_options_h2_names_the_active_choice(site):
    page = (site / "options.html").read_text(encoding="utf-8")
    assert re.search(r'<section data-hz="3m" data-type="call" hidden><h2>About 3 months · calls', page)


def _header_classes(page: str, table_id: str) -> list[tuple[str, str]]:
    m = re.search(r'<table id="' + re.escape(table_id) + r'".*?<thead><tr>(.*?)</tr></thead>', page, re.S)
    assert m, table_id
    return [(re.sub(r"<[^>]+>", "", label).strip(), cls) for cls, label in
            re.findall(r"<th class=['\"]([^'\"]*)['\"][^>]*>(.*?)</th>", m.group(1))]


def test_phone_width_keeps_only_the_named_columns(site):
    over = _header_classes((site / "index.html").read_text(encoding="utf-8"), "t-large")
    kept = [label for label, cls in over if "hide-sm" not in cls]
    assert kept == ["#", "Ticker / company / sector", "Price", "Score", "1Y", "Main risk / weakest evidence"]
    opt = _header_classes((site / "options.html").read_text(encoding="utf-8"), "o-3m-call")
    kept = [label for label, cls in opt if "hide-sm" not in cls]
    assert kept == ["#", "Underlying", "Expiry", "Strike", "Bid / ask", "Premium*", "Breakeven at expiry", "Research score"]


def test_ticker_column_is_sticky_in_every_wide_table(site):
    for page, tid in (("index.html", "t-large"), ("options.html", "o-3m-call"), ("watchlist.html", "t-watch")):
        assert any("tk" in cls.split() for _, cls in _header_classes((site / page).read_text(encoding="utf-8"), tid)), page


def _outside_details(html: str) -> str:
    return re.sub(r"(?s)<details\b.*?</details>", " ", html)


def test_long_paragraphs_are_folded_except_on_methodology(site):
    from agent_trading.dashboard import spec
    full = [spec.MULTIBAGGER_DEFINITION[:80], spec.PROBABILITY_STATEMENT[:80], spec.SCENARIO_METHOD[:80]]
    pages = [site / "index.html"] + list((site / "stock").glob("*.html"))
    for p in pages:
        text = p.read_text(encoding="utf-8").replace("&#x27;", "'")
        for f in full:
            assert f.replace("'", "'") not in _outside_details(text), (p.name, f[:30])
    meth = (site / "methodology.html").read_text(encoding="utf-8").replace("&#x27;", "'")
    assert all(f in _outside_details(meth) for f in full)
