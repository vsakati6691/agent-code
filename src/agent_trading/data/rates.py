"""Risk-free rate (3-month T-bill) for crediting interest on idle cash in backtests.

Alpha Vantage publishes a monthly average yield. To avoid look-ahead, the
value for month M is only used from the first trading day of month M+1.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from ..config import Settings
from .alphavantage import AlphaVantageClient, AlphaVantageError

log = logging.getLogger(__name__)
RATES_FILE = "tbill_3m.csv"
TRADING_DAYS = 252


def rates_path(settings: Settings) -> Path:
    return settings.resolve(settings.data.cache_dir) / RATES_FILE


def refresh_rates(settings: Settings, client: AlphaVantageClient, today: date, max_age_days: int = 7) -> bool:
    path = rates_path(settings)
    if path.exists() and (today - date.fromtimestamp(path.stat().st_mtime)).days < max_age_days:
        return False
    try:
        series = client.treasury_yield("3month")
    except AlphaVantageError as exc:
        log.warning("T-bill rate fetch failed: %s", exc)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    series.to_csv(path, date_format="%Y-%m-%d")
    return True


def load_monthly_rates(settings: Settings) -> pd.Series | None:
    path = rates_path(settings)
    if not path.exists():
        return None
    s = pd.read_csv(path, parse_dates=["date"], index_col="date")["yield_pct"]
    return s.sort_index()


def daily_cash_rate(monthly_pct: pd.Series | None, dates: pd.DatetimeIndex) -> pd.Series | None:
    """Per-trading-day simple rate for each date, using the previous month's yield."""
    if monthly_pct is None or monthly_pct.empty:
        return None
    published = monthly_pct.copy()
    published.index = published.index + pd.offsets.MonthBegin(1)  # usable from next month
    aligned = published.reindex(published.index.union(dates)).sort_index().ffill().reindex(dates)
    return (aligned.fillna(0.0) / 100.0 / TRADING_DAYS).clip(lower=0.0)
