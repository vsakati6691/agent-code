"""Number formatting shared by the site modules (missing or non-finite values print as n/a)."""
from __future__ import annotations

import math


def ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def pct(v, digits: int = 0, sign: bool = False) -> str:
    if not ok(v):
        return "n/a"
    return f"{v:{'+' if sign else ''}.{digits}%}"


def num(v, digits: int = 2) -> str:
    return f"{v:,.{digits}f}" if ok(v) else "n/a"


def money(v, digits: int = 2) -> str:
    if not ok(v):
        return "n/a"
    return f"-${-v:,.{digits}f}" if v < 0 else f"${v:,.{digits}f}"


def cap(v) -> str:
    if not ok(v):
        return "n/a"
    if v < 0:
        return "-" + cap(-v)
    return f"${v / 1e12:.2f}T" if v >= 1e12 else f"${v / 1e9:.1f}B" if v >= 1e9 else f"${v / 1e6:.0f}M"


def sval(v) -> str:
    """data-v attribute for numeric sorting."""
    return f"{v:.6g}" if ok(v) else ""
