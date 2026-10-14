"""Dataset states and per-company evidence checks (spec 2026-10-14.5, display only).

Adapted from ticker-dossier (MIT, https://github.com/nixiakT/ticker-dossier at
568457f7b1db6359b727aaa2a4c0192ea6fd3154):
* `market_data/coverage.py` -> one coverage record per dataset (source, timestamp, what succeeded and what
  failed), here reduced to the five states in spec.DATASET_STATES;
* `research/analysis/quality.py` (QualityGate) -> passed checks, warnings, missing information and next
  checks for one company.
Unlike the upstream project there is no sample-data fallback: a dataset that was not collected is 'missing'.
Everything is derived from a stored snapshot, so older snapshots get the same treatment.
"""
from __future__ import annotations

from datetime import date, datetime

from . import spec

STATE_LABELS = {"available": "Available", "partial": "Partial", "stale": "Stale", "missing": "Missing",
                "provider_error": "Provider error"}


def record(dataset: str, source: str, state: str, detail: str, coverage: str = "", as_of: str | None = None,
           retrieved_at: str | None = None) -> dict:
    if state not in spec.DATASET_STATES:
        raise ValueError(f"unknown dataset state {state!r}")
    return {"dataset": dataset, "source": source, "state": state, "label": STATE_LABELS[state],
            "meaning": spec.DATASET_STATES[state], "detail": detail, "coverage": coverage, "as_of": as_of,
            "retrieved_at": retrieved_at}


def _share_state(ok: int, requested: int) -> str:
    if requested <= 0:
        return "missing"
    if ok <= 0:
        return "provider_error"
    return "available" if ok / requested >= spec.DATASET_PARTIAL_BELOW else "partial"


def _age_days(earlier: str | None, later: str) -> int | None:
    try:
        return (date.fromisoformat(str(later)[:10]) - datetime.fromisoformat(str(earlier)).date()).days
    except (TypeError, ValueError):
        return None


def earnings_state(snap: dict) -> tuple[str, str]:
    """('available' | 'missing' | 'provider_error', detail) for the earnings calendar lookup.

    Snapshots before 2026-10-14.5 carry no status, so a failed lookup is recognised from the note."""
    ev = snap.get("events") or {}
    if ev.get("items") is None and "status" not in ev:
        return "missing", "not collected in this snapshot"
    if ev.get("status") == "unavailable" or str(ev.get("note", "")).startswith("Earnings dates unavailable"):
        reason = ev.get("reason") or str(ev.get("note", "")).replace("Earnings dates unavailable: ", "")
        state = ev.get("state") or ("missing" if "not configured" in reason else "provider_error")
        return state, f"lookup failed or was not configured: {reason}"
    n = len(ev.get("items") or [])
    window = ev.get("window_days", 45)
    if n:
        return "available", f"{n} scheduled report date(s) for listed names in the next {window} days"
    return "available", f"lookup succeeded; no listed name has a scheduled report in the next {window} days"


def datasets(snap: dict) -> list[dict]:
    """One state per dataset behind this snapshot, with its source and coverage."""
    as_of, at = str(snap["as_of"]), str(snap.get("run_finished") or "")
    src = snap.get("sources") or {}
    u = snap.get("universe") or {}
    out = []

    n_sp, cov = u.get("sp500_count") or 0, u.get("sp500_price_coverage")
    ok_sp = round((cov or 0) * n_sp)
    out.append(record("S&P 500 daily prices", src.get("cboe", "Cboe delayed quotes"), _share_state(ok_sp, n_sp),
                      "as-of close and history validated for each member", f"{ok_sp} of {n_sp}", as_of, at))

    elig = u.get("broad_eligible") or 0
    failed = sum(v for k, v in (u.get("broad_exclusion_counts") or {}).items()
                 if k.startswith(("data unavailable", "no quote", "stale quote", "not evaluated")))
    out.append(record("Broad-universe quotes", src.get("cboe", "Cboe delayed quotes"),
                      _share_state(elig - failed, elig),
                      f"{failed} quote(s) failed or had no trade in the as-of session" if failed else
                      "every eligible listing returned an as-of quote", f"{elig - failed} of {elig}", as_of, at))

    sec_problem = any("sec" in p.lower() for p in snap.get("problems") or [])
    fetch_fail = sum(1 for b in (snap.get("bands") or {}).values() for x in b.get("excluded", [])
                     if str(x.get("reason", "")).startswith(("data unavailable", "not evaluated")))
    out.append(record("Company facts (XBRL)", src.get("sec", "SEC EDGAR"),
                      "partial" if sec_problem or fetch_fail else "available",
                      ("; ".join(p for p in snap.get("problems") or [] if "sec" in p.lower()) or
                       f"{fetch_fail} stock(s) excluded because a request failed") if sec_problem or fetch_fail else
                      "facts filed on or before the as-of date, for every evaluated stock", "", as_of, at))

    state, detail = earnings_state(snap)
    out.append(record("Earnings calendar", src.get("alphavantage", "Alpha Vantage EARNINGS_CALENDAR"), state,
                      detail, "", as_of, (snap.get("events") or {}).get("retrieved_at") or at))

    items = (snap.get("events") or {}).get("items") or []
    checked = [i for i in items if i.get("last_results_status")]
    verified = [i for i in checked if str(i["last_results_status"]).startswith("verified")]
    out.append(record("Results filings (8-K item 2.02)", src.get("sec", "SEC EDGAR"),
                      ("missing" if not items else _share_state(len(verified), len(items))),
                      "last results release found in recent SEC filings" if items else
                      "nothing to verify: no scheduled report dates were available",
                      f"{len(verified)} of {len(items)}" if items else "", as_of, at))

    tr = snap.get("tradability") or {}
    stored, todo = tr.get("verdicts_stored") or 0, tr.get("to_check") or 0
    age = _age_days(tr.get("oldest_check"), as_of)
    max_age = tr.get("max_age_days", spec.TRADABILITY_MAX_AGE_DAYS)
    if not stored:
        t_state, t_detail = "missing", "no stored read-only Robinhood check, so nothing could be published"
    elif age is not None and age > max_age:
        t_state, t_detail = "stale", f"oldest stored check is {age} days old (max {max_age})"
    elif todo:
        t_state, t_detail = "partial", f"{todo} listed-or-nearly-listed symbol(s) still need a check"
    else:
        t_state, t_detail = "available", "every symbol that would make a list has a fresh check"
    out.append(record("Robinhood tradability verdicts", tr.get("source", "Robinhood MCP (read-only)"), t_state,
                      t_detail, f"{stored} stored", as_of, tr.get("newest_check")))

    w = snap.get("watchlist") or {}
    if w.get("entries"):
        listed = [e for e in w["entries"] if e.get("status") == "listed"]
        priced = [e for e in listed if e.get("price") is not None]
        out.append(record("Watchlist prices", src.get("cboe", "Cboe delayed quotes"),
                          _share_state(len(priced), len(listed)) if listed else "missing",
                          "as-of price verified for each listed watchlist symbol",
                          f"{len(priced)} of {len(listed)} listed", as_of, at))

    o_state, o_detail = options_state(snap)
    o = snap.get("options") or {}
    cov = f"{len(o.get('underlyings') or [])} of {len(o.get('underlyings') or []) + len(o.get('chain_problems') or {})} chains" \
        if o.get("enabled") and o.get("status") == "ok" else ""
    out.append(record("Option chains", src.get("cboe", "Cboe delayed quotes"), o_state, o_detail, cov, as_of,
                      o.get("collected_at") or at))
    return out


def options_state(snap: dict) -> tuple[str, str]:
    """(dataset state, plain-language detail) for the option chains behind a snapshot.

    missing = collection switched off or not configured; provider_error = the collection ran and failed, or no
    chain could be used for a reason other than staleness; stale = every chain was rejected as stale; partial =
    some chains were rejected; available = every requested chain was collected and validated."""
    o = snap.get("options") or {}
    if not o.get("enabled"):
        why = o.get("status") or "not configured"
        return "missing", f"not collected for this snapshot ({why})"
    if o.get("status") != "ok":
        return "provider_error", f"collection failed: {o.get('status')}"
    problems = o.get("chain_problems") or {}
    usable = o.get("underlyings") or []
    if not usable:
        if problems and all("stale" in str(v).lower() for v in problems.values()):
            return "stale", f"every chain was rejected as stale ({len(problems)} of {len(problems)})"
        return "provider_error", (f"no chain could be used: {len(problems)} rejected" if problems else
                                  "no chain was collected")
    if problems:
        return "partial", (f"{len(usable)} of {len(usable) + len(problems)} chains usable; {len(problems)} rejected "
                           "(stale, failed or unreadable)")
    return "available", f"delayed chains collected and validated for all {len(usable)} underlying(s)"


# --- per-company evidence check (adapted from ticker-dossier QualityGate) -------------------------------

QUALITY_LEVELS = ("high", "medium", "low", "none")


def quality_level(label: str | None) -> str:
    """One scale for every page: the ranked lists' confidence and the watchlist's evidence quality."""
    s = str(label or "none").lower()
    if s.startswith("high") or s == "medium-high":
        return "high" if s.startswith("high") else "medium"
    return s if s in QUALITY_LEVELS else "none"


def company_check(c: dict, as_of: str) -> dict:
    """{"level", "passed", "warnings", "missing", "next_checks"} for one ranked candidate."""
    m, fund = c.get("metrics") or {}, c.get("fundamentals") or {}
    passed, warnings, missing, nxt = [], [], [], []
    passed.append(f"As-of close verified for the {c.get('price_date')} session ({(c.get('sources') or {}).get('price', 'Cboe')}).")
    filed = fund.get("last_filed")
    if filed:
        try:
            age = (date.fromisoformat(as_of) - date.fromisoformat(filed)).days
            msg = f"Latest SEC filing used: {fund.get('last_form') or 'filing'} filed {filed} ({age} days before the as-of date)."
            (passed if age <= 120 else warnings).append(msg)
        except ValueError:
            warnings.append("The latest filing date could not be read.")
    n_sub = len(c.get("sub_scores") or {})
    miss = list(c.get("missing") or [])
    if n_sub:
        passed.append(f"{n_sub - len(miss)} of {n_sub} scored inputs measured.")
    for k in miss:
        warnings.append(f"Missing input: {k.replace('_', ' ')} (scored 0, weight not redistributed).")
    derived = sum(1 for d in fund.get("derived_revenue") or [] if d)
    if derived:
        warnings.append(f"{derived} of the last {len(fund.get('derived_revenue') or [])} quarters were derived from "
                        "cumulative or annual filings rather than tagged directly.")
    for f in c.get("flags") or []:
        warnings.append(f"{f[0].upper()}{f[1:]}.")
    warnings.append("Prices come from one source (Cboe delayed quotes) and are not cross-checked against a second "
                    "source; fundamentals are SEC filings as tagged, not reconciled to another provider.")
    for k, v in (c.get("not_scored") or {}).items():
        missing.append(f"{k.replace('_', ' ')}: {v}")
    missing += [f"{x} (not collected)" for x in spec.FORENSIC_RULES["not_collected"]]
    if m.get("fcf_ttm") is None:
        nxt.append("Read the cash-flow statement: trailing free cash flow could not be computed.")
    if miss:
        nxt.append("Check the latest 10-Q/10-K for the missing inputs listed above.")
    nxt.append("Read the 10-K risk factors and the competition section, which no score here covers.")
    return {"level": quality_level(c.get("confidence_label")), "label": c.get("confidence_label"),
            "passed": passed, "warnings": warnings, "missing": missing, "next_checks": nxt,
            "missing_count": len(miss)}
