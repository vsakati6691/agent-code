"""Conditional size comparisons from stored public inputs; no provider access."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from . import leaders_scenarios, spec
from .fmt import cap as cap_text
from .fmt import ok
from .schema import LEADERS_CHALLENGER, LEADERS_OUTSIDE

CONFIG_FILE = Path(__file__).resolve().parents[3] / "config" / "leaders_2030_challengers.json"
OUTSIDE_FILE = Path(__file__).resolve().parents[3] / "config" / "leaders_outside_index.json"
CASES = ("bear", "base", "bull")
SHARE_BASIS = "SEC diluted weighted-average shares (latest reported quarter available)"
# the large list's exclusion text, written by pipeline_score.one_class_per_company from the same template
CLASS_EXCLUSION = re.compile(re.escape(spec.ONE_CLASS_EXCLUSION).replace(re.escape("{ticker}"), "(.+?)"))
NO_DILUTED_SHARES = (
    "dated diluted shares unavailable in the stored snapshot (no company-wide diluted count in SEC XBRL; "
    "multi-class issuers may report only per-class counts)"
)
FALLBACK_FLAG = "shares from weighted-average fallback"  # pipeline_score.market_cap


def collection_kind(record: dict) -> str:
    """Why collection kept no inputs. Older snapshots store no kind: retained SEC facts mean the price failed."""
    return record.get("unavailable_kind") or ("price" if record.get("fundamentals") else "SEC statements")


def usd(value: float) -> str:
    """Market-cap text that does not round a mis-scaled sub-$1M value to $0M."""
    return cap_text(value) if abs(value) >= 1e6 else f"${value:,.0f}"


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


def load_outside(path: Path = OUTSIDE_FILE) -> list[dict]:
    """Validate the closed outside-index schema (spec.LEADERS_OUTSIDE_RULES) at every build."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {"companies"} or not isinstance(raw["companies"], list):
        raise ValueError("outside-index config requires only a companies array")
    names = set()
    for row in raw["companies"]:
        if not isinstance(row, dict) or set(row) != set(LEADERS_OUTSIDE["required"]):
            raise ValueError("outside-index fields must exactly match the registered schema")
        for key in ("name", "valuation_basis", "valuation_source", "status", "status_source"):
            if not isinstance(row[key], str) or not row[key].strip():
                raise ValueError(f"outside-index {key} must be non-empty text")
        if not isinstance(row["notes"], str):
            raise ValueError("outside-index notes must be text")
        if row["kind"] not in spec.LEADERS_OUTSIDE_RULES["kinds"]:
            raise ValueError("invalid outside-index kind")
        ticker = row["ticker"]
        if row["kind"] == "private" and ticker is not None:
            raise ValueError("a private company must have a null ticker")
        if row["kind"] == "listed_non_index" and (
            not isinstance(ticker, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker)
        ):
            raise ValueError("a listed company requires a valid ticker")
        if not ok(row["valuation_usd"]) or row["valuation_usd"] <= 0:
            raise ValueError("outside-index valuation must be finite and positive")
        for key in ("valuation_date", "status_date"):
            if not valid_date(row[key]):
                raise ValueError(f"outside-index {key} must be an ISO date")
        for key in ("valuation_url", "status_url"):
            if not isinstance(row[key], str) or not re.fullmatch(r"https://\S+", row[key]):
                raise ValueError(f"outside-index {key} must be an https URL")
        for key in ("valuation_confirmed", "status_confirmed"):
            if not isinstance(row[key], bool):
                raise ValueError(f"outside-index {key} must be true or false")
        name = row["name"].strip().casefold()
        if name in names:
            raise ValueError("duplicate outside-index company")
        names.add(name)
    return raw["companies"]


def outside_rows(entries: list[dict], as_of: str, current_caps: list[float]) -> tuple[list[dict], list[str]]:
    """Entries valid at the snapshot date, with where the valuation would sit among current caps (scale only)."""
    rules = spec.LEADERS_OUTSIDE_RULES
    rows, omitted = [], []
    for entry in entries:
        latest = max(entry["valuation_date"], entry["status_date"])
        age = (date.fromisoformat(as_of) - date.fromisoformat(entry["valuation_date"])).days
        if latest > as_of:
            omitted.append(f"{entry['name']}: dated after the snapshot ({latest})")
        elif age > rules["max_age_days"]:
            omitted.append(
                f"{entry['name']}: valuation older than {rules['max_age_days']} days ({entry['valuation_date']})"
            )
        elif entry["valuation_usd"] < rules["min_valuation_usd"]:
            omitted.append(f"{entry['name']}: valuation below {cap_text(rules['min_valuation_usd'])}")
        else:
            would = 1 + sum(c > entry["valuation_usd"] for c in current_caps)
            rows.append({**entry, "would_rank": would, "valuation_age_days": age})
    rows.sort(key=lambda r: (-r["valuation_usd"], r["name"]))
    return rows, omitted


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


def share_jump(f: dict, shares: tuple) -> str | None:
    """A latest count more than 10x from one in the preceding four quarters is a unit error or an unrestated split."""
    value, dated = shares
    limit = spec.LEADERS_SHARE_CHECKS["jump_limit"]
    start = date.fromisoformat(dated).toordinal() - 380  # four quarters, allowing 52/53-week calendars
    for s, d in zip(f.get("diluted_shares") or [], f.get("quarters") or [], strict=False):
        if not (ok(s) and s > 0 and valid_date(d) and d < dated and date.fromisoformat(d).toordinal() >= start):
            continue
        if max(value / s, s / value) > limit:
            return (
                f"diluted share count {value:,.0f} ({dated}) differs more than {limit:g}x from {s:,.0f} ({d}): "
                "unit error or unrestated split"
            )
    return None


def cover_basis(record: dict, m: dict, current: float) -> float | None:
    """The stored cover-page equity value behind EV/Sales; None when missing or not independent of the diluted count."""
    recorded = record.get("market_cap_basis")  # stored from 2026-10-19.4
    if recorded == "diluted fallback" or FALLBACK_FLAG in (record.get("flags") or []):
        return None
    value = m.get("market_cap")
    if not ok(value):
        ev_s, revenue = m.get("ev_to_sales"), m.get("revenue_ttm")
        if not (ok(ev_s) and ok(revenue)):
            return None
        # scoring.compute_metrics: EV = market cap + (net debt or 0)
        value = ev_s * revenue - (m["net_debt"] if ok(m.get("net_debt")) else 0.0)
    # older snapshots record no basis: a value equal to close x the same diluted count is the fallback itself
    if value <= 0 or (recorded is None and abs(value / current - 1) < 1e-6):
        return None
    return value


def basis_check(current: float, other: float) -> str | None:
    """Close x diluted shares against the stored cover-page equity value behind EV/Sales."""
    tolerance = spec.LEADERS_SHARE_CHECKS["basis_tolerance"]
    if max(current / other, other / current) > tolerance:
        return (
            f"share bases disagree: close x diluted shares gives {usd(current)}, the stored cover-page "
            f"basis behind EV/Sales gives {usd(other)} (more than {tolerance:g}x apart: a stale or per-class "
            "cover count, shares issued after the quarter, an unrestated split or a unit error)"
        )
    return None


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
        "scenario_2030": {
            f"{case}_{field}": None for case in CASES for field in ("cap", "price", "shares", "implied_cagr")
        },
        "scenario_assumptions": {},
        "aggressive_assumption": False,
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
        "other_share_classes": [],
        "gap_kind": None,
    }
    missing: list[tuple[str, str]] = []  # (coarse kind, reason), so gaps are grouped without parsing text
    other = "other inputs"
    price = record.get("price")
    if not ok(price) or price <= 0 or record.get("price_date") != as_of:
        missing.append(("price", "no verified as-of price in the stored snapshot"))
    if shares[0] is None:
        missing.append(("share count", NO_DILUTED_SHARES))
    filed = f.get("last_filed")
    if not valid_date(filed) or filed > as_of:
        missing.append(("SEC statements", "no dated SEC financial statements filed by the snapshot date"))
    elif (date.fromisoformat(as_of) - date.fromisoformat(filed)).days > spec.MAX_FILING_AGE_DAYS:
        missing.append(("SEC statements", f"fundamentals stale: latest 10-K/10-Q filed {filed}"))
    if not missing:
        current = price * shares[0]
        basis = cover_basis(record, m, current) if ok(current) else None
        # an independent cover-page basis decides; without one the jump test applies (spec 2026-10-19.4)
        if not ok(current):
            problem = "current market cap is not a finite number"
        elif basis is not None:
            problem = basis_check(current, basis)
            jump = share_jump(f, shares) if problem else None
            problem = f"{problem}; {jump}" if jump else problem
        else:
            problem = share_jump(f, shares)
        if problem:
            missing.append(("share count", problem))
        else:
            row["current_market_cap_usd"] = current
            row["market_cap_date"] = as_of
            if basis is None:
                row["missing_inputs"].append(
                    "diluted share count not cross-checked: no independent cover-page basis stored"
                )
    asset_type = record.get("asset_type")
    if asset_type and not asset_type.startswith("operating company"):
        missing.append((other, f"no scenario method for this security type ({asset_type})"))
    positional = leaders_scenarios.positional_metrics(snap.get("spec_version"))
    if len(quarters) < 4:
        missing.append((other, "too few reported quarters for a revenue-based valuation (new filer)"))
    elif positional and not leaders_scenarios.unbroken(quarters, spec.LEADERS_SHARE_CHECKS["ttm_quarters"]):
        missing.append((other, "stored TTM revenue is not four adjacent quarters (gap in the reported series)"))
    if not ok(m.get("revenue_ttm")) or m["revenue_ttm"] <= 0:
        missing.append((other, "too little reported revenue for a revenue-based valuation (pre-revenue)"))
    growth, growth_basis = leaders_scenarios.growth_input(record, m, as_of, positional)
    if growth is None:
        missing.append((other, growth_basis))
    # today's EV/Sales from this row's own cap, so the scenarios never contradict it (spec 2026-10-19.4)
    ev_to_sales, current = None, row["current_market_cap_usd"]
    if ok(current) and ok(m.get("net_debt")) and ok(m.get("revenue_ttm")) and m["revenue_ttm"] > 0:
        if current + m["net_debt"] > 0:
            ev_to_sales = (current + m["net_debt"]) / m["revenue_ttm"]
        else:
            missing.append((other, "enterprise value not positive, so EV/Sales cannot anchor the valuation"))
    if not ok(m.get("net_debt")):
        missing.append((other, "net debt / net cash unavailable in the stored snapshot"))
    if not ok(m.get("dilution")):
        missing.append((other, "trailing dilution unavailable in the stored snapshot"))
    if (date.fromisoformat(spec.WATCHLIST_TARGET_DATE) - date.fromisoformat(as_of)).days <= 0:
        missing.append((other, "the 2030 target is not after the snapshot date"))
    if record.get("unavailable_reason"):
        missing.insert(0, (collection_kind(record), record["unavailable_reason"]))
    if missing:
        reasons = [reason for _, reason in missing]
        row["missing_inputs"] = list(dict.fromkeys(row["missing_inputs"] + reasons))
        row["unavailable_reason"] = record.get("unavailable_reason") or "; ".join(reasons)
        row["gap_kind"] = missing[0][0]
        return row
    try:
        result = leaders_scenarios.company_scenarios(
            current_cap=row["current_market_cap_usd"],
            shares=shares[0],
            metrics={**m, "ev_to_sales": ev_to_sales},
            years=(date.fromisoformat(spec.WATCHLIST_TARGET_DATE) - date.fromisoformat(as_of)).days / 365.25,
            growth=growth,
            basis=growth_basis,
            cyclical=leaders_scenarios.is_cyclical(ticker, record),
        )
        for case in CASES:
            values = result[case]
            if not all(ok(values[field]) for field in ("cap", "price", "shares", "implied_cagr")):
                raise ValueError("non-finite scenario or non-positive projected shares")
            row["scenario_2030"].update(
                {f"{case}_{field}": values[field] for field in ("cap", "price", "shares", "implied_cagr")}
            )
            row["scenario_assumptions"][case] = values["assumptions"]
        row["aggressive_assumption"] = (
            row["scenario_2030"]["base_implied_cagr"] > spec.LEADERS_SCENARIO_RULES["aggressive_cap_cagr"]
        )
    except (ValueError, OverflowError, ZeroDivisionError, TypeError) as exc:
        row["scenario_2030"] = {key: None for key in row["scenario_2030"]}
        row["scenario_assumptions"] = {}
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


def share_classes(snap: dict, records: dict[str, dict], members: list[str]) -> dict[str, str]:
    """{ticker: class ranked instead} for each company (SEC CIK) listed under several index tickers.

    Only classes with a verified as-of price compete when any has one, so a class with no data never
    hides one that has it. Among them the most liquid wins: higher stored 20-day median dollar volume
    when every class has one, else the class the snapshot's large list evaluated, else ticker order
    (spec 2026-10-19.4).
    """
    by_cik: dict[int, list[str]] = defaultdict(list)
    for ticker in members:
        cik = (records.get(ticker) or {}).get("cik")
        if ok(cik) and cik > 0:
            by_cik[int(cik)].append(ticker)
    evaluated = {}
    for excluded in ((snap.get("bands") or {}).get("large") or {}).get("excluded") or []:
        found = CLASS_EXCLUSION.fullmatch(str(excluded.get("reason") or ""))
        if found:
            evaluated[excluded.get("ticker")] = found[1]
    merged = {}
    for tickers in by_cik.values():
        if len(tickers) < 2:
            continue
        priced = [
            t
            for t in tickers
            if ok(records[t].get("price")) and records[t]["price"] > 0 and records[t].get("price_date") == snap["as_of"]
        ]
        pool = priced or tickers
        volumes = {t: records[t].get("dollar_volume") for t in pool}
        named = {evaluated[t] for t in tickers if t in evaluated} & set(pool)
        if all(ok(v) for v in volumes.values()):
            winner = max(pool, key=lambda t: (volumes[t], t))  # pipeline_score.one_class_per_company order
        elif len(named) == 1:
            winner = named.pop()
        else:
            winner = min(pool)
        merged.update({t: winner for t in tickers if t != winner})
    return merged


def build(snap: dict, challengers: list[dict], outside: list[dict] | None = None) -> dict:
    """A separate derived artifact: never mutate, rescore or backfill the source snapshot."""
    records = stored_records(snap)
    members = sorted(set((snap.get("universe") or {}).get("sp500_members") or []))
    merged = share_classes(snap, records, members)
    companies = [t for t in members if t not in merged]
    rows = [computed_row(t, records.get(t, {}), snap) for t in companies]
    for row in rows:
        row["other_share_classes"] = sorted(t for t, winner in merged.items() if winner == row["ticker"])
    current = sorted(
        (r for r in rows if ok(r["current_market_cap_usd"])), key=lambda r: (-r["current_market_cap_usd"], r["ticker"])
    )
    for rank, row in enumerate(current, 1):
        row["current_rank"] = rank
    if any(entry["ticker"] in members for entry in outside or []):
        raise ValueError("an outside-index company is already in this snapshot's S&P 500 universe")
    outside_index, omitted_outside = outside_rows(
        outside or [], snap["as_of"], [r["current_market_cap_usd"] for r in current]
    )
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
            gaps.append(
                {
                    "ticker": row["ticker"],
                    "reason": row["unavailable_reason"],
                    "kind": row["gap_kind"] or "other inputs",
                    "ranked": row["current_rank"] is not None,
                }
            )
    candidates.sort(key=lambda r: (r["current_rank"] or 999999, r["rank_2030"] or 999999, r["company_name"]))
    computed = sum(r["scenario_basis"] != "curated assumption" and r["rank_2030"] is not None for r in rows)
    return {
        "entries": candidates,
        "gaps": gaps,
        "share_classes": [{"ticker": t, "ranked_as": merged[t]} for t in sorted(merged)],
        "outside_index": outside_index,
        "omitted_outside": omitted_outside,
        "omitted_challengers": omitted,
        "universe_count": len(members),
        "company_count": len(companies),
        "current_cap_count": len(current),
        "computed_count": computed,
        "partial": len(current) < len(companies) or computed < len(companies),
        "counts": dict(Counter(r["movement"] for r in candidates)),
        "as_of": snap["as_of"],
        "methodology_version": spec.SPEC_VERSION,
        "snapshot_methodology_version": snap.get("spec_version"),
        "snapshot_id": snap.get("snapshot_id") or snap["as_of"],
        "registered_challengers": len(challengers),
        "top_n": spec.LEADERS_TOP_N,
    }
