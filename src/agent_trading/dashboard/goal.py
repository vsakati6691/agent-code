"""Pure reference arithmetic for the browser-only Plan 2030 calculator.

These functions never read accounts, select securities, rank allocations or persist inputs.
"""

import math


def finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def ending_value(capital: float, monthly: float, years: float, rate: float) -> float | None:
    """End-of-month contributions; fractional final month compounds without an extra contribution."""
    if not all(finite(x) for x in (capital, monthly, years, rate)):
        return None
    if capital < 0 or monthly < 0 or not 0 <= years <= 100 or rate <= -1:
        return None
    try:
        n = math.floor(years * 12 + 1e-9)
        value = capital * (1 + rate) ** years
        value += sum(monthly * (1 + rate) ** (years - i / 12) for i in range(1, n + 1))
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def required_rate(capital: float, target: float, monthly: float, years: float) -> float | None:
    if not all(finite(x) for x in (capital, target, monthly, years)):
        return None
    if capital <= 0 or target <= 0 or monthly < 0 or not 0 < years <= 100:
        return None
    low, high = -0.999999999999, 1.0
    floor = ending_value(capital, monthly, years, low)
    if floor is None or floor > target:
        return None  # no finite solution in the supported range (e.g. target below last contribution)
    while high < 1_000_000 and (ending_value(capital, monthly, years, high) or math.inf) < target:
        high *= 2
    ceiling = ending_value(capital, monthly, years, high)
    if ceiling is not None and ceiling < target:
        return None
    for _ in range(120):
        middle = (low + high) / 2
        value = ending_value(capital, monthly, years, middle)
        if value is None or value > target:
            high = middle
        else:
            low = middle
    return (low + high) / 2


def weighted_endings(capital: float, monthly: float, years: float, weights: dict, rates: dict) -> dict:
    """Weights split initial capital and every contribution; no rebalancing or missing-value renormalization."""
    missing = []
    result = {key: None for key in ("bear", "base", "bull")}
    if not weights or any(not finite(v) or not 0 <= v <= 1 for v in weights.values()):
        return {"values": result, "reason": "Weights must be between 0 and 100%."}
    if abs(sum(weights.values()) - 1) > 1e-8:
        return {"values": result, "reason": "Weights must total 100%."}
    for ticker, weight in weights.items():
        if weight > 0 and any(not finite((rates.get(ticker) or {}).get(k)) for k in result):
            missing.append(ticker)
    if missing:
        return {"values": result, "reason": "Stored scenario unavailable: " + ", ".join(missing)}
    for key in result:
        values = [ending_value(capital * w, monthly * w, years, rates[t][key]) for t, w in weights.items() if w > 0]
        result[key] = sum(values) if all(v is not None for v in values) else None
    return {"values": result, "reason": ""}


def stressed_ending(capital: float, monthly: float, years: float, rate: float, drawdown: float) -> float | None:
    """Zero return during year one, shock at its end (including 12 contributions), then base compounding."""
    if not finite(drawdown) or not 0 <= drawdown <= 1 or not finite(years) or years < 1:
        return None
    first = ending_value(capital, monthly, 1, 0)
    return None if first is None else ending_value(first * (1 - drawdown), monthly, years - 1, rate)
