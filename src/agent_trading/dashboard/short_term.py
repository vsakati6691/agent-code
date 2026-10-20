"""Bounded, delayed intraday option research. No orders, model probabilities or weekly rescoring."""

from __future__ import annotations

import logging
import math
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from ..market_calendar import is_trading_day
from . import spec
from .http import FetchError
from .provider_parsers import parse_occ

NY = ZoneInfo("America/New_York")
RULES = {**spec.LIVE_GAP_RULES["short_term"], "windows": spec.DASHBOARD_REFINEMENT_RULES["short_term_windows"]}
log = logging.getLogger(__name__)


def session_close(day: date) -> datetime:
    november = date(day.year, 11, 1)
    thanksgiving = november + timedelta(days=(3 - november.weekday()) % 7 + 21)
    early = (day.month, day.day) in ((7, 3), (12, 24)) or day == thanksgiving + timedelta(days=1)
    return datetime.combine(day, time(13 if early else 16), NY)


def session_open(now: datetime) -> bool:
    local = now.astimezone(NY)
    return is_trading_day(local.date()) and datetime.combine(local.date(), time(9, 30), NY) <= local < session_close(
        local.date()
    )


def _number(value: object) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError("missing numeric field")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite numeric field")
    return result


def _timestamp(value: object, default_zone) -> datetime:
    if not isinstance(value, str) or "T" not in value and " " not in value:
        raise ValueError("missing timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (result if result.tzinfo else result.replace(tzinfo=default_zone)).astimezone(UTC)


def select(symbol: str, under: dict, contracts: list[dict], now: datetime) -> dict:
    """Select genuine listed contracts; calendar DTE never means trading-day DTE."""
    if now.tzinfo is None:
        raise ValueError("collection time must be timezone-aware")
    today = now.astimezone(NY).date()
    result = {"symbol": symbol, "state": "unavailable", "rows": [], "rejections": {}}
    if not session_open(now):
        return {**result, "state": "closed", "reason": "Outside the regular research session"}
    try:
        stamp = _timestamp(under.get("timestamp"), UTC)
        trade = _timestamp(under.get("last_trade_time"), NY)
        spot = _number(under.get("price"))
        if under.get("symbol") != symbol or spot <= 0:
            raise ValueError("underlying symbol or spot invalid")
        for observed in (stamp, trade):
            age = (now - observed).total_seconds()
            if (
                observed.astimezone(NY).date() != today
                or not session_open(observed)
                or not -RULES["future_tolerance_seconds"] <= age <= RULES["max_quote_age_minutes"] * 60
            ):
                raise ValueError("stale, future or off-session quote")
        if not isinstance(contracts, list) or not contracts:
            raise ValueError("empty chain")
    except (ValueError, TypeError, AttributeError, OverflowError):
        return {**result, "reason": "Missing, malformed or stale chain/underlying quote"}
    result.update(state="available", quote_time=stamp.isoformat(), underlying_trade_time=trade.isoformat(), spot=spot)
    # Reject every occurrence of a duplicate OCC id: a conflicting quote must not win by input order.
    counts = Counter(
        row["option"].strip().upper()
        for row in contracts
        if isinstance(row, dict) and isinstance(row.get("option"), str)
    )
    parsed = [
        ({**row, "option": row["option"].strip().upper()}, parse_occ(row["option"]))
        for row in contracts
        if isinstance(row, dict) and isinstance(row.get("option"), str)
    ]
    expiries = sorted(
        {
            occ["expiration"]
            for _, occ in parsed
            if occ
            and occ["root"] == symbol
            and is_trading_day(occ["expiration"])
            and 0 < (occ["expiration"] - today).days <= RULES["max_next_dte"]
        }
    )
    rejected = Counter()
    qualified = []
    for row, occ in parsed:
        if not occ or occ["root"] != symbol or not is_trading_day(occ["expiration"]):
            rejected["nonstandard or invalid contract"] += 1
            continue
        expiry = occ["expiration"]
        dte = (expiry - today).days
        windows = [f"{dte}DTE"] if 0 <= dte <= RULES["max_next_dte"] else []
        if not windows:
            continue
        try:
            bid, ask, oi, volume = (_number(row.get(key)) for key in ("bid", "ask", "open_interest", "volume"))
            strike = occ["strike"]
            if (
                counts[row["option"]] != 1
                or strike <= 0
                or not 0 < bid <= ask
                or oi < RULES["min_open_interest"]
                or volume < RULES["min_volume"]
                or not oi.is_integer()
                or not volume.is_integer()
            ):
                raise ValueError("invalid or illiquid quote")
            premium = _number(ask * 100)
            spread = (ask - bid) / (ask / 2 + bid / 2)
            if spread > RULES["max_spread_pct"] or abs(strike / spot - 1) > RULES["max_moneyness_distance"]:
                raise ValueError("spread or moneyness filter")
        except (ValueError, TypeError, OverflowError):
            rejected["duplicate, invalid quote or liquidity/moneyness filter"] += 1
            continue
        qualified.append(
            {
                "option": row["option"],
                "symbol": symbol,
                "type": occ["type"],
                "expiry": str(expiry),
                "dte": dte,
                "strike": strike,
                "bid": bid,
                "ask": ask,
                "premium": round(premium, 2),
                "max_premium_loss": round(premium, 2),
                "spread": spread,
                "volume": int(volume),
                "open_interest": int(oi),
                "quote_time": stamp.isoformat(),
                "cutoff": session_close(expiry).isoformat(),
                "valid_until": min(
                    stamp + timedelta(minutes=RULES["max_quote_age_minutes"]),
                    trade + timedelta(minutes=RULES["max_quote_age_minutes"]),
                    session_close(today),
                ).isoformat(),
                "windows": windows,
            }
        )
    ranked = sorted(qualified, key=lambda row: (row["spread"], -row["volume"], -row["open_interest"], row["option"]))
    for window in RULES["windows"]:
        for kind in ("call", "put"):
            result["rows"].extend(
                {**row, "window": window}
                for row in [r for r in ranked if window in r["windows"] and r["type"] == kind][
                    : RULES["per_symbol_type_window"]
                ]
            )
    result.update(
        rejections=dict(rejected),
        listed_expiries=[str(d) for d in expiries],
        reason=None if result["rows"] else "No contracts passed the registered filters",
    )
    return result


def collect(providers, now: datetime | None = None) -> dict:
    live_clock = now is None
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("collection time must be timezone-aware")
    records = []
    for symbol in RULES["symbols"]:
        if not session_open(now):
            records.append(
                {"symbol": symbol, "state": "closed", "reason": "Outside the regular research session", "rows": []}
            )
            continue
        try:
            under, chain = providers.option_chain(symbol)
            # Recheck after the request so a chain fetched across the cutoff cannot stay eligible.
            record = select(symbol, under, chain, datetime.now(UTC) if live_clock else now)
        except (FetchError, OSError, ValueError, TypeError, KeyError, AttributeError):
            log.warning("Short-term chain unavailable for %s; continuing with other symbols", symbol)
            record = {
                "symbol": symbol,
                "state": "provider_error",
                "reason": "Provider failed or returned malformed data",
                "rows": [],
            }
        records.append(record)
    available = sum(record["state"] == "available" for record in records)
    status = (
        "closed"
        if all(record["state"] == "closed" for record in records)
        else "ok"
        if available == len(records)
        else "partial"
        if available
        else "failed"
    )
    return {
        "collected_at": now.isoformat(),
        "as_of": str(now.astimezone(NY).date()),
        "spec_version": spec.SPEC_VERSION,
        "spec_hash": spec.spec_hash(),
        "status": status,
        "source": "Cboe delayed public option chains",
        "windows": list(RULES["windows"]),
        "symbols": records,
    }
