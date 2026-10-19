"""Pure, dated decision-research calculations. Missing inputs never become zero."""

from __future__ import annotations

import math
from datetime import date

from . import scoring, spec
from .fundamentals import Fundamentals, quarter_back, ttm

# key, label, format. The same schema drives detail cards and the sortable scanner.
FIELDS = {
    "valuation": (
        ("pe", "Trailing P/E", "multiple"),
        ("forward_pe", "Forward P/E", "multiple"),
        ("peg", "PEG (provider estimate)", "multiple"),
        ("ev_sales", "EV/Sales", "multiple"),
        ("fcf_yield", "FCF yield", "pct"),
    ),
    "growth": (
        ("revenue_cagr_3y", "Revenue CAGR · 3Y", "pct"),
        ("revenue_cagr_5y", "Revenue CAGR · 5Y", "pct"),
        ("eps_cagr_3y", "Diluted EPS CAGR · 3Y", "pct"),
        ("eps_cagr_5y", "Diluted EPS CAGR · 5Y", "pct"),
        ("revenue_yoy", "Latest quarter revenue YoY", "pct"),
        ("eps_yoy", "Latest quarter EPS YoY", "pct"),
        ("growth_trend", "Revenue growth trend", "text"),
        ("gross_margin", "Gross margin TTM", "pct"),
        ("gross_margin_change", "Gross margin trend", "pp"),
        ("operating_margin", "Operating margin TTM", "pct"),
        ("operating_margin_change", "Operating margin trend", "pp"),
        ("fcf_margin", "FCF margin TTM", "pct"),
        ("fcf_margin_change", "FCF margin trend", "pp"),
    ),
    "balance": (
        ("net_debt_ebitda", "Net debt / EBITDA", "multiple"),
        ("corporate_cash", "Cash & equivalents", "money"),
        ("debt", "Total debt", "money"),
        ("interest_coverage", "Interest coverage", "multiple"),
        ("share_change", "Diluted shares · 1Y change", "pct"),
    ),
    "ownership": (
        ("insider_net", "Insider net purchases · 6M", "shares"),
        ("analyst_target", "Analyst target", "money"),
        ("rating_count", "Analyst rating count", "number"),
    ),
    "timing": (
        ("next_earnings", "Next earnings (unverified)", "text"),
        ("below_high", "Below 52-week high", "pct"),
        ("return_1y", "1Y price return", "pct"),
        ("extended", "Extension flag", "text"),
    ),
    "quality": (("quality", "Fundamental quality / 100", "number"), ("momentum", "Momentum / 100", "number")),
}


def finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def field(value=None, reason="Required source inputs unavailable", **meta) -> dict:
    if isinstance(value, (int, float)) and not finite(value):
        value = None
    return {"value": value, "reason": reason if value is None else None, **meta}


def ratio(n, d):
    return n / d if finite(n) and finite(d) and d > 0 else None


def change(new, old):
    v = ratio(new, old)
    return v - 1 if v is not None else None


def cagr(series: dict[str, float], years: int) -> dict:
    if not series:
        return field(reason="No full fiscal-year XBRL series")
    end = max(series)
    target = date.fromisoformat(end).toordinal() - round(years * 365.2425)
    prior = min(series, key=lambda d: abs(date.fromisoformat(d).toordinal() - target))
    if abs(date.fromisoformat(prior).toordinal() - target) > spec.DECISION_RULES["annual_match_days"]:
        return field(reason=f"No comparable fiscal year {years} years before {end}")
    new, old = series[end], series[prior]
    if not finite(new) or not finite(old) or min(new, old) <= 0:
        return field(reason="CAGR requires positive beginning and ending values")
    return field((new / old) ** (1 / years) - 1, period=f"{prior} to {end}")


def trend(delta, band: float, labels=("accelerating", "stable", "decelerating")):
    if not finite(delta):
        return None
    return labels[0] if delta > band + 1e-12 else labels[2] if delta < -band - 1e-12 else labels[1]


def margin_change(numerators: list, revenues: list) -> tuple:
    current, old = ratio(ttm(numerators), ttm(revenues)), ratio(ttm(numerators, 4), ttm(revenues, 4))
    return current, current - old if current is not None and old is not None else None


def percentile(value, peers: list) -> dict:
    peers = [v for v in peers if finite(v)]
    if not finite(value) or len(peers) < 2:
        return field(
            reason="Percentile needs this value and at least two available values in the same list", n=len(peers)
        )
    rank = sum(v < value for v in peers) + (sum(v == value for v in peers) - 1) / 2
    return field(100 * rank / (len(peers) - 1), n=len(peers))


def score_split(metrics: dict, f: Fundamentals | None = None) -> dict:
    quality = scoring.score_one("", metrics, f, [], spec.GROWTH_COMPONENTS).composite
    momentum = [
        scoring.scale(metrics[k], scale)
        for c in spec.COMPONENTS
        if c.key in ("momentum", "relative")
        for k, scale in c.metrics.items()
        if finite(metrics.get(k))
    ]
    # Require all three metrics: partial evidence must not inflate the displayed score.
    return {
        "quality": field(quality, "Insufficient critical fundamentals for a quality score"),
        "momentum": field(
            100 * sum(momentum) / 3 if len(momentum) == 3 else None,
            "Needs 12–1 month momentum and 6M/12M benchmark-relative returns",
        ),
    }


def build(
    f: Fundamentals,
    metrics: dict,
    closes,
    highs,
    as_of: date,
    earnings: str | None,
    observed_at: str,
    enrichment: dict | None = None,
) -> dict:
    extra = enrichment or {}
    groups = {g: {"as_of": f.last_filed, "source": "SEC EDGAR XBRL", "fields": {}} for g in FIELDS}
    groups["valuation"].update(
        as_of=as_of.isoformat(), source="SEC filings + delayed Cboe price; Alpha Vantage estimates"
    )
    for g in ("ownership", "timing"):
        groups[g].update(
            as_of=observed_at,
            source="Alpha Vantage" if g == "ownership" else "Cboe delayed; Alpha Vantage earnings calendar",
        )
    groups["quality"].update(
        as_of=as_of.isoformat(), source="Registered model; SEC fundamentals and delayed Cboe prices"
    )
    out = {g: groups[g]["fields"] for g in groups}

    # A missing entire quarter must not shift a prior fiscal year into the YoY comparison.
    def aligned(values):
        if not f.quarters:
            return []
        # the quarter ending i quarters of calendar time back, within spec.QUARTER_WINDOWS["match_days"]
        back = [quarter_back(f.quarters, 0, i / 4) for i in range(spec.DECISION_RULES["max_quarters"])]
        return [values[j] if j is not None and j < len(values) else None for j in back]

    flow = {key: aligned(values) for key, values in f.flows.items()}
    eps, shares = aligned(f.quarterly_eps), aligned(f.diluted_shares)
    rev = flow.get("revenue", [])
    fcf = [
        a - b if finite(a) and finite(b) else None
        for a, b in zip(flow.get("ocf", []), flow.get("capex", []), strict=False)
    ]

    def at(values, i):
        return values[i] if len(values) > i else None

    for key in ("revenue", "eps"):
        for years in spec.DECISION_RULES["cagr_years"]:
            out["growth"][f"{key}_cagr_{years}y"] = cagr(f.annual.get(key, {}), years)
    q_yoy, previous = change(at(rev, 0), at(rev, 4)), change(at(rev, 1), at(rev, 5))
    out["growth"].update(
        revenue_yoy=field(q_yoy, "Latest and year-earlier revenue quarter required; positive base"),
        eps_yoy=field(
            change(at(eps, 0), at(eps, 4)), "Direct diluted EPS quarters with a positive year-earlier base required"
        ),
        growth_trend=field(
            trend(
                q_yoy - previous if q_yoy is not None and previous is not None else None,
                spec.DECISION_RULES["growth_trend_band"],
            ),
            "Needs latest and preceding quarter YoY revenue growth",
        ),
    )
    for key, values in (
        ("gross", flow.get("gross_profit", [])),
        ("operating", flow.get("operating_income", [])),
        ("fcf", fcf),
    ):
        margin, delta = margin_change(values, rev)
        out["growth"][f"{key}_margin"] = field(margin, "Four complete quarters and positive TTM revenue required")
        out["growth"][f"{key}_margin_change"] = field(
            delta,
            "Eight complete quarters required",
            trend=trend(delta, spec.DECISION_RULES["margin_trend_band"], ("improving", "stable", "deteriorating")),
        )
    inst = f.instants
    debt = inst.get("debt_total")
    parts = [inst.get(k) for k in ("debt_long", "debt_current", "short_borrowings")]
    if not finite(debt):
        debt = sum(parts) if all(finite(v) for v in parts) else None
    cash = inst.get("cash_equivalents")
    net = debt - cash if finite(debt) and finite(cash) else None
    oi, dna = ttm(flow.get("operating_income", [])), ttm(flow.get("dna", []))
    ebitda = oi + dna if finite(oi) and finite(dna) else None
    out["balance"].update(
        corporate_cash=field(cash, "Cash and equivalents not tagged"),
        debt=field(debt, "Total debt or all three debt components not tagged; missing is not zero"),
        net_debt_ebitda=field(
            ratio(net, ebitda), "Complete debt/cash and positive EBITDA required; net cash stays negative"
        ),
        interest_coverage=field(
            ratio(oi, ttm(flow.get("interest_expense", []))),
            "TTM operating income and positive interest expense required",
        ),
        share_change=field(
            change(at(shares, 0), at(shares, 4)), "Diluted share counts in latest and year-earlier quarters required"
        ),
    )
    cap = metrics.get("market_cap")
    ni = ttm(flow.get("net_income", []))
    ev = cap + net if finite(cap) and finite(net) else None
    out["valuation"].update(
        pe=field(ratio(cap, ni), "Positive TTM net income and market cap required"),
        ev_sales=field(
            ratio(ev, ttm(rev)) if finite(ev) and ev > 0 else None,
            "Positive enterprise value/revenue and complete debt/cash required",
        ),
        fcf_yield=field(
            ratio(ttm(fcf), cap), "Complete TTM operating cash flow/capex and positive market cap required"
        ),
    )
    estimates = extra.get("estimates", {})
    for group, keys in (("valuation", ("forward_pe", "peg")), ("ownership", ("analyst_target", "rating_count"))):
        for key in keys:
            out[group][key] = estimates.get(
                key, field(reason=extra.get("estimates_reason", "Alpha Vantage estimates not collected"))
            )
    out["ownership"]["insider_net"] = extra.get(
        "insider_net", field(reason=extra.get("insider_reason", "Insider transaction data not collected"))
    )
    close = list(closes)
    high = list(highs)
    ret = change(close[-1], close[-253]) if len(close) >= 253 else None
    below = (
        1 - close[-1] / max(high[-252:]) if len(high) >= 252 and all(finite(v) and v > 0 for v in high[-252:]) else None
    )
    out["timing"].update(
        next_earnings=field(earnings, "No scheduled earnings date supplied"),
        below_high=field(below, "252 daily high prices required"),
        return_1y=field(ret, "253 closing prices required"),
        extended=field("extended" if ret > spec.DECISION_RULES["extended_return"] else "not extended", "")
        if ret is not None
        else field(reason="1Y return unavailable"),
    )
    out["quality"].update(score_split(metrics, f))
    for g, fields in out.items():
        for value in fields.values():
            value.setdefault("as_of", groups[g]["as_of"])
    return {
        "groups": groups,
        "business": extra.get("business", {"reason": "10-K narrative not collected"}),
        "spark": close[-253:] if len(close) >= 253 else [],
        "price_as_of": as_of.isoformat(),
        "filing_as_of": f.last_filed,
        "period_end": f.quarters[0] if f.quarters else None,
        "observed_at": observed_at,
    }


def add_percentiles(candidates: list[dict]) -> None:
    """Mutate only the new snapshot's published list, never historical snapshots."""
    for key, _, _ in FIELDS["valuation"]:
        values = [
            c.get("decision_research", {}).get("groups", {}).get("valuation", {}).get("fields", {}).get(key, {})
            for c in candidates
        ]
        for value in values:
            value["percentile"] = percentile(value.get("value"), [v.get("value") for v in values])
