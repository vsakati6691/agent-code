"""Completed-session ingestion checks and dated notes for immutable pre-close data."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from ..market_calendar import is_trading_day, previous_trading_day

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


def quote_session_bar(quote, history: pd.DataFrame, as_of: date, tolerance: float) -> tuple[pd.DataFrame | None, str]:
    """The as-of daily bar from a close-verified quote (spec PRICE_BAR_RULE), or why it cannot supply one.

    `quote` must already have passed quote_close_reason. Every value in the bar is the quote's own."""
    bar = {"open": quote.open, "high": quote.high, "low": quote.low, "close": quote.close, "volume": quote.volume}
    if any(v is None or v <= 0 for k, v in bar.items() if k != "volume") or bar["volume"] is None or bar["volume"] < 0:
        return None, "close-only quote available; daily OHLCV history is missing for the as-of session"
    if quote.last_trade is None or quote.last_trade.date() != as_of:
        return None, "end-of-session quote not used: its last trade is not in the as-of session"
    if not bar["low"] - 1e-6 <= bar["close"] <= bar["high"] + 1e-6:
        return None, "end-of-session quote not used: its close lies outside its own high-low range"
    last = history.index[-1].date()
    if last != previous_trading_day(as_of):
        return None, f"end-of-session quote not used: the history file ends {last}, before the preceding session"
    prev = float(history["close"].iloc[-1])
    if quote.change is None or abs(quote.close - quote.change - prev) > tolerance:
        return None, f"end-of-session quote not used: its close less its change does not match the {last} history close"
    index = pd.DatetimeIndex([pd.Timestamp(as_of)], name=history.index.name)
    frame = pd.DataFrame({k: [float(v)] for k, v in bar.items()}, index=index)
    return frame, "as-of bar taken from the end-of-session Cboe quote; the history file had not yet published it"


def correction(snap: dict) -> str:
    if not preclose(snap):
        return ""
    return (
        f"Correction {CORRECTION_DATE}: this snapshot finished before the as-of session closed. "
        "Its stored prices are intraday observations, not verified closes. Price-based scores, market caps, "
        "scenarios and option distances retain those original inputs. Daily closes are shown separately; "
        "the immutable snapshot has not been rewritten."
    )
