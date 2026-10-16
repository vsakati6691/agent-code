"""Strict FINRA consolidated equity short-interest file parsing (not short-sale volume)."""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import date

from .http import FetchError
from .providers import canonical

# Verified against the complete public 2026-09-30 download on 2026-10-16.
COLUMNS = (
    "accountingYearMonthNumber",
    "symbolCode",
    "issueName",
    "issuerServicesGroupExchangeCode",
    "marketClassCode",
    "currentShortPositionQuantity",
    "previousShortPositionQuantity",
    "stockSplitFlag",
    "averageDailyVolumeQuantity",
    "daysToCoverQuantity",
    "revisionFlag",
    "changePercent",
    "changePreviousNumber",
    "settlementDate",
)
LABEL = "Short interest as a percentage of XBRL diluted shares outstanding"


def parse_file(text: str, as_of: date) -> dict[str, dict]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter="|")
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise FetchError("FINRA column layout changed; entire dataset rejected")
    result, dates = {}, set()
    for row in reader:
        try:
            if None in row or any(v is None for v in row.values()):
                raise ValueError
            settled = date.fromisoformat(row["settlementDate"])
            if row["accountingYearMonthNumber"] != settled.strftime("%Y%m%d"):
                raise ValueError
            if not re.fullmatch(r"[A-Za-z0-9./-]+", row["symbolCode"]):
                raise ValueError
            ticker = canonical(row["symbolCode"])
            current = int(row["currentShortPositionQuantity"])
            prior = int(row["previousShortPositionQuantity"]) if row["previousShortPositionQuantity"] else None
            if current < 0 or (prior is not None and prior < 0) or ticker in result:
                raise ValueError
            if settled > as_of:
                raise ValueError
            dates.add(settled)
            result[ticker] = {
                "state": "available",
                "settlement_date": str(settled),
                "shares_short": current,
                "previous_report_shares": prior,
                "change_shares": current - prior if prior is not None else None,
                "change_reason": None if prior is not None else "Prior report share count unavailable",
                "stock_split_flag": row["stockSplitFlag"],
                "revision_flag": row["revisionFlag"],
            }
        except (KeyError, TypeError, ValueError):
            raise FetchError(
                "FINRA invalid row, duplicate symbol or settlement date; entire dataset rejected"
            ) from None
    if not result or len(dates) != 1:
        raise FetchError("FINRA empty file or mixed settlement dates; entire dataset rejected")
    return result


def with_denominator(
    row: dict, shares: float | None, shares_date: str | None, average_volume: float | None = None
) -> dict:
    def valid(v):
        return isinstance(v, (float, int)) and math.isfinite(v) and v > 0

    return {
        **row,
        "percent_label": LABEL,
        "diluted_shares": shares if valid(shares) else None,
        "shares_date": shares_date,
        "shares_basis": "Quarterly diluted weighted-average shares; not float",
        "percent_of_diluted_shares": row["shares_short"] / shares if valid(shares) and shares_date else None,
        "percent_reason": None if valid(shares) and shares_date else "Dated XBRL diluted shares unavailable",
        "days_to_cover": row["shares_short"] / average_volume if valid(average_volume) else None,
        "days_to_cover_reason": None
        if valid(average_volume)
        else "Average daily share volume not stored for this company",
    }
