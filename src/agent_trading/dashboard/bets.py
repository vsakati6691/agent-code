"""Registered options explorer and browser-calculator reference. Public research only."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date

from . import options, spec

# Columnar JSON avoids repeating these keys up to 720 times. No source precision is discarded.
COLUMNS = ("option", "underlying", "type", "tier", "horizon", "premium_band", "expiration", "dte", "strike",
           "spot", "ask", "premium", "breakeven", "required_move", "implied_move", "delta", "spread_pct",
           "open_interest", "volume", "theta", "iv", "events_status", "quote_time_utc", "score")
WARNING = ("Buying an option can lose the entire premium; contracts in the long-shot tier can expire worthless; "
           "size bets so losing all of them is acceptable. Not advice.")


def premium_band(premium: float) -> str:
    for key, lo, hi, inclusive in spec.EXPLORER_PREMIUM_BANDS:
        if premium >= lo and (hi is None and premium > lo or hi is not None and
                              (premium <= hi if inclusive else premium < hi)):
            return key
    raise ValueError("invalid premium")


def eligible(row: dict, underlying: str, as_of: date, tier: str) -> tuple[bool, str]:
    """Core delegates to the weekly eligibility; the disjoint Long-shot tier never changes those rules."""
    kind = row.get("type")
    if kind not in spec.OPTION_TYPES:
        return False, "unknown option type"
    if not all(isinstance(row.get(k), (int, float)) and math.isfinite(row[k]) for k in
               ("bid", "ask", "strike", "delta", "iv", "theta", "open_interest", "volume")):
        return False, "required numeric input unavailable"
    if row["strike"] <= 0 or not options.horizon_for((row["expiration"] - as_of).days):
        return False, "outside the registered expiry windows or invalid strike"
    if tier == "Core":
        return options.eligible(row, underlying, as_of, kind)
    if tier != "Long-shot":
        return False, "unknown tier"
    rules = spec.EXPLORER_LONG_RULES
    if row.get("root") != underlying.replace(".", ""):
        return False, "adjusted/non-standard contract"
    bid, ask = row["bid"], row["ask"]
    if bid <= 0 or ask <= bid:
        return False, "no two-sided market"
    if (ask - bid) / ((ask + bid) / 2) > rules["max_spread_pct"]:
        return False, "spread too wide"
    if row["open_interest"] < rules["min_open_interest"] or row["volume"] < rules["min_volume"]:
        return False, "open interest or volume too low"
    delta = row["delta"]
    if (kind == "call" and delta < 0) or (kind == "put" and delta > 0) or not (
            rules["min_delta"] <= abs(delta) < rules["max_delta_exclusive"]):
        return False, "delta outside long-shot tier"
    if row["iv"] <= 0 or not options.theta_available(row):
        return False, "IV or theta unavailable"
    return True, ""


def research_row(row: dict, symbol: str, spot: float, as_of: date, tier: str, events: list,
                 events_known: bool, quote: dict) -> dict:
    """Same premium, breakeven, implied move and score as options.research_row, without unused model grids."""
    kind, ask, bid = row["type"], row["ask"], row["bid"]
    dte = (row["expiration"] - as_of).days
    be = options.breakeven(kind, row["strike"], ask)
    signed, needed = options.required_move(kind, spot, be)
    implied = row["iv"] * math.sqrt(dte / 365.0)
    spread = (ask - bid) / ((ask + bid) / 2)
    inputs = {"spread_pct": spread, "open_interest": row["open_interest"], "required_move": needed,
              "breakeven_move": signed, "implied_move_1sd": implied,
              "theta_share_per_day": abs(row["theta"]) / ((ask + bid) / 2)}
    before = [e for e in events if as_of < e["date"] <= row["expiration"]]
    premium = ask * spec.OPTION_RULES["standard_multiplier"]
    return {"option": row["option"], "underlying": symbol, "type": kind, "tier": tier,
            "horizon": options.horizon_for(dte), "premium_band": premium_band(premium),
            "expiration": str(row["expiration"]), "dte": dte, "strike": row["strike"], "spot": spot,
            "ask": ask, "premium": premium, "breakeven": be, "required_move": needed, "implied_move": implied,
            "delta": row["delta"], "spread_pct": spread, "open_interest": row["open_interest"],
            "volume": row["volume"], "theta": row["theta"], "iv": row["iv"],
            "events_status": "unknown" if not events_known else "scheduled" if before else "none scheduled",
            "quote_time_utc": quote.get("quote_time_utc"), "score": options.rank_score(inputs)["total"]}


def build(chains: dict, as_of: date, events: dict, events_known: bool = True) -> dict:
    groups, rejects, seen = defaultdict(list), defaultdict(int), set()
    for symbol, chain in sorted(chains.items()):
        if isinstance(chain, str):
            continue                   # refresh.chain_status stores the specific failure
        under, rows = chain
        if options.chain_status(under, as_of):
            continue
        quote = options.quote_info(under, as_of)
        # Sort first so duplicate source rows are resolved independently of source order.
        for row in sorted(rows, key=lambda r: (str(r.get("option")), str(sorted(r.items())))):
            if row.get("option") in seen:
                continue
            seen.add(row.get("option"))
            delta = row.get("delta")
            tier = "Long-shot" if isinstance(delta, (int, float)) and abs(delta) < spec.EXPLORER_LONG_RULES["max_delta_exclusive"] else "Core"
            ok, reason = eligible(row, symbol, as_of, tier)
            if not ok:
                rejects[reason] += 1
                continue
            item = research_row(row, symbol, under["close"], as_of, tier, events.get(symbol, []), events_known, quote)
            groups[(tier, row["type"], item["horizon"], item["premium_band"])].append(item)
    selected = []
    for key, rows in sorted(groups.items()):
        rows.sort(key=lambda r: (-r["score"], r["underlying"], r["expiration"], r["strike"], r["option"]))
        selected.extend(rows[:spec.EXPLORER_PER_BAND])
    return {"spec_version": spec.SPEC_VERSION, "columns": list(COLUMNS),
            "rows": [[r[k] for k in COLUMNS] for r in selected], "eligible_count": sum(map(len, groups.values())),
            "selected_count": len(selected), "rejections": dict(rejects), "status": "available",
            "row_status": "available", "row_reason": "passed registered eligibility and premium-band selection",
            "probability": spec.PROBABILITY_NOT_ESTABLISHED}


def unpack(payload: dict) -> list[dict]:
    return [dict(zip(payload["columns"], row, strict=True)) for row in payload.get("rows", [])]


# Mirrors assets_bets.MATH_JS exactly. Integer cents prevent repeated floating-point loss sums.
MAX_CENTS = 99_999_999_999
MAX_QUANTITY = 9999


def budget_cents(value) -> int | None:
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]{1,9}(?:\.[0-9]{1,2})?", text):
        return None
    whole, _, fraction = text.partition(".")
    result = int(whole) * 100 + int((fraction + "00")[:2])
    return result if result <= MAX_CENTS else None


def premium_cents(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    cents = math.ceil(value * 100 - 1e-7)
    return cents if 0 < cents <= MAX_CENTS else None


def within_budget(premium, budget) -> bool:
    cost, limit = premium_cents(premium), budget_cents(budget)
    return cost is not None and limit is not None and cost <= limit


def size(premium, budget) -> dict:
    cost, limit = premium_cents(premium), budget_cents(budget)
    if cost is None or limit is None:
        return {"status": "invalid", "contracts": None, "max_loss_cents": None}
    count = limit // cost
    return {"status": "ok", "contracts": count, "max_loss_cents": count * cost}


def slip_total(entries: list[dict], budget) -> dict:
    total = 0
    for item in entries:
        cost, qty = item.get("cost_cents"), item.get("quantity")
        if (isinstance(cost, bool) or not isinstance(cost, (int, float)) or not 0 < cost <= MAX_CENTS or
                cost != int(cost) or isinstance(qty, bool) or not isinstance(qty, (int, float)) or
                not 1 <= qty <= MAX_QUANTITY or qty != int(qty)):
            return {"status": "invalid", "max_loss_cents": None, "over_budget": None}
        total += cost * qty
        if total > 2**53 - 1:
            return {"status": "invalid", "max_loss_cents": None, "over_budget": None}
    limit = budget_cents(budget)
    return {"status": "ok", "max_loss_cents": total, "over_budget": None if limit is None else total > limit}
