"""Deterministic pre-trade checks. The validator only says yes or no.

It re-derives every limit from the broker's own account state and a fresh
quote, independently of the strategy and sizing code, and fails closed: any
missing input is a rejection. The limits come from `account_limits` in the
config, which the loader already forces to be no looser than HARD_LIMITS.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from ..config import LEVERAGED_INVERSE_ETFS, Settings
from ..killswitch import status as kill_switch_status
from .models import AccountState, OrderRequest, Quote
from .session import submission_window_open


@dataclass(frozen=True)
class ExecutionLimits:
    max_order_notional: float
    max_total_exposure: float
    min_cash_reserve: float
    max_daily_purchases: float
    max_daily_entries: int
    capital: float
    allowed_symbols: frozenset[str]
    max_quote_age_seconds: float = 60.0
    max_limit_deviation_pct: float = 0.01    # limit at most 1% through the quote
    max_spread_pct: float = 0.005            # skip symbols quoting wider than 0.5%
    max_account_age_seconds: float = 120.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "ExecutionLimits":
        al = settings.account_limits
        return cls(al.max_order_notional, al.max_total_exposure, al.min_cash_reserve, al.max_daily_purchases,
                   al.max_daily_entries, settings.live.capital,
                   frozenset(s.upper() for s in al.live_allowed_symbols) - LEVERAGED_INVERSE_ETFS)


def validate(req: OrderRequest, settings: Settings, limits: ExecutionLimits, account: AccountState | None,
             quote: Quote | None, ledger_unresolved: list[dict], buys_today: tuple[int, float],
             now: datetime, buys_halted: str = "") -> list[str]:
    """Reasons to refuse `req`. An empty list means the order may be sent."""
    out: list[str] = []
    ks = kill_switch_status(settings)
    if ks.engaged:
        out.append(f"kill switch engaged ({ks.reason or 'no reason recorded'})")
    if req.side not in ("buy", "sell"):
        out.append(f"unsupported side {req.side!r}")
    if not isinstance(req.quantity, int) or isinstance(req.quantity, bool) or req.quantity <= 0:
        out.append("quantity must be a positive whole number of shares")
    if not (isinstance(req.limit_price, (int, float)) and math.isfinite(req.limit_price) and req.limit_price > 0):
        out.append("limit price must be a positive number")
    if req.time_in_force != "gfd":
        out.append("only day (gfd) orders are allowed")
    ok, why = submission_window_open(now)
    if not ok:
        out.append(why)
    if out:
        return out

    sym = req.symbol.upper()
    if sym in LEVERAGED_INVERSE_ETFS:
        out.append(f"{sym} is a leveraged/inverse ETF")
    if req.side == "buy" and sym not in limits.allowed_symbols:
        out.append(f"{sym} is not on the live allowlist")

    # Anything in flight for this symbol, at the broker or in our own ledger,
    # blocks a new order: an ambiguous earlier attempt must be resolved first.
    if any(r["symbol"] == sym for r in ledger_unresolved):
        out.append(f"an earlier {sym} order is still unresolved in the ledger")

    if account is None:
        return out + ["no account state from the broker"]
    age = (now - account.fetched_at).total_seconds()
    if age > limits.max_account_age_seconds or age < -5:
        out.append(f"account state is {age:.0f}s old (max {limits.max_account_age_seconds:g}s)")
    if any(o.symbol == sym for o in account.open_orders):
        out.append(f"the broker already has an open {sym} order")

    if quote is None:
        return out + [f"no quote for {sym}"]
    qage = (now - quote.as_of).total_seconds()
    if qage > limits.max_quote_age_seconds or qage < -5:
        out.append(f"{sym} quote is {qage:.0f}s old (max {limits.max_quote_age_seconds:g}s)")
    if not (0 < quote.bid <= quote.ask):
        return out + [f"{sym} quote is not two-sided (bid {quote.bid}, ask {quote.ask})"]
    mid = (quote.bid + quote.ask) / 2
    if (quote.ask - quote.bid) / mid > limits.max_spread_pct:
        out.append(f"{sym} spread {(quote.ask - quote.bid) / mid:.2%} exceeds {limits.max_spread_pct:.2%}")
    if req.side == "buy" and req.limit_price > quote.ask * (1 + limits.max_limit_deviation_pct):
        out.append(f"buy limit {req.limit_price:.2f} is more than {limits.max_limit_deviation_pct:.0%} above the ask")
    if req.side == "sell" and req.limit_price < quote.bid * (1 - limits.max_limit_deviation_pct):
        out.append(f"sell limit {req.limit_price:.2f} is more than {limits.max_limit_deviation_pct:.0%} below the bid")

    held = account.positions.get(sym, 0.0)
    if req.side == "sell":
        if req.quantity > held + 1e-9:
            out.append(f"sell {req.quantity} exceeds the {held:g} {sym} shares held (no short selling)")
        return out

    if buys_halted:
        out.append(f"new buys halted: {buys_halted}")
    if held > 0:
        out.append(f"{sym} is already held (one position per ticker)")
    entries, bought = buys_today
    invested = max(0.0, account.total_value - account.cash)   # broker market value of positions
    notional = req.notional
    if notional > limits.max_order_notional + 1e-9:
        out.append(f"order ${notional:,.2f} exceeds ${limits.max_order_notional:,.0f} per order")
    if entries + 1 > limits.max_daily_entries:
        out.append(f"daily entry limit {limits.max_daily_entries} reached")
    if bought + notional > limits.max_daily_purchases + 1e-9:
        out.append(f"daily purchases would be ${bought + notional:,.2f} (max ${limits.max_daily_purchases:,.0f})")
    if invested + notional > min(limits.max_total_exposure, limits.capital) + 1e-9:
        out.append(f"exposure would be ${invested + notional:,.2f} (max ${min(limits.max_total_exposure, limits.capital):,.0f})")
    spendable = min(account.settled_cash, account.cash, account.buying_power)
    if spendable - notional < limits.min_cash_reserve - 1e-9:
        out.append(f"settled cash ${spendable:,.2f} minus ${notional:,.2f} would breach the "
                   f"${limits.min_cash_reserve:,.0f} reserve")
    return out
