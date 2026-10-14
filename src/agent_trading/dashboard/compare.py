"""Side-by-side comparison data for 2-4 companies from one snapshot (spec 2026-10-14.5, COMPARE_RULES).

Adapted from filingcopilot `src/filingcopilot/comparison.py` (MIT,
https://github.com/francisown/filingcopilot at 80d3cb15d71b4b596b30de2502a73c215b535824):
* `rebased_chart` -> `rebase_common`: price paths are compared only on dates every selected name has, rebased
  to 100 on the first common date, never interpolated, with the omitted dates counted;
* `collect_company` -> each column keeps one period basis, and a missing cell always carries a visible reason;
* the request rule of 2 to 4 distinct names.
The browser page (assets.COMPARE_JS) mirrors `comparability()` and `rebase_common()`; these Python versions
are the tested reference.
"""
from __future__ import annotations

import math
from datetime import date

from . import research, spec
from .scenarios import RETURN_WINDOWS
from .evidence import quality_level

# (key, label, kind) per group; kind drives formatting in the page
GROUPS = [
    ("Growth", [("revenue_growth_ttm", "Revenue growth (TTM)", "pct"), ("revenue_cagr_3y", "Revenue growth, 3-yr a year", "pct"),
                ("operating_income_growth_ttm", "Operating income growth (TTM)", "pct"),
                ("fcf_growth_ttm", "Free-cash-flow growth (TTM)", "pct")]),
    ("Margins and cash flow", [("gross_margin", "Gross margin", "pct"), ("operating_margin", "Operating margin", "pct"),
                               ("fcf_margin", "Free-cash-flow margin", "pct"), ("fcf_ttm", "Free cash flow (TTM)", "money"),
                               ("revenue_ttm", "Revenue (TTM)", "money")]),
    ("Valuation", [("ev_to_sales", "EV / Sales", "x"), ("pe", "P/E", "x"), ("fcf_yield", "Free-cash-flow yield", "pct"),
                   ("implied_revenue_cagr", "Growth the price implies (5 yr)", "pct"), ("market_cap", "Market cap", "money")]),
    ("Debt and dilution", [("net_debt", "Net debt (negative = net cash)", "money"),
                           ("net_debt_to_ebitda", "Net debt / EBITDA", "x"), ("current_ratio", "Current ratio", "x"),
                           ("dilution", "Share count change, 1 yr", "pct"), ("sbc_to_revenue", "Stock-based pay / revenue", "pct")]),
]
RETURN_KEYS = ("3m", "6m", "1y", "3y", "5y")
SESSIONS = dict(RETURN_WINDOWS)
ORDER = ("large", "mid", "small", "multibagger", "ai_large", "ai_mid")


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _clean(v):
    return v if _ok(v) else None


def candidate_entry(c: dict, snap: dict, lists: list[str], profile_name: str, as_of: str) -> dict:
    m, h, f = c.get("metrics") or {}, c.get("history") or {}, c.get("fundamentals") or {}
    rets = {}
    for k in RETURN_KEYS:
        r = (h.get("returns") or {}).get(k)
        rets[k] = None if not r else {"value": _clean(r.get("stock")), "start": r.get("start"), "end": r.get("end") or as_of,
                                      "sessions": r.get("sessions") or SESSIONS[k]}
    dd = h.get("drawdowns") or {}
    return {
        "ticker": c["ticker"], "name": c.get("name"), "kind": "listed", "lists": lists, "band": c["band"],
        "profile": profile_name, "benchmark": c.get("benchmark"), "sector": c.get("sector"),
        "price": _clean(c.get("price")), "price_date": c.get("price_date"),
        "period": {"latest_quarter": (f.get("quarters") or [None])[0], "currency": "USD",
                   "basis": "trailing four reported quarters"},
        "metrics": {k: _clean(m.get(k)) for _, rows in GROUPS for k, _, _ in rows},
        "returns": rets,
        "drawdowns": {"max_5y": _clean((dd.get("max_5y") or {}).get("value")), "from_52w_high": _clean(dd.get("from_52w_high")),
                      "worst_1y": _clean(dd.get("worst_1y_return"))},
        "components": {k: _clean(v) for k, v in (c.get("components") or {}).items()},
        "composite": _clean(c.get("composite")),
        "quality": {"level": quality_level(c.get("confidence_label")), "label": c.get("confidence_label"),
                    "missing": list(c.get("missing") or []), "flags": list(c.get("flags") or [])},
        "chart": {"dates": (c.get("chart") or {}).get("dates") or [], "values": (c.get("chart") or {}).get("stock") or []},
        "not_stored": [],
        "sources": research.sources(c, as_of),
        "url": f"stock/{c['band']}-{c['ticker']}.html",
    }


def watchlist_entry(e: dict, as_of: str) -> dict:
    km = e.get("key_metrics") or {}
    rets = {k: ({"value": _clean((e.get("returns") or {}).get(k)), "start": None, "end": as_of, "sessions": None}
                if _ok((e.get("returns") or {}).get(k)) else None) for k in RETURN_KEYS}
    cik = e.get("cik")
    return {
        "ticker": e["ticker"], "name": e.get("name"), "kind": "watchlist", "lists": ["watchlist"], "band": None,
        "profile": None, "benchmark": None, "sector": e.get("sector"), "price": _clean(e.get("price")),
        "price_date": e.get("price_date"),
        "period": {"latest_quarter": None, "currency": "USD", "basis": "trailing four reported quarters"},
        "metrics": {k: _clean(km.get(k)) for _, rows in GROUPS for k, _, _ in rows},
        "returns": rets, "drawdowns": {"max_5y": None, "from_52w_high": None, "worst_1y": None},
        "components": {}, "composite": None,
        "quality": {"level": quality_level(e.get("evidence_quality")), "label": e.get("evidence_quality"),
                    "missing": list(e.get("missing") or []), "flags": list(e.get("price_flags") or [])},
        "chart": {"dates": [], "values": []},
        "not_stored": [k for _, rows in GROUPS for k, _, _ in rows if k not in km],
        "sources": ([{"label": "SEC company facts (XBRL)", "url": research.SEC_FACTS.format(cik=int(cik)),
                      "date": f"filed by {as_of}"}] if cik else []) +
                   [{"label": e.get("price_source") or "Cboe delayed quotes", "url": None, "date": f"close of {e.get('price_date')}"}],
        "url": f"symbol/{e['ticker']}.html",
    }


def payload(snap: dict, profile_names: dict[str, str]) -> dict:
    """Every company that can be compared in this snapshot, one entry per ticker."""
    as_of = str(snap["as_of"])
    seen: dict[str, dict] = {}
    bands = snap.get("bands") or {}
    for key in [k for k in ORDER if k in bands] + sorted(k for k in bands if k not in ORDER):
        for c in bands[key].get("candidates", []):
            if c["ticker"] in seen:
                seen[c["ticker"]]["lists"].append(key)
                continue
            seen[c["ticker"]] = candidate_entry(c, snap, [key], profile_names.get(key, "standard"), as_of)
    for e in (snap.get("watchlist") or {}).get("entries") or []:
        if e["ticker"] in seen or not str(e.get("asset_type") or "").startswith("operating company"):
            continue
        if not e.get("key_metrics"):
            continue
        seen[e["ticker"]] = watchlist_entry(e, as_of)
    return {"as_of": as_of, "spec_version": snap.get("spec_version"), "entries": list(seen.values()),
            "groups": [{"title": t, "rows": [{"key": k, "label": lab, "kind": kind} for k, lab, kind in rows]}
                       for t, rows in GROUPS],
            "returns": list(RETURN_KEYS), "rules": {k: v for k, v in spec.COMPARE_RULES.items()}}


def comparability(entries: list[dict]) -> list[str]:
    """Plain-language warnings for measurements that do not line up across the selected names."""
    rules = spec.COMPARE_RULES
    if not rules["min_names"] <= len(entries) <= rules["max_names"]:
        return [f"Choose {rules['min_names']} to {rules['max_names']} different companies."]
    out = []
    dates = {e.get("price_date") for e in entries}
    if len(dates) > 1:
        out.append("Prices are from different sessions: " + ", ".join(f"{e['ticker']} {e.get('price_date')}" for e in entries) + ".")
    qs = [(e["ticker"], e["period"]["latest_quarter"]) for e in entries if e["period"].get("latest_quarter")]
    if len(qs) >= 2:
        ds = [date.fromisoformat(q) for _, q in qs]
        if (max(ds) - min(ds)).days > rules["max_quarter_end_gap_days"]:
            out.append("Trailing figures cover different periods (latest quarter ends: " +
                       ", ".join(f"{t} {q}" for t, q in qs) + ").")
    if any(not e["period"].get("latest_quarter") for e in entries):
        out.append("Watchlist names have no stored quarter dates; their trailing figures cannot be period-matched.")
    profiles = {e["profile"] for e in entries if e["profile"]}
    if len(profiles) > 1:
        out.append("Score components come from different scoring profiles (" + ", ".join(sorted(profiles)) +
                   "), so the composite scores are not comparable.")
    if any(e["kind"] == "watchlist" for e in entries):
        out.append("Watchlist names are not scored: no components or composite.")
    bench = {e["benchmark"] for e in entries if e["benchmark"]}
    if len(bench) > 1:
        out.append("Names are measured against different benchmarks (" + ", ".join(sorted(bench)) + ").")
    return out


def rebase_common(entries: list[dict], start: str | None = None) -> dict:
    """Price paths on the dates every selected name has (no interpolation), rebased to 100 on the first."""
    series = [e for e in entries if e["chart"]["dates"]]
    if len(series) < 2:
        return {"found": False, "reason": "At least two names need stored price paths.", "series": []}
    common = set.intersection(*(set(e["chart"]["dates"]) for e in series))
    days = sorted(d for d in common if start is None or d >= start)
    if len(days) < 2:
        return {"found": False, "reason": "Fewer than two common dates in this window.", "series": []}
    out = []
    for e in series:
        obs = dict(zip(e["chart"]["dates"], e["chart"]["values"]))
        base = obs[days[0]]
        out.append({"ticker": e["ticker"], "points": [[d, obs[d] / base * 100] for d in days],
                    "change": obs[days[-1]] / base - 1, "omitted": len(e["chart"]["dates"]) - len(days)})
    return {"found": True, "start": days[0], "end": days[-1], "common_days": len(days), "series": out}


def window_start(entries: list[dict], key: str, as_of: str, years: int) -> str:
    """Chart window start: the return table's start session when every selected name stores the same one."""
    starts = {((e["returns"].get(key) or {}).get("start") or "") for e in entries}
    if len(starts) == 1 and "" not in starts:
        return starts.pop()
    return f"{int(as_of[:4]) - years}{as_of[4:]}"


def pack(data: dict) -> dict:
    """Page form of `payload()`: each distinct list of chart dates is stored once (most names share one)."""
    sets: list[list[str]] = []
    entries = []
    for e in data["entries"]:
        dates = e["chart"]["dates"]
        if dates not in sets:
            sets.append(dates)
        entries.append({**e, "chart": {"dset": sets.index(dates), "values": e["chart"]["values"]}})
    return {**data, "entries": entries, "date_sets": sets}
