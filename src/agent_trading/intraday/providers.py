"""Read-only Massive adapter and normalized JSON replay. All HTTP uses the existing GET gate."""

import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import ValidationError

from ..dashboard.http import FetchError, HttpClient, ProviderLimits
from ..dashboard.providers import Providers
from ..logging_setup import register_secret
from .calendar import NY, next_session
from .config import Settings
from .models import Bar, Contract, EventRisk, Snapshot

SECTORS = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
    "Communication Services": "XLC",
}


class DataProvider(Protocol):
    def snapshot(self, now: datetime, *, include_stocks: bool = True) -> Snapshot: ...


class FileProvider:
    """An atomic file replaced by a collector; stored timestamps are never refreshed here."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def snapshot(self, now: datetime, *, include_stocks: bool = True) -> Snapshot:
        return Snapshot.model_validate_json(self.path.read_text(encoding="utf-8"))


def stamp(value: int, divisor: int = 1_000_000_000) -> datetime:
    return datetime.fromtimestamp(value / divisor, UTC)


def parse_contract(raw: dict) -> Contract:
    details, quote, under, day = raw["details"], raw["last_quote"], raw["underlying_asset"], raw["day"]
    greek = raw["greeks"]
    feed = "realtime" if quote.get("timeframe") == "REAL-TIME" and under.get("timeframe") == "REAL-TIME" else "delayed"
    return Contract(
        symbol=details["ticker"],
        underlying=under["ticker"],
        right=details["contract_type"].upper(),
        expiry=details["expiration_date"],
        strike=details["strike_price"],
        multiplier=details["shares_per_contract"],
        bid=quote["bid"],
        ask=quote["ask"],
        bid_size=quote["bid_size"],
        ask_size=quote["ask_size"],
        quote_at=stamp(quote["last_updated"]),
        underlying_at=stamp(under["last_updated"]),
        underlying_price=under["price"],
        volume_at=stamp(day["last_updated"]),
        volume=day["volume"],
        open_interest=raw["open_interest"],
        delta=greek["delta"],
        gamma=greek["gamma"],
        theta=greek["theta"],
        vega=greek["vega"],
        iv=raw["implied_volatility"],
        source="Massive option snapshot",
        feed=feed,
    )


class MassiveProvider:
    def __init__(
        self, api_key: str, cfg: Settings, events_path: str | Path | None = None, http: HttpClient | None = None
    ):
        if not api_key or api_key == "replace-me":
            raise ValueError("MASSIVE_API_KEY missing; configure it in .env or use an explicitly labeled fixture")
        register_secret(api_key)
        self.key, self.cfg, self.events_path = api_key, cfg, events_path
        self.http = http or HttpClient(None, "agent-code-intraday-research/1.0", timeout=10)
        self.http.limits["massive"] = ProviderLimits(cfg.provider_interval_seconds, cfg.provider_request_budget)
        self._membership: tuple[datetime, dict[str, str]] | None = None
        self._history: dict[tuple[str, str], list[Bar]] = {}
        self._latest: Snapshot | None = None

    def _pages(self, path: str, params: dict) -> list[dict]:
        url, result, seen = "https://api.massive.com" + path, [], set()
        for _ in range(30):
            split = urlsplit(url)
            if split.scheme != "https" or split.netloc != "api.massive.com" or split.path != path or url in seen:
                raise FetchError("invalid or cyclic Massive pagination")
            seen.add(url)
            raw = self.http.get_json(url, params={**params, "apiKey": self.key}, max_age_hours=0)
            if not isinstance(raw, dict) or raw.get("status") not in {"OK", "DELAYED"}:
                raise FetchError("Massive response unavailable or not entitled")
            result.extend(raw.get("results", []))
            url = raw.get("next_url")
            if not url:
                return result
            params = {}
        raise FetchError("Massive pagination exceeded bound; incomplete data rejected")

    def bars(self, symbol: str, start: str, end: str) -> list[Bar]:
        if not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", symbol):
            raise ValueError("invalid stock symbol")
        raw = self._pages(
            f"/v2/aggs/ticker/{symbol}/range/1/minute/{start}/{end}",
            {"adjusted": "false", "sort": "asc", "limit": 50000},
        )
        # Unadjusted prices keep historical point-in-time values; split sessions need fresh baselines.
        return [
            Bar(
                end=stamp(r["t"], 1000) + timedelta(minutes=1),
                open=r["o"],
                high=r["h"],
                low=r["l"],
                close=r["c"],
                volume=r["v"],
                vwap=r["vw"],
            )
            for r in raw
        ]

    def chain(self, symbol: str, now: datetime) -> tuple[list[Contract], int]:
        rows = self._pages(
            f"/v3/snapshot/options/{symbol}",
            {"expiration_date": next_session(now.astimezone(NY).date()).isoformat(), "limit": 250},
        )
        contracts, invalid = [], 0
        for row in rows:
            try:
                contracts.append(parse_contract(row))
            except (KeyError, TypeError, ValueError, OverflowError):
                invalid += 1
        return contracts, invalid

    def snapshot(self, now: datetime, *, include_stocks: bool = True) -> Snapshot:
        self.http.deadline = time.monotonic() + self.cfg.scan_deadline_seconds
        self.http.used.clear()
        problems, bars, contracts = [], {}, []
        day = now.astimezone(NY).date()
        if self._membership is None or self._membership[0].astimezone(NY).date() != day:
            table = Providers(self.http).sp500()
            self._membership = (now, {symbol: SECTORS.get(row.sector, "UNKNOWN") for symbol, row in table.iterrows()})
        membership_at, universe = self._membership
        events = {}
        if self.events_path:
            raw = json.loads(Path(self.events_path).read_text(encoding="utf-8"))
            events = {k: EventRisk.model_validate(v) for k, v in raw.items()}
        if include_stocks:
            for symbol in sorted({"SPY"} | set(universe.values()) | set(universe)):
                try:
                    key = (symbol, day.isoformat())
                    if key not in self._history:
                        start = day - timedelta(days=self.cfg.rvol_sessions * 3 + 10)
                        self._history[key] = self.bars(symbol, start.isoformat(), (day - timedelta(days=1)).isoformat())
                    bars[symbol] = self._history[key] + self.bars(symbol, day.isoformat(), day.isoformat())
                except (FetchError, ValueError, KeyError, TypeError):
                    problems.append(
                        f"{symbol}: stock collection failed or deadline exceeded; remaining coverage unavailable"
                    )
                    break
        elif self._latest:
            bars = self._latest.bars
        result = Snapshot(
            observed_at=now,
            membership_at=membership_at,
            membership_source="Wikipedia S&P 500 via existing provider (current list only)",
            universe=universe,
            bars=bars,
            events=events,
            contracts=contracts,
            feed="realtime",
            source="Massive (timestamps/entitlements checked; never inferred from receipt time)",
            problems=problems,
        )
        self._latest = result
        return result

    def enrich(self, snap: Snapshot, symbols: list[str], now: datetime) -> Snapshot:
        self.http.deadline = time.monotonic() + self.cfg.scan_deadline_seconds
        contracts, problems = [], list(snap.problems)
        for symbol in sorted(set(symbols)):
            try:
                rows, invalid = self.chain(symbol, now)
                contracts.extend(rows)
                if invalid:
                    problems.append(f"{symbol}: {invalid} contracts missing required quote/Greek data")
            except (FetchError, ValueError, KeyError, TypeError, ValidationError):
                problems.append(f"{symbol}: options unavailable, request budget spent, or plan not entitled")
                break  # no provider-error retry loop
        return snap.model_copy(update={"contracts": contracts, "problems": problems})
