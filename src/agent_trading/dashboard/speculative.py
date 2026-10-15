"""Bounded 30–90 DTE research, comparable IV observations and budget arithmetic."""
from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from . import bets, options, spec
from .decisions import field, finite
from ..market_calendar import is_trading_day

RULES = spec.SPECULATIVE_RULES
IV_METHOD = "atm-pair-20-40d-nearest30-v1"


def targets(snap: dict) -> list[str]:
    return sorted({c["ticker"] for key in spec.DECISION_RULES["growth_bands"]
                   for c in snap.get("bands", {}).get(key, {}).get("candidates", [])[:RULES["top_per_list"]]})


def standard(row: dict, symbol: str) -> bool:
    return row.get("root") == symbol.replace(".", "") and row.get("type") in ("call", "put")


def eligible(row: dict, symbol: str, as_of: date) -> tuple[bool, str]:
    if not standard(row, symbol):
        return False, "adjusted/non-standard contract"
    if not isinstance(row.get("expiration"), date):
        return False, "expiry missing"
    dte = (row["expiration"] - as_of).days
    if not RULES["min_dte"] <= dte <= RULES["max_dte"]:
        return False, "outside 30–90 DTE"
    if not all(finite(row.get(k)) for k in ("bid", "ask", "strike", "delta", "iv", "theta", "open_interest", "volume")):
        return False, "required quote, Greek or liquidity input missing"
    bid, ask, delta = row["bid"], row["ask"], row["delta"]
    if bid <= 0 or ask <= bid or row["strike"] <= 0:
        return False, "no valid two-sided market"
    if (ask-bid)/((ask+bid)/2) > RULES["max_spread_pct"] + 1e-12:
        return False, "spread above 10% of mid"
    if row["open_interest"] <= RULES["open_interest_above"] or row["volume"] < RULES["min_volume"]:
        return False, "needs OI above 500 and volume at least 10"
    if not RULES["min_delta"] <= abs(delta) <= RULES["max_delta"] or (row["type"] == "call") != (delta > 0):
        return False, "delta outside 0.25–0.40 or incorrect sign"
    if row["iv"] <= 0 or row["theta"] == 0:
        return False, "IV or nonzero theta unavailable"
    return True, ""


def atm_pair(rows: list[dict], symbol: str, spot: float, as_of: date, *, earnings: date | None = None) -> dict:
    """Same strike/expiry call and put IV; no substitute for missing sides."""
    if not finite(spot) or spot <= 0:
        return field(reason="Positive underlying price required")
    candidates = []
    for row in rows:
        if not standard(row, symbol) or not isinstance(row.get("expiration"), date):
            continue
        dte = (row["expiration"] - as_of).days
        in_window = ((earnings <= row["expiration"] and 0 < dte <= RULES["max_dte"]) if earnings else
                     RULES["iv_min_dte"] <= dte <= RULES["iv_max_dte"])
        if not in_window or not finite(row.get("strike")) or row["strike"] <= 0:
            continue
        candidates.append(row)
    if not candidates:
        return field(reason="No standard contracts in the required IV expiry window")
    exp = min({r["expiration"] for r in candidates}, key=lambda e: (e if earnings else abs((e-as_of).days-RULES["iv_target_dte"]), e))
    strike = min({r["strike"] for r in candidates if r["expiration"] == exp}, key=lambda k: (abs(k-spot), k))
    pair = {}
    for row in candidates:
        if row["expiration"] == exp and row["strike"] == strike:
            if all(finite(row.get(k)) and row[k] > 0 for k in ("iv", "bid", "ask")) and row["ask"] >= row["bid"]:
                pair[row["type"]] = row["iv"]
    if len(pair) != 2:
        return field(reason="Nearest ATM strike/expiry lacks a valid call/put IV pair; no substitute used", expiration=exp.isoformat(), strike=strike)
    return field((pair["call"]+pair["put"])/2, expiration=exp.isoformat(), strike=strike, method=IV_METHOD)


def iv_rank(current, observations: list[dict], as_of: date) -> dict:
    if not finite(current) or current <= 0:
        return field(reason="Current comparable ATM IV unavailable", sessions=0)
    by_session = {}
    for obs in observations:
        try:
            day = date.fromisoformat(obs["as_of"])
        except (ValueError, KeyError, TypeError):
            continue
        if (0 < (as_of-day).days <= RULES["iv_rank_days"] and is_trading_day(day) and obs.get("method") == IV_METHOD
                and finite(obs.get("iv")) and obs["iv"] > 0):
            # Conflicting copies of a date cannot count as a valid historical observation.
            if day in by_session and by_session[day] != obs["iv"]:
                by_session[day] = None
            else:
                by_session[day] = obs["iv"]
    values = [v for _, v in sorted(by_session.items()) if v is not None] + [current]
    count = len(values)
    if count < RULES["iv_rank_sessions"]:
        return field(reason=f"Only {count}/252 comparable daily IV sessions stored; no historical IV backfill", sessions=count)
    values = values[-RULES["iv_rank_sessions"]:]
    low, high = min(values), max(values)
    if high == low:
        return field(reason="IV history has no range", sessions=len(values))
    return field(100*(current-low)/(high-low), sessions=len(values))


def put_call_ratio(rows: list[dict], symbol: str, as_of: date) -> dict:
    volumes, seen = {"call": 0.0, "put": 0.0}, set()
    for row in rows:
        if not standard(row, symbol) or not isinstance(row.get("expiration"), date):
            continue
        if not RULES["min_dte"] <= (row["expiration"]-as_of).days <= RULES["max_dte"]:
            continue
        if row.get("option") in seen:
            continue
        seen.add(row.get("option"))
        if not finite(row.get("volume")) or row["volume"] < 0:
            return field(reason="At least one standard 30–90 DTE contract has missing/invalid volume")
        volumes[row["type"]] += row["volume"]
    return field(volumes["put"]/volumes["call"] if volumes["call"] > 0 else None,
                 "No positive call volume in the standard 30–90 DTE chain", basis="put volume / call volume, 30–90 DTE")


def earnings_move(rows, symbol, spot, as_of, earnings: str | None) -> dict:
    try:
        day = date.fromisoformat(earnings)
    except (ValueError, TypeError):
        return field(reason="Next earnings date unavailable")
    if not 0 < (day-as_of).days <= RULES["max_dte"]:
        return field(reason="Next earnings is outside the next 90 days")
    pair = atm_pair(rows, symbol, spot, as_of, earnings=day)
    iv = pair["value"]
    if iv is None:
        return pair
    move = iv*math.sqrt((day-as_of).days/365)
    return field(move, dollars=spot*move, earnings=earnings, iv_expiry=pair["expiration"],
                 model="Constant-IV square-root-time estimate; not an event-specific forecast or probability")


def exits(ask: float, expiration: date) -> dict:
    if not finite(ask) or ask <= 0 or not isinstance(expiration, date):
        return {"profit_premium": None, "loss_premium": None, "close_date": None,
                "reason": "Positive entry premium and expiry required"}
    return {"profit_premium": ask*(1+RULES["profit_exit"]), "loss_premium": ask*(1+RULES["loss_exit"]),
            "close_date": (expiration-timedelta(days=RULES["exit_dte"])).isoformat()}


def budget(account_size, premium, options_pct=5, trade_pct=1) -> dict:
    """Reference for the browser-only hypothetical calculator, in integer cents."""
    values = (account_size, premium, options_pct, trade_pct)
    if not all(finite(v) for v in values) or not 0 < account_size < 1e12 or premium <= 0 or not 0 <= options_pct <= 100 or not 0 <= trade_pct <= 100:
        return {"valid": False, "reason": "Enter a positive hypothetical account value and percentages from 0 to 100"}
    cents = lambda n: int((Decimal(str(n))*100).to_integral_value(rounding=ROUND_HALF_UP))
    size, cost = cents(account_size), cents(premium)
    cap = lambda pct: int((Decimal(size)*Decimal(str(pct))/100).to_integral_value(rounding=ROUND_FLOOR))
    overall, trade = cap(options_pct), cap(trade_pct)
    return {"valid": True, "options_budget": overall/100, "trade_budget": trade/100,
            "exceeds_options": cost > overall, "exceeds_trade": cost > trade,
            "inconsistent_caps": trade_pct > options_pct}


def build(chains: dict, as_of: date, events: dict, history: dict | None = None, events_known: bool = True) -> dict:
    result = {}
    for symbol, chain in sorted(chains.items()):
        item = {"contracts": [], "as_of": as_of.isoformat(), "source": options.QUOTE_SOURCE}
        result[symbol] = item
        if isinstance(chain, str) or chain is None:
            item["reason"] = chain or "Option chain unavailable"
            continue
        under, rows = chain
        reason = options.chain_status(under, as_of)
        spot = under.get("close")
        if under.get("symbol") != symbol or not finite(spot) or spot <= 0:
            reason = "Chain symbol/closing price invalid"
        if reason:
            item["reason"] = reason
            continue
        quote = options.quote_info(under, as_of)
        item.update(quote_time=quote["quote_time_utc"], underlying_last_trade=quote["underlying_last_trade"])
        iv = atm_pair(rows, symbol, spot, as_of)
        future = sorted(e["date"] for e in events.get(symbol, []) if e["date"] > as_of) if events_known else []
        earn = future[0].isoformat() if future else None
        item.update(iv=iv, iv_rank=iv_rank(iv["value"], (history or {}).get(symbol, []), as_of),
                    expected_move=earnings_move(rows, symbol, spot, as_of, earn),
                    put_call_ratio=put_call_ratio(rows, symbol, as_of), earnings_as_of=as_of.isoformat())
        rejects, selected, seen = {}, [], set()
        for row in rows:
            ok, why = eligible(row, symbol, as_of)
            if not ok:
                rejects[why] = rejects.get(why, 0)+1
                continue
            if row["option"] in seen:
                continue
            seen.add(row["option"])
            r = bets.research_row(row, symbol, spot, as_of, "Speculative", events.get(symbol, []), events_known, quote)
            r.update(max_loss=r["premium"], bid=row["bid"], exits=exits(row["ask"], row["expiration"]))
            selected.append(r)
        selected.sort(key=lambda r: (-r["score"], r["expiration"], r["strike"], r["type"], r["option"]))
        item.update(contracts=selected[:RULES["per_ticker"]], rejections=rejects,
                    reason=None if selected else "No contracts passed all 30–90 DTE, delta, spread and liquidity rules")
    return {"as_of": as_of.isoformat(), "iv_method": IV_METHOD, "tickers": result}


def stored_history(store, as_of: date) -> dict:
    """Read only verified previous records, one comparable observation per session."""
    out = {}
    for session in store.dates():
        if not 0 < (as_of-date.fromisoformat(session)).days <= RULES["iv_rank_days"]:
            continue
        payload = store.load(session)  # integrity failure propagates; never silently trusts damaged history
        focus = payload.get("speculative") or {}
        if focus.get("iv_method") != IV_METHOD:
            continue
        for symbol, item in focus.get("tickers", {}).items():
            value = (item.get("iv") or {}).get("value")
            if finite(value) and value > 0:
                out.setdefault(symbol, []).append({"as_of": session, "iv": value, "method": IV_METHOD})
    return out
