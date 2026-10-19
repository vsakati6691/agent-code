"""Weekly, display-only enrichment after candidate selection. Never changes ranking inputs."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from . import sec_insiders, short_interest
from . import sec_institutions as institutions
from .decision_sources import latest_10k, parse_efts, risk_excerpt
from .http import BudgetExceeded, FetchError
from .pipeline_context import as_of_for
from .providers import EXTERNAL_PROVIDERS
from .store import IntegrityError

OLD = "Not collected in this snapshot; a new weekly collection is required"


def missing(reason: str = OLD, state: str = "missing") -> dict:
    return {"state": state, "reason": reason}


def institutional_record(
    archives: list[dict],
    mapping: dict,
    ticker: str,
    as_of: date,
    error: dict | None = None,
    *,
    providers=None,
    current_collection: bool = False,
) -> dict:
    """Isolate a malformed company as well as bulk failures; absence is not zero ownership."""
    try:
        record = error or institutions.company(archives, mapping, ticker, as_of)
        if not isinstance(record, dict) or not record.get("state"):
            raise ValueError("invalid institutional record")
    except (FetchError, OSError, ValueError, KeyError, TypeError, AttributeError):
        record = missing("SEC 13F company data unavailable or malformed", "provider_error")
    record = {"provider": "sec", **record, "fallback_status": "not_needed"}
    if record["state"] != "available":
        record["fallback_status"] = "historical_disabled" if not current_collection else "unconfigured"
        if current_collection and providers is not None and getattr(providers, "fmp_key", None):
            primary_state, primary_reason = record["state"], record.get("reason")
            try:
                fallback = providers.institutional_holders(ticker, as_of)
                if not isinstance(fallback, dict) or fallback.get("state") != "available":
                    raise FetchError("Invalid FMP institutional fallback record")
                record = {
                    **fallback,
                    "fallback_status": "available",
                    "primary_state": primary_state,
                    "primary_reason": primary_reason,
                }
            except (FetchError, OSError, ValueError, KeyError, TypeError, AttributeError):
                record["fallback_status"] = "provider_error"
                record["fallback_reason"] = "FMP unavailable, malformed, not entitled or budget exhausted"
    return {**record, "score_adjustment": 0.0, "scoring_status": "neutral (display-only dataset)"}


def subjects(bands: dict, watchlist: dict) -> dict[str, list[dict]]:
    result = {}
    for band in bands.values():
        for company in band.get("candidates", []):
            result.setdefault(company["ticker"], []).append(company)
    for entry in watchlist.get("entries", []):
        if (entry.get("asset_type") or "").startswith("operating company"):
            result.setdefault(entry["ticker"], []).append(entry)
    return result


def _bulk(providers, as_of: date, store) -> tuple[list[dict], dict]:
    archives = []
    with providers.http.budget_group("sec_bulk"):
        index = providers.http.get_text(institutions.INDEX, max_age_hours=168)
        choices = []
        for url in institutions.links(index, institutions.INDEX, r"_form13f\.zip$"):
            try:
                end, quarter = institutions.archive_period(url)
            except FetchError:
                continue  # pre-March-2024 legacy archive naming is not used for new collection
            if end <= as_of:
                choices.append((end, quarter, url))
        for end, quarter, url in sorted(choices, reverse=True)[:2]:
            cached = store.source_aggregate("13f", str(quarter)) if store else None
            if cached is None:
                body = providers.http.get_bytes(url)
                cached = {
                    **institutions.aggregate_zip(body, quarter, as_of),
                    "source": url,
                    "filing_window_end": str(end),
                    "collected_as_of": str(as_of),
                }
                if store:
                    store.write_source_aggregate("13f", str(quarter), cached)
            if cached.get("collected_as_of", "9999") <= str(as_of):
                archives.append(cached)
        index = providers.http.get_text(institutions.FTD_INDEX, max_age_hours=168)
        choices = []
        for url in institutions.links(index, institutions.FTD_INDEX, r"cnsfails\d{6}[ab]\.zip$"):
            match = re.search(r"cnsfails(\d{4})(\d{2})([ab])\.zip$", url)
            if urlsplit(url).hostname != "www.sec.gov" or not match:
                continue
            year, month, half = match.groups()
            import calendar

            end = date(int(year), int(month), 15 if half == "a" else calendar.monthrange(int(year), int(month))[1])
            # The page supplies links only once released; no future settlement files are eligible.
            if end <= as_of:
                choices.append((end, url))
        if not choices:
            raise FetchError("No eligible dated SEC FTD download link")
        end, url = max(choices)
        mapping = store.source_aggregate("ftd", str(end)) if store else None
        if mapping is None:
            mapping = {
                **institutions.ftd_mapping(providers.http.get_bytes(url), as_of),
                "source": url,
                "file_date": str(end),
                "collected_as_of": str(as_of),
            }
            if store:
                store.write_source_aggregate("ftd", str(end), mapping)
        if mapping.get("collected_as_of", "9999") > str(as_of):
            raise FetchError("CUSIP mapping was collected after this as-of date")
    return archives, mapping


def _short(providers, as_of: date) -> dict:
    url = EXTERNAL_PROVIDERS["short_interest"]["endpoint"]
    index = providers.http.get_text(url, max_age_hours=24)
    choices = []
    for link in institutions.links(index, url, r"/shrt\d{8}\.csv$"):
        stamp = re.search(r"shrt(\d{4})(\d{2})(\d{2})\.csv$", link)
        if urlsplit(link).hostname != "cdn.finra.org":
            continue
        settled = date(*(int(s) for s in stamp.groups()))
        if settled <= as_of:
            choices.append((settled, link))
    if not choices:
        raise FetchError("FINRA index has no eligible dated download")
    current = None
    for settled, link in sorted(choices, reverse=True)[:2]:
        rows = short_interest.parse_file(providers.http.get_text(link, max_age_hours=168), as_of)
        if any(r["settlement_date"] != str(settled) for r in rows.values()):
            raise FetchError("FINRA settlement date differs from download filename")
        for row in rows.values():
            row["source"] = link
        if current is None:
            current = rows
        else:
            for ticker, row in current.items():
                prior = rows.get(ticker)
                row["prior_settlement_date"] = str(settled) if prior else None
                # FINRA's prior quantity can be split-adjusted/revised. Preserve that published comparison.
                row["prior_source"] = link
    return current or {}


def _risk(ctx, cik: int, previous: dict, business: dict) -> dict:
    prior = previous.get("risk_excerpt") or {}
    # The immediately preceding snapshot can predate external.risk_excerpt.
    # Its original decision-research quotation is still reusable evidence.
    for existing in (previous.get("legacy_business") or {}, business):
        candidate = existing.get("risk_record") or {}
        if not candidate.get("excerpt") and existing.get("risk"):
            candidate = {
                "state": "available",
                "excerpt": existing["risk"],
                "filed": existing.get("filed"),
                "url": existing.get("url"),
                "form": "10-K",
                "reason": None,
                "character_range": None,
                "range_reason": "Legacy stored excerpt has no character offsets",
            }
        if candidate.get("excerpt") and (candidate.get("filed") or "") >= (prior.get("filed") or ""):
            prior = candidate
    try:
        # Reuse submissions obtained for the insider list; no extra risk lookup outside the two-attempt cap.
        sub = getattr(ctx.providers, "_submissions", {}).get(cik, {})
        annual = latest_10k(sub, cik, ctx.as_of)
        if prior.get("excerpt") and annual and (prior.get("filed") or "") >= annual[1]:
            return prior
        with ctx.providers.http.budget_group("sec_risk", max_attempts=2):
            raw = ctx.providers.http.get_json(
                EXTERNAL_PROVIDERS["risk_excerpts"]["endpoint"],
                {
                    "q": '"risk factors"',
                    "ciks": f"{cik:010d}",
                    "forms": "10-K,10-Q",
                    "dateRange": "custom",
                    "startdt": annual[1] if annual else str(ctx.as_of - timedelta(days=550)),
                    "enddt": str(ctx.as_of),
                    "from": 0,
                    "size": 100,
                },
                max_age_hours=168,
            )
            filing = parse_efts(raw, cik, ctx.as_of)
            if not filing:
                return {**prior, **missing("No eligible 10-K/10-Q risk filing in EFTS")}
            return risk_excerpt(ctx.providers.http.get_text(filing["url"], max_age_hours=168), filing)
    except BudgetExceeded:
        return {**prior, "state": "partial", "reason": "excerpt refresh deferred"}
    except (FetchError, KeyError, TypeError, ValueError, AttributeError):
        return {
            **prior,
            "state": "provider_error",
            "reason": "Risk excerpt refresh failed; previous excerpt retained if available",
        }


def collect(ctx, bands: dict, watchlist: dict, previous: dict | None, store=None) -> dict:
    companies = subjects(bands, watchlist)
    previous_companies = subjects((previous or {}).get("bands", {}), (previous or {}).get("watchlist", {}))
    prior = {
        t: {
            **(rows[0].get("external") or {}),
            "legacy_business": (rows[0].get("decision_research") or {}).get("business") or {},
        }
        for t, rows in previous_companies.items()
    }
    summaries = {}
    current_collection = ctx.as_of == as_of_for(datetime.fromisoformat(ctx.started))
    try:
        if not current_collection:
            raise FetchError("Current SEC bulk index cannot establish historical archive availability; no backfill")
        archives, mapping = _bulk(ctx.providers, ctx.as_of, store)
        institutional_error = None
    except (FetchError, IntegrityError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        archives, mapping = [], {}
        reason = (
            "SEC 13F collection unavailable"
            if current_collection
            else "Current SEC bulk index cannot establish historical availability; no backfill"
        )
        institutional_error = missing(reason, "partial" if isinstance(exc, BudgetExceeded) else "provider_error")
    try:
        if not current_collection:
            raise FetchError("Current FINRA index cannot establish historical release availability; no backfill")
        shorts, short_error = _short(ctx.providers, ctx.as_of), None
    except (FetchError, OSError, ValueError, KeyError, TypeError) as exc:
        shorts, short_error = {}, missing(str(exc), "partial" if isinstance(exc, BudgetExceeded) else "provider_error")
    # Resume previously deferred names first. Retained dated Form 4 transactions avoid refetching their history.
    order = sorted(
        companies, key=lambda t: (prior.get(t, {}).get("insiders", {}).get("reason") != "deferred to next run", t)
    )
    for ticker in order:
        entries = companies[ticker]
        c = entries[0]
        cik = next((e.get("cik") for e in entries if e.get("cik")), None)
        external = {}
        if cik:
            external["insiders"] = sec_insiders.collect(
                ctx.providers, int(cik), ctx.as_of, prior.get(ticker, {}).get("insiders")
            )
            business = (c.get("decision_research") or {}).get("business", {})
            external["risk_excerpt"] = _risk(ctx, int(cik), prior.get(ticker, {}), business)
        else:
            external["insiders"] = missing("No SEC CIK for this company")
            external["risk_excerpt"] = missing("No SEC CIK for this company")
        external["institutions"] = institutional_record(
            archives,
            mapping,
            ticker,
            ctx.as_of,
            institutional_error,
            providers=ctx.providers,
            current_collection=current_collection,
        )
        f = ctx.facts.get(int(cik), (None,))[0] if cik else None
        shares, shares_date = None, None
        if f:
            shares, shares_date = next(
                ((s, str(q)) for s, q in zip(f.diluted_shares, f.quarters, strict=False) if s and s > 0), (None, None)
            )
        external["short_interest"] = short_error or (
            short_interest.with_denominator(shorts[ticker], shares, shares_date, c.get("average_daily_volume"))
            if ticker in shorts
            else missing("Symbol absent from FINRA report; absence is not zero short interest")
        )
        for e in entries:
            e["external"] = external
    for key in ("insiders", "institutions", "risk_excerpt", "short_interest"):
        records = [entries[0]["external"][key] for entries in companies.values()]
        states = [r["state"] for r in records]
        available = states.count("available")
        state = (
            "available"
            if records and available == len(records)
            else "partial"
            if any(s in ("available", "partial") for s in states)
            else ("provider_error" if "provider_error" in states else "stale" if "stale" in states else "missing")
        )
        summaries[key] = {
            "state": state,
            "requested": len(records),
            "available": available,
            "deferred": sum(r.get("reason") in ("deferred to next run", "excerpt refresh deferred") for r in records),
            "source": EXTERNAL_PROVIDERS["risk_excerpts" if key == "risk_excerpt" else key]["endpoint"],
            "retrieved_at": ctx.started,
            "reasons": sorted({r["reason"] for r in records if r.get("reason")}),
        }
        if key == "institutions":
            summaries[key]["fallback"] = {
                state: sum(r.get("fallback_status") == state for r in records)
                for state in ("available", "provider_error", "unconfigured", "historical_disabled", "not_needed")
            }
    return summaries
