"""Cash dividends and total-return price adjustment.

Robinhood bars are split-adjusted only (price return). For total-return
research (GTAA's bond and REIT ETFs pay most of their return as income) the
OHLC series is back-adjusted: on each ex-date, all earlier prices are scaled by
(1 - dividend / previous close), the standard total-return adjustment that
assumes dividends are reinvested at the ex-date close.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..config import Settings
from .alphavantage import AlphaVantageClient, AlphaVantageError

log = logging.getLogger(__name__)
DIV_DIR = "dividends"


def _path(settings: Settings, symbol: str) -> Path:
    return settings.resolve(settings.data.cache_dir) / DIV_DIR / f"{symbol.upper()}.csv"


def save_dividends(settings: Settings, symbol: str, divs: pd.Series) -> Path:
    p = _path(settings, symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    divs.to_csv(p, date_format="%Y-%m-%d")
    return p


def load_dividends(settings: Settings, symbol: str) -> pd.Series | None:
    p = _path(settings, symbol)
    if not p.exists():
        return None
    s = pd.read_csv(p, parse_dates=["ex_date"], index_col="ex_date")["amount"]
    return s.sort_index()


def import_dividends_file(settings: Settings, symbol: str, path: Path) -> pd.Series:
    """Import an Alpha Vantage DIVIDENDS payload (JSON) or a CSV with ex_date,amount."""
    import json

    from .alphavantage import parse_dividends_json

    text = Path(path).read_text(encoding="utf-8-sig")  # tolerate a byte-order mark (Windows editors)
    if text.lstrip().startswith("{"):
        s = parse_dividends_json(json.loads(text), symbol)
    else:
        df = pd.read_csv(path, parse_dates=["ex_date"], encoding="utf-8-sig")
        s = pd.Series(df["amount"].astype(float).values, index=df["ex_date"], name="amount").sort_index()
        s.index.name = "ex_date"
    if (s < 0).any():
        raise ValueError(f"{symbol}: negative dividend amounts")
    save_dividends(settings, symbol, s)
    return s


def fetch_dividends(settings: Settings, client: AlphaVantageClient, symbols: list[str]) -> dict[str, str]:
    status = {}
    for sym in symbols:
        try:
            s = client.dividends(sym)
        except AlphaVantageError as exc:
            status[sym] = f"failed: {exc}"
            log.warning("Dividend fetch failed: %s", exc)
            continue
        save_dividends(settings, sym, s)
        status[sym] = f"{len(s)} dividends"
    return status


def total_return_bars(df: pd.DataFrame, divs: pd.Series | None) -> pd.DataFrame:
    """Back-adjust OHLC for cash dividends (volume unchanged). No dividends = unchanged copy."""
    out = df.copy()
    if divs is None or divs.empty:
        return out
    close = df["close"]
    factor = pd.Series(1.0, index=df.index)
    for ex, amount in divs.items():
        prior = close.loc[:ex - pd.Timedelta(days=1)]
        if prior.empty or amount <= 0:
            continue
        f = 1.0 - amount / float(prior.iloc[-1])
        if not 0.5 < f < 1.0:  # implausible (>50% of price): skip rather than corrupt the series
            continue
        factor.loc[factor.index < ex] *= f
    for col in ("open", "high", "low", "close"):
        out[col] = df[col] * factor
    return out
