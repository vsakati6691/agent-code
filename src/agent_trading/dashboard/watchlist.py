"""Owner watchlist: symbol verification and conditional year-end-2030 price scenarios (spec 2026-10-14.2).

The ticker list comes from `config/research_watchlist.json` (tickers only, with
the date they were imported; it is not synchronised with any account). Each run:

1. resolves every symbol against the current exchange listings and the SEC
   ticker file. Unresolved or OTC symbols stay visible with the reason; nothing
   is guessed or substituted;
2. reads the verified as-of price;
3. applies the method that fits the security:
   * operating company -> revenue x EV/Sales path to 2030-12-31;
   * unleveraged ETF -> exposure-class return assumptions net of assumed fee
     and distribution yield;
   * leveraged ETF -> daily-reset model with volatility drag and financing
     cost, or "Scenario unavailable" when it cannot be specified;
   * anything else, or too little evidence -> "Scenario unavailable".

The watchlist never feeds the ranked growth lists. Scenarios are conditional,
not predictions; no probability is assigned.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import spec
from .providers import canonical, common_stock_reason

CONFIG_FILE = Path(__file__).resolve().parents[3] / "config" / "research_watchlist.json"
TARGET = date.fromisoformat(spec.WATCHLIST_TARGET_DATE)


@dataclass(frozen=True)
class WatchlistConfig:
    tickers: tuple[str, ...]
    imported_at: str
    source: str

    @classmethod
    def load(cls, path: Path = CONFIG_FILE) -> "WatchlistConfig | None":
        if not Path(path).exists():
            return None
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        forbidden = {"account_number", "quantity", "shares", "cost_basis", "average_buy_price", "balance",
                     "positions", "equity", "market_value"}
        if forbidden & {k.lower() for k in raw}:
            raise ValueError("watchlist config may contain tickers only (no account or position fields)")
        tickers = tuple(dict.fromkeys(canonical(t) for t in raw["tickers"] if str(t).strip()))
        return cls(tickers, str(raw["imported_at"]), str(raw.get("source", "")))


def years_to_target(as_of: date) -> float:
    return max(0.0, (TARGET - as_of).days / 365.25)


def annualized(multiple: float, years: float) -> float | None:
    if years <= 0 or multiple <= 0:
        return None
    return multiple ** (1 / years) - 1


# --- classification -----------------------------------------------------------------------

def _has(name: str, kw: str) -> bool:
    kw = kw.strip().lower()
    return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", name.lower()) is not None


def leverage_of(name: str) -> int | None:
    """Daily leverage from the fund name: magnitude from 2x/3x/Ultra/UltraPro, sign from bear/short/inverse.
    None = not a leveraged or inverse fund."""
    hits = [lev for kw, lev in spec.LEVERAGED_KEYWORDS.items() if _has(name, kw)]
    if not hits:
        return None
    magnitude = max(abs(h) for h in hits)
    return -magnitude if any(h < 0 for h in hits) else magnitude


def exposure_class(name: str):
    for rule in spec.ETF_EXPOSURE_RULES:
        if any(_has(name, kw) for kw in rule[2]):
            return rule
    return None


def leveraged_underlying(name: str) -> str | None:
    for kw, sym in spec.LEVERAGED_UNDERLYING_HINTS.items():
        if _has(name, kw):
            return sym
    return None


def resolve(ticker: str, dirs: pd.DataFrame, sec: pd.DataFrame) -> dict:
    """Official name, exchange, asset type and listing status from the listings and the SEC file."""
    out = {"ticker": ticker, "name": None, "exchange": None, "asset_type": None, "status": None, "cik": None}
    if ticker in sec.index:
        out["cik"] = int(sec.loc[ticker, "cik"])
        out["name"] = str(sec.loc[ticker, "name"])
    if ticker in dirs.index:
        d = dirs.loc[ticker]
        out["name"] = str(d["name"])
        out["exchange"] = str(d["exchange"])
        if bool(d["test_issue"]):
            out["asset_type"], out["status"] = "test issue", "not a real security"
        elif bool(d["etf"]):
            lev = leverage_of(out["name"])
            out["asset_type"] = "leveraged/inverse ETF" if lev not in (None,) else "ETF"
            out["status"] = "listed"
        else:
            why = common_stock_reason(out["name"], False, False, str(d.get("financial_status", "")))
            out["asset_type"] = "operating company (common stock)" if why is None else f"other security ({why})"
            out["status"] = "listed"
    elif out["cik"] is not None:
        ex = str(sec.loc[ticker, "exchange"] or "")
        out["exchange"] = ex or None
        out["asset_type"] = "SEC registrant"
        out["status"] = "OTC or not exchange-listed" if ex in ("OTC", "") else f"listed on {ex} (not in the directories)"
    else:
        out["status"] = ("unresolved: not in current exchange listings or the SEC ticker file (possibly delisted, "
                         "renamed or mistyped); no substitute is assumed")
    return out


# --- scenario models --------------------------------------------------------------------

def company_scenarios(price: float, shares: float, revenue_ttm: float, revenue_growth: float, ev_to_sales: float,
                      net_cash: float, dilution: float | None, years: float, margin: float | None = None,
                      margin_source: str = "FCF") -> dict:
    """Revenue x EV/Sales path to the target date (fractional years), per spec.WATCHLIST_COMPANY_METHOD.

    `margin`: today's TTM FCF margin (or operating margin) for the margin cross-check; None = not available."""
    if not all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in (price, shares, revenue_ttm, ev_to_sales)):
        raise ValueError("price, shares, revenue and EV/Sales must be positive")
    base_g = min(spec.SCENARIO_GROWTH_CAP, max(spec.SCENARIO_GROWTH_FLOOR, revenue_growth))
    dil = dilution if dilution is not None and math.isfinite(dilution) else 0.0
    out = {}
    for rule in spec.SCENARIOS:
        g = max(spec.SCENARIO_GROWTH_FLOOR, base_g * rule.growth_multiplier + rule.growth_shift)
        g0, rev, t, path = g, revenue_ttm, 0.0, []
        while t < years - 1e-9:
            step = min(1.0, years - t)
            rev *= (1 + g) ** step
            path.append(g)
            g += spec.SCENARIO_GROWTH_FADE * (spec.SCENARIO_TERMINAL_GROWTH - g)
            t += step
        exit_mult = max(spec.SCENARIO_MIN_EV_SALES, ev_to_sales * rule.exit_multiple_factor)
        d = dil + rule.dilution_shift
        sh = shares * (1 + d) ** years
        ev_2030 = rev * exit_mult
        value = max(0.0, (ev_2030 + net_cash) / sh)
        a = {"starting_revenue_growth": g0, "growth_path": path, "revenue_2030": rev, "exit_ev_to_sales": exit_mult,
             "annual_dilution": d, "shares_2030": sh, "net_cash_held": net_cash, "ev_2030": ev_2030,
             "margin_source": margin_source if margin is not None else None}
        if margin is not None and math.isfinite(margin):
            m30 = margin + rule.margin_shift
            fcf = rev * m30
            a.update(margin_today=margin, margin_2030=m30, fcf_2030=fcf,
                     implied_ev_to_fcf=ev_2030 / fcf if fcf > 0 else None,
                     cash_support=("not supported: 2030 free cash flow would be negative" if fcf <= 0 else
                                   f"stretched: implies {ev_2030 / fcf:.0f}x EV/FCF in 2030"
                                   if ev_2030 / fcf > spec.WATCHLIST_MAX_SUPPORTED_EV_FCF else
                                   f"consistent: implies {ev_2030 / fcf:.0f}x EV/FCF in 2030"))
        else:
            a.update(margin_today=None, margin_2030=None, fcf_2030=None, implied_ev_to_fcf=None,
                     cash_support="not checked: no margin data")
        out[rule.key] = {"price": value, "change": value / price - 1, "annualized": annualized(value / price, years),
                         "assumptions": a}
    return out


def etf_scenarios(price: float, rule, years: float) -> dict:
    cls, title, _, rets, fee, yld = rule
    out = {}
    for key, r_total in zip(("bear", "base", "bull"), rets):
        r_price = (1 + r_total) / (1 + fee) / (1 + yld) - 1
        value = price * (1 + r_price) ** years
        out[key] = {"price": value, "change": value / price - 1, "annualized": r_price,
                    "assumptions": {"exposure": title, "total_return_assumption": r_total, "assumed_fee": fee,
                                    "assumed_distribution_yield": yld, "price_return": r_price}}
    return out


def realized_vol(close: pd.Series, bars: int = 756) -> float | None:
    r = np.log(close.iloc[-bars - 1:]).diff().dropna()
    return float(r.std() * math.sqrt(252)) if len(r) >= 250 else None


def leveraged_scenarios(price: float, lev: int, underlying_rule, sigma: float, years: float) -> dict:
    """Daily-reset model (spec.LEVERAGED_METHOD): g = L mu - L^2 sigma^2 / 2 - (L - 1) r - fee."""
    out = {}
    for key, r_total in zip(("bear", "base", "bull"), underlying_rule[3]):
        s = sigma * spec.LEVERAGED_VOL_FACTORS[key]
        mu = math.log1p(r_total) + s * s / 2          # arithmetic drift of the index for this scenario
        g = lev * mu - lev * lev * s * s / 2 - (lev - 1) * spec.LEVERAGED_FINANCING_RATE - spec.LEVERAGED_ASSUMED_FEE
        value = price * math.exp(g * years)
        out[key] = {"price": value, "change": value / price - 1, "annualized": math.exp(g) - 1,
                    "assumptions": {"leverage": lev, "index_total_return": r_total, "index_volatility": s,
                                    "volatility_drag": lev * lev * s * s / 2,
                                    "financing_cost": (lev - 1) * spec.LEVERAGED_FINANCING_RATE,
                                    "assumed_fee": spec.LEVERAGED_ASSUMED_FEE, "log_growth_rate": g}}
    return out


# --- narrative ----------------------------------------------------------------------------

def company_narrative(m: dict, earnings: str | None) -> dict:
    g, om, fcf = m.get("revenue_growth_ttm"), m.get("operating_margin"), m.get("fcf_ttm")
    catalysts = [f"Next scheduled earnings: {earnings} (Alpha Vantage, unverified)"] if earnings else \
        ["No scheduled earnings date from the data source"]
    if g is not None:
        catalysts.append(f"Sustaining revenue growth near the trailing {g:.0%}")
    bear = []
    if m.get("implied_growth_gap") is not None and m["implied_growth_gap"] < 0:
        from .scenarios import implied_growth_text
        bear.append(implied_growth_text(m.get("implied_revenue_cagr"), m.get("revenue_growth_ttm")) +
                    ": more than recent results.")
    if fcf is not None and fcf < 0:
        bear.append("Free cash flow is negative, so growth depends on funding (dilution or debt).")
    if m.get("dilution") is not None and m["dilution"] > 0.05:
        bear.append(f"Diluted shares grew {m['dilution']:.0%} in a year.")
    if om is not None and om < 0:
        bear.append(f"Operating margin is negative ({om:.0%}).")
    if not bear:
        bear.append("Multiple compression: EV/Sales falling toward the bear-case level even if revenue grows.")
    inval = []
    if g is not None and g > 0:
        inval.append(f"Trailing revenue growth falls below {g / 2:.0%} (half of today's {g:.0%}).")
    inval.append("Diluted share count grows more than 8% in a year.")
    if fcf is not None and fcf > 0:
        inval.append("Trailing free cash flow turns negative.")
    else:
        inval.append("Cash covers less than two years of the current cash burn.")
    return {"catalysts": catalysts, "bear_case": " ".join(bear), "invalidation": inval}


def etf_narrative(rule, lev: int | None) -> dict:
    if lev:
        return {"catalysts": ["Direction AND volatility of the tracked index; low-volatility uptrends help, choppy "
                              "markets hurt"],
                "bear_case": (f"A {lev}x daily-reset fund loses value in volatile, sideways markets even when the "
                              "index ends flat, and a large index decline can cut it by far more than "
                              f"{lev} times the index loss over multi-year periods."),
                "invalidation": ["Index volatility stays well above its trailing level",
                                 "Financing rates or fund costs rise materially",
                                 "The fund changes its objective, leverage or is closed"]}
    title = rule[1] if rule else "its exposure"
    return {"catalysts": [f"Returns of {title.lower()}; fund-level catalysts are not tracked"],
            "bear_case": ("Concentrated exposure: the whole theme can de-rate together." if rule and
                          rule[0] in ("semis", "thematic") else
                          "Index valuation compresses toward historical averages."),
            "invalidation": ["The fund changes its index, strategy or fee materially",
                             "The fund closes or delists (thematic funds close more often)"]}


def evidence_quality(kind: str, f=None, bars: int = 0) -> str:
    if kind == "company":
        if f is not None and f.n_quarters >= 12 and bars >= 756 and not f.any_derived():
            return "medium-high"
        if f is not None and f.n_quarters >= 8:
            return "medium"
        return "low"
    return "low" if kind == "leveraged" else "medium"
