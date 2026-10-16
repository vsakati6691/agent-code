"""Interactive scenario calculator: the published inputs and a reference implementation (spec 2026-10-14.5).

The browser calculator (assets.LAB_JS) runs the same arithmetic as `scenarios.scenario_table` on inputs a
visitor chooses; `run()` here is its line-for-line reference, tested to reproduce the published base case
when given the published inputs. Results are never stored, ranked or published.

The idea of explicit, bounded user assumptions with the formula shown next to the result, and a clear
"not a target price" note, is adapted from filingcopilot `src/filingcopilot/scenarios.py` (MIT,
https://github.com/francisown/filingcopilot at 80d3cb15d71b4b596b30de2502a73c215b535824). The formula itself is
this project's EV/Sales scenario method (spec.SCENARIO_METHOD).
"""

from __future__ import annotations

import math

from . import spec

FORMULA = (
    "value per share in year t = (revenue_t x EV/Sales_t + net cash) / shares_t, where revenue grows at a "
    "rate starting at your starting growth and fading each year toward the terminal rate, EV/Sales moves "
    "in a straight line from today's to your exit multiple, and shares grow at your dilution rate"
)


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def inputs(c: dict) -> dict | None:
    """Everything the calculator needs for one listed company, or None when no scenario was published."""
    sc, m = c.get("scenarios"), c.get("metrics") or {}
    if not sc or not all(
        _ok(x) and x > 0 for x in (c.get("price"), c.get("market_cap"), m.get("revenue_ttm"), m.get("ev_to_sales"))
    ):
        return None
    base = sc["base"]["assumptions"]
    years = sorted(int(y) for y in sc["base"]["years"])
    published = {
        "starting_revenue_growth": base["starting_revenue_growth"],
        "exit_ev_to_sales": base["exit_ev_to_sales"],
        "annual_dilution": base["annual_dilution"],
        "fcf_margin": base.get("fcf_margin_end"),
    }
    cases = {k: {str(y): sc[k]["years"][str(y)]["value_per_share"] for y in years} for k in ("bear", "base", "bull")}
    return {
        "ticker": c["ticker"],
        "price": c["price"],
        "price_date": c.get("price_date"),
        "shares": c["market_cap"] / c["price"],
        "revenue_ttm": m["revenue_ttm"],
        "ev_to_sales": m["ev_to_sales"],
        "net_cash": base["net_cash_held"],
        "fcf_margin_today": base.get("fcf_margin_start"),
        "years": years,
        "fade": spec.SCENARIO_GROWTH_FADE,
        "terminal": spec.SCENARIO_TERMINAL_GROWTH,
        "published": published,
        "cases": cases,
        "bounds": {
            k: [
                min(lo, published[k]) if _ok(published.get(k)) else lo,
                max(hi, published[k]) if _ok(published.get(k)) else hi,
            ]
            for k, (lo, hi) in ((k, v) for k, v in spec.SCENARIO_LAB_BOUNDS.items() if k != "note")
        },
        "note": spec.SCENARIO_LAB_BOUNDS["note"],
        "formula": FORMULA,
    }


def clamp(inp: dict, name: str, value: float) -> float:
    """Keep an input inside its bounds (widened to include the published value, so a reset always reproduces it)."""
    lo, hi = inp["bounds"][name]
    return min(hi, max(lo, value))


def run(inp: dict, choice: dict) -> dict:
    """{year: {revenue, ev_to_sales, shares, value_per_share, multiple_of_price, fcf, ev_to_fcf}} for `choice`."""
    g = clamp(inp, "starting_revenue_growth", choice["starting_revenue_growth"])
    exit_mult = clamp(inp, "exit_ev_to_sales", choice["exit_ev_to_sales"])
    d = clamp(inp, "annual_dilution", choice["annual_dilution"])
    margin = choice.get("fcf_margin")
    margin = clamp(inp, "fcf_margin", margin) if _ok(margin) else None
    m0 = inp.get("fcf_margin_today")
    horizon = max(inp["years"])
    out, rev = {}, inp["revenue_ttm"]
    for y in range(1, horizon + 1):
        rev *= 1 + g
        g += inp["fade"] * (inp["terminal"] - g)
        if y not in inp["years"]:
            continue
        frac = y / horizon
        mult = inp["ev_to_sales"] + (exit_mult - inp["ev_to_sales"]) * frac
        sh = inp["shares"] * (1 + d) ** y
        value = max(0.0, (rev * mult + inp["net_cash"]) / sh)
        mg = None if margin is None else (margin if not _ok(m0) else m0 + (margin - m0) * frac)
        fcf = None if mg is None else rev * mg
        out[y] = {
            "revenue": rev,
            "ev_to_sales": mult,
            "shares": sh,
            "value_per_share": value,
            "multiple_of_price": value / inp["price"],
            "fcf": fcf,
            "ev_to_fcf": (rev * mult / fcf) if fcf and fcf > 0 else None,
        }
    return out
