"""Final deterministic check of live tickets, immediately before they are written.

Strategies and the RiskEngine propose and size; this module only says yes or
no. It re-derives every hard account limit from the account snapshot and the
day's bars, independently of the sizing code, and fails closed:

* global blockers reject every ticket: live disabled, kill switch engaged,
  snapshot missing, unverified, too old or not from the ticket day, a day the
  market is closed, or an account that does not reconcile;
* buy blockers reject every buy but keep sells: loss limits, unknown settled
  cash, or an open buy order at the broker (a placed ticket whose status is not
  yet known must not be duplicated);
* each buy must be an allowed, unleveraged symbol with a fresh bar, a sane
  limit and stop, at most `max_order_notional`, not already held, and the batch
  must stay within the daily entry and purchase limits, the exposure cap and
  the cash reserve. The daily limits include `issued_today`: tickets that an
  earlier run already issued for the same ticket day, which may be placed.

Nothing here talks to a broker; the owner still places every ticket by hand.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .account import AccountSnapshot, verify_snapshot
from .config import LEVERAGED_INVERSE_ETFS, AccountLimitsConfig, ConfigError, Settings, validate
from .killswitch import status as kill_switch_status
from .market_calendar import is_trading_day
from .risk import TradingStatus

ET = ZoneInfo("America/New_York")
LIMIT_SANITY_PCT = 0.02  # a limit more than 2% from the day's close is treated as a pricing error


@dataclass
class GateResult:
    approved: list = field(default_factory=list)
    rejected: list[tuple[object, str]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)  # reasons every ticket was rejected
    buy_blockers: list[str] = field(default_factory=list)  # reasons every buy was rejected
    engage_kill_switch: str | None = None  # set when the drawdown review limit is reached


def close_on(bars: dict[str, pd.DataFrame], symbol: str, as_of: date) -> float | None:
    """The symbol's close on exactly `as_of` (None if that bar is missing)."""
    df = bars.get(symbol)
    if df is None or df.empty:
        return None
    ts = pd.Timestamp(as_of)
    if ts not in df.index:
        return None
    value = float(df.loc[ts, "close"])
    return value if math.isfinite(value) and value > 0 else None


def positions_value(snap: AccountSnapshot, bars: dict[str, pd.DataFrame], as_of: date) -> tuple[float, list[str]]:
    """Market value of the snapshot's positions at the `as_of` close, and symbols without a price."""
    total, missing = 0.0, []
    for p in snap.positions:
        if p["quantity"] <= 0:
            continue
        px = close_on(bars, p["symbol"], as_of)
        if px is None:
            missing.append(p["symbol"])
        else:
            total += p["quantity"] * px
    return total, missing


def spendable_cash(snap: AccountSnapshot, capital: float, invested: float) -> float | None:
    """Settled cash usable for buys, never above the live capital cap. None = unknown."""
    settled = snap.settled_cash
    if settled is None:
        return None
    return max(0.0, min(settled, capital - invested))


def buy_headroom(limits: AccountLimitsConfig, cash: float, invested: float, bought: float, entries: int) -> float:
    """Largest notional the next buy may have under every hard account limit."""
    if entries >= limits.max_daily_entries:
        return 0.0
    return max(
        0.0,
        min(
            limits.max_order_notional,
            limits.max_daily_purchases - bought,
            limits.max_total_exposure - invested - bought,
            cash - limits.min_cash_reserve - bought,
        ),
    )


def _global_blockers(
    settings: Settings, snap: AccountSnapshot | None, as_of: date, now: datetime, bars: dict[str, pd.DataFrame]
) -> list[str]:
    al = settings.account_limits
    out = []
    try:
        validate(settings)
    except ConfigError:
        return ["invalid safety configuration"]
    if not settings.live.enabled:
        out.append("live tickets are disabled (live.enabled: false)")
    ks = kill_switch_status(settings)
    if ks.engaged:
        out.append(
            f"KILL SWITCH engaged ({ks.reason or 'no reason recorded'}, {ks.engaged_at or 'time unknown'}); "
            "release it with `kill-switch release` after reviewing the account"
        )
    if not is_trading_day(as_of):
        out.append(f"{as_of} is not an NYSE trading day")
    if snap is None:
        out.append("no account snapshot")
        return out
    problems = verify_snapshot(snap, settings, now)
    if problems:
        return out + problems
    age_h = (now - snap.fetched).total_seconds() / 3600
    if age_h > al.ticket_snapshot_max_age_hours:
        out.append(f"account snapshot is {age_h:.1f} h old (tickets need < {al.ticket_snapshot_max_age_hours:g} h)")
    if snap.fetched.astimezone(ET).date() != as_of:
        out.append(f"account snapshot is from {snap.fetched.astimezone(ET).date()}, not the ticket day {as_of}")
    invested, missing = positions_value(snap, bars, as_of)
    if missing:
        out.append(f"cannot reconcile: no {as_of} close for held {', '.join(sorted(missing))}")
    else:
        expected = snap.cash + invested
        tol = max(1.0, snap.total_value * al.reconcile_tolerance_pct)
        if abs(expected - snap.total_value) > tol:
            out.append(
                f"account does not reconcile: cash ${snap.cash:,.2f} + positions ${invested:,.2f} = "
                f"${expected:,.2f} vs account value ${snap.total_value:,.2f}"
            )
    return out


def check_tickets(
    settings: Settings,
    tickets: list,
    snap: AccountSnapshot | None,
    as_of: date,
    bars: dict[str, pd.DataFrame],
    status: TradingStatus | None,
    now: datetime | None = None,
    issued_today: list | tuple = (),
) -> GateResult:
    """Approve or reject each ticket. Sells are checked before buys.

    `issued_today`: tickets already issued for `as_of` by earlier runs. Their buys count against the
    daily purchase and entry limits, and no symbol is ticketed twice on the same side in one day."""
    now = now or datetime.now(UTC)
    al = settings.account_limits
    res = GateResult()
    res.blockers = _global_blockers(settings, snap, as_of, now, bars)
    if res.blockers:
        res.rejected = [(t, "; ".join(res.blockers)) for t in tickets]
        return res

    held = {p["symbol"]: p["quantity"] for p in snap.positions if p["quantity"] > 0}
    invested, _ = positions_value(snap, bars, as_of)
    if status is None:
        res.buy_blockers.append("live loss-limit status unknown")
    elif not all(math.isfinite(v) for v in (status.peak_equity, status.drawdown, status.day_pnl)):
        res.buy_blockers.append("live loss-limit status is non-finite")
    else:
        if not status.new_entries_allowed:
            res.buy_blockers.append(status.reason)
        if status.peak_equity > 0 and status.drawdown >= status.peak_equity * al.drawdown_review_pct - 1e-9:
            reason = (
                f"drawdown ${status.drawdown:.2f} from the high-water mark ${status.peak_equity:.2f} reached the "
                f"{al.drawdown_review_pct:.0%} review limit"
            )
            res.buy_blockers.append(reason)
            res.engage_kill_switch = reason
        start_of_day = status.peak_equity - status.drawdown - status.day_pnl
        if start_of_day > 0 and -status.day_pnl >= start_of_day * al.daily_loss_limit_pct - 1e-9:
            res.buy_blockers.append(
                f"daily loss ${-status.day_pnl:.2f} reached the {al.daily_loss_limit_pct:.0%} limit"
            )
    cash = spendable_cash(snap, settings.live.capital, invested)
    if cash is None:
        res.buy_blockers.append("settled cash unknown (snapshot has no unsettled_funds; add it from get_accounts)")
    if any(str(o.get("side", "")).lower() == "buy" for o in snap.open_orders):
        res.buy_blockers.append("an open buy order exists at the broker; reconcile it before new buys")

    allowed = {s.upper() for s in al.live_allowed_symbols}
    valid_tickets = []
    for t in tickets:
        reason = _ticket_value_problem(t)
        if reason:
            res.rejected.append((t, reason))
        else:
            valid_tickets.append(t)
    tickets = valid_tickets
    if any(_ticket_value_problem(t) for t in issued_today):
        res.blockers.append("invalid previously issued ticket; reconcile before issuing more")
        res.rejected.extend((t, res.blockers[-1]) for t in tickets)
        return res
    ticketed = {(t.symbol.upper(), t.side) for t in issued_today}
    selling: set[str] = set()
    for t in [t for t in tickets if t.side == "sell"]:
        reason = None
        if t.symbol not in held:
            reason = "not held (no short selling)"
        elif t.quantity > held[t.symbol] + 1e-9:
            reason = f"sell quantity {t.quantity:g} exceeds the {held[t.symbol]:g} held"
        elif t.symbol in selling:
            reason = "duplicate sell ticket"
        elif (t.symbol.upper(), "sell") in ticketed:
            reason = "already ticketed today"
        elif not (math.isfinite(t.limit_price) and t.limit_price > 0):
            reason = "invalid limit price"
        if reason:
            res.rejected.append((t, reason))
        else:
            res.approved.append(t)
            selling.add(t.symbol)

    issued_buys = [t for t in issued_today if t.side == "buy"]
    bought, entries = sum(t.notional for t in issued_buys), len(issued_buys)
    seen: set[str] = set()
    for t in [t for t in tickets if t.side == "buy"]:
        if (t.symbol.upper(), "buy") in ticketed:
            res.rejected.append((t, "already ticketed today"))
            continue
        reason = _buy_reason(t, al, allowed, held, seen, bars, as_of)
        if reason is None and res.buy_blockers:
            reason = "; ".join(res.buy_blockers)
        if reason is None:
            room = buy_headroom(al, cash, invested, bought, entries)
            if t.notional > room + 0.005:
                reason = (
                    f"notional ${t.notional:,.2f} exceeds the remaining room ${room:,.2f} "
                    f"(max ${al.max_order_notional:g}/order, ${al.max_daily_purchases:g}/day, "
                    f"{al.max_daily_entries} entries/day, ${al.max_total_exposure:g} exposure, "
                    f"${al.min_cash_reserve:g} cash reserve)"
                )
        if reason:
            res.rejected.append((t, reason))
            continue
        res.approved.append(t)
        seen.add(t.symbol)
        bought += t.notional
        entries += 1
    return res


def _ticket_value_problem(ticket) -> str | None:
    if ticket.side not in {"buy", "sell"}:
        return "invalid ticket side"
    for name in ("quantity", "limit_price"):
        value = getattr(ticket, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            return f"invalid {name}: must be finite and positive"
    if not math.isfinite(ticket.quantity * ticket.limit_price):
        return "invalid ticket notional"
    return None


def _buy_reason(
    t,
    al: AccountLimitsConfig,
    allowed: set[str],
    held: dict,
    seen: set[str],
    bars: dict[str, pd.DataFrame],
    as_of: date,
) -> str | None:
    sym = t.symbol.upper()
    if sym in LEVERAGED_INVERSE_ETFS:
        return "leveraged/inverse ETF: prohibited for the real account"
    if sym not in allowed:
        return "symbol is not in account_limits.live_allowed_symbols"
    if sym in held:
        return "already held (one position per ticker)"
    if sym in seen:
        return "duplicate buy ticket"
    if not (math.isfinite(t.quantity) and t.quantity > 0 and math.isfinite(t.limit_price) and t.limit_price > 0):
        return "invalid quantity or limit price"
    if t.stop_price is None or not (0 < t.stop_price < t.limit_price):
        return "missing or invalid stop-loss"
    close = close_on(bars, sym, as_of)
    if close is None:
        return f"no verified {as_of} close for {sym} (stale or missing data)"
    if abs(t.limit_price / close - 1) > LIMIT_SANITY_PCT:
        return f"limit {t.limit_price:.2f} is more than {LIMIT_SANITY_PCT:.0%} from the {as_of} close {close:.2f}"
    if t.notional > al.max_order_notional + 0.005:
        return f"notional ${t.notional:,.2f} exceeds the ${al.max_order_notional:g} per-order limit"
    return None
