"""Form 4 transactions and bounded, point-in-time P/S aggregates."""

from __future__ import annotations

import calendar
import math
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from .http import BudgetExceeded, FetchError

CLASSIFICATION = "Form 4 codes P/S (open market or private); A, M, F, G and derivative rows excluded"
LABEL = "P/S purchases/sales (open market or private)"


def year_before(day: date) -> date:
    return day.replace(year=day.year - 1, day=min(day.day, calendar.monthrange(day.year - 1, day.month)[1]))


def parse_form4(body: bytes, accession: str, filed: str, cik: int) -> dict:
    if len(body) > 16_000_000 or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise FetchError("Form 4 unsafe or oversized XML")
    try:
        root = ET.fromstring(body)
        for element in root.iter():
            element.tag = element.tag.rsplit("}", 1)[-1]
        if root.tag != "ownershipDocument" or int(root.findtext("issuer/issuerCik", "0")) != int(cik):
            raise ValueError
        form = root.findtext("documentType")
        if form not in ("4", "4/A"):
            raise ValueError
        owners = sorted({str(int(e.text)) for e in root.findall("reportingOwner/reportingOwnerId/rptOwnerCik")})
        if not owners:
            raise ValueError
        plan = root.findtext("aff10b5One")
        if plan not in (None, "0", "1", "true", "false"):
            raise ValueError
        transactions = []
        for table, derivative in (
            ("nonDerivativeTable/nonDerivativeTransaction", False),
            ("derivativeTable/derivativeTransaction", True),
        ):
            for node in root.findall(table):
                day = date.fromisoformat(node.findtext("transactionDate/value", ""))
                code = node.findtext("transactionCoding/transactionCode", "").upper()
                if not re.fullmatch("[A-Z]", code):
                    raise ValueError
                raw_shares = node.findtext("transactionAmounts/transactionShares/value")
                raw_price = node.findtext("transactionAmounts/transactionPricePerShare/value")
                shares = float(raw_shares) if raw_shares else None
                price = float(raw_price) if raw_price else None
                if any(v is not None and (not math.isfinite(v) or v < 0) for v in (shares, price)):
                    raise ValueError
                transactions.append(
                    {
                        "date": str(day),
                        "code": code,
                        "shares": shares,
                        "price": price,
                        "derivative": derivative,
                        "security": node.findtext("securityTitle/value", ""),
                        "owners": owners,
                        "accession": accession,
                    }
                )
        return {
            "accession": accession,
            "filed": filed,
            "form": form,
            "owners": owners,
            "plan_10b5_1": None if plan is None else plan in ("1", "true"),
            "transactions": transactions,
        }
    except (ET.ParseError, ValueError, TypeError):
        raise FetchError("Form 4 ownership XML invalid or issuer mismatched") from None


def aggregate(filings: list[dict], as_of: date, reason: str | None = None) -> dict:
    # Amendments do not identify each superseded transaction reliably. Do not double count them.
    if any(f["form"] == "4/A" for f in filings):
        reason = reason or "Form 4/A amendment requires reconciliation; complete net activity unavailable"
    rows = [
        r
        for f in filings
        if f["filed"] <= str(as_of)
        for r in f["transactions"]
        if str(year_before(as_of)) <= r["date"] <= str(as_of)
    ]
    excluded = {}
    for row in rows:
        if row["derivative"] or row["code"] not in ("P", "S"):
            key = "derivative" if row["derivative"] else row["code"]
            excluded[key] = excluded.get(key, 0) + 1
    out = {
        "state": "partial" if reason else "available",
        "reason": reason,
        "as_of": str(as_of),
        "classification_basis": CLASSIFICATION,
        "label": LABEL,
        "latest_transaction_date": max((r["date"] for r in rows), default=None),
        "accessions": [f["accession"] for f in filings],
        "excluded_rows": excluded,
        "filings": filings,
        "source": "SEC EDGAR Form 4",
        "windows": {},
    }
    for key, start in (("90d", as_of - timedelta(days=89)), ("12m", year_before(as_of))):
        selected = [r for r in rows if r["date"] >= str(start) and not r["derivative"] and r["code"] in ("P", "S")]
        shares_ok = not reason and all(r["shares"] is not None for r in selected)
        dollars_ok = shares_ok and all(r["price"] is not None for r in selected)
        out["windows"][key] = {
            "start": str(start),
            "end": str(as_of),
            "net_shares": sum(r["shares"] * (1 if r["code"] == "P" else -1) for r in selected) if shares_ok else None,
            "net_dollars": sum(r["shares"] * r["price"] * (1 if r["code"] == "P" else -1) for r in selected)
            if dollars_ok
            else None,
            "buyers": len({o for r in selected if r["code"] == "P" for o in r["owners"]}) if not reason else None,
            "sellers": len({o for r in selected if r["code"] == "S" for o in r["owners"]}) if not reason else None,
            "reason": reason or (None if shares_ok else "P/S share count missing"),
            "dollars_reason": reason or (None if dollars_ok else "P/S shares or transaction price missing"),
        }
    if any(w["net_shares"] is None or w["net_dollars"] is None for w in out["windows"].values()):
        out["state"] = "partial"
        out["reason"] = reason or "P/S shares or transaction price missing; see each window's reasons"
    return out


def filing_rows(raw: dict) -> list[dict]:
    fields = ("form", "filingDate", "accessionNumber", "primaryDocument")
    if any(not isinstance(raw.get(f), list) for f in fields) or len({len(raw[f]) for f in fields}) != 1:
        raise FetchError("SEC submissions filing layout changed")
    return [dict(zip(fields, vals, strict=True)) for vals in zip(*(raw[f] for f in fields), strict=True)]


def collect(providers, cik: int, as_of: date, previous: dict | None = None) -> dict:
    filings, reason = [], None
    retained = {f["accession"]: f for f in (previous or {}).get("filings", []) if "transactions" in f}
    try:
        with providers.http.budget_group("sec_insiders"):
            submissions = providers.submissions(cik)
            raw = submissions.get("filings", {})
            rows = filing_rows(raw.get("recent", {}))
            for page in raw.get("files", []):
                if page.get("filingTo", "") < str(year_before(as_of)) or page.get("filingFrom", "9999") > str(as_of):
                    continue
                name = page.get("name", "")
                if not re.fullmatch(r"CIK\d+-submissions-\d+\.json", name):
                    raise FetchError("Invalid historical submissions filename")
                rows.extend(
                    filing_rows(providers.http.get_json(f"https://data.sec.gov/submissions/{name}", max_age_hours=168))
                )
            seen = set()
            for row in sorted(rows, key=lambda r: (r["filingDate"], r["accessionNumber"]), reverse=True):
                if row["form"] not in ("4", "4/A") or not str(year_before(as_of)) <= row["filingDate"] <= str(as_of):
                    continue
                accession = row["accessionNumber"]
                if accession in seen:
                    continue
                seen.add(accession)
                if accession in retained:
                    filings.append(retained[accession])
                    continue
                doc = row["primaryDocument"].split("/")[-1]  # bypass the optional SEC XSL HTML rendering
                if (
                    not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession)
                    or not re.fullmatch(r"[\w.-]+\.xml", doc)
                    or ".." in doc
                ):
                    raise FetchError("Invalid Form 4 document path")
                url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{doc}"
                item = parse_form4(providers.http.get_bytes(url, max_age_hours=8760), accession, row["filingDate"], cik)
                item["url"] = url
                filings.append(item)
    except BudgetExceeded:
        reason = "deferred to next run"
    except (FetchError, ValueError, KeyError, TypeError, AttributeError) as exc:
        reason = str(exc) if isinstance(exc, FetchError) else "Invalid Form 4 filing metadata"
    result = aggregate(filings, as_of, reason)
    if reason and reason != "deferred to next run" and not filings:
        result["state"] = "provider_error"
    return result
