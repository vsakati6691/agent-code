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


def test_detail_page_keeps_list_title_casing(site):
    page = (site / "stock" / "large-S11.html").read_text(encoding="utf-8")
    assert "in the Large cap (S&amp;P 500 members) list" in page and "s&amp;p 500 members" not in page
