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
