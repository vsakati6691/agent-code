"""Educational call-option comparisons for S&P 500 underlyings (not 'best calls to buy').

Rules (spec.HORIZONS, OPTION_RULES, OPTION_RANKING) are fixed in advance. Contracts
come only from a current, timestamped chain; when no valid chain exists the
horizon shows an unavailable state. Nothing here invents prices or Greeks:
Black-Scholes is used only for the clearly labelled before-expiration
sensitivity table, starting from the chain's own implied volatility.
"""
from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np

from . import spec
from ..market_calendar import is_trading_day

MULT = spec.OPTION_RULES["standard_multiplier"]


# --- pricing model (sensitivity only) ----------------------------------------------------

def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_call(s: float, k: float, t: float, vol: float, r: float = spec.RISK_FREE_RATE) -> float:
    """Black-Scholes call value (no dividends). At or after expiry it is the intrinsic value."""
    if t <= 0 or vol <= 0:
        return max(0.0, s - k)
    d1 = (math.log(s / k) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    return s * _ncdf(d1) - k * math.exp(-r * t) * _ncdf(d2)


def payoff_at_expiry(s_t: float, strike: float, premium: float) -> float:
    """Profit per share of a long call held to expiration."""
    return max(0.0, s_t - strike) - premium


# --- per-contract research row ------------------------------------------------------------

def business_days_between(a: date, b: date) -> int:
    return int(np.busday_count(a, b))


def contract_flags(row: dict, underlying: str, as_of: date) -> list[str]:
    r = spec.OPTION_RULES
    flags = ["delayed quote (end-of-session snapshot, not live)"]
    if row["root"] != underlying.replace(".", ""):
        flags.append("adjusted or non-standard contract (root differs from the underlying)")
    bid, ask = row.get("bid"), row.get("ask")
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        flags.append("no two-sided market")
    else:
        mid = (bid + ask) / 2
        if (ask - bid) / mid > r["max_spread_pct"]:
            flags.append(f"wide spread ({(ask - bid) / mid:.0%} of mid)")
    if (row.get("open_interest") or 0) < r["min_open_interest"]:
        flags.append(f"low open interest ({row.get('open_interest') or 0:.0f})")
    if (row.get("volume") or 0) < r["min_volume"]:
        flags.append(f"low volume ({row.get('volume') or 0:.0f})")
    lt = row.get("last_trade_time")
    if lt:
        try:
            last = datetime.fromisoformat(lt).date()
            if last < as_of:
                flags.append(f"last trade {last} (before the as-of session)")
        except ValueError:
            pass
    if row.get("iv") is None or not row.get("iv"):
        flags.append("implied volatility unavailable")
    return flags


def eligible(row: dict, underlying: str, as_of: date) -> tuple[bool, str]:
    r = spec.OPTION_RULES
    if row["type"] != "call":
        return False, "not a call"
    if row["root"] != underlying.replace(".", ""):
        return False, "adjusted/non-standard contract"
    bid, ask = row.get("bid"), row.get("ask")
    if bid is None or ask is None or bid <= 0 or ask <= bid:
        return False, "no two-sided market"
    if (ask - bid) / ((ask + bid) / 2) > r["max_spread_pct"]:
        return False, "spread too wide"
    if (row.get("open_interest") or 0) < r["min_open_interest"]:
        return False, "open interest too low"
    if (row.get("volume") or 0) < r["min_volume"]:
        return False, "volume too low"
    d = row.get("delta")
    if d is None or not (r["min_delta"] <= d <= r["max_delta"]):
        return False, "delta outside 0.30-0.70"
    if not row.get("iv") or row["iv"] <= 0:
        return False, "no implied volatility"
    return True, ""


def research_row(row: dict, spot: float, as_of: date, underlying: str, events: list[dict]) -> dict:
    bid, ask = row["bid"], row["ask"]
    mid = (bid + ask) / 2
    dte = (row["expiration"] - as_of).days
    t = dte / 365.0
    premium = ask                         # cost to open at the quoted ask (conservative)
    breakeven = row["strike"] + premium
    be_move = breakeven / spot - 1
    iv = row["iv"]
    implied_move = iv * math.sqrt(t)
    theta_share = abs(row.get("theta") or 0.0) / mid if mid > 0 else None
    payoffs = []
    for mv in spec.PAYOFF_MOVES:
        s_t = spot * (1 + mv)
        pl = payoff_at_expiry(s_t, row["strike"], premium)
        payoffs.append({"move": mv, "underlying": s_t, "pl_per_contract": pl * MULT, "return_on_premium": pl / premium})
    sens = sensitivity(spot, row["strike"], t, iv, mid)
    before = [e for e in events if as_of < e["date"] <= row["expiration"]]
    return {
        "underlying": underlying, "option": row["option"], "strike": row["strike"],
        "expiration": row["expiration"].isoformat(), "dte": dte, "bid": bid, "ask": ask, "mid": mid,
        "spread_pct": (ask - bid) / mid, "volume": row.get("volume"), "open_interest": row.get("open_interest"),
        "iv": iv, "delta": row.get("delta"), "gamma": row.get("gamma"), "theta": row.get("theta"),
        "vega": row.get("vega"), "rho": row.get("rho"), "multiplier": MULT,
        "adjusted": row["root"] != underlying.replace(".", ""),
        "premium_per_contract_ask": premium * MULT, "premium_per_contract_mid": mid * MULT,
        "breakeven": breakeven, "breakeven_move": be_move, "max_loss_per_contract": premium * MULT,
        "implied_move_1sd": implied_move, "theta_share_per_day": theta_share,
        "payoffs": payoffs, "sensitivity": sens, "events_before_expiry": before,
        "flags": contract_flags(row, underlying, as_of), "spot": spot,
    }


def sensitivity(spot: float, strike: float, t: float, iv: float, mid: float) -> dict:
    """Model-estimated value change after `days_forward` days for price and IV shifts (Black-Scholes)."""
    p = spec.SENSITIVITY
    t2 = max(0.0, t - p["days_forward"] / 365.0)
    grid = []
    for mv in p["price_moves"]:
        row = []
        for dv in p["iv_shifts"]:
            v = bs_call(spot * (1 + mv), strike, t2, max(0.01, iv + dv))
            row.append({"price_move": mv, "iv_shift": dv, "model_value": v, "change_vs_mid": v / mid - 1 if mid else None})
        grid.append(row)
    model_now = bs_call(spot, strike, t, iv)
    return {"days_forward": p["days_forward"], "grid": grid, "model_value_now": model_now,
            "model_vs_mid_now": model_now / mid - 1 if mid else None, "note": spec.RISK_FREE_RATE_NOTE}


def rank_score(r: dict) -> dict:
    """Pre-registered composite (spec.OPTION_RANKING). Upside is not an input."""
    spread = max(0.0, min(1.0, 1 - r["spread_pct"] / spec.OPTION_RULES["max_spread_pct"]))
    oi = r["open_interest"] or 0
    oi_s = max(0.0, min(1.0, (math.log10(max(oi, 1)) - math.log10(500)) / (math.log10(20000) - math.log10(500))))
    liquidity = 0.5 * spread + 0.5 * oi_s
    ratio = r["breakeven_move"] / r["implied_move_1sd"] if r["implied_move_1sd"] > 0 else float("inf")
    be = max(0.0, min(1.0, 1 - ratio))
    th = r["theta_share_per_day"]
    decay = 0.0 if th is None else max(0.0, min(1.0, 1 - th / 0.01))
    w = {k: v[0] for k, v in spec.OPTION_RANKING.items()}
    total = w["liquidity"] * liquidity + w["breakeven"] * be + w["time_decay"] * decay
    return {"liquidity": liquidity, "breakeven": be, "time_decay": decay, "total": round(100 * total, 2)}


def chain_status(under: dict, as_of: date) -> str | None:
    """Why a chain cannot be used (None = usable): it must be from the as-of session."""
    lt = under.get("last_trade_time")
    if not lt:
        return "chain has no underlying trade time"
    try:
        last = datetime.fromisoformat(lt).date()
    except ValueError:
        return "chain timestamp unreadable"
    lag = business_days_between(last, as_of) if last < as_of else 0
    if last > as_of:
        return f"chain is from {last}, after the as-of date {as_of}"
    if lag > spec.OPTION_RULES["max_quote_age_business_days"] and is_trading_day(as_of):
        return f"stale chain: underlying last traded {last}, as-of session is {as_of}"
    if not under.get("close") and not under.get("price"):
        return "chain has no underlying price"
    return None


def build_horizons(chains: dict[str, tuple[dict, list[dict]] | str], as_of: date,
                   events: dict[str, list[dict]]) -> dict:
    """{horizon: {"rows": [...ranked...], "considered": n, "rejections": {...}, "status": ...}}.

    `chains`: underlying -> (underlying info, option rows) or an error string."""
    r = spec.OPTION_RULES
    out = {}
    usable, chain_problems = {}, {}
    for sym, ch in chains.items():
        if isinstance(ch, str):
            chain_problems[sym] = ch
            continue
        problem = chain_status(ch[0], as_of)
        if problem:
            chain_problems[sym] = problem
        else:
            usable[sym] = ch
    for h in spec.HORIZONS:
        rows, rejections, considered = [], {}, 0
        for sym, (under, opts) in usable.items():
            spot = under.get("close") or under.get("price")
            cand = []
            for o in opts:
                dte = (o["expiration"] - as_of).days
                if not (h.min_dte <= dte <= h.max_dte) or o["type"] != "call":
                    continue
                considered += 1
                ok, why = eligible(o, sym, as_of)
                if not ok:
                    rejections[why] = rejections.get(why, 0) + 1
                    continue
                rr = research_row(o, spot, as_of, sym, events.get(sym, []))
                rr["rank_components"] = rank_score(rr)
                cand.append(rr)
            cand.sort(key=lambda x: (-x["rank_components"]["total"], x["expiration"], x["strike"]))
            rows += cand[: r["max_per_underlying_per_horizon"]]
        rows.sort(key=lambda x: (-x["rank_components"]["total"], x["underlying"], x["expiration"], x["strike"]))
        rows = rows[: r["max_per_horizon"]]
        for i, x in enumerate(rows, 1):
            x["rank"] = i
        status = "ok" if rows else ("unavailable: no valid option chains" if not usable else
                                    "no contract met the liquidity and delta rules")
        out[h.key] = {"title": h.title, "window": [h.min_dte, h.max_dte], "rows": rows, "considered": considered,
                      "rejections": rejections, "status": status}
    out["chain_problems"] = chain_problems
    out["underlyings"] = sorted(usable)
    return out
