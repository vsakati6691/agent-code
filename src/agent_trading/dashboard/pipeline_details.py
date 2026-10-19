"""Assemble company research details, concentration notes and changes from stored evidence."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from . import scenarios, scoring, spec
from .pipeline_collect import _guard
from .pipeline_context import Context, as_of_for
from .providers import SOURCES


def _clean(x):
    if isinstance(x, float):
        return None if not math.isfinite(x) else x
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, np.integer)):
        return _clean(x.item())
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    return x


def candidate_detail(ctx: Context, band: spec.Band, row: dict, bench: pd.Series, earnings: dict) -> dict:
    s: scoring.Score = row["score"]
    m, f, df = row["metrics"], row["fundamentals"], row["bars"]
    hist = scenarios.history_stats(df["close"], bench)
    scen = None
    scen_note = None
    try:
        if m.get("enterprise_value") is not None and m["enterprise_value"] <= 0:
            scen_note = (
                "Scenarios not computed: enterprise value is not positive (net cash exceeds market cap), "
                "so the EV/Sales scenario model does not apply."
            )
        elif m["ev_to_sales"] and m["revenue_growth_ttm"] is not None and m["revenue_ttm"]:
            shares = m["market_cap"] / row["close"]
            scen = scenarios.scenario_table(
                row["close"],
                shares,
                m["revenue_ttm"],
                m["revenue_growth_ttm"],
                m["ev_to_sales"],
                -(m["net_debt"] or 0.0),
                m.get("fcf_margin"),
                m.get("dilution"),
                band.scenario_years,
            )
        else:
            scen_note = "Scenarios not computed: revenue, growth or EV/Sales unavailable."
    except ValueError as exc:
        scen_note = f"Scenarios not computed: {exc}"
    q = f.quarters
    fundamentals_table = {
        "quarters": q[:8],
        **{
            k: f.flows[k][:8]
            for k in ("revenue", "gross_profit", "operating_income", "net_income", "ocf", "capex", "sbc")
        },
        "derived_revenue": f.derived["revenue"][:8],
        "diluted_shares": f.diluted_shares[:8],
        "balance_sheet": f.instants,
        "last_filed": f.last_filed,
        "last_form": f.last_form,
        "cover_shares": f.cover_shares,
        "cover_shares_date": f.cover_shares_date,
    }
    next_earn = earnings.get(row["ticker"])
    from . import decisions

    research = decisions.build(
        f,
        m,
        df["close"],
        df["high"],
        ctx.as_of,
        next_earn,
        ctx.started,
        decision_enrichment(ctx, row) if band.key in spec.DECISION_RULES["growth_bands"] else None,
    )
    if next_earn is None and ctx.earnings_reason:
        research["groups"]["timing"]["fields"]["next_earnings"]["reason"] = ctx.earnings_reason
    return _clean(
        {
            "ticker": row["ticker"],
            "name": row["name"],
            "sector": row["sector"],
            "band": band.key,
            "rank": s.rank,
            "price": row["close"],
            "price_date": ctx.as_of,
            "market_cap": m["market_cap"],
            "cik": row["cik"],
            "sources": {"price": df.attrs.get("price_source", SOURCES["cboe"]), "fundamentals": SOURCES["sec"]},
            "data_timestamp": ctx.started,
            "composite": s.composite,
            "raw_composite": s.raw_composite,
            "sector_penalty": s.sector_penalty,
            "components": s.components,
            "decision_research": research,
            "basic_fundamentals": ctx.decision_extras.get(row["ticker"], {}).get("basic_fundamentals"),
            "sub_scores": s.sub_scores,
            "metrics": m,
            "missing": s.missing,
            "confidence": s.confidence,
            "confidence_label": s.confidence_label,
            "flags": s.flags,
            "counterargument": s.counterargument,
            "thesis": scenarios.thesis(m, s.components),
            "bear_case": scenarios.bear_case(m, s.counterargument),
            "risks": scenarios.key_risks(m, s.flags, hist, f.concentration),
            "invalidation": scenarios.invalidation(m, scen),
            "history": hist,
            "chart": scenarios.chart_series(df["close"], bench),
            "benchmark": band.benchmark,
            "scenarios": scen,
            "scenario_note": scen_note,
            "fundamentals": fundamentals_table,
            "next_earnings": next_earn,
            "not_scored": spec.NOT_SCORED_FACTORS,
            "dollar_volume": row["dollar_volume"],
            "probability": spec.PROBABILITY_STATEMENT,
        }
    )


def concentration_warnings(cands: list[dict]) -> list[str]:
    out = []
    if not cands:
        return out
    sectors = pd.Series([c["sector"] for c in cands]).value_counts()
    top, n = sectors.index[0], int(sectors.iloc[0])
    if n / len(cands) > 0.4:
        out.append(f"{n} of {len(cands)} candidates are in {top}: the list is concentrated in one sector.")
    rets = pd.DataFrame({c["ticker"]: c["bars"]["close"].pct_change().iloc[-252:] for c in cands}).dropna(how="all")
    if rets.shape[1] >= 3:
        corr = rets.corr().to_numpy()
        avg = float(corr[np.triu_indices_from(corr, 1)].mean())
        if avg > 0.6:
            out.append(
                f"Average pairwise correlation of daily returns is {avg:.2f}: the candidates tend to move "
                "together, so they diversify each other little."
            )
    return out


def rank_changes(current: list[dict], previous: list[dict] | None) -> list[dict]:
    """Per-ticker movement vs the previous snapshot, explained by component-score changes."""
    if previous is None:
        return [{"ticker": c["ticker"], "change": "new (first snapshot)", "explanation": ""} for c in current]
    prev = {p["ticker"]: p for p in previous}
    out = []
    for c in current:
        p = prev.get(c["ticker"])
        if p is None:
            out.append(
                {
                    "ticker": c["ticker"],
                    "change": "new",
                    "from": None,
                    "to": c["rank"],
                    "explanation": "entered the top list this week",
                }
            )
            continue
        deltas = {k: (c["components"].get(k) or 0) - (p["components"].get(k) or 0) for k in c["components"]}
        top = sorted(deltas.items(), key=lambda kv: -abs(kv[1]))[:3]
        expl = ", ".join(f"{k} {v * 100:+.1f}" for k, v in top if abs(v) >= 0.005) or "component scores unchanged"
        score_change = (
            (c["composite"] - p["composite"])
            if c.get("composite") is not None and p.get("composite") is not None
            else None
        )
        out.append(
            {
                "ticker": c["ticker"],
                "change": p["rank"] - c["rank"],
                "from": p["rank"],
                "to": c["rank"],
                "score_change": score_change,
                "component_changes": {k: round(v * 100, 1) for k, v in top if abs(v) >= 0.005},
                "explanation": f"component score changes (points of 100): {expl}",
            }
        )
    for t, p in prev.items():
        if t not in {c["ticker"] for c in current}:
            out.append(
                {
                    "ticker": t,
                    "change": "dropped",
                    "from": p["rank"],
                    "to": None,
                    "explanation": "no longer in the top list (lower score, excluded or out of band)",
                }
            )
    return out


def decision_enrichment(ctx: Context, row: dict) -> dict:
    """Current vendor estimates are display-only; never backfill a historical run."""
    from .decision_sources import estimates, insider_net

    ticker = row["ticker"]
    if ticker in ctx.decision_extras:
        return ctx.decision_extras[ticker]
    out = {}
    for method, key in (("overview", "estimates"), ("insider_transactions", "insider")):
        fn = getattr(ctx.providers, method, None)
        if ctx.as_of != as_of_for(datetime.now(UTC)):
            raw, why = None, "Current-only provider data cannot be backfilled into a historical snapshot"
        elif not callable(fn):
            raw, why = None, "Provider does not implement this dataset"
        else:
            provider = "overview" if key == "estimates" and getattr(ctx.providers, "fmp_key", None) else "alphavantage"
            raw, why = _guard(ctx, provider, fn, ticker)
        if raw is None:
            out[key + "_reason"] = why
        elif key == "estimates":
            out[key] = estimates(raw, ctx.started)
            out["basic_fundamentals"] = {
                k: raw.get(k)
                for k in (
                    "Symbol",
                    "Name",
                    "MarketCapitalization",
                    "Sector",
                    "Industry",
                    "Beta",
                    "_source",
                    "_observed_at",
                )
            }
        else:
            out["insider_net"] = insider_net(raw, ctx.as_of, ctx.started)
    fn = getattr(ctx.providers, "annual_filing", None)
    raw, why = (
        _guard(ctx, "sec", fn, row["cik"], ctx.as_of)
        if callable(fn)
        else (None, "Provider does not implement 10-K text retrieval")
    )
    out["business"] = raw or {"reason": why}
    ctx.decision_extras[ticker] = out
    return out
