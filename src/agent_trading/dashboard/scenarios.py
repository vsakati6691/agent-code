"""Bear / base / bull valuation ranges and the rule-based research narrative.

Values are conditional on the explicit assumptions returned with them
(spec.SCENARIO_METHOD). They are not forecasts, targets, maxima or probabilities.
"""
from __future__ import annotations

import math

import pandas as pd

from . import spec


def growth_path(start: float, years: int) -> list[float]:
    """Annual growth rates for years 1..n: the start rate fading toward the terminal rate."""
    g, out = start, []
    for _ in range(years):
        out.append(g)
        g += spec.SCENARIO_GROWTH_FADE * (spec.SCENARIO_TERMINAL_GROWTH - g)
    return out


def scenario_table(price: float, shares: float, revenue_ttm: float, revenue_growth: float, ev_to_sales: float,
                   net_cash: float, fcf_margin: float | None, dilution: float | None) -> dict:
    """{scenario: {"assumptions": {...}, "years": {1: {...}, 3: {...}, 5: {...}}}}."""
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (price, shares, revenue_ttm, ev_to_sales)):
        raise ValueError("scenario inputs must be finite numbers")
    if price <= 0 or shares <= 0 or revenue_ttm <= 0 or ev_to_sales <= 0:
        raise ValueError("price, shares, revenue and EV/Sales must be positive")
    base_g = min(spec.SCENARIO_GROWTH_CAP, max(spec.SCENARIO_GROWTH_FLOOR, revenue_growth))
    dil = dilution if dilution is not None and math.isfinite(dilution) else 0.0
    margin = fcf_margin if fcf_margin is not None and math.isfinite(fcf_margin) else None
    horizon = max(spec.SCENARIO_YEARS)
    out = {}
    for rule in spec.SCENARIOS:
        g0 = max(spec.SCENARIO_GROWTH_FLOOR, base_g * rule.growth_multiplier + rule.growth_shift)
        path = growth_path(g0, horizon)
        exit_mult = max(spec.SCENARIO_MIN_EV_SALES, ev_to_sales * rule.exit_multiple_factor)
        d = dil + rule.dilution_shift
        years = {}
        rev = revenue_ttm
        for y in range(1, horizon + 1):
            rev *= 1 + path[y - 1]
            if y not in spec.SCENARIO_YEARS:
                continue
            frac = y / horizon
            mult = ev_to_sales + (exit_mult - ev_to_sales) * frac
            sh = shares * (1 + d) ** y
            equity = rev * mult + net_cash
            value = max(0.0, equity / sh)
            years[y] = {
                "revenue": rev, "ev_to_sales": mult, "shares": sh, "value_per_share": value,
                "multiple_of_price": value / price,
                "annualized": (value / price) ** (1 / y) - 1 if value > 0 else -1.0,
                "fcf_margin": None if margin is None else margin + rule.margin_shift * frac,
            }
        out[rule.key] = {
            "assumptions": {
                "starting_revenue_growth": g0, "growth_path": path, "exit_ev_to_sales": exit_mult,
                "annual_dilution": d, "fcf_margin_start": margin,
                "fcf_margin_year5": None if margin is None else margin + rule.margin_shift,
                "net_cash_held": net_cash,
            },
            "years": years,
        }
    bull5 = out["bull"]["years"][horizon]["multiple_of_price"]
    out["flags"] = {"bull_doubles_in_5y": bull5 >= 2.0, "bull_multibagger_5y": bull5 >= 5.0}
    return out


# --- price history ---------------------------------------------------------------------------

def max_drawdown(close: pd.Series) -> tuple[float, str | None, str | None]:
    """(max drawdown, peak date, trough date) of a price series."""
    if close.empty:
        return 0.0, None, None
    peak = close.cummax()
    dd = close / peak - 1
    trough = dd.idxmin()
    peak_date = close.loc[:trough].idxmax()
    return float(dd.min()), str(peak_date.date()), str(trough.date())


def history_stats(close: pd.Series, bench: pd.Series | None) -> dict:
    """Trailing price returns vs benchmark and drawdowns. Price returns (dividends excluded)."""
    out = {"returns": {}, "drawdowns": {}}
    for key, n in (("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252), ("3y", 756), ("5y", 1260)):
        if len(close) > n:
            r = float(close.iloc[-1] / close.iloc[-1 - n] - 1)
            b = None
            if bench is not None:
                aligned = bench.reindex(close.index).ffill()
                if len(aligned.dropna()) > n and aligned.iloc[-1 - n] > 0:
                    b = float(aligned.iloc[-1] / aligned.iloc[-1 - n] - 1)
            out["returns"][key] = {"stock": r, "benchmark": b, "excess": None if b is None else r - b}
        else:
            out["returns"][key] = None
    five = close.iloc[-1261:]
    mdd, peak, trough = max_drawdown(five)
    out["drawdowns"]["max_5y"] = {"value": mdd, "peak": peak, "trough": trough}
    out["drawdowns"]["from_52w_high"] = float(close.iloc[-1] / close.iloc[-252:].max() - 1)
    yearly = close.iloc[::252]
    if len(yearly) > 1:
        out["drawdowns"]["worst_1y_return"] = float((close / close.shift(252) - 1).min())
    out["bars"] = len(close)
    out["first_date"] = str(close.index[0].date())
    return out


def chart_series(close: pd.Series, bench: pd.Series | None, bars: int = 1260, step: int = 5) -> dict:
    """Weekly-sampled, rebased-to-100 series for the detail-page chart."""
    c = close.iloc[-bars - 1:]       # same base bar as the 5-year return in history_stats
    idx = c.index[::step].append(c.index[-1:]).unique()
    out = {"dates": [str(d.date()) for d in idx], "stock": [round(float(c.loc[d] / c.iloc[0] * 100), 2) for d in idx]}
    if bench is not None:
        b = bench.reindex(c.index).ffill()
        if b.notna().all() and b.iloc[0] > 0:
            out["benchmark"] = [round(float(b.loc[d] / b.iloc[0] * 100), 2) for d in idx]
    return out


# --- narrative ---------------------------------------------------------------------------------

def _pct(v, fmt="{:.0%}"):
    return "n/a" if v is None or not isinstance(v, (int, float)) or not math.isfinite(v) else fmt.format(v)


def thesis(m: dict, comps: dict) -> str:
    """Rule-based summary of the strongest evidence. Generated from reported data; not a recommendation."""
    best = sorted(((v or 0.0, k) for k, v in comps.items()), reverse=True)[:2]
    titles = {c.key: c.title.lower() for c in spec.COMPONENTS}
    parts = [f"Revenue grew {_pct(m.get('revenue_growth_ttm'))} over the trailing twelve months "
             f"({_pct(m.get('revenue_cagr_3y'))} a year over three years)"]
    if m.get("operating_margin") is not None:
        parts.append(f"with a {_pct(m.get('operating_margin'))} operating margin")
    if m.get("fcf_margin") is not None:
        parts.append(f"and a {_pct(m.get('fcf_margin'))} free-cash-flow margin")
    s = " ".join(parts) + ". "
    s += f"Its strongest scored areas are {titles[best[0][1]]} and {titles[best[1][1]]}. "
    if m.get("ev_to_sales") is not None:
        s += (f"It trades at {m['ev_to_sales']:.1f}x EV/Sales; the price implies about "
              f"{_pct(m.get('implied_revenue_cagr'))} annual revenue growth for five years under the "
              f"dashboard's fixed assumptions.")
    return s


def bear_case(m: dict, counter: str) -> str:
    items = [counter]
    if m.get("implied_growth_gap") is not None and m["implied_growth_gap"] < 0:
        items.append(f"The valuation needs about {_pct(m.get('implied_revenue_cagr'))} annual revenue growth, "
                     f"above the trailing {_pct(m.get('revenue_growth_ttm'))}.")
    if m.get("growth_acceleration") is not None and m["growth_acceleration"] < 0:
        items.append(f"Growth is slowing ({_pct(m['growth_acceleration'], '{:+.0%}')} vs a year earlier).")
    if m.get("dilution") is not None and m["dilution"] > 0.03:
        items.append(f"Shareholders are being diluted ({_pct(m['dilution'], '{:.1%}')} a year).")
    if m.get("fcf_ttm") is not None and m["fcf_ttm"] < 0:
        items.append("Free cash flow is negative, so growth depends on outside funding or existing cash.")
    return " ".join(dict.fromkeys(items))


def key_risks(m: dict, f_flags: list[str], hist: dict | None, concentration: float | None) -> list[str]:
    risks = []
    if m.get("sbc_to_revenue") is not None and m["sbc_to_revenue"] > 0.10:
        risks.append(f"Stock-based compensation is {_pct(m['sbc_to_revenue'])} of revenue.")
    if m.get("dilution") is not None and m["dilution"] > 0.03:
        risks.append(f"Diluted share count rose {_pct(m['dilution'], '{:.1%}')} in a year.")
    nd = m.get("net_debt_to_ebitda")
    if nd is not None and (not math.isfinite(nd) or nd > 3):
        risks.append("Leverage is high relative to EBITDA (or EBITDA is not positive).")
    if m.get("current_ratio") is not None and m["current_ratio"] < 1:
        risks.append(f"Current ratio below 1 ({m['current_ratio']:.2f}).")
    if m.get("fcf_ttm") is not None and m["fcf_ttm"] < 0:
        risks.append("Negative trailing free cash flow.")
    if m.get("ev_to_sales") is not None and m["ev_to_sales"] > 15:
        risks.append(f"High valuation ({m['ev_to_sales']:.0f}x EV/Sales) leaves little room for disappointment.")
    if concentration is not None:
        risks.append(f"The filing tags a concentration-risk percentage of {_pct(concentration)} (see the 10-K).")
    if hist and hist.get("drawdowns", {}).get("max_5y", {}).get("value", 0) < -0.5:
        risks.append(f"The stock fell {_pct(-hist['drawdowns']['max_5y']['value'])} peak to trough in the last "
                     "five years.")
    risks += [f"{fl[0].upper()}{fl[1:]}." for fl in f_flags if fl.startswith("limited")]
    return risks or ["No rule-based risk flag triggered; read the 10-K risk factors."]


def invalidation(m: dict, scen: dict | None) -> list[str]:
    """Observable conditions that would undercut the research case (checked by any later snapshot)."""
    out = []
    g = m.get("revenue_growth_ttm")
    if g is not None and g > 0:
        out.append(f"Trailing revenue growth falls below {_pct(g / 2)} (half of today's {_pct(g)}).")
    if m.get("operating_margin") is not None:
        out.append(f"Operating margin falls more than 5 points below today's {_pct(m['operating_margin'])}.")
    if m.get("fcf_ttm") is not None and m["fcf_ttm"] > 0:
        out.append("Trailing free cash flow turns negative.")
    out.append("Diluted share count grows more than 5% in a year.")
    if m.get("excess_12m") is not None:
        out.append("The stock trails its benchmark by more than 20 points over six months.")
    if scen and scen["base"]["assumptions"]["starting_revenue_growth"] > 0:
        g0 = scen["base"]["assumptions"]["starting_revenue_growth"]
        out.append(f"Two consecutive quarters of year-over-year revenue growth below the bear case's starting "
                   f"rate ({_pct(scen['bear']['assumptions']['starting_revenue_growth'])}; base case {_pct(g0)}).")
    return out
