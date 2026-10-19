"""Leaders-only conditional valuation; registered assumptions, never calibrated probabilities."""

from __future__ import annotations

from datetime import date

from . import spec
from .fmt import ok
from .fundamentals import consecutive


def unbroken(quarters: list, n: int) -> bool:
    try:
        return consecutive(list(quarters), 0, n)
    except (TypeError, ValueError):
        return False


def _version_key(version: str) -> tuple[str, int] | None:
    day, _, n = version.partition(".")
    try:
        return date.fromisoformat(day).isoformat(), int(n)
    except ValueError:
        return None


def positional_metrics(version: str | None) -> bool:
    """True when a snapshot's stored TTM metrics were computed by list position (before 2026-10-19.4)."""
    key = _version_key(version) if isinstance(version, str) else None
    return key is None or key < _version_key(spec.LEADERS_SHARE_CHECKS["date_matched_from"])


def growth_input(record: dict, metrics: dict, as_of: str, positional: bool = True) -> tuple[float | None, str]:
    """Prefer the three-year TTM series; dated fiscal-year endpoints are an explicit fallback.

    Snapshots before 2026-10-19.4 computed the stored TTM CAGR by list position, so for them it counts
    only over an unbroken run of 16 stored quarters; later snapshots already match quarter dates.
    """
    value = metrics.get("revenue_cagr_3y")
    quarters = (record.get("fundamentals") or {}).get("quarters") or []
    if ok(value) and (not positional or unbroken(quarters, spec.LEADERS_SHARE_CHECKS["cagr_quarters"])):
        return value, "TTM revenue CAGR over three years"
    group = ((record.get("decision_research") or {}).get("groups") or {}).get("growth") or {}
    field = (group.get("fields") or {}).get("revenue_cagr_3y") or {}
    stamp = field.get("as_of") or group.get("as_of")
    try:
        dated = isinstance(stamp, str) and date.fromisoformat(stamp).isoformat() == stamp and stamp <= as_of
    except ValueError:
        dated = False
    if ok(field.get("value")) and dated:
        return field["value"], f"Fiscal-year revenue CAGR over three years, filed {stamp}"
    return None, "three-year revenue CAGR unavailable; one-year growth is not substituted"


def is_cyclical(ticker: str, record: dict) -> bool:
    rules = spec.LEADERS_SCENARIO_RULES
    return ticker in rules["cyclical_tickers"] or any(
        str(record.get(key) or "").casefold().strip() in rules["cyclical_sectors"]
        for key in ("sector", "industry", "ai_role")
    )


def company_scenarios(
    *, current_cap: float, shares: float, metrics: dict, years: float, growth: float, basis: str, cyclical: bool
) -> dict:
    rules = spec.LEADERS_SCENARIO_RULES
    if not all(ok(v) and v > 0 for v in (current_cap, shares, years, metrics["revenue_ttm"], metrics["ev_to_sales"])):
        raise ValueError("cap, shares, horizon, revenue and EV/Sales must be finite and positive")
    if not all(ok(v) for v in (growth, metrics["net_debt"], metrics["dilution"])):
        raise ValueError("growth, net debt and dilution must be finite")
    base = min(rules["growth_cap"], max(rules["growth_floor"], growth))
    fade = rules["large_cap_fade"] if current_cap > rules["large_cap_threshold_usd"] else rules["fade"]
    result = {}
    for case in spec.SCENARIOS:
        g = max(rules["growth_floor"], base * case.growth_multiplier + case.growth_shift)
        terminal = rules["terminal_growth"]
        if case.key == "bear":
            ceiling = rules["cyclical_bear_growth_ceiling"] if cyclical else rules["bear_growth_ceiling"]
            g, terminal = min(g, base, ceiling), rules["bear_terminal_growth"]
        elif case.key == "bull":
            g = max(g, base)
        revenue, elapsed, path = metrics["revenue_ttm"], 0.0, []
        while elapsed < years - 1e-9:
            step = min(1.0, years - elapsed)
            revenue *= (1 + g) ** step
            path.append(g)
            g += fade * (terminal - g)
            elapsed += step
        dilution = metrics["dilution"] + case.dilution_shift
        if dilution <= -1:
            raise ValueError("projected share growth must exceed -100%")
        projected_shares = shares * (1 + dilution) ** years
        exit_multiple = max(spec.SCENARIO_MIN_EV_SALES, metrics["ev_to_sales"] * case.exit_multiple_factor)
        raw_cap = max(0.0, revenue * exit_multiple - metrics["net_debt"])
        cap = min(raw_cap, current_cap * rules["bear_cap_ceiling_fraction"]) if case.key == "bear" else raw_cap
        if not all(ok(v) for v in (raw_cap, projected_shares)) or projected_shares <= 0:
            raise ValueError("non-finite valuation or non-positive projected shares")
        result[case.key] = {
            "cap": cap,
            "price": cap / projected_shares,
            "shares": projected_shares,
            "implied_cagr": (cap / current_cap) ** (1 / years) - 1,
            "assumptions": {
                "growth_basis": basis,
                "observed_revenue_cagr_3y": growth,
                "growth_path": path,
                "fade": fade,
                "terminal_growth": terminal,
                "cyclical": cyclical,
                "revenue_2030": revenue,
                "exit_ev_to_sales": exit_multiple,
                "net_cash_held": -metrics["net_debt"],
                "annual_dilution": dilution,
                "years": years,
                "unconstrained_cap": raw_cap,
                "bear_stress_adjustment": raw_cap - cap,
            },
        }
    return result
