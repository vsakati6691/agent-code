"""Evaluate the fixed watchlist using the registered company and fund methods."""

from __future__ import annotations

from . import etf_inputs, scenarios, scoring, spec
from . import watchlist as wl_mod
from .pipeline_collect import _facts, _guard, latest_bars, watchlist_bars
from .pipeline_context import Context
from .pipeline_score import fundamentals_flags, market_cap
from .providers import SOURCES, sector_from_sic
from .watchlist import WatchlistConfig


def evaluate_watchlist(ctx: Context, ref: dict, cfg: WatchlistConfig, earnings: dict) -> dict:
    """Verify each watchlist symbol and build its conditional 2030 price scenarios (spec 2026-10-14.2).

    Kept apart from the ranked lists: nothing here changes any ranking."""
    years = wl_mod.years_to_target(ctx.as_of)
    sp = ref["sp500"]
    entries = []
    for t in cfg.tickers:
        info = wl_mod.resolve(t, ref["dirs"], ref["sec"])
        e = {
            **info,
            "price": None,
            "price_date": None,
            "price_source": SOURCES["cboe"],
            "method": None,
            "scenarios": None,
            "unavailable_reason": None,
            "missing": [],
            "assumptions_note": None,
            "sector": None,
            "catalysts": [],
            "bear_case": None,
            "invalidation": [],
            "evidence_quality": "none",
            "sources": [SOURCES["nasdaqtrader"], SOURCES["sec"]],
            "returns": None,
            "key_metrics": {},
            "unlock": [],
        }
        entries.append(e)
        if info["asset_type"] in ("ETF", "leveraged/inverse ETF"):
            e["etf_metadata"] = etf_inputs.metadata(t, ctx.as_of)
        if info["status"] != "listed":
            e["unavailable_reason"] = info["status"]
            e["unlock"] = wl_mod.unlock_steps("unresolved" if info["status"].startswith("unresolved") else "type")
            continue
        df, why, pflags, short_note = watchlist_bars(ctx, t)
        if df is None:
            e["unavailable_reason"] = f"no verified as-of price ({why})"
            e["unlock"] = wl_mod.unlock_steps("price")
            continue
        close = float(df["close"].iloc[-1])
        e.update(
            price=close,
            price_date=ctx.as_of,
            price_flags=pflags,
            price_validation="as-of bar verified",
            history_bars=len(df),
            history_note=short_note,
        )
        if short_note:
            e["missing"].append(short_note)
        e["sources"].append(SOURCES["cboe"])
        hist = scenarios.history_stats(df["close"], None)
        e["returns"] = {k: (v or {}).get("stock") for k, v in hist["returns"].items()}
        e["history_start"] = hist["first_date"]
        e["history"] = hist
        kind = info["asset_type"] or ""
        if kind.startswith("operating company"):
            _watchlist_company(ctx, e, df, close, years, earnings, sp)
        elif kind in ("ETF", "leveraged/inverse ETF"):
            _watchlist_etf(ctx, e, close, years)
        else:
            e["unavailable_reason"] = f"no scenario method for this security type ({kind or 'unknown'})"
            e["unlock"] = wl_mod.unlock_steps("type")
    themes: dict[str, int] = {}
    for e in entries:
        e.update(wl_mod.upside_fields(e))
        key = e["sector"] or ("Unresolved" if e["status"] != "listed" else "Unknown")
        themes[key] = themes.get(key, 0) + 1
    return {
        "imported_at": cfg.imported_at,
        "source": cfg.source,
        "target_date": spec.WATCHLIST_TARGET_DATE,
        "years_to_target": years,
        "statement": spec.WATCHLIST_STATEMENT,
        "separation": spec.WATCHLIST_SEPARATION,
        "entries": entries,
        "concentration": themes,
        "status": "ok",
    }


def _watchlist_company(ctx, e, df, close, years, earnings, sp) -> None:
    e["method"] = "company: revenue x EV/Sales to 2030-12-31"
    e["sector"] = sp.loc[e["ticker"], "sector"] if e["ticker"] in sp.index else None
    if e["cik"] is None:
        e["unavailable_reason"] = "no SEC registrant (CIK) for this symbol, so no reported fundamentals"
        e["unlock"] = wl_mod.unlock_steps("no_cik")
        return
    f, why = _facts(ctx, e["cik"])
    if f is None:
        e["unavailable_reason"] = f"fundamentals unavailable ({why})"
        return
    if e["sector"] is None:
        sub, _ = _guard(ctx, "sec", ctx.providers.submissions, e["cik"])
        e["sector"] = sector_from_sic(sub.get("sic")) if sub else "Unknown"

    def cadence():
        sub, _ = _guard(ctx, "sec", ctx.providers.submissions, e["cik"])
        return wl_mod.next_filing_estimate(sub, f.last_filed, ctx.as_of)

    flags, why = fundamentals_flags(f, ctx.as_of, len(df))
    if why:
        e["unavailable_reason"] = why
        e["unlock"] = wl_mod.unlock_steps("stale", why=why, next_filing=cadence())
        return
    cap, cap_flags = market_cap(f, close)
    if cap is None:
        e["unavailable_reason"] = "market cap unavailable (no share count)"
        return
    m = scoring.compute_metrics(f, df["close"], None, cap)
    e["key_metrics"] = {
        k: m.get(k)
        for k in (
            "market_cap",
            "revenue_ttm",
            "revenue_growth_ttm",
            "gross_margin",
            "operating_margin",
            "fcf_ttm",
            "fcf_margin",
            "ev_to_sales",
            "net_debt",
            "dilution",
            "sbc_to_revenue",
            "implied_revenue_cagr",
        )
    }
    e["missing"] += [f for f in flags + cap_flags]
    e["evidence_quality"] = wl_mod.evidence_quality("company", f, len(df))
    narrative = wl_mod.company_narrative(m, earnings.get(e["ticker"]))
    e.update(catalysts=narrative["catalysts"], bear_case=narrative["bear_case"], invalidation=narrative["invalidation"])
    if not earnings.get(e["ticker"]):
        e["missing"].append("no scheduled earnings date")
    if f.n_quarters < 4:
        e["unavailable_reason"] = "too few reported quarters for a revenue-based valuation (new filer)"
        e["unlock"] = wl_mod.unlock_steps("quarters", quarters=f.n_quarters, next_filing=cadence())
        return
    if not m["revenue_ttm"] or m["revenue_ttm"] <= 0:
        e["unavailable_reason"] = "too little reported revenue for a revenue-based valuation (pre-revenue)"
        e["unlock"] = wl_mod.unlock_steps("revenue", revenue=cap_text(m["revenue_ttm"]), next_filing=cadence())
        return
    if m["revenue_growth_ttm"] is None:
        e["unavailable_reason"] = "revenue growth not computable (fewer than 8 reported quarters)"
        e["unlock"] = wl_mod.unlock_steps("growth", quarters=f.n_quarters, next_filing=cadence())
        return
    if m["enterprise_value"] is None or m["enterprise_value"] <= 0 or not m["ev_to_sales"]:
        e["unavailable_reason"] = "enterprise value not positive, so EV/Sales cannot anchor the valuation"
        e["unlock"] = wl_mod.unlock_steps(
            "ev", ev=cap_text(m["enterprise_value"]), net_cash=cap_text(-(m["net_debt"] or 0)), cap=cap_text(cap)
        )
        return
    margin, source = (
        (m.get("fcf_margin"), "FCF") if m.get("fcf_margin") is not None else (m.get("operating_margin"), "operating")
    )
    if margin is None:
        e["missing"].append("no margin data, so the cash-generation cross-check could not run")
    e["scenarios"] = wl_mod.company_scenarios(
        close,
        cap / close,
        m["revenue_ttm"],
        m["revenue_growth_ttm"],
        m["ev_to_sales"],
        -(m["net_debt"] or 0.0),
        m.get("dilution"),
        years,
        margin,
        source,
    )
    e["assumptions_note"] = spec.WATCHLIST_COMPANY_METHOD


def cap_text(v) -> str:
    from .fmt import cap as _cap

    return _cap(v)


def _watchlist_etf(ctx, e, close, years) -> None:
    name = e["name"] or ""
    meta = etf_inputs.metadata(e["ticker"], ctx.as_of)
    e["etf_metadata"] = meta
    e["etf_metadata_status"] = "Dated metadata unavailable at this snapshot date." if meta is None else meta["label"]
    if meta:
        e["sources"].append(meta["source_url"])
        if meta["launched_under_12_months"]:
            e["missing"].append("Launched less than 12 months ago; observed history is limited.")
        if hasattr(ctx.providers, "fund_filing"):
            filing, why = _guard(ctx, "sec", ctx.providers.fund_filing, meta, ctx.as_of)
            e["sec_fund_filing"] = filing or {"status": "unavailable", "reason": why}
        else:
            e["sec_fund_filing"] = {
                "status": "unavailable",
                "reason": "SEC fund filings not supplied by this provider.",
            }
    lev = wl_mod.leverage_of(name)
    e["evidence_quality"] = wl_mod.evidence_quality("leveraged" if lev else "etf")
    e["missing"].append(
        "Distribution yield remains assumed; the expense input is owner-supplied, unverified."
        if meta
        else spec.FEE_NOTE
    )
    if lev:
        e["method"] = "leveraged ETF: daily-reset model with volatility drag"
        narrative = wl_mod.etf_narrative(None, lev)
        e.update(
            catalysts=narrative["catalysts"], bear_case=narrative["bear_case"], invalidation=narrative["invalidation"]
        )
        e["sector"] = f"Leveraged ETF ({lev}x)"
        if lev < 0:
            e["unavailable_reason"] = "inverse fund: the daily-reset model here covers long leverage only"
            e["unlock"] = wl_mod.unlock_steps("inverse")
            return
        und = wl_mod.leveraged_underlying(name)
        if und is None:
            e["unavailable_reason"] = "the tracked index could not be identified from the fund name"
            e["unlock"] = wl_mod.unlock_steps("lev_index")
            return
        rule = wl_mod.exposure_class(
            next(k for k, v in spec.LEVERAGED_UNDERLYING_HINTS.items() if v == und and wl_mod._has(name, k))
        )
        udf, why, _ = latest_bars(ctx, und)
        sigma = wl_mod.realized_vol(udf["close"]) if udf is not None else None
        if rule is None or sigma is None:
            e["unavailable_reason"] = f"no 3-year price history for the tracked index fund {und}"
            e["unlock"] = wl_mod.unlock_steps("lev_history", index=und)
            return
        e["scenarios"] = wl_mod.leveraged_scenarios(
            close, lev, rule, sigma, years, fee=meta["expense_ratio"] if meta else None
        )
        e["assumptions_note"] = spec.LEVERAGED_METHOD + f" Tracked index proxy: {und}; trailing volatility {sigma:.0%}."
        return
    rule = next(
        (r for r in spec.ETF_EXPOSURE_RULES if meta and r[0] == meta["exposure_class"]), None
    ) or wl_mod.exposure_class(name)
    narrative = wl_mod.etf_narrative(rule, None)
    e.update(catalysts=narrative["catalysts"], bear_case=narrative["bear_case"], invalidation=narrative["invalidation"])
    e["method"] = "ETF: exposure-class return assumptions"
    if rule is None:
        e["sector"] = "ETF (exposure not classified)"
        e["unavailable_reason"] = "the fund's exposure could not be classified from its name; no assumption is made"
        e["unlock"] = wl_mod.unlock_steps("etf_class")
        return
    e["sector"] = f"ETF: {rule[1]}"
    e["scenarios"] = wl_mod.etf_scenarios(close, rule, years, fee=meta["expense_ratio"] if meta else None)
    e["assumptions_note"] = (
        "Fund-level model: exposure-class total-return assumptions net of the dated expense input when available (otherwise assumed fee) and "
        "distribution yield give a price return, compounded to 2030-12-31. "
        "Company valuation formulas are not applied to funds."
    )
