"""Point-in-time fundamentals from SEC XBRL company facts.

Only facts FILED on or before the as-of date are used, so a weekly snapshot never
sees a later filing (no look-ahead) and an old snapshot can be rebuilt exactly.

Quarterly values come from 10-Q/10-K facts with an 80-120 day span (13-week
quarters and the 16-week quarters of 12/16-week fiscal calendars). Where a
company reports only year-to-date figures (cash flows) or only the fiscal year
(the fourth quarter), the discrete quarter is derived by subtracting cumulative
facts that share a start date; such quarters are flagged as derived.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import spec

FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A", "10-KT")
QUARTER_DAYS = spec.QUARTER_WINDOWS["quarter_span_days"]

FLOW_TAGS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense",
        "RegulatedAndUnregulatedOperatingRevenue",
    ],
    "gross_profit": ["GrossProfit"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "ocf": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "dna": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
    ],
    "interest_expense": ["InterestExpense", "InterestAndDebtExpense", "InterestExpenseDebt"],
}
SHARE_TAGS = ["WeightedAverageNumberOfDilutedSharesOutstanding"]
INSTANT_TAGS = {
    "cash_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "short_investments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    ],
    "debt_long": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt"],
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "short_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
    "assets": ["Assets"],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "debt_total": ["LongTermDebtAndShortTermBorrowings"],
}
CONCENTRATION_TAG = "ConcentrationRiskPercentage1"


def _d(s: str) -> date:
    return date.fromisoformat(s)


@dataclass
class Fundamentals:
    cik: int
    entity: str
    quarters: list[str]  # quarter end dates, newest first
    flows: dict[str, list[float | None]]  # discrete quarterly values aligned to `quarters`
    derived: dict[str, list[bool]]  # True where a quarter was derived by subtraction
    diluted_shares: list[float | None]
    instants: dict[str, float | None]  # latest balance sheet (at quarters[0] when available)
    cover_shares: float | None  # latest dei cover-page shares outstanding
    cover_shares_date: str | None
    last_filed: str | None
    last_form: str | None
    concentration: float | None = None
    notes: list[str] = field(default_factory=list)
    annual: dict[str, dict[str, float]] = field(default_factory=dict)
    quarterly_eps: list[float | None] = field(default_factory=list)

    @property
    def n_quarters(self) -> int:
        return len(self.quarters)

    def any_derived(self, keys=("revenue", "operating_income", "ocf", "capex"), n: int = 8) -> bool:
        return any(any(self.derived.get(k, [])[:n]) for k in keys)


def _facts(group: dict, tag: str, unit_ok, as_of: date) -> list[dict]:
    node = group.get(tag)
    if not node:
        return []
    out = []
    for unit, arr in node.get("units", {}).items():
        if not unit_ok(unit):
            continue
        for f in arr:
            if (
                f.get("form") in FORMS
                and f.get("filed")
                and _d(f["filed"]) <= as_of
                and f.get("end")
                and _d(f["end"]) <= as_of
            ):
                out.append(f)
    return out


def _rank(f: dict) -> tuple:
    """Prefer a 10-K for annual spans, then the latest filing (restatements win)."""
    annual = "start" in f and (_d(f["end"]) - _d(f["start"])).days > 300
    return (f["form"].startswith("10-K") if annual else True, f["filed"])


def _quarterly(group: dict, tags: list[str], unit_ok, as_of: date, additive: bool = True):
    """{quarter_end: (value, derived)} using the tag with the most recent coverage."""
    best = None
    for tag in tags:
        facts = _facts(group, tag, unit_ok, as_of)
        spans: dict[tuple[str, str], dict] = {}
        for f in facts:
            if "start" not in f:
                continue
            k = (f["start"], f["end"])
            if k not in spans or _rank(f) > _rank(spans[k]):
                spans[k] = f
        q: dict[str, tuple[float, bool]] = {}
        lo, hi = QUARTER_DAYS
        for (s, e), f in spans.items():
            if lo <= (_d(e) - _d(s)).days <= hi:
                q[e] = (float(f["val"]), False)
        if additive:
            by_start: dict[str, list[tuple[str, float]]] = {}
            for (s, e), f in spans.items():
                by_start.setdefault(s, []).append((e, float(f["val"])))
            for lst in by_start.values():
                lst.sort()
                for (e0, v0), (e1, v1) in zip(lst, lst[1:], strict=False):
                    if lo <= (_d(e1) - _d(e0)).days <= hi and e1 not in q:
                        q[e1] = (v1 - v0, True)
        if not q:
            continue
        latest = max(q)
        if best is None or latest > best[0] or (latest == best[0] and len(q) > len(best[1])):
            best = (latest, q, tag)
    return best[1] if best else {}


def _instant(group: dict, tags: list[str], as_of: date) -> dict[str, float]:
    best = None
    for tag in tags:
        vals: dict[str, tuple[float, str]] = {}
        for f in _facts(group, tag, lambda u: u == "USD", as_of):
            if "start" in f:
                continue
            if f["end"] not in vals or f["filed"] > vals[f["end"]][1]:
                vals[f["end"]] = (float(f["val"]), f["filed"])
        if vals and (best is None or max(vals) > max(best)):
            best = {k: v[0] for k, v in vals.items()}
    return best or {}


def _near(series: dict, end: str, days: int = 20):
    for k, v in series.items():
        if abs((_d(k) - _d(end)).days) <= days:
            return v
    return None


def build(facts: dict, as_of: date, max_quarters: int = 16) -> Fundamentals:
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    dei = (facts.get("facts") or {}).get("dei") or {}
    usd = lambda u: u == "USD"  # noqa: E731
    series = {k: _quarterly(gaap, tags, usd, as_of) for k, tags in FLOW_TAGS.items()}
    shares = _quarterly(gaap, SHARE_TAGS, lambda u: u == "shares", as_of, additive=False)
    eps = _quarterly(gaap, ["EarningsPerShareDiluted"], lambda u: u == "USD/shares", as_of, additive=False)

    anchor = series["revenue"] or series["net_income"]
    ends: list[str] = []
    for e in sorted(anchor, reverse=True):  # one entry per quarter (52/53-week calendars drift)
        if all(abs((_d(e) - _d(c)).days) > 20 for c in ends):
            ends.append(e)
    ends = ends[:max_quarters]

    flows, derived = {}, {}
    for k, s in series.items():
        vals = [_near(s, e) for e in ends]
        flows[k] = [None if v is None else v[0] for v in vals]
        derived[k] = [bool(v and v[1]) for v in vals]
    # fill gross profit from revenue - cost of revenue where only the cost is tagged
    flows["gross_profit"] = [
        gp if gp is not None else (r - c if r is not None and c is not None else None)
        for gp, r, c in zip(flows["gross_profit"], flows["revenue"], flows["cost_of_revenue"], strict=False)
    ]
    dil = [_near(shares, e) for e in ends]

    instants = {}
    for k, tags in INSTANT_TAGS.items():
        vals = _instant(gaap, tags, as_of)
        v = _near(vals, ends[0], 10) if ends and vals else None
        instants[k] = v

    filings = [f for k in ("revenue", "net_income") for tag in FLOW_TAGS[k] for f in _facts(gaap, tag, usd, as_of)]
    last = max(filings, key=lambda f: f["filed"]) if filings else None

    # only the cover page of the latest statements filing (or later): issuers that switch to per-class
    # cover counts leave an old undimensioned value behind (spec 2026-10-19.2)
    cover, cover_date = None, None
    by_end: dict[str, tuple[float, str]] = {}
    for f in _facts(dei, "EntityCommonStockSharesOutstanding", lambda u: u == "shares", as_of):
        e = f["end"]
        if last is not None and f["filed"] < last["filed"]:
            continue
        if e not in by_end or f["filed"] > by_end[e][1]:
            by_end[e] = (float(f["val"]), f["filed"])
    if by_end:
        cover_date = max(by_end)
        cover = by_end[cover_date][0]

    conc = None
    for f in _facts(gaap, CONCENTRATION_TAG, lambda u: u == "pure", as_of):
        if conc is None or f["filed"] > conc[1]:
            conc = (float(f["val"]), f["filed"])

    return Fundamentals(
        cik=int(facts.get("cik") or 0),
        entity=str(facts.get("entityName", "")),
        quarters=ends,
        flows=flows,
        derived=derived,
        diluted_shares=[None if v is None else v[0] for v in dil],
        instants=instants,
        cover_shares=cover,
        cover_shares_date=cover_date,
        last_filed=last["filed"] if last else None,
        last_form=last["form"] if last else None,
        concentration=conc[0] if conc else None,
        annual={
            "revenue": annual_series(gaap, FLOW_TAGS["revenue"], "USD", as_of),
            "eps": annual_series(gaap, ["EarningsPerShareDiluted"], "USD/shares", as_of),
        },
        quarterly_eps=[v[0] if v else None for v in (_near(eps, e) for e in ends)],
    )


def annual_series(group: dict, tags: list[str], unit: str, as_of: date) -> dict[str, float]:
    """Full fiscal years, one consistent tag; latest available restatement wins."""
    candidates = []
    for tag in tags:
        by_end = {}
        for f in _facts(group, tag, lambda u: u == unit, as_of):
            if not f.get("start") or not 330 <= (_d(f["end"]) - _d(f["start"])).days <= 380:
                continue
            old = by_end.get(f["end"])
            if old is None or _rank(f) > _rank(old):
                by_end[f["end"]] = f
        if by_end:
            candidates.append(by_end)
    best = max(candidates, key=lambda x: (max(x), len(x)), default={})
    return {end: float(f["val"]) for end, f in best.items()}


def consecutive(quarters: list[str], start: int, n: int = 4) -> bool:
    """True when quarters[start:start+n] are n adjacent fiscal quarters (newest first)."""
    if start < 0 or start + n > len(quarters):
        return False
    ends = [_d(q) for q in quarters[start : start + n]]
    lo, hi = spec.QUARTER_WINDOWS["step_days"]
    if not all(lo <= (a - b).days <= hi for a, b in zip(ends, ends[1:], strict=False)):
        return False
    span_lo, span_hi = spec.QUARTER_WINDOWS["ttm_span_days"]
    return n != 4 or span_lo <= (ends[0] - ends[-1]).days <= span_hi


def quarter_back(quarters: list[str], start: int, years: float) -> int | None:
    """Index of the quarter ending about `years` before quarters[start]; None when no end date is close enough."""
    if not 0 <= start < len(quarters):
        return None
    target = _d(quarters[start]).toordinal() - round(years * 365.2425)
    best = min(range(start, len(quarters)), key=lambda i: abs(_d(quarters[i]).toordinal() - target))
    if abs(_d(quarters[best]).toordinal() - target) > spec.QUARTER_WINDOWS["match_days"]:
        return None
    return best


def ttm(values: list[float | None], offset: int = 0, quarters: list[str] | None = None) -> float | None:
    """Sum of 4 consecutive quarters starting `offset` quarters back; None if any is missing.

    With `quarters` (the aligned end dates, newest first) the offset is calendar time: the window
    must start about offset/4 years before the newest quarter and be four adjacent quarters, so a gap
    in the reported series never splices quarters from different years (spec 2026-10-19.2).
    Without it the offset counts list positions.
    """
    if quarters is not None:
        start = quarter_back(quarters, 0, offset / 4)
        if start is None or not consecutive(quarters, start):
            return None
        offset = start
    window = values[offset : offset + 4]
    if len(window) < 4 or any(v is None for v in window):
        return None
    return float(sum(window))


def growth(new: float | None, old: float | None) -> float | None:
    """Growth on a positive base only; None when not computable."""
    if new is None or old is None or old <= 0:
        return None
    return new / old - 1


def total_debt(inst: dict[str, float | None]) -> float | None:
    parts = [inst.get("debt_long"), inst.get("debt_current"), inst.get("short_borrowings")]
    if all(p is None for p in parts):
        return None
    return float(sum(p for p in parts if p is not None))


def cash_like(inst: dict[str, float | None]) -> float | None:
    if inst.get("cash_equivalents") is None and inst.get("short_investments") is None:
        return None
    return float((inst.get("cash_equivalents") or 0.0) + (inst.get("short_investments") or 0.0))
