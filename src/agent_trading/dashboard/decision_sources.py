"""Current estimates and attributable 10-K excerpts; no invented company narratives."""

from __future__ import annotations

import calendar
import re
from datetime import date
from html.parser import HTMLParser

from .decisions import field, finite


def number(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if finite(v) else None


def estimates(raw: dict, observed_at: str) -> dict:
    keys = {"forward_pe": "ForwardPE", "peg": "PEGRatio", "analyst_target": "AnalystTargetPrice"}
    out = {
        key: field(
            v if v is not None and v > 0 else None,
            f"Alpha Vantage {source} missing or nonpositive",
            as_of=observed_at,
            source="Alpha Vantage OVERVIEW; current estimate, not point-in-time history",
        )
        for key, source in keys.items()
        for v in [number(raw.get(source))]
    }
    ratings = [number(raw.get("AnalystRating" + name)) for name in ("StrongBuy", "Buy", "Hold", "Sell", "StrongSell")]
    valid = all(v is not None and v >= 0 and v.is_integer() for v in ratings)
    out["rating_count"] = field(
        int(sum(ratings)) if valid else None,
        "All five analyst rating category counts required",
        as_of=observed_at,
        source="Alpha Vantage OVERVIEW",
    )
    return out


def six_months_before(d: date) -> date:
    month = d.year * 12 + d.month - 1 - 6
    year, m = divmod(month, 12)
    return date(year, m + 1, min(d.day, calendar.monthrange(year, m + 1)[1]))


def insider_net(raw: dict, as_of: date, observed_at: str) -> dict:
    rows = raw.get("data")
    meta = {
        "as_of": observed_at,
        "source": "Alpha Vantage INSIDER_TRANSACTIONS",
        "period": f"{six_months_before(as_of)} to {as_of}",
    }
    if not isinstance(rows, list) or not rows:
        return field(reason="No insider transactions returned; absence is not evidence of zero buying", **meta)
    selected = []
    for row in rows:
        try:
            d = date.fromisoformat(str(row.get("transaction_date")))
        except ValueError:
            return field(reason="Insider response contains an undated transaction", **meta)
        if six_months_before(as_of) <= d <= as_of:
            selected.append(row)
    if not selected:
        return field(reason="No transactions in the six-month window; completeness unverified", **meta)
    # A/D also includes grants, gifts, vesting and exercises. Never call these purchases/sales.
    if any(not r.get("transaction_code") for r in selected):
        return field(
            reason="Provider supplies acquisitions/disposals without Form 4 P/S transaction codes; market buying/selling cannot be distinguished",
            **meta,
        )
    net = 0.0
    for r in selected:
        code = str(r["transaction_code"]).upper()
        if code not in ("P", "S"):
            continue
        shares = number(r.get("shares"))
        if shares is None or shares < 0:
            return field(reason="Purchase/sale share count missing or invalid", **meta)
        net += shares * (1 if code == "P" else -1)
    return field(net, **meta)


class FilingText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "ix:hidden"):
            self.hidden += 1
        if tag in ("p", "div", "br", "tr", "h1", "h2", "h3") and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "ix:hidden") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def filing_excerpts(markup: str, url: str, filed: str) -> dict:
    parser = FilingText()
    parser.feed(markup)
    text = re.sub(r"\s+", " ", " ".join(parser.parts))
    headers = list(
        re.finditer(
            r"\bITEM\s+(1A|1B|1C|1|2)\s*[.\-:]?\s+(BUSINESS|RISK\s+FACTORS|UNRESOLVED|CYBERSECURITY|PROPERTIES)",
            text,
            re.I,
        )
    )
    sections = {"1": [], "1A": []}
    for i, match in enumerate(headers):
        key = match[1].upper()
        if key in sections:
            chunk = text[match.end() : headers[i + 1].start() if i + 1 < len(headers) else len(text)]
            if len(chunk) >= 300:
                sections[key].append(chunk)
    business = max(sections["1"], key=len, default="")
    risks = max(sections["1A"], key=len, default="")

    def sentence(section, pattern):
        candidates = re.split(r"(?<=[.!?])\s+", section)
        result = next(
            (s.strip() for s in candidates if 60 <= len(s.strip()) <= 700 and re.search(pattern, s, re.I)), None
        )
        return result[:397] + "…" if result and len(result) > 400 else result

    return {
        "description": sentence(business, r"\b(we|our|company|provides?|develops?|designs?|manufactures?)\b"),
        "growth": sentence(business, r"\b(grow\w*|expand\w*|demand|opportunit\w*)\b"),
        "risk": sentence(risks, r"\b(risk\w*|adverse\w*|could|may|depend\w*|compet\w*)\b"),
        "reason": "No reliable matching sentence in the identified 10-K section",
        "url": url,
        "filed": filed,
        "source": "SEC 10-K, issuer statements; excerpts, not independent forecasts",
    }


def latest_10k(submissions: dict, cik: int, as_of: date) -> tuple[str, str] | None:
    r = (submissions.get("filings") or {}).get("recent") or {}
    rows = zip(
        r.get("form", []),
        r.get("filingDate", []),
        r.get("accessionNumber", []),
        r.get("primaryDocument", []),
        strict=False,
    )
    eligible = [
        (filed, accession, doc)
        for form, filed, accession, doc in rows
        if form == "10-K"
        and filed <= as_of.isoformat()
        and re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession)
        and re.fullmatch(r"[\w.-]+\.html?", doc, re.I)
        and ".." not in doc
    ]
    if not eligible:
        return None
    filed, accession, doc = max(eligible)
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{doc}", filed
