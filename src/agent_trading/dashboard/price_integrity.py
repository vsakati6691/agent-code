"""Completed-session ingestion checks and dated notes for immutable pre-close data."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from ..market_calendar import is_trading_day

ET = ZoneInfo("America/New_York")
CORRECTION_DATE = "2026-10-16"
# This published run finished at 12:52 ET, before its claimed as-of close.
PRE_CLOSE_RUN = "2026-10-15T14:37:46+00:00"
SHORT_NOTE = f"Intraday input · correction {CORRECTION_DATE}"


def timestamp(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed).astimezone(ET)


def preclose(snap: dict) -> bool:
    finished = timestamp(snap.get("run_finished"))
    return bool(finished and finished.date().isoformat() == snap.get("as_of") and finished.hour < 16)


def record_note(record: dict) -> str:
    quoted = timestamp(record.get("quote_time_utc"))
    affected = record.get("data_timestamp") == PRE_CLOSE_RUN or (
        quoted
        and is_trading_day(quoted.date())
        and 9 <= quoted.hour < 16
        and quoted.date().isoformat() == record.get("quote_date_ny")
        and str(record.get("underlying_last_trade", ""))[:10] == record.get("quote_date_ny")
    )
    return SHORT_NOTE if affected else ""


def quote_close_reason(quote, as_of: date) -> str | None:
    observed = timestamp(quote.fetched)
    if observed is None:
        return "quote snapshot timestamp unavailable; closing price not verified"
    if observed.date() < as_of or (observed.date() == as_of and observed.hour < 16):
        return "quote snapshot predates the as-of close"
    return None


def correction(snap: dict) -> str:
    if not preclose(snap):
        return ""
    return (
        f"Correction {CORRECTION_DATE}: this snapshot finished before the as-of session closed. "
        "Its stored prices are intraday observations, not verified closes. Price-based scores, market caps, "
        "scenarios and option distances retain those original inputs. Daily closes are shown separately; "
        "the immutable snapshot has not been rewritten."
    )
