"""Dated curated ETF inputs and strictly matched public SEC fund filings."""

import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

from . import spec
from .http import BudgetExceeded, FetchError

CONFIG = Path(__file__).resolve().parents[3] / "config" / "etf_exposure.json"
LABEL = "owner-supplied, unverified"


def config_hash(raw: dict) -> str:
    return hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load(path: Path = CONFIG) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if path == CONFIG and config_hash(raw) != spec.ETF_INPUTS_SHA256:
        raise ValueError("ETF inputs changed without registering their hash under a new methodology version")
    known = {rule[0] for rule in spec.ETF_EXPOSURE_RULES}
    for ticker, row in raw.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9.]{0,9}", ticker):
            raise ValueError("Invalid ETF ticker")
        date.fromisoformat(row["as_of"])
        date.fromisoformat(row["inception_date"])
        if row["exposure_class"] not in known or row["label"] != LABEL:
            raise ValueError("Unknown ETF exposure or verification label")
        fee = row["expense_ratio"]
        if not isinstance(fee, (int, float)) or not math.isfinite(fee) or not 0 <= fee < 1:
            raise ValueError("Invalid ETF expense ratio")
        if not row["source_url"].startswith("https://") or not row["issuer"] or not row["index_tracked"]:
            raise ValueError("ETF metadata needs issuer, index and HTTPS source")
    return raw


def metadata(ticker: str, as_of: date) -> dict | None:
    row = load().get(ticker)
    if not row or date.fromisoformat(row["as_of"]) > as_of:
        return None
    inception = date.fromisoformat(row["inception_date"])
    if inception > as_of:
        return None
    anniversary = (
        inception.replace(year=inception.year + 1, day=min(inception.day, 28))
        if inception.month == 2 and inception.day == 29
        else inception.replace(year=inception.year + 1)
    )
    return {**row, "launched_under_12_months": as_of < anniversary}


def _text(root, tag: str) -> str:
    return next((str(e.text or "").strip() for e in root.iter() if e.tag.rsplit("}", 1)[-1].lower() == tag.lower()), "")


def parse_filing(text: str, expected: dict, form: str, as_of: date) -> dict:
    """Accept structured N-PORT only for the exact series or fund name; never infer a fee from unrelated numbers."""
    if len(text) > 5_000_000 or "<!ENTITY" in text.upper() or "<!DOCTYPE" in text.upper():
        raise ValueError("Unsupported SEC XML document")
    root = ElementTree.fromstring(text)
    series = _text(root, "seriesId")
    name = _text(root, "seriesName") or _text(root, "fundName")
    normalize = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    if expected.get("sec_series_id"):
        if series != expected["sec_series_id"]:
            raise ValueError("SEC series does not match the ETF")
    elif normalize(name) != normalize(expected["fund_name"]):
        raise ValueError("SEC fund name does not match the ETF")
    reported = _text(root, "repPdDate") or _text(root, "reportDate")
    if not reported or date.fromisoformat(reported) > as_of:
        raise ValueError("Missing or future SEC reporting date")
    holdings = []
    if form.startswith("NPORT"):
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] != "invstOrSec":
                continue
            try:
                weight = float(_text(node, "pctVal")) / 100
            except ValueError:
                continue
            holding = _text(node, "name")
            if holding and math.isfinite(weight):
                holdings.append({"name": holding, "weight": weight})
    holdings.sort(key=lambda row: row["weight"], reverse=True)
    return {
        "status": "available",
        "form": form,
        "reported_at": reported,
        "series_id": series,
        "fund_name": name,
        "top_holdings": holdings[:5],
        "expense_ratio": None,
        "fee_note": "No standardized annual operating expense ratio extracted from this filing; the dated issuer/prospectus input remains in use.",
    }


def collect_filing(providers, expected: dict, as_of: date) -> dict:
    cik = expected.get("sec_cik")
    if not cik:
        return {"status": "unavailable", "reason": "No verified SEC fund CIK mapped."}
    if providers.http.budget_left("sec") <= 25:
        return {"status": "unavailable", "reason": "SEC request budget reserved for existing earnings checks."}
    recent = providers.submissions(cik).get("filings", {}).get("recent", {})
    rows = list(
        zip(*(recent.get(k, []) for k in ("form", "filingDate", "accessionNumber", "primaryDocument")), strict=False)
    )
    eligible = sorted(
        (r for r in rows if r[0] in ("NPORT-P", "NPORT-P/A", "N-CEN", "N-CEN/A") and r[1] <= as_of.isoformat()),
        key=lambda r: r[1],
        reverse=True,
    )
    for form, filed, accession, document in eligible[:3]:
        # Strip the SEC stylesheet route to obtain the raw XML; refuse arbitrary paths.
        filename = document.rsplit("/", 1)[-1]
        if not re.fullmatch(r"[0-9-]+", accession) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.xml", filename):
            continue
        if providers.http.budget_left("sec") <= 25:
            break
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{filename}"
        try:
            parsed = parse_filing(providers.http.get_text(url, max_age_hours=168), expected, form, as_of)
            return {**parsed, "filed_at": filed, "source_url": url}
        except BudgetExceeded:
            raise
        except (FetchError, ValueError, ElementTree.ParseError):
            continue
    return {
        "status": "unavailable",
        "reason": "No matching dated structured N-PORT/N-CEN among the three latest eligible filings; no holdings or fee inferred.",
    }
