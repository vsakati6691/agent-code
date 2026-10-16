"""SEC bulk 13F aggregation and dated, incomplete FTD CUSIP mappings."""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import re
import zipfile
from collections import defaultdict
from datetime import date, timedelta
from html import unescape
from urllib.parse import urljoin, urlsplit

from .http import FetchError
from .providers import canonical

INDEX = "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
FTD_INDEX = "https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data"


def links(markup: str, base: str, pattern: str) -> list[str]:
    return list(
        dict.fromkeys(
            urljoin(base, unescape(value))
            for value in re.findall(r'href=["\x27]([^"\x27]+)', markup, re.I)
            if re.search(pattern, value, re.I)
        )
    )


def _date(value: str) -> date:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%Y%m%d"):
        from datetime import datetime

        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            pass
    raise FetchError("SEC bulk file contains an invalid date")


def archive_period(url: str) -> tuple[date, date]:
    match = re.search(r"\d{2}[a-z]{3}\d{4}-(\d{2})([a-z]{3})(\d{4})_form13f\.zip$", url, re.I)
    if not match or urlsplit(url).hostname != "www.sec.gov":
        raise FetchError("Unrecognized SEC 13F archive URL")
    end = _date("-".join(match.groups()))
    absolute = end.year * 12 + end.month - 3
    year, zero_month = divmod(absolute, 12)
    month = zero_month + 1
    quarter = date(year, month, calendar.monthrange(year, month)[1])
    if quarter.month not in (3, 6, 9, 12):
        raise FetchError("Unrecognized SEC 13F archive filing window")
    return end, quarter


def zip_tables(body: bytes) -> zipfile.ZipFile:
    try:
        z = zipfile.ZipFile(io.BytesIO(body))
        if len(body) > 250_000_000 or sum(f.file_size for f in z.infolist()) > 3_000_000_000:
            raise ValueError
        return z
    except (ValueError, zipfile.BadZipFile):
        raise FetchError("SEC bulk response is not a supported ZIP") from None


def _rows(z: zipfile.ZipFile, table: str, fields: set[str]):
    matches = [n for n in z.namelist() if n.split("/")[-1].upper() == table + ".TSV"]
    if len(matches) != 1:
        raise FetchError(f"13F {table} table missing or duplicated")
    with z.open(matches[0]) as binary:
        reader = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig"), delimiter="\t")
        if not fields <= set(reader.fieldnames or []):
            raise FetchError(f"13F {table} column layout changed")
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise FetchError(f"13F {table} malformed row")
            yield row


def aggregate_zip(body: bytes, quarter: date, as_of: date) -> dict:
    z = zip_tables(body)
    try:
        submissions = {
            r["ACCESSION_NUMBER"]: r
            for r in _rows(
                z, "SUBMISSION", {"ACCESSION_NUMBER", "FILING_DATE", "SUBMISSIONTYPE", "CIK", "PERIODOFREPORT"}
            )
            if _date(r["PERIODOFREPORT"]) == quarter
            and _date(r["FILING_DATE"]) <= as_of
            and r["SUBMISSIONTYPE"] in ("13F-HR", "13F-HR/A")
        }
        managers = defaultdict(list)
        for r in _rows(z, "COVERPAGE", {"ACCESSION_NUMBER", "FILINGMANAGER_NAME", "ISAMENDMENT", "AMENDMENTTYPE"}):
            acc = r["ACCESSION_NUMBER"]
            if acc in submissions:
                sub = submissions[acc]
                managers[sub["CIK"]].append((sub, r))
        selected, unresolved = {}, 0
        for cik, records in managers.items():
            chosen = []
            for sub, cover in sorted(records, key=lambda x: (_date(x[0]["FILING_DATE"]), x[0]["ACCESSION_NUMBER"])):
                amendment = cover["AMENDMENTTYPE"].upper().strip()
                if sub["SUBMISSIONTYPE"] == "13F-HR" or amendment == "RESTATEMENT":
                    chosen = [(sub, cover)]
                elif amendment in ("NEW HOLDINGS", "ADDS NEW HOLDINGS ENTRIES") and chosen:
                    chosen.append((sub, cover))
                else:
                    chosen = []
                    unresolved += 1
            for sub, cover in chosen:
                selected[sub["ACCESSION_NUMBER"]] = (cik, cover["FILINGMANAGER_NAME"])
        holdings = defaultdict(lambda: defaultdict(int))
        names = {}
        for r in _rows(z, "INFOTABLE", {"ACCESSION_NUMBER", "CUSIP", "SSHPRNAMT", "SSHPRNAMTTYPE", "PUTCALL"}):
            manager = selected.get(r["ACCESSION_NUMBER"])
            if not manager or r["SSHPRNAMTTYPE"] != "SH" or r["PUTCALL"].strip():
                continue
            cusip = r["CUSIP"].strip().upper()
            try:
                amount = int(r["SSHPRNAMT"])
                if amount < 0 or not re.fullmatch(r"[A-Z0-9*@#]{9}", cusip):
                    raise ValueError
            except ValueError:
                raise FetchError("13F invalid CUSIP or reported share quantity") from None
            cik, name = manager
            if amount:
                holdings[cusip][cik] += amount
                names[cik] = name
        if not selected or not holdings:
            raise FetchError("13F archive has no usable holdings for its report quarter")
        aggregates = {}
        for cusip, amounts in holdings.items():
            top = sorted(amounts, key=lambda c: (-amounts[c], c))[:10]
            aggregates[cusip] = {
                "holder_count": len(amounts),
                "reported_shares": sum(amounts.values()),
                "top_holders": [{"cik": c, "name": names[c], "shares": amounts[c]} for c in top],
            }
        return {
            "report_quarter_end": str(quarter),
            "state": "partial" if unresolved else "available",
            "reason": f"{unresolved} amendment(s) could not be reconciled" if unresolved else None,
            "by_cusip": aggregates,
            "archive_sha256": hashlib.sha256(body).hexdigest(),
            "note": "Reported long SH holdings excluding puts/calls; managers' reported holdings may overlap. Not total institutional ownership.",
        }
    except (UnicodeError, csv.Error, zipfile.BadZipFile) as exc:
        raise FetchError(f"13F archive parse failed ({type(exc).__name__})") from None
    finally:
        z.close()


def ftd_mapping(body: bytes, as_of: date) -> dict:
    z = zip_tables(body)
    mappings = defaultdict(set)
    dates = {}
    try:
        names = [n for n in z.namelist() if n.lower().endswith(".txt")]
        if len(names) != 1:
            raise FetchError("FTD archive text file missing or ambiguous")
        with z.open(names[0]) as binary:
            reader = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig"), delimiter="|")
            if not {"SETTLEMENT DATE", "CUSIP", "SYMBOL"} <= set(reader.fieldnames or []):
                raise FetchError("FTD column layout changed")
            for row in reader:
                if row.get("SETTLEMENT DATE", "").startswith("Record Count"):
                    continue
                day = _date(row["SETTLEMENT DATE"])
                if day > as_of:
                    continue
                ticker, cusip = canonical(row.get("SYMBOL", "")), row.get("CUSIP", "").strip().upper()
                if not ticker or not re.fullmatch(r"[A-Z0-9*@#]{9}", cusip):
                    continue
                mappings[ticker].add(cusip)
                dates[ticker] = max(dates.get(ticker, ""), str(day))
        reverse = defaultdict(set)
        for ticker, cusips in mappings.items():
            for cusip in cusips:
                reverse[cusip].add(ticker)
        ambiguous = {t for cs in reverse.values() if len(cs) > 1 for t in cs}
        return {
            "symbols": {
                t: {
                    "cusip": next(iter(cs)) if len(cs) == 1 and t not in ambiguous else None,
                    "date": dates[t],
                    "reason": None if len(cs) == 1 and t not in ambiguous else "Ambiguous CUSIP mapping",
                }
                for t, cs in mappings.items()
            },
            "archive_sha256": hashlib.sha256(body).hexdigest(),
        }
    finally:
        z.close()


def stale_after(quarter: date) -> date:
    month = quarter.month + 3
    year = quarter.year + (month > 12)
    month = (month - 1) % 12 + 1
    return date(year, month, calendar.monthrange(year, month)[1]) + timedelta(days=45)


def company(archives: list[dict], mapping: dict, ticker: str, as_of: date) -> dict:
    match = mapping.get("symbols", {}).get(ticker, {})
    base = {
        "mapping_date": mapping.get("file_date"),
        "mapping_url": mapping.get("source"),
        "mapping_settlement_date": match.get("date"),
        "cusip": match.get("cusip"),
    }
    if not match.get("cusip"):
        return {**base, "state": "missing", "reason": match.get("reason") or "no CUSIP mapping"}
    if not archives:
        return {**base, "state": "missing", "reason": "13F quarterly aggregate unavailable"}
    latest = max(archives, key=lambda a: a["report_quarter_end"])
    values = latest["by_cusip"].get(match["cusip"])
    if values is None:
        return {**base, "state": "missing", "reason": "CUSIP not present in the collected 13F quarter"}
    quarter = date.fromisoformat(latest["report_quarter_end"])
    prior_quarter = date(quarter.year, quarter.month - 2, 1) - timedelta(days=1)
    prior_archive = next((a for a in archives if a["report_quarter_end"] == str(prior_quarter)), {})
    prior = prior_archive.get("by_cusip", {}).get(match["cusip"])
    comparable = prior and latest["state"] == "available" and prior_archive.get("state") == "available"
    return {
        **base,
        **values,
        "state": "stale" if as_of > stale_after(quarter) else latest["state"],
        "reason": "Next quarter filing deadline passed without a newer dataset"
        if as_of > stale_after(quarter)
        else latest.get("reason"),
        "report_quarter_end": str(quarter),
        "filing_lag_days": (as_of - quarter).days,
        "stale_after": str(stale_after(quarter)),
        "source": latest.get("source"),
        "note": latest["note"],
        "holder_count_change": values["holder_count"] - prior["holder_count"] if comparable else None,
        "reported_shares_change": values["reported_shares"] - prior["reported_shares"] if comparable else None,
        "change_reason": None if comparable else "Comparable prior-quarter aggregate unavailable",
    }
