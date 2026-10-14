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


# ratio metrics are shown as percentages; everything else as a plain rounded number
PCT_METRICS = {
    "revenue_growth_ttm", "revenue_cagr_3y", "growth_consistency", "growth_acceleration",
    "operating_income_growth_ttm", "fcf_growth_ttm", "fcf_margin_change", "fcf_margin", "gross_margin",
    "operating_margin", "roic", "accruals", "dilution", "sbc_to_revenue", "fcf_yield", "implied_growth_gap",
    "implied_revenue_cagr", "return_12_1", "excess_6m", "excess_12m", "return_6m", "return_12m",
    "operating_margin_change",
}
MULTIPLE_METRICS = {"net_debt_to_ebitda", "current_ratio", "ev_to_sales", "ev_to_sales_per_growth", "pe"}


def plain(v: float, sig: int = 4) -> str:
    """A rounded number with no scientific notation (4 significant digits by default)."""
    if v == 0:
        return "0"
    from math import floor, log10
    decimals = max(0, sig - 1 - int(floor(log10(abs(v)))))
    out = f"{round(v, decimals):,.{decimals}f}"
    return out.rstrip("0").rstrip(".") if "." in out else out


def metric(name: str, v) -> str:
    """Display form of one scoring input: percentages for ratios, rounded plain numbers otherwise."""
    if v is None:
        return "n/a"
    if not ok(v):
        return "not meaningful"
    if name in ("operating_income_growth_ttm", "fcf_growth_ttm") and v == -1.0:
        return "not meaningful (negative base)"
    if name in PCT_METRICS:
        return f"{v:+.1%}" if name in ("growth_acceleration", "fcf_margin_change", "implied_growth_gap",
                                        "operating_margin_change", "excess_6m", "excess_12m", "return_12_1") \
            else f"{v:.1%}"
    if name == "log_market_cap":
        return f"{cap(10 ** v)} market cap"
    if name in MULTIPLE_METRICS:
        return f"{plain(v)}x"
    return plain(v)


def csv_value(v):
    """CSV cell: rounded floats without scientific notation; missing or non-finite values are empty."""
    if isinstance(v, bool) or v is None:
        return "" if v is None else str(v)
    if isinstance(v, float):
        return plain(v, 6).replace(",", "") if ok(v) else ""
    return v


def net_position(net_debt, capital: bool = True) -> str:
    """'Net debt $X' or 'Net cash $X' (never both words); net_debt < 0 means net cash."""
    if not ok(net_debt):
        return "Net debt n/a" if capital else "net debt n/a"
    word = "debt" if net_debt > 0 else "cash"
    return f"{'N' if capital else 'n'}et {word} {cap(abs(net_debt))}"


SUMMARIES = {
    "multibagger": "A 'multibagger' here means a bull case of at least 5x today's price in five years; 2x and "
                   "10-year tests are shown separately, and none of it is a forecast.",
    "probability": "No probabilities are shown, because no model here has proven out-of-sample calibration.",
    "scenario_method": "Values come from a revenue growth path and an EV/Sales multiple, with every assumption "
                       "listed; they are conditional, not forecasts.",
}


def summary_details(summary: str, full: str, label: str = "Full definition") -> str:
    """One-sentence summary with the full text in a toggle (overview and detail pages)."""
    import html
    return (f'<div class="small summary">{html.escape(summary)} <details class="more"><summary>{html.escape(label)}'
            f'</summary><p>{html.escape(full)}</p></details></div>')


def tracking_schedule(dates: list[str]) -> str:
    """When forward-return tracking and evidence claims become available, from the first snapshot date."""
    from datetime import date as _date

    from . import spec
    from ..market_calendar import next_trading_day
    if not dates:
        return ("Tracking starts once the first weekly snapshot exists: 1-month results 21 trading sessions later, "
                f"then 3, 6 and 12 months; no edge is claimed before {spec.MIN_SNAPSHOTS_FOR_EVIDENCE} snapshots.")
    first = _date.fromisoformat(dates[0])

    def after(n):
        d = first
        for _ in range(n):
            d = next_trading_day(d)
        return d.isoformat()
    h = spec.TRACK_HORIZONS
    return (f"Tracking starts {h['1m']} trading sessions after the first snapshot ({dates[0]}): 1-month results from "
            f"about {after(h['1m'])}, 3-month from {after(h['3m'])}, 6-month from {after(h['6m'])} and 12-month from "
            f"{after(h['12m'])}. Any claim of an edge waits for at least {spec.MIN_SNAPSHOTS_FOR_EVIDENCE} weekly "
            f"snapshots ({len(dates)} stored so far).")


def sval(v) -> str:
    """data-v attribute for numeric sorting (plain digits, never scientific notation)."""
    return plain(v, 8).replace(",", "") if ok(v) else ""
