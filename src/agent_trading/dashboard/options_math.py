"""Pure option payoff and pricing math, used only for labelled sensitivity analysis."""

import math

from . import spec


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
