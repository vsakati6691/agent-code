"""Raw metrics, component scores, evidence confidence and the strongest counterargument.

Rules come from spec.py and are applied mechanically:
* every sub-metric maps to 0..1 on a fixed scale;
* a missing sub-metric scores 0 and is listed; weights are never redistributed;
* a stock with a critical component entirely missing, or more than
  MAX_MISSING_METRICS missing sub-metrics, is not ranked (it is listed as excluded);
* ties break on the growth component, then ticker, so ranks are deterministic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import spec
from .fundamentals import Fundamentals, cash_like, growth, total_debt, ttm


def scale(value: float | None, s: spec.Scale) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    t = (value - s.lo) / (s.hi - s.lo)
    t = min(1.0, max(0.0, t))
    return 1.0 - t if s.reverse else t


# --- raw metrics ---------------------------------------------------------------------------

def price_return(close: pd.Series, start_back: int, end_back: int = 0) -> float | None:
    """Return from `start_back` bars before the last bar to `end_back` bars before it."""
    if len(close) <= start_back:
        return None
    a, b = float(close.iloc[-1 - start_back]), float(close.iloc[-1 - end_back])
    return b / a - 1 if a > 0 else None


def implied_revenue_cagr(ev: float | None, revenue: float | None) -> float | None:
    p = spec.IMPLIED_GROWTH
    if ev is None or revenue is None or revenue <= 0 or ev <= 0:
        return None
    ratio = ev * (1 + p["discount_rate"]) ** p["years"] / (revenue * p["exit_ev_sales"])
    return ratio ** (1 / p["years"]) - 1


def compute_metrics(f: Fundamentals, close: pd.Series, bench: pd.Series | None, market_cap: float | None) -> dict:
    fl = f.flows
    rev = fl["revenue"]
    m: dict[str, float | None] = {}
    rev_ttm, rev_prev = ttm(rev), ttm(rev, 4)
    m["revenue_ttm"] = rev_ttm
    m["revenue_growth_ttm"] = growth(rev_ttm, rev_prev)
    rev_3y = ttm(rev, 12)
    m["revenue_cagr_3y"] = ((rev_ttm / rev_3y) ** (1 / 3) - 1) if rev_ttm and rev_3y and rev_3y > 0 and rev_ttm > 0 else None
    yoy = [growth(rev[i], rev[i + 4]) if i + 4 < len(rev) else None for i in range(8)]
    known = [g for g in yoy if g is not None]
    m["growth_consistency"] = sum(g > 0 for g in known) / 8 if len(known) == 8 else None
    m["growth_acceleration"] = yoy[0] - yoy[4] if yoy[0] is not None and len(yoy) > 4 and yoy[4] is not None else None

    oi, oi_prev = ttm(fl["operating_income"]), ttm(fl["operating_income"], 4)
    ocf, ocf_prev = ttm(fl["ocf"]), ttm(fl["ocf"], 4)
    capex, capex_prev = ttm(fl["capex"]), ttm(fl["capex"], 4)
    fcf = ocf - capex if ocf is not None and capex is not None else None
    fcf_prev = ocf_prev - capex_prev if ocf_prev is not None and capex_prev is not None else None
    m["operating_income_ttm"], m["fcf_ttm"] = oi, fcf
    # growth on a non-positive base is "not meaningful" -> scored 0, but it is not missing
    m["operating_income_growth_ttm"] = growth(oi, oi_prev) if oi_prev is not None and oi is not None else None
    if oi_prev is not None and oi is not None and oi_prev <= 0:
        m["operating_income_growth_ttm"] = -1.0
    m["fcf_growth_ttm"] = growth(fcf, fcf_prev) if fcf_prev is not None and fcf is not None else None
    if fcf_prev is not None and fcf is not None and fcf_prev <= 0:
        m["fcf_growth_ttm"] = -1.0
    m["fcf_margin"] = fcf / rev_ttm if fcf is not None and rev_ttm else None
    m["fcf_margin_change"] = (m["fcf_margin"] - fcf_prev / rev_prev
                              if m["fcf_margin"] is not None and fcf_prev is not None and rev_prev else None)

    gp = ttm(fl["gross_profit"])
    m["gross_margin"] = gp / rev_ttm if gp is not None and rev_ttm else None
    m["operating_margin"] = oi / rev_ttm if oi is not None and rev_ttm else None
    inst = f.instants
    debt, cash = total_debt(inst), cash_like(inst)
    eq = inst.get("equity")
    invested = (debt or 0.0) + eq - (cash or 0.0) if eq is not None else None
    m["roic"] = oi * (1 - spec.ROIC_TAX_RATE) / invested if oi is not None and invested and invested > 0 else None
    ni = ttm(fl["net_income"])
    m["net_income_ttm"] = ni
    m["accruals"] = (ni - ocf) / inst["assets"] if ni is not None and ocf is not None and inst.get("assets") else None

    dna = ttm(fl["dna"])
    ebitda = oi + dna if oi is not None and dna is not None else None
    net_debt = (debt or 0.0) - (cash or 0.0) if (debt is not None or cash is not None) else None
    m["net_debt"] = net_debt
    if net_debt is None:
        m["net_debt_to_ebitda"] = None
    elif net_debt <= 0:
        m["net_debt_to_ebitda"] = 0.0
    elif ebitda is not None and ebitda > 0:
        m["net_debt_to_ebitda"] = net_debt / ebitda
    else:
        m["net_debt_to_ebitda"] = float("inf") if ebitda is not None else None
    ca, cl = inst.get("current_assets"), inst.get("current_liabilities")
    m["current_ratio"] = ca / cl if ca is not None and cl else None
    sh = f.diluted_shares
    m["dilution"] = sh[0] / sh[4] - 1 if len(sh) > 4 and sh[0] and sh[4] else None
    sbc = ttm(fl["sbc"])
    m["sbc_to_revenue"] = sbc / rev_ttm if sbc is not None and rev_ttm else None

    ev = market_cap + (net_debt or 0.0) if market_cap is not None else None
    m["market_cap"], m["enterprise_value"] = market_cap, ev
    ev_s = ev / rev_ttm if ev is not None and rev_ttm and rev_ttm > 0 else None
    m["ev_to_sales"] = ev_s
    g = m["revenue_growth_ttm"]
    if ev_s is None or g is None:
        m["ev_to_sales_per_growth"] = None
    else:
        m["ev_to_sales_per_growth"] = ev_s / (g * 100) if g > 0 else float("inf")
    m["fcf_yield"] = fcf / market_cap if fcf is not None and market_cap else None
    m["pe"] = market_cap / ni if market_cap and ni and ni > 0 else None
    imp = implied_revenue_cagr(ev, rev_ttm)
    m["implied_revenue_cagr"] = imp
    m["implied_growth_gap"] = g - imp if g is not None and imp is not None else None

    m["return_12_1"] = price_return(close, 252, 21)
    for key, n in (("6m", 126), ("12m", 252)):
        r = price_return(close, n)
        b = price_return(bench, n) if bench is not None else None
        m[f"return_{key}"] = r
        m[f"excess_{key}"] = r - b if r is not None and b is not None else None
    return m


# --- scoring --------------------------------------------------------------------------------

@dataclass
class Score:
    ticker: str
    composite: float | None
    components: dict[str, float | None]
    sub_scores: dict[str, float]
    missing: list[str]
    excluded_reason: str | None
    confidence: float
    confidence_label: str
    counterargument: str
    rank: int | None = None
    flags: list[str] = field(default_factory=list)


def confidence(metrics_present: float, f: Fundamentals | None, flags: list[str]) -> tuple[float, str]:
    c = metrics_present
    if f is not None and f.any_derived():
        c *= 0.85
    if any(fl.startswith("limited") for fl in flags):
        c *= 0.8
    if "shares from weighted-average fallback" in flags:
        c *= 0.9
    if "latest filing older than 120 days" in flags:
        c *= 0.9
    return round(c, 3), ("high" if c >= 0.8 else "medium" if c >= 0.6 else "low")


COUNTER_TEXT = {   # neutral wording: the weakest input is not always "bad", only the weakest
    "revenue_growth_ttm": "Weakest evidence: trailing revenue growth ({v:+.0%}).",
    "revenue_cagr_3y": "Weakest evidence: three-year revenue growth ({v:+.0%} a year), so the growth record is short or uneven.",
    "growth_consistency": "Weakest evidence: only {v:.0%} of the last 8 quarters grew year over year.",
    "growth_acceleration": "Weakest evidence: revenue growth changed {v:+.0%} vs a year earlier (deceleration risk).",
    "operating_income_growth_ttm": "Weakest evidence: operating income growth ({v:+.0%}).",
    "fcf_growth_ttm": "Weakest evidence: free-cash-flow growth ({v:+.0%}).",
    "fcf_margin_change": "Weakest evidence: free-cash-flow margin changed {v:+.1%} in a year.",
    "gross_margin": "Weakest evidence: gross margin ({v:.0%}).",
    "operating_margin": "Weakest evidence: operating margin ({v:.0%}).",
    "roic": "Weakest evidence: return on invested capital ({v:.0%}).",
    "accruals": "Weakest evidence: earnings vs operating cash flow (accruals {v:+.1%} of assets).",
    "net_debt_to_ebitda": "Weakest evidence: leverage (net debt {v:.1f}x EBITDA).",
    "current_ratio": "Weakest evidence: liquidity (current ratio {v:.2f}).",
    "dilution": "Weakest evidence: share count changed {v:+.1%} in a year.",
    "sbc_to_revenue": "Weakest evidence: stock-based compensation ({v:.0%} of revenue).",
    "ev_to_sales_per_growth": "Weakest evidence: valuation for the growth delivered (EV/Sales per point of growth {v:.2f}).",
    "fcf_yield": "Weakest evidence: free-cash-flow yield ({v:.1%}).",
    "implied_growth_gap": "Weakest evidence: the price implies revenue growth {v:+.0%} away from recent results "
                          "(negative = the price assumes faster growth).",
    "return_12_1": "Weakest evidence: price momentum ({v:+.0%} over 12-1 months).",
    "excess_6m": "Weakest evidence: six-month return relative to the benchmark ({v:+.0%}).",
    "excess_12m": "Weakest evidence: twelve-month return relative to the benchmark ({v:+.0%}).",
}


def counterargument(sub: dict[str, float], metrics: dict, missing: list[str]) -> str:
    """The weakest scored evidence, weighted by its component weight; missing critical data first."""
    weights = {m: c.weight / len(c.metrics) for c in spec.COMPONENTS for m in c.metrics}
    crit_missing = [m for m in missing if any(m in c.metrics and c.critical for c in spec.COMPONENTS)]
    if crit_missing:
        return f"Key evidence is missing ({', '.join(crit_missing)}), so the score may overstate the case."
    present = [(weights[m] * (1 - s), m) for m, s in sub.items() if m not in missing]
    if not present:
        return "Too little evidence to judge."
    _, worst = max(present)
    v = metrics.get(worst)
    text = COUNTER_TEXT[worst]
    if isinstance(v, (int, float)) and math.isfinite(v) and v != -1.0:
        try:
            return text.format(v=v)
        except (TypeError, ValueError):
            pass
    if worst in ("operating_income_growth_ttm", "fcf_growth_ttm") and v == -1.0:
        return f"Weakest evidence: {'operating income' if worst.startswith('operating') else 'free cash flow'} "                "was zero or negative a year ago, so its growth is not meaningful."
    if worst == "net_debt_to_ebitda" and isinstance(v, float) and not math.isfinite(v):
        return "Weakest evidence: net debt with zero or negative EBITDA."
    if worst == "ev_to_sales_per_growth" and isinstance(v, float) and not math.isfinite(v):
        return "Weakest evidence: revenue is not growing, so EV/Sales is not supported by growth."
    return text.split(" (")[0].rstrip(".") + "."


def score_one(ticker: str, metrics: dict, f: Fundamentals | None, flags: list[str]) -> Score:
    sub: dict[str, float] = {}
    missing: list[str] = []
    comps: dict[str, float | None] = {}
    crit_missing = []
    for c in spec.COMPONENTS:
        vals = []
        for name, s in c.metrics.items():
            raw = metrics.get(name)
            if raw is None or (isinstance(raw, float) and math.isnan(raw)):
                missing.append(name)
                sub[name] = 0.0
            else:
                sub[name] = scale(raw, s)
            vals.append(sub[name])
        all_missing = all(n in missing for n in c.metrics)
        comps[c.key] = None if all_missing else float(np.mean(vals))
        if all_missing and c.critical:
            crit_missing.append(c.title)
    reason = None
    if crit_missing:
        reason = "missing critical data: " + "; ".join(crit_missing)
    elif len(missing) > spec.MAX_MISSING_METRICS:
        reason = f"too little evidence: {len(missing)} of {len(sub)} sub-metrics missing"
    composite = None if reason else round(100 * sum(
        c.weight * (comps[c.key] or 0.0) for c in spec.COMPONENTS), 2)
    conf, label = confidence(1 - len(missing) / len(sub), f, flags)
    return Score(ticker, composite, comps, sub, missing, reason, conf, label,
                 counterargument(sub, metrics, missing), flags=list(flags))


def rank(scores: list[Score]) -> list[Score]:
    """Assign ranks 1..n to scored stocks; deterministic tie-breaks (spec.TIE_BREAK)."""
    ranked = sorted([s for s in scores if s.composite is not None],
                    key=lambda s: (-s.composite, -(s.components.get("growth") or 0.0), s.ticker))
    for i, s in enumerate(ranked, 1):
        s.rank = i
    return ranked
