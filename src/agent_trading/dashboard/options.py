"""Educational call AND put comparisons for S&P 500 underlyings (not 'best options to buy').

Rules (spec.HORIZONS, OPTION_RULES, OPTION_RANKING) are fixed in advance. Contracts
come only from a current, timestamped chain; when no valid chain exists the
horizon shows an unavailable state. Nothing here invents prices or Greeks:
Black-Scholes is used only for the clearly labelled before-expiration
sensitivity table, starting from the chain's own implied volatility.

Puts use the same windows, liquidity filters, per-underlying limit and ranking
weights as calls, with put-specific math: |delta| for the delta band, breakeven
= strike - premium, payoff = max(strike - price, 0) - premium, and the required
move measured downward. Puts are ranked on contract characteristics for the
same underlyings; they are not derived by reversing the growth rankings.

Spec 2026-10-14.6: six lists of up to 5; theta is required (a missing theta is
never scored as zero decay); quote freshness uses the chain's snapshot timestamp
and keeps a contract's last trade separate from its quote time; earnings status
is 'unknown' when the calendar was not collected; every contract carries the
probability gate's verdict (not established) and plain-language risk notes.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import numpy as np

from ..market_calendar import is_trading_day
from . import probability, spec

MULT = spec.OPTION_RULES["standard_multiplier"]
NY = ZoneInfo("America/New_York")
QUOTE_SOURCE = "Cboe delayed quotes (end-of-session snapshot of a delayed feed; never live)"
QUOTE_DELAY = "delayed: about 15 minutes during the session; the snapshot is taken after the as-of session closes"
UNDERLYING_PRICE_SOURCE = "underlying close reported in the Cboe chain for the as-of session"


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


def bs_put(s: float, k: float, t: float, vol: float, r: float = spec.RISK_FREE_RATE) -> float:
    """Black-Scholes European put value (no dividends), by put-call parity."""
    if t <= 0 or vol <= 0:
        return max(0.0, k - s)
    return bs_call(s, k, t, vol, r) - s + k * math.exp(-r * t)


def bs_value(kind: str, s: float, k: float, t: float, vol: float, r: float = spec.RISK_FREE_RATE) -> float:
    return bs_call(s, k, t, vol, r) if kind == "call" else bs_put(s, k, t, vol, r)


def payoff_at_expiry(s_t: float, strike: float, premium: float, kind: str = "call") -> float:
    """Profit per share of a long option held to expiration, before fees (spec.FEE_TREATMENT)."""
    intrinsic = max(0.0, s_t - strike) if kind == "call" else max(0.0, strike - s_t)
    return intrinsic - premium


def breakeven(kind: str, strike: float, premium: float) -> float:
    return strike + premium if kind == "call" else strike - premium


def required_move(kind: str, spot: float, be: float) -> tuple[float, float]:
    """(signed move from spot to breakeven, move still needed in the option's favourable direction >= 0)."""
    signed = be / spot - 1
    needed = max(0.0, signed) if kind == "call" else max(0.0, -signed)
    return signed, needed


def horizon_for(dte: int) -> str | None:
    """The spec horizon whose window contains `dte` calendar days, or None."""
    for h in spec.HORIZONS:
        if h.min_dte <= dte <= h.max_dte:
            return h.key
    return None


# --- quote freshness (spec.OPTION_QUOTE_RULE) ----------------------------------------------------


def business_days_between(a: date, b: date) -> int:
    return int(np.busday_count(a, b))


def parse_quote_time(stamp) -> tuple[str | None, date | None]:
    """(ISO time in UTC, New York date) of a chain snapshot. Cboe writes 'YYYY-MM-DD HH:MM:SS' in UTC."""
    if not stamp:
        return None, None
    try:
        dt = datetime.fromisoformat(str(stamp).strip().replace("T", " "))
    except ValueError:
        return None, None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds"), dt.astimezone(NY).date()


def quote_info(under: dict, as_of: date) -> dict:
    """Freshness facts for one chain: the snapshot (quote) time and the underlying's last trade, kept apart."""
    utc, ny = parse_quote_time(under.get("timestamp"))
    if utc is None:
        status = (
            "unknown: the chain carries no snapshot timestamp, so freshness is judged from the underlying's "
            "last trade only"
        )
    elif ny < as_of:
        status = f"stale: the snapshot was taken {ny} (New York date), before the as-of session {as_of}"
    elif ny == as_of:
        status = "snapshot taken in the as-of session (end-of-session values)"
    else:
        status = f"snapshot taken {ny} (New York date), after the as-of session closed (end-of-session values)"
    return {
        "quote_time_utc": utc,
        "quote_date_ny": ny.isoformat() if ny else None,
        "quote_status": status,
        "quote_stale": utc is not None and ny < as_of,
        "underlying_last_trade": under.get("last_trade_time"),
        "quote_source": QUOTE_SOURCE,
        "quote_delay": QUOTE_DELAY,
    }


def chain_status(under: dict, as_of: date) -> str | None:
    """Why a chain cannot be used (None = usable): the underlying must have traded in the as-of session and the
    chain's own snapshot must not predate it."""
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
    q = quote_info(under, as_of)
    if q["quote_stale"]:
        return (
            f"stale chain: quote snapshot taken {q['quote_date_ny']} (New York date), before the as-of session {as_of}"
        )
    if not under.get("close") and not under.get("price"):
        return "chain has no underlying price"
    return None


# --- per-contract research row ------------------------------------------------------------


def theta_available(row: dict) -> bool:
    """spec.OPTION_THETA_RULE: a missing theta, or one reported as exactly zero, is 'unavailable'."""
    t = row.get("theta")
    return t is not None and t == t and t != 0


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
    if not lt:
        flags.append("contract last trade time unknown (bid and ask quoted without a recorded trade)")
    else:
        try:
            last = datetime.fromisoformat(lt).date()
            if last < as_of:
                flags.append(
                    f"contract last traded {last}, before the as-of session (its bid/ask is still the snapshot quote)"
                )
        except ValueError:
            flags.append("contract last trade time unreadable")
    if row.get("iv") is None or not row.get("iv"):
        flags.append("implied volatility unavailable")
    if not theta_available(row):
        flags.append("theta unavailable (time decay not measurable)")
    return flags


def eligible(row: dict, underlying: str, as_of: date, kind: str = "call") -> tuple[bool, str]:
    r = spec.OPTION_RULES
    if row["type"] != kind:
        return False, f"not a {kind}"
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
    if (
        d is None
        or (kind == "call" and d < 0)
        or (kind == "put" and d > 0)
        or not (r["min_delta"] <= abs(d) <= r["max_delta"])
    ):
        return False, "delta outside 0.30-0.70" if kind == "call" else "delta outside -0.70 to -0.30"
    if not row.get("iv") or row["iv"] <= 0:
        return False, "no implied volatility"
    if r.get("require_theta", True) and not theta_available(row):
        return False, "theta unavailable (time decay not measurable)"
    return True, ""


def _money(v: float, digits: int = 2) -> str:
    return f"-${-v:,.{digits}f}" if v < 0 else f"${v:,.{digits}f}"


def risk_notes(r: dict) -> dict:
    """Plain-language liquidity, time-decay, volatility, event and maximum-loss notes (display only)."""
    t = spec.OPTION_RISK_THRESHOLDS
    kind, strike = r["type"], r["strike"]
    sp, oi, th, iv = r.get("spread_pct"), r.get("open_interest") or 0, r.get("theta_share_per_day"), r.get("iv")
    liq = [
        f"The bid-ask spread is {sp:.1%} of the mid price"
        + (", so entering and exiting costs that much before the stock moves at all" if sp > t["spread_wide"] else "")
    ]
    if oi < t["open_interest_thin"]:
        liq.append(f"only {oi:,.0f} contracts are outstanding, so exiting at a fair price may be harder")
    else:
        liq.append(f"{oi:,.0f} contracts are outstanding")
    if th is None:
        decay = "Time decay cannot be measured: theta is unavailable."
    else:
        pace = "quickly" if th > t["decay_fast"] else "at a moderate pace"
        decay = (
            f"With the stock standing still, the option loses about {th:.2%} of its mid value per day "
            f"({_money(abs(r.get('theta') or 0), 3)} per share), {pace}; the loss accelerates as expiry nears."
        )
    move = r.get("implied_move_1sd")
    vol = (
        f"Implied volatility of {iv:.0%} a year means the option market itself expects roughly a {move:.0%} move "
        f"by expiry (one standard deviation). "
        + ("That is high. " if iv > t["iv_high"] else "")
        + "A fall in implied volatility lowers the option's price even if the stock does not move."
    )
    st = r.get("events_status")
    if st == "scheduled":
        dates = ", ".join(str(e["date"]) for e in r.get("events_before_expiry", []))
        ev = (
            f"An earnings report is scheduled before expiry ({dates}; unverified): the stock can gap either way, "
            "and implied volatility usually drops after the report."
        )
    elif st == "none scheduled":
        ev = (
            "No earnings report is scheduled before expiry in the collected calendar (unverified; dividends and "
            "other events are not checked)."
        )
    else:
        ev = (
            "Unknown: the earnings calendar was not collected for this snapshot, so an earnings report before "
            "expiry cannot be ruled out."
        )
    side = "at or below" if kind == "call" else "at or above"
    max_loss = (
        f"A long {kind} can lose the entire premium, {_money(r['max_loss_per_contract'], 0)} for one contract, "
        f"if the stock is {side} {_money(strike)} at expiry. Figures are before fees."
    )
    return {
        "liquidity": "; ".join(liq) + ".",
        "time_decay": decay,
        "volatility": vol,
        "event": ev,
        "max_loss": max_loss,
    }


def research_row(
    row: dict,
    spot: float,
    as_of: date,
    underlying: str,
    events: list[dict],
    events_known: bool = True,
    quote: dict | None = None,
) -> dict:
    kind = row["type"]
    bid, ask = row["bid"], row["ask"]
    mid = (bid + ask) / 2
    dte = (row["expiration"] - as_of).days
    t = dte / 365.0
    premium = ask  # spec.PREMIUM_ASSUMPTION: cost to open at the delayed ask
    be = breakeven(kind, row["strike"], premium)
    signed, needed = required_move(kind, spot, be)
    iv = row["iv"]
    implied_move = iv * math.sqrt(t)
    theta = row.get("theta") if theta_available(row) else None
    theta_share = abs(theta) / mid if (theta is not None and mid > 0) else None
    payoffs = []
    for mv in spec.PAYOFF_MOVES:
        s_t = spot * (1 + mv)
        pl = payoff_at_expiry(s_t, row["strike"], premium, kind)
        payoffs.append({"move": mv, "underlying": s_t, "pl_per_contract": pl * MULT, "return_on_premium": pl / premium})
    sens = sensitivity(spot, row["strike"], t, iv, mid, kind)
    before = [e for e in events if as_of < e["date"] <= row["expiration"]]
    if not events_known:
        ev_status, ev_note = "unknown", "earnings calendar not collected for this snapshot"
    elif before:
        ev_status, ev_note = "scheduled", "scheduled earnings before expiry (Alpha Vantage, unverified)"
    else:
        ev_status, ev_note = (
            "none scheduled",
            "no scheduled earnings before expiry in the collected calendar (unverified)",
        )
    hz = horizon_for(dte)
    q = quote or {}
    out = {
        "type": kind,
        "underlying": underlying,
        "option": row["option"],
        "strike": row["strike"],
        "expiration": row["expiration"].isoformat(),
        "dte": dte,
        "horizon": hz,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_pct": (ask - bid) / mid,
        "volume": row.get("volume"),
        "open_interest": row.get("open_interest"),
        "iv": iv,
        "delta": row.get("delta"),
        "gamma": row.get("gamma"),
        "theta": theta,
        "vega": row.get("vega"),
        "rho": row.get("rho"),
        "multiplier": MULT,
        "adjusted": row["root"] != underlying.replace(".", ""),
        "premium_basis": "ask",
        "premium_per_share_ask": premium,
        "premium_per_share_mid": mid,
        "premium_per_contract_ask": premium * MULT,
        "premium_per_contract_mid": mid * MULT,
        "breakeven": be,
        "breakeven_move": signed,
        "required_move": needed,
        "max_loss_per_contract": premium * MULT,
        "implied_move_1sd": implied_move,
        "theta_share_per_day": theta_share,
        "theta_available": theta is not None,
        "payoffs": payoffs,
        "payoff_note": "exact arithmetic at expiration on the ask premium, before fees",
        "fees": spec.FEE_TREATMENT,
        "sensitivity": sens,
        "events_before_expiry": before,
        "events_status": ev_status,
        "events_note": ev_note,
        "flags": contract_flags(row, underlying, as_of),
        "spot": spot,
        "underlying_price_source": UNDERLYING_PRICE_SOURCE,
        "contract_last_trade": row.get("last_trade_time") or None,
        "contract_last_price": row.get("last_price"),
        "quote_time_utc": q.get("quote_time_utc"),
        "quote_date_ny": q.get("quote_date_ny"),
        "quote_status": q.get("quote_status") or "unknown",
        "quote_source": q.get("quote_source") or QUOTE_SOURCE,
        "quote_delay": q.get("quote_delay") or QUOTE_DELAY,
        "underlying_last_trade": q.get("underlying_last_trade"),
        "probability": probability.display(kind, hz),
    }
    out["risks"] = risk_notes(out)
    return out


def sensitivity(
    spot: float, strike: float, t: float, iv: float, mid: float, kind: str = "call", rate: dict | None = None
) -> dict:
    """Model-estimated value after `days_forward` days for price and IV shifts (Black-Scholes)."""
    p = spec.SENSITIVITY
    r = spec.RISK_FREE_RATE if rate is None else rate.get("value")
    if r is None:
        return {
            "days_forward": p["days_forward"],
            "grid": [],
            "rate_input": rate,
            "reason": rate.get("reason", "Dated rate unavailable"),
            "note": "Model estimate unavailable: " + rate.get("reason", "Dated rate unavailable"),
            "assumptions": "Dated DGS1MO risk-free rate unavailable; no replacement rate assumed",
        }
    t2 = max(0.0, t - p["days_forward"] / 365.0)
    grid = []
    for mv in p["price_moves"]:
        row = []
        for dv in p["iv_shifts"]:
            v = bs_value(kind, spot * (1 + mv), strike, t2, max(0.01, iv + dv), r)
            row.append(
                {"price_move": mv, "iv_shift": dv, "model_value": v, "change_vs_mid": v / mid - 1 if mid else None}
            )
        grid.append(row)
    model_now = bs_value(kind, spot, strike, t, iv, r)
    rate_note = f"DGS1MO {r:.3%}, observed {rate['date']} (FRED)" if rate else "4% risk-free rate (legacy assumption)"
    return {
        "days_forward": p["days_forward"],
        "grid": grid,
        "model_value_now": model_now,
        "model_vs_mid_now": model_now / mid - 1 if mid else None,
        "rate_input": rate or {"value": r, "date": None, "source": "Registered legacy assumption"},
        "note": rate_note + "; no dividends (model estimate).",
        "assumptions": (
            "European exercise, no dividends, constant volatility equal to the chain's implied "
            f"volatility, {rate_note}, value compared with today's mid; before fees"
        ),
    }


def apply_dated_rate(payload, rate: dict) -> None:
    """Apply only to newly collected rows, after selection; stored snapshots are never repriced."""
    if isinstance(payload, dict):
        if "sensitivity" in payload and {"spot", "strike", "dte", "iv", "mid", "type"} <= payload.keys():
            payload["sensitivity"] = sensitivity(
                payload["spot"],
                payload["strike"],
                payload["dte"] / 365,
                payload["iv"],
                payload["mid"],
                payload["type"],
                rate,
            )
        else:
            for value in payload.values():
                apply_dated_rate(value, rate)
    elif isinstance(payload, list):
        for value in payload:
            apply_dated_rate(value, rate)


def rank_score(r: dict) -> dict:
    """Pre-registered composite (spec.OPTION_RANKING). Upside is not an input. A missing time-decay input is kept
    as missing (None) and contributes nothing; such contracts are ineligible under spec.OPTION_THETA_RULE."""
    spread = max(0.0, min(1.0, 1 - r["spread_pct"] / spec.OPTION_RULES["max_spread_pct"]))
    oi = r["open_interest"] or 0
    oi_s = max(0.0, min(1.0, (math.log10(max(oi, 1)) - math.log10(500)) / (math.log10(20000) - math.log10(500))))
    liquidity = 0.5 * spread + 0.5 * oi_s
    needed = r.get("required_move", max(0.0, r["breakeven_move"]))
    ratio = needed / r["implied_move_1sd"] if r["implied_move_1sd"] > 0 else float("inf")
    be = max(0.0, min(1.0, 1 - ratio))
    th = r.get("theta_share_per_day")
    decay = None if th is None else max(0.0, min(1.0, 1 - th / 0.01))
    w = {k: v[0] for k, v in spec.OPTION_RANKING.items()}
    total = w["liquidity"] * liquidity + w["breakeven"] * be + w["time_decay"] * (decay or 0.0)
    return {
        "liquidity": liquidity,
        "breakeven": be,
        "time_decay": decay,
        "time_decay_missing": decay is None,
        "total": round(100 * total, 2),
    }


def _shortfall(kind: str, h: spec.Horizon, rows: list, considered: int, rejections: dict, usable: dict) -> str | None:
    """Why a list holds fewer than the limit, in words (None when the list is full)."""
    limit = spec.OPTION_RULES["max_per_type_per_horizon"]
    if len(rows) >= limit:
        return None
    if not usable:
        return "No option chain passed the freshness checks, so no contract could be evaluated."
    if considered == 0:
        return f"No {kind} on any usable chain expires {h.min_dte}-{h.max_dte} days after the as-of date."
    parts = [
        f"{v} left out by the per-underlying limit" if k == "per-underlying limit" else f"{v} failed: {k}"
        for k, v in sorted(rejections.items(), key=lambda kv: -kv[1])
    ]
    return (
        f"Only {len(rows)} of up to {limit} {kind}s met every rule. {considered} {kind}s in the {h.min_dte}-{h.max_dte} "
        f"day window were checked; {'; '.join(parts) or 'none failed'}. The list is not padded and no rule is relaxed."
    )


def _rank_list(
    usable: dict,
    h: spec.Horizon,
    kind: str,
    as_of: date,
    events: dict,
    events_known: bool = True,
    quotes: dict | None = None,
) -> dict:
    r = spec.OPTION_RULES
    rows, rejections, considered = [], {}, 0
    for sym, (under, opts) in usable.items():
        spot = under.get("close") or under.get("price")
        cand = []
        for o in opts:
            dte = (o["expiration"] - as_of).days
            if not (h.min_dte <= dte <= h.max_dte) or o["type"] != kind:
                continue
            considered += 1
            ok, why = eligible(o, sym, as_of, kind)
            if not ok:
                rejections[why] = rejections.get(why, 0) + 1
                continue
            rr = research_row(o, spot, as_of, sym, events.get(sym, []), events_known, (quotes or {}).get(sym))
            rr["rank_components"] = rank_score(rr)
            cand.append(rr)
        cand.sort(key=lambda x: (-x["rank_components"]["total"], x["expiration"], x["strike"]))
        kept = cand[: r["max_per_underlying_per_horizon"]]
        if len(cand) > len(kept):
            rejections["per-underlying limit"] = rejections.get("per-underlying limit", 0) + len(cand) - len(kept)
        rows += kept
    rows.sort(key=lambda x: (-x["rank_components"]["total"], x["underlying"], x["expiration"], x["strike"]))
    if len(rows) > r["max_per_type_per_horizon"]:
        rejections["list limit (ranked below the cutoff)"] = len(rows) - r["max_per_type_per_horizon"]
    rows = rows[: r["max_per_type_per_horizon"]]
    for i, x in enumerate(rows, 1):
        x["rank"] = i
    status = (
        "ok"
        if rows
        else ("unavailable: no valid option chains" if not usable else f"no {kind} met the liquidity and delta rules")
    )
    return {
        "rows": rows,
        "count": len(rows),
        "limit": r["max_per_type_per_horizon"],
        "considered": considered,
        "rejections": rejections,
        "status": status,
        "shortfall": _shortfall(kind, h, rows, considered, rejections, usable),
    }


def build_horizons(
    chains: dict[str, tuple[dict, list[dict]] | str],
    as_of: date,
    events: dict[str, list[dict]],
    events_known: bool = True,
) -> dict:
    """{horizon: {"calls": {...}, "puts": {...}}}, each list ranked separately.

    `chains`: underlying -> (underlying info, option rows) or an error string.
    `events_known`: False when the earnings calendar was not collected (every contract's event status is then
    'unknown', never 'none scheduled')."""
    out = {}
    usable, chain_problems, quotes = {}, {}, {}
    for sym, ch in chains.items():
        if isinstance(ch, str):
            chain_problems[sym] = ch
            continue
        problem = chain_status(ch[0], as_of)
        if problem:
            chain_problems[sym] = problem
        else:
            usable[sym] = ch
            quotes[sym] = quote_info(ch[0], as_of)
    for h in spec.HORIZONS:
        out[h.key] = {
            "title": h.title,
            "window": [h.min_dte, h.max_dte],
            **{f"{k}s": _rank_list(usable, h, k, as_of, events, events_known, quotes) for k in spec.OPTION_TYPES},
        }
    out["chain_problems"] = chain_problems
    out["underlyings"] = sorted(usable)
    out["underlying_prices"] = {s: (u.get("close") or u.get("price")) for s, (u, _) in usable.items()}
    out["quotes"] = quotes
    out["events_known"] = events_known
    out["rules"] = dict(spec.OPTION_RULES)
    out["ranking_weights"] = {k: v[0] for k, v in spec.OPTION_RANKING.items()}
    out["spec_version"] = spec.SPEC_VERSION
    out["quote_source"] = QUOTE_SOURCE
    out["probability"] = probability.status_summary()
    return out
