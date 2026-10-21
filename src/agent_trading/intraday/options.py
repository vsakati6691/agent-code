"""Listed next-session contracts only; no synthetic quotes or expiry substitution."""

import math
import re
from datetime import datetime
from decimal import ROUND_CEILING, Decimal

from .calendar import NY, next_session
from .config import Settings
from .models import Contract

OCC = re.compile(r"^(?:O:)?([A-Z.]{1,6})(\d{6})([CP])(\d{8})$")


def cents(dollars: float) -> int:
    return int((Decimal(str(dollars)) * 100).to_integral_value(rounding=ROUND_CEILING))


def premium_cents(price: float, multiplier: int) -> int:
    return int((Decimal(str(price)) * multiplier * 100).to_integral_value(rounding=ROUND_CEILING))


def quote_problems(c: Contract, now: datetime, cfg: Settings, fixture: bool = False) -> list[str]:
    result = []
    if c.feed != ("fixture" if fixture else "realtime"):
        result.append("quote feed is not eligible for this simulation")
    for name, stamp in [("quote", c.quote_at), ("underlying", c.underlying_at)]:
        if not 0 <= (now - stamp).total_seconds() <= cfg.max_quote_age_seconds:
            result.append(f"stale or future {name}")
    if c.bid <= 0 or c.bid > c.ask:
        result.append("zero or crossed quote")
    if c.bid_size <= 0 or c.ask_size <= 0:
        result.append("missing displayed quote size")
    match = OCC.fullmatch(c.symbol)
    if not match or (match[1], match[2], match[3], int(match[4])) != (
        c.underlying,
        c.expiry.strftime("%y%m%d"),
        c.right[0],
        round(c.strike * 1000),
    ):
        result.append("contract identifier disagrees with contract details")
    if c.multiplier != 100:
        result.append("non-standard deliverable")
    if c.expiry < now.astimezone(NY).date():
        result.append("expired contract")
    return result


def contract_problems(
    c: Contract, symbol: str, right: str, now: datetime, cfg: Settings, fixture: bool = False
) -> list[str]:
    result = quote_problems(c, now, cfg, fixture)
    if c.underlying != symbol or c.right != right:
        result.append("underlying or direction mismatch")
    if c.expiry != next_session(now.astimezone(NY).date()):
        result.append("not a listed next-session expiry")
    if not cfg.minimum_delta <= abs(c.delta) <= cfg.maximum_delta or (c.delta > 0) != (right == "CALL"):
        result.append("delta outside directional band")
    if c.open_interest < cfg.minimum_oi or c.volume < cfg.minimum_option_volume:
        result.append("insufficient open interest or volume")
    if c.volume_at > now or c.volume_at.astimezone(NY).date() != now.astimezone(NY).date():
        result.append("option volume is not from this session")
    if (c.ask - c.bid) / ((c.ask + c.bid) / 2) > cfg.maximum_spread:
        result.append("spread too wide")
    limit = math.ceil((c.ask + cfg.slippage) * 100 - 1e-9) / 100
    if premium_cents(limit, c.multiplier) + 2 * cents(cfg.fee_per_contract) > cents(cfg.max_trade_loss):
        result.append("one contract exceeds full-premium risk budget")
    return result


def select(
    contracts: list[Contract], symbol: str, right: str, now: datetime, cfg: Settings, fixture: bool = False
) -> tuple[Contract | None, dict[str, list[str]]]:
    rejected, eligible = {}, []
    for c in contracts:
        if c.underlying != symbol:
            continue
        reasons = contract_problems(c, symbol, right, now, cfg, fixture)
        if reasons:
            rejected[c.symbol] = reasons
        else:
            eligible.append(c)
    eligible.sort(
        key=lambda c: (abs(abs(c.delta) - 0.5), (c.ask - c.bid) / ((c.ask + c.bid) / 2), -c.open_interest, c.symbol)
    )
    return (eligible[0] if eligible else None), rejected
