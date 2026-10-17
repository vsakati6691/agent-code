"""Shared pure fill mechanics; sequencing and portfolio risk stay in each engine."""


def stop_fill(open_price: float, low: float, stop: float) -> float | None:
    """A long protective stop fills at the stop or a worse opening gap, before costs."""
    return min(open_price, stop) if low <= stop else None
