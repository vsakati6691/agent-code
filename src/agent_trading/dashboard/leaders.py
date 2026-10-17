"""Conditional size comparisons from stored public inputs; no provider access."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from . import scenarios, spec
from .fmt import ok
from .schema import LEADERS_CHALLENGER

CONFIG_FILE = Path(__file__).resolve().parents[3] / "config" / "leaders_2030_challengers.json"
CASES = ("bear", "base", "bull")
SHARE_BASIS = "SEC diluted weighted-average shares (latest reported quarter available)"


def valid_date(value) -> bool:
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def load_challengers(path: Path = CONFIG_FILE) -> list[dict]:
    """Validate the closed config schema at every build, including builds without snapshots."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"challengers"} or not isinstance(raw["challengers"], list):
        raise ValueError("leaders config requires only a challengers array")
    names, tickers = set(), set()
    for row in raw["challengers"]:
        if not isinstance(row, dict) or set(row) != set(LEADERS_CHALLENGER["required"]):
            raise ValueError("challenger fields must exactly match the registered schema")
        for key in ("name", "assumption_source", "notes"):
            if not isinstance(row[key], str) or (key != "notes" and not row[key].strip()):
                raise ValueError(f"challenger {key} must be text; a name and source are required")
        if row["listing_status"] not in ("listed_non_index", "private", "pre_ipo"):
            raise ValueError("invalid challenger listing_status")
        ticker = row["ticker"]
        if ticker is not None and (not isinstance(ticker, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker)):
            raise ValueError("invalid challenger ticker")
        if row["listing_status"] == "private" and ticker is not None:
            raise ValueError("a private challenger must have a null ticker")
        if row["listing_status"] == "listed_non_index" and ticker is None:
            raise ValueError("a listed challenger requires a ticker")
        cap = row["assumed_2030_market_cap_usd"]
        if not ok(cap) or cap <= 0:
            raise ValueError("challenger assumed cap must be finite and positive")
        if not valid_date(row["assumption_date"]):
            raise ValueError("challenger assumption_date must be an ISO date")
        drivers = row["growth_drivers"]
        if not isinstance(drivers, list) or any(
            not isinstance(d, str)
            or not valid_date(d[:10])
            or not d[10:].strip(" :—-")
            or d[:10] > row["assumption_date"]
            for d in drivers
        ):
            raise ValueError("challenger growth_drivers must be dated text, no later than the assumption date")
        name = row["name"].strip().casefold()
        if name in names or ticker is not None and ticker in tickers:
            raise ValueError("duplicate challenger name or ticker")
        names.add(name)
        tickers.add(ticker)
    return raw["challengers"]


def growth_drivers(record: dict, as_of: str) -> list[str]:
    research = record.get("decision_research") or {}
    group = (research.get("groups") or {}).get("growth") or {}
    fields = group.get("fields") or {}
    drivers = []
    for key, label in (
        ("revenue_cagr_3y", "Fiscal-year revenue CAGR, 3Y"),
        ("revenue_cagr_5y", "Fiscal-year revenue CAGR, 5Y"),
        ("eps_cagr_3y", "Fiscal-year diluted EPS CAGR, 3Y"),
        ("eps_cagr_5y", "Fiscal-year diluted EPS CAGR, 5Y"),
        ("gross_margin", "TTM gross margin"),
        ("operating_margin", "TTM operating margin"),
        ("fcf_margin", "TTM free-cash-flow margin"),
    ):
        field = fields.get(key) or {}
        dated = field.get("as_of") or group.get("as_of")
        if ok(field.get("value")) and valid_date(dated) and dated <= as_of:
            period = f" ({field['period']})" if field.get("period") else ""
            drivers.append(f"{dated}: {label} {field['value']:+.1%}{period}; SEC XBRL.")
    business = research.get("business") or {}
    if valid_date(business.get("filed")) and business["filed"] <= as_of and business.get("url"):
        for key in ("description", "growth"):
            if business.get(key):
                drivers.append(f"{business['filed']}: Issuer excerpt: {business[key]} Source: {business['url']}")
    return drivers


def stored_records(snap: dict) -> dict[str, dict]:
    """Prefer prospectively retained inputs; old snapshots can supply their published company details."""
    rows = {r["ticker"]: r for r in snap.get("leaders_2030_inputs", [])}
    for band in snap.get("bands", {}).values():
        for record in band.get("candidates", []):
            ticker = record["ticker"]
            if ticker not in rows or not rows[ticker].get("decision_research"):
                rows[ticker] = {**record, **rows.get(ticker, {})}
                if record.get("decision_research"):
                    rows[ticker]["decision_research"] = record["decision_research"]
    for record in (snap.get("watchlist") or {}).get("entries", []):
        rows.setdefault(record["ticker"], record)
    return rows


def computed_row(ticker: str, record: dict, snap: dict) -> dict:
    as_of = snap["as_of"]
    f = record.get("fundamentals") or {}
    m = record.get("metrics") or record.get("key_metrics") or {}
    quarters = f.get("quarters") or []
    shares = max(
        (
            (s, d)
            for s, d in zip(f.get("diluted_shares") or [], quarters, strict=False)
            if ok(s) and s > 0 and valid_date(d) and d <= as_of
        ),
        key=lambda pair: pair[1],
        default=(None, None),
    )
    row = {
        "ticker": ticker,
        "company_name": record.get("name") or ticker,
        "sector": record.get("sector") or "Unknown",
        "listing_status": "index_member",
        "current_rank": None,
        "current_market_cap_usd": None,
        "market_cap_date": None,
        "price_date": record.get("price_date"),
        "shares_outstanding": shares[0],
        "shares_date": shares[1],
        "shares_basis": SHARE_BASIS,
        "shares_assumption": spec.LEADERS_SHARE_RULE,
        "scenario_2030": {f"{case}_{field}": None for case in CASES for field in ("cap", "price", "shares")},
        "rank_2030": None,
        "rank_delta": None,
        "movement": "unavailable",
        "growth_drivers": growth_drivers(record, as_of),
        "evidence_grade": record.get("evidence_quality")
        or ("medium" if len(quarters) >= 8 else "low" if quarters else "none"),
        "missing_inputs": list(record.get("missing") or []),
        "unavailable_reason": None,
        "is_scenario": True,
        "scenario_basis": f"registered model {spec.SPEC_VERSION}",
        "methodology_version": spec.SPEC_VERSION,
        "snapshot_id": snap.get("snapshot_id") or as_of,
        "snapshot_methodology_version": snap.get("spec_version"),
        "assumption_source": None,
        "assumption_date": None,
        "notes": "",
    }
    missing = []
    price = record.get("price")
    if not ok(price) or price <= 0 or record.get("price_date") != as_of:
        missing.append("no verified as-of price in the stored snapshot")
    if shares[0] is None:
        missing.append("dated diluted shares unavailable in the stored snapshot")
    filed = f.get("last_filed")
    if not valid_date(filed) or filed > as_of:
        missing.append("no dated SEC financial statements filed by the snapshot date")
    elif (date.fromisoformat(as_of) - date.fromisoformat(filed)).days > spec.MAX_FILING_AGE_DAYS:
        missing.append(f"fundamentals stale: latest 10-K/10-Q filed {filed}")
    if not missing:
        if ok(price * shares[0]):
            row["current_market_cap_usd"] = price * shares[0]
            row["market_cap_date"] = as_of
        else:
            missing.append("current market cap is not a finite number")
    asset_type = record.get("asset_type")
    if asset_type and not asset_type.startswith("operating company"):
        missing.append(f"no scenario method for this security type ({asset_type})")
    if len(quarters) < 4:
        missing.append("too few reported quarters for a revenue-based valuation (new filer)")
    if not ok(m.get("revenue_ttm")) or m["revenue_ttm"] <= 0:
        missing.append("too little reported revenue for a revenue-based valuation (pre-revenue)")
    if not ok(m.get("revenue_growth_ttm")):
        missing.append("revenue growth not computable (fewer than 8 reported quarters)")
    if not ok(m.get("ev_to_sales")) or m["ev_to_sales"] <= 0:
        missing.append("enterprise value not positive, so EV/Sales cannot anchor the valuation")
    if not ok(m.get("net_debt")):
        missing.append("net debt / net cash unavailable in the stored snapshot")
    if not ok(m.get("dilution")):
        missing.append("trailing dilution unavailable in the stored snapshot")
    if (date.fromisoformat(spec.WATCHLIST_TARGET_DATE) - date.fromisoformat(as_of)).days <= 0:
        missing.append("the 2030 target is not after the snapshot date")
    if record.get("unavailable_reason"):
        missing.insert(0, record["unavailable_reason"])
    if missing:
        row["missing_inputs"] = list(dict.fromkeys(row["missing_inputs"] + missing))
        row["unavailable_reason"] = record.get("unavailable_reason") or "; ".join(missing)
        return row
    margin = m.get("fcf_margin") if ok(m.get("fcf_margin")) else m.get("operating_margin")
    try:
        result = scenarios.company_scenarios(
            price,
            shares[0],
            m["revenue_ttm"],
            m["revenue_growth_ttm"],
            m["ev_to_sales"],
            -m["net_debt"],
            m["dilution"],
            (date.fromisoformat(spec.WATCHLIST_TARGET_DATE) - date.fromisoformat(as_of)).days / 365.25,
            margin,
            "FCF" if ok(m.get("fcf_margin")) else "operating",
        )
        for case in CASES:
            value, projected = result[case]["price"], result[case]["assumptions"]["shares_2030"]
            if not all(ok(v) for v in (value, projected, value * projected)) or projected <= 0:
                raise ValueError("non-finite scenario or non-positive projected shares")
            row["scenario_2030"].update(
                {f"{case}_cap": value * projected, f"{case}_price": value, f"{case}_shares": projected}
            )
    except (ValueError, OverflowError, ZeroDivisionError, TypeError) as exc:
        row["scenario_2030"] = {key: None for key in row["scenario_2030"]}
        row["unavailable_reason"] = f"Scenario unavailable: {exc}"
        row["missing_inputs"].append(row["unavailable_reason"])
    return row


def movement(current: int | None, future: int | None, curated: bool = False) -> str:
    if curated:
        return "curated_challenger"
    if future is None:
        return "unavailable"
    if current is not None and current <= spec.LEADERS_TOP_N:
        return "stays_in_top_20" if future <= spec.LEADERS_TOP_N else "drops_out_of_top_20"
    return "rises_into_top_20" if future <= spec.LEADERS_TOP_N else "unavailable"


def build(snap: dict, challengers: list[dict]) -> dict:
    """A separate derived artifact: never mutate, rescore or backfill the source snapshot."""
    records = stored_records(snap)
    members = sorted(set((snap.get("universe") or {}).get("sp500_members") or []))
    rows = [computed_row(t, records.get(t, {}), snap) for t in members]
    current = sorted(
        (r for r in rows if ok(r["current_market_cap_usd"])), key=lambda r: (-r["current_market_cap_usd"], r["ticker"])
    )
    for rank, row in enumerate(current, 1):
        row["current_rank"] = rank
    omitted = []
    for entry in challengers:
        if entry["ticker"] in members:
            raise ValueError("a curated challenger is already in this snapshot's S&P 500 universe")
        if entry["assumption_date"] > snap["as_of"]:
            omitted.append(f"{entry['name']}: assumption dated after the snapshot ({entry['assumption_date']})")
            continue
        row = computed_row(entry["ticker"], {}, snap)
        row.update(
            company_name=entry["name"],
            listing_status=entry["listing_status"],
            shares_basis=None,
            shares_assumption="Not applicable: curated cap assumption; no share count or computed price",
            movement="curated_challenger",
            growth_drivers=list(entry["growth_drivers"]),
            evidence_grade="none",
            missing_inputs=[],
            unavailable_reason=None,
            scenario_basis="curated assumption",
            assumption_source=entry["assumption_source"],
            assumption_date=entry["assumption_date"],
            notes=entry["notes"],
        )
        row["scenario_2030"]["base_cap"] = entry["assumed_2030_market_cap_usd"]
        rows.append(row)
    future = sorted(
        (r for r in rows if ok(r["scenario_2030"]["base_cap"])),
        key=lambda r: (-r["scenario_2030"]["base_cap"], r["ticker"] or "", r["company_name"]),
    )
    for rank, row in enumerate(future, 1):
        row["rank_2030"] = rank
        row["rank_delta"] = row["current_rank"] - rank if row["current_rank"] is not None else None
    candidates, gaps = [], []
    for row in rows:
        curated = row["scenario_basis"] == "curated assumption"
        row["movement"] = movement(row["current_rank"], row["rank_2030"], curated)
        if (
            curated
            or (row["current_rank"] or 999999) <= spec.LEADERS_TOP_N
            or (row["rank_2030"] or 999999) <= spec.LEADERS_TOP_N
        ):
            candidates.append(row)
        elif row["unavailable_reason"]:
            gaps.append({"ticker": row["ticker"], "reason": row["unavailable_reason"]})
    candidates.sort(key=lambda r: (r["current_rank"] or 999999, r["rank_2030"] or 999999, r["company_name"]))
    computed = sum(r["scenario_basis"] != "curated assumption" and r["rank_2030"] is not None for r in rows)
    return {
        "entries": candidates,
        "gaps": gaps,
        "omitted_challengers": omitted,
        "universe_count": len(members),
        "current_cap_count": len(current),
        "computed_count": computed,
        "partial": len(current) < len(members) or computed < len(members),
        "counts": dict(Counter(r["movement"] for r in candidates)),
        "as_of": snap["as_of"],
        "methodology_version": spec.SPEC_VERSION,
        "snapshot_methodology_version": snap.get("spec_version"),
        "snapshot_id": snap.get("snapshot_id") or snap["as_of"],
        "registered_challengers": len(challengers),
        "top_n": spec.LEADERS_TOP_N,
    }
