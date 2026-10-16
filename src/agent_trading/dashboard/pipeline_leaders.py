"""Retain inputs the weekly run already holds, without invoking any provider."""

from __future__ import annotations

import pandas as pd

from . import decisions, scoring, spec
from .fmt import ok
from .pipeline_details import _clean
from .pipeline_score import market_cap
from .watchlist import evidence_quality


def retained_inputs(ctx, ref: dict) -> list[dict]:
    rows = []
    for ticker, identity in ref["sp500"].iterrows():
        cik = identity.get("cik")
        cik = int(cik) if pd.notna(cik) else None
        f, why = ctx.facts.get(cik, (None, "SEC financial statements not collected for this member"))
        bars, price_why, flags = ctx.histories.get(ticker, (None, "As-of price not collected for this member", []))
        if bars is None:
            bars, price_why, flags = ctx.histories.get(
                (ticker, spec.WATCHLIST_MIN_PRICE_BARS), (bars, price_why, flags)
            )
        row = {
            "ticker": ticker,
            "name": identity.get("name", ticker),
            "sector": identity.get("sector", "Unknown"),
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
