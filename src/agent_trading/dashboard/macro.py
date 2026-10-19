"""Dated FRED observations; all requests go through the dashboard HTTP client."""

from __future__ import annotations

import math
from datetime import date

from .http import BudgetExceeded, FetchError

SERIES = ("DGS1MO", "DGS3MO", "DGS2", "DGS10", "FEDFUNDS", "CPIAUCSL", "UNRATE")
OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"
METADATA = "https://api.stlouisfed.org/fred/series"


def parse_series(raw: dict, metadata: dict, series: str, as_of: date) -> dict:
    """Never substitute a missing observation, or use a revision from after the cutoff."""
    if not isinstance(raw, dict) or not isinstance(metadata, dict):
        raise FetchError("FRED response must be an object")
    info = metadata.get("seriess", [])
    if (
        not isinstance(info, list)
        or len(info) != 1
        or not isinstance(info[0], dict)
        or info[0].get("id") != series
        or not info[0].get("last_updated")
    ):
        raise FetchError("FRED series metadata missing or mismatched")
    rows = raw.get("observations")
    if not isinstance(rows, list):
        raise FetchError("FRED observations layout changed")
    values = {}
    for row in rows:
        try:
            day = date.fromisoformat(row["date"])
            vintage = date.fromisoformat(row["realtime_start"])
            if day > as_of or vintage > as_of:
                continue
            if row["value"] == ".":
                continue
            value = float(row["value"])
            if not math.isfinite(value):
                raise ValueError
            if day.isoformat() in values:
                raise ValueError
            values[day.isoformat()] = value
        except (KeyError, TypeError, ValueError):
            raise FetchError("FRED observation contains invalid dates or values") from None
    if not values:
        return {"state": "missing", "reason": "No dated FRED observation available by the as-of date"}
    latest = max(values)
    result = {
        "state": "available",
        "value": values[latest],
        "observation_date": latest,
        "last_updated": info[0]["last_updated"],
        "vintage_date": str(as_of),
        "units": info[0].get("units"),
        "source": f"https://fred.stlouisfed.org/series/{series}",
    }
    if series == "CPIAUCSL":
        prior = str(int(latest[:4]) - 1) + latest[4:]
        result["observations"] = [{"date": d, "value": v} for d, v in sorted(values.items())]
        result["yoy"] = None
        result["yoy_reason"] = "Matching year-earlier CPI observation unavailable or nonpositive"
        if values.get(prior, 0) > 0:
            result.update(yoy=values[latest] / values[prior] - 1, yoy_dates=[prior, latest], yoy_reason=None)
        else:
            result.update(state="partial", reason=result["yoy_reason"])
    return result


def collect(providers, as_of: date) -> dict:
    key = getattr(providers, "fred_key", None)
    result = {"series": {}, "source": "FRED", "as_of": str(as_of)}
    for series in SERIES:
        if not key:
            result["series"][series] = {"state": "missing", "reason": "FRED_API_KEY not configured"}
            continue
        try:
            params = {
                "series_id": series,
                "api_key": key,
                "file_type": "json",
                "realtime_start": str(as_of),
                "realtime_end": str(as_of),
            }
            # Thirteen monthly observations are needed for CPI YoY; daily series need only recent data.
            raw = providers.http.get_json(
                OBSERVATIONS,
                {
                    **params,
                    "sort_order": "desc",
                    "limit": 15 if series == "CPIAUCSL" else 10,
                    "observation_end": str(as_of),
                },
                max_age_hours=12,
            )
            metadata = providers.http.get_json(METADATA, params, max_age_hours=12)
            result["series"][series] = parse_series(raw, metadata, series, as_of)
        except BudgetExceeded:
            result["series"][series] = {"state": "partial", "reason": "FRED request budget spent"}
        except (FetchError, KeyError, TypeError, ValueError):
            # Never echo a response or request parameters, which might contain the API key.
            result["series"][series] = {
                "state": "provider_error",
                "reason": "FRED request or response validation failed",
            }
    states = [r["state"] for r in result["series"].values()]
    result["state"] = (
        "available"
        if all(s == "available" for s in states)
        else ("missing" if not key else "partial" if "available" in states or "partial" in states else "provider_error")
    )
    return result


def rate_input(macro: dict | None) -> dict:
    row = ((macro or {}).get("series") or {}).get("DGS1MO", {})
    if row.get("state") == "available" and isinstance(row.get("value"), (int, float)):
        return {
            "value": row["value"] / 100,
            "date": row["observation_date"],
            "source": row["source"],
            "series": "DGS1MO",
            "reason": None,
        }
    return {
        "value": None,
        "date": None,
        "series": "DGS1MO",
        "reason": row.get("reason", "Dated DGS1MO rate not collected"),
    }
