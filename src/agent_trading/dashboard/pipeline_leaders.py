"""Complete weekly index inputs within existing budgets, then retain them without I/O."""

from __future__ import annotations

import pandas as pd

from . import decisions, scoring, spec
from .fmt import ok
from .pipeline_collect import _facts, watchlist_bars
from .pipeline_context import Context
from .pipeline_details import _clean
from .pipeline_score import market_cap
from .watchlist import evidence_quality


def _cik(ticker: str, identity, ref: dict) -> int | None:
    cik = identity.get("cik")
    if pd.notna(cik):
        return int(cik)
    sec = ref.get("sec")
    return int(sec.loc[ticker, "cik"]) if sec is not None and ticker in sec.index else None


def collect_inputs(ctx: Context, ref: dict) -> dict:
    """Fill gaps after list screening, independently of price/liquidity/tradability gates.

    Successful and failed lookups are memoized. A short-history fallback only
    revalidates the HTTP-cached history; other rejected prices stay rejected.
    Development --limit remains bounded and can never imply full coverage.
    """
    before = ctx.providers.http.usage().get("requests", {}).copy()
    members = ref["sp500"]
    selected = members.iloc[: ctx.limit] if ctx.limit else members
    for ticker, identity in selected.iterrows():
        watchlist_bars(ctx, ticker)
        cik = _cik(ticker, identity, ref)
        if cik is not None:
            _facts(ctx, cik)
    after = ctx.providers.http.usage().get("requests", {})
    return {
        "members_requested": len(selected),
        "universe_count": len(members),
        "limited": bool(ctx.limit),
        "additional_requests": {
            key: after.get(key, 0) - before.get(key, 0) for key in sorted(before.keys() | after.keys())
        },
    }


def retained_inputs(ctx, ref: dict) -> list[dict]:
    rows = []
    for ticker, identity in ref["sp500"].iterrows():
        cik = _cik(ticker, identity, ref)
        f, why = ctx.facts.get(cik, (None, "SEC financial statements not collected for this member"))
        if cik is None:
            why = "No SEC registrant identifier for this member"
        bars, price_why, flags = ctx.histories.get(ticker, (None, "As-of price not collected for this member", []))
        if bars is None:
            bars, price_why, flags = ctx.histories.get(
                (ticker, spec.WATCHLIST_MIN_PRICE_BARS), (bars, price_why, flags)
            )
        row = {
            "ticker": ticker,
            "name": identity.get("name", ticker),
            "sector": identity.get("sector", "Unknown"),
            "industry": identity.get("industry") if pd.notna(identity.get("industry")) else None,
            "cik": cik,
            "price": None,
            "price_date": None,
            "missing": flags,
            "unavailable_reason": why if f is None else price_why if bars is None else None,
        }
        if bars is not None and len(bars):
            row.update(price=float(bars["close"].iloc[-1]), price_date=str(bars.index[-1].date()))
        if f is not None:
            row["fundamentals"] = {
                "quarters": f.quarters,
                "diluted_shares": f.diluted_shares,
                "last_filed": f.last_filed,
            }
            row["evidence_quality"] = evidence_quality("company", f, len(bars) if bars is not None else 0)
        if f is not None and bars is not None and ok(row["price"]):
            cap, _ = market_cap(f, row["price"])
            m = scoring.compute_metrics(f, bars["close"], None, cap)
            row["metrics"] = {
                key: m.get(key)
                for key in (
                    "revenue_ttm",
                    "revenue_growth_ttm",
                    "revenue_cagr_3y",
                    "ev_to_sales",
                    "net_debt",
                    "dilution",
                    "gross_margin",
                    "operating_margin",
                    "fcf_margin",
                )
            }
            fields = {
                key: {"value": m.get(key), "as_of": f.last_filed}
                for key in ("gross_margin", "operating_margin", "fcf_margin")
            }
            for metric, series in (("revenue", "revenue"), ("eps", "eps")):
                for years in (3, 5):
                    fields[f"{metric}_cagr_{years}y"] = {
                        **decisions.cagr(f.annual.get(series, {}), years),
                        "as_of": f.last_filed,
                    }
            row["decision_research"] = {
                "groups": {"growth": {"fields": fields, "as_of": f.last_filed}},
                "business": ctx.decision_extras.get(ticker, {}).get("business", {}),
            }
        rows.append(row)
    return _clean(rows)
