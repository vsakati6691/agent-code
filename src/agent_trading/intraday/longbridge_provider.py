"""Streaming stock collection, observed option books and automatic event screening."""

import json
import re
import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from ..dashboard.http import HttpClient
from ..dashboard.providers import Providers
from .calendar import NY, next_session, session
from .config import Settings
from .longbridge_api import DataUnavailable, LongbridgeAPI, utc
from .models import Bar, Contract, EventRisk, Snapshot
from .providers import SECTORS


def symbol_us(symbol: str) -> str:
    if not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", symbol):
        raise ValueError("invalid US stock symbol")
    return symbol + ".US"


def occ_symbol(symbol: str) -> str:
    match = re.fullmatch(r"([A-Z.]{1,6})(\d{6})([CP])(\d{1,8})\.US", symbol)
    if not match:
        raise ValueError("invalid Longbridge option symbol")
    return f"O:{match[1]}{match[2]}{match[3]}{int(match[4]):08d}"


def vendor_symbol(symbol: str) -> str:
    match = re.fullmatch(r"(?:O:)?([A-Z.]{1,6})(\d{6})([CP])(\d{8})", symbol)
    if not match:
        raise ValueError("invalid normalized option symbol")
    return f"{match[1]}{match[2]}{match[3]}{int(match[4])}.US"


def candle(raw, now: datetime) -> Bar | None:
    end = utc(raw.timestamp) + timedelta(minutes=1)
    s = session(end.astimezone(NY).date())
    if end > now or not s or not s.open < end <= s.close:
        return None  # no partial bars or extended sessions
    if raw.volume <= 0 or raw.turnover <= 0:
        return None  # no invented VWAP for a zero-volume candle
    return Bar(
        end=end,
        open=raw.open,
        high=raw.high,
        low=raw.low,
        close=raw.close,
        volume=raw.volume,
        vwap=Decimal(raw.turnover) / raw.volume,
    )


def previous_sessions(day: date, count: int) -> list[date]:
    result = []
    while len(result) < count:
        day -= timedelta(days=1)
        if session(day):
            result.append(day)
    return sorted(result)


def news_time(value) -> datetime:
    if isinstance(value, datetime):
        return utc(value)
    return datetime.fromtimestamp(int(value), UTC)


def complete_day(bars: list[Bar], day: date) -> bool:
    s = session(day)
    if not s:
        return False
    expected = {s.open + timedelta(minutes=i + 1) for i in range(int((s.close - s.open).total_seconds() / 60))}
    return len(bars) == len(expected) and {b.end for b in bars} == expected


class BarCache:
    """Only complete, unadjusted regular sessions are persisted. Receipt time is irrelevant."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self, symbol: str, day: date) -> list[Bar]:
        symbol_us(symbol)
        try:
            raw = json.loads((self.path / symbol / f"{day}.json").read_text(encoding="utf-8"))
            bars = [Bar.model_validate(b) for b in raw["bars"]]
            if raw["symbol"] != symbol or raw["source"] != "Longbridge unadjusted" or not complete_day(bars, day):
                return []
            return bars
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def save(self, symbol: str, day: date, bars: list[Bar]):
        symbol_us(symbol)
        if not complete_day(bars, day):
            return
        dest = self.path / symbol / f"{day}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_suffix(".tmp")
        temp.write_text(
            json.dumps(
                {"symbol": symbol, "source": "Longbridge unadjusted", "bars": [b.model_dump(mode="json") for b in bars]}
            ),
            encoding="utf-8",
        )
        temp.replace(dest)


class LongbridgeProvider:
    """One persistent collector per service. Snapshot reads never wait for history warm-up."""

    def __init__(
        self,
        cfg: Settings,
        *,
        api=None,
        cache="data/intraday/longbridge-bars",
        clock=lambda: datetime.now(UTC),
        membership_loader=None,
    ):
        self.cfg, self.api, self.clock = cfg, api or LongbridgeAPI(), clock
        self.cache = BarCache(cache)
        self.membership_loader = membership_loader or self._membership
        self._lock, self._stop = threading.RLock(), threading.Event()
        self._thread = None
        self._day = None
        self._membership_at = clock()
        self._universe: dict[str, str] = {}
        self._bars: dict[str, dict[datetime, Bar]] = {}
        self._events: dict[str, EventRisk] = {}
        self._news: dict[str, list[dict]] = {}
        self._calendar: dict[str, list[str]] = {}
        self._calendar_at: datetime | None = None
        self._errors: list[str] = []
        self._progress = "not started"
        self._depth: dict[str, tuple[tuple, datetime]] = {}
        self._depth_path = self.cache.path / "depth-observations.json"
        if self._depth_path.exists():
            try:
                saved = json.loads(self._depth_path.read_text(encoding="utf-8"))
                self._depth = {s: (tuple(v[0]), datetime.fromisoformat(v[1])) for s, v in saved.items()}
                if any(at.tzinfo is None for _, at in self._depth.values()):
                    raise ValueError("naive depth cache")
            except (OSError, ValueError, TypeError, KeyError):
                raise DataUnavailable(
                    "Longbridge depth observation cache is invalid; preserve it for diagnosis"
                ) from None
        self._chains: dict[tuple[str, date], list[str]] = {}
        self._held: list[Contract] = []
        self._options_error: str | None = None
        self.api.on_candle(self._push)

    @staticmethod
    def _membership():
        http = HttpClient(None, "agent-code-intraday/1.0", timeout=10)
        table = Providers(http).sp500()
        return {symbol: SECTORS.get(row.sector, "UNKNOWN") for symbol, row in table.iterrows()}

    def start(self):
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._worker, name="longbridge-market-data", daemon=True)
                self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def set_holdings(self, contracts: list[Contract]):
        self._held = contracts

    def _merge(self, symbol: str, rows):
        parsed = [b for r in rows if (b := candle(r, self.clock())) is not None]
        with self._lock:
            target = self._bars.setdefault(symbol, {})
            target.update({b.end: b for b in parsed})

    def _push(self, symbol, event):
        if not event.is_confirmed or not symbol.endswith(".US"):
            return
        try:
            self._merge(symbol[:-3], [event.candlestick])
        except (ValueError, TypeError, AttributeError):
            with self._lock:
                message = "Longbridge invalid confirmed candle; incomplete coverage blocks entries"
                if message not in self._errors:
                    self._errors.append(message)

    def warmup(self, day: date):
        universe = self.membership_loader()
        if not 480 <= len(universe) <= 520 or "UNKNOWN" in universe.values():
            raise DataUnavailable("S&P 500 membership or sector coverage incomplete")
        with self._lock:
            self._universe, self._membership_at, self._day = universe, self.clock(), day
            self._events, self._calendar_at, self._chains = {}, None, {}
        symbols = sorted({"SPY"} | set(universe.values()) | set(universe))
        days = previous_sessions(day, self.cfg.rvol_sessions)
        sdk = self.api.sdk
        # Subscribe first: the live minute stream continues during historical warm-up.
        for i, symbol in enumerate(symbols):
            if self._stop.is_set():
                return
            self._progress = f"subscribing minute bars {i + 1}/{len(symbols)}"
            for d in days:
                cached = self.cache.load(symbol, d)
                with self._lock:
                    self._bars.setdefault(symbol, {}).update({b.end: b for b in cached})
            self._merge(
                symbol,
                self.api.call(
                    "quote", "subscribe_candlesticks", symbol_us(symbol), sdk.Period.Min_1, sdk.TradeSessions.Intraday
                ),
            )
        for i, symbol in enumerate(symbols):
            for offset in range(0, len(days), 2):
                if self._stop.is_set():
                    return
                pair = days[offset : offset + 2]
                with self._lock:
                    have = list(self._bars[symbol].values())
                if any(not complete_day([b for b in have if b.end.astimezone(NY).date() == d], d) for d in pair):
                    self._progress = f"warming RVOL history {i + 1}/{len(symbols)}"
                    # Two sessions <= 780 bars: never silently truncate the API's 1,000-bar cap.
                    self._merge(
                        symbol,
                        self.api.call(
                            "quote",
                            "history_candlesticks_by_date",
                            symbol_us(symbol),
                            sdk.Period.Min_1,
                            sdk.AdjustType.NoAdjust,
                            pair[0],
                            pair[-1],
                            sdk.TradeSessions.Intraday,
                        ),
                    )
                with self._lock:
                    have = list(self._bars[symbol].values())
                for d in pair:
                    self.cache.save(symbol, d, [b for b in have if b.end.astimezone(NY).date() == d])
            with self._lock:
                self._bars[symbol] = {
                    at: b for at, b in self._bars[symbol].items() if at.astimezone(NY).date() >= days[0]
                }
        self._progress = "stock history warm; collecting event coverage"

    def _calendar_rows(self, category, day):
        start, end = day.isoformat(), day.isoformat()
        seen, result, expected, returned = set(), [], {}, {}
        for offset in range(0, 2000, 100):
            page = self.api.call("calendar", "finance_calendar", category, start, end, "US", offset)
            batch = []
            for group in page.list:
                key = getattr(group, "date", start)
                if group.count is not None:
                    expected[key] = max(expected.get(key, 0), group.count)
                returned[key] = returned.get(key, 0) + len(group.infos)
                batch.extend(group.infos)
            fingerprint = tuple((getattr(r, "id", ""), r.symbol, r.content, getattr(r, "datetime", "")) for r in batch)
            if fingerprint and fingerprint in seen:
                raise DataUnavailable("Longbridge calendar pagination repeated")
            seen.add(fingerprint)
            result.extend(batch)
            cursor = page.next_date
            more = bool(cursor and date.fromisoformat(cursor) <= day)
            if len(batch) < 100 and not more:
                if any(returned.get(k, 0) < count for k, count in expected.items()):
                    raise DataUnavailable("Longbridge calendar page is incomplete")
                return result
            if not batch:
                raise DataUnavailable("Longbridge calendar cursor points to missing events")
        raise DataUnavailable("Longbridge calendar pagination limit reached")

    def refresh_calendar(self, now):
        day = now.astimezone(NY).date()
        risks: dict[str, list[str]] = {}
        cat = self.api.sdk.CalendarCategory
        for category in (cat.Report, cat.Dividend, cat.Split, cat.MacroData):
            for row in self._calendar_rows(category, day):
                if category == cat.MacroData:
                    if row.star >= 2 or row.star == 0:
                        risks.setdefault("MARKET", []).append(row.content)
                elif row.symbol.endswith(".US"):
                    risks.setdefault(row.symbol[:-3], []).append(row.content or str(category))
                else:
                    raise DataUnavailable("Calendar event has no recognized US symbol")
        with self._lock:
            self._calendar, self._calendar_at = risks, now
            self._events = {}  # a refreshed risk calendar invalidates all previous clearances

    def refresh_event(self, symbol, now):
        raw = self.api.call("content", "news", "SPY.US" if symbol == "MARKET" else symbol_us(symbol))
        headlines = []
        risk_words = re.compile(
            r"earnings|guidance|bankrupt|merger|acquisition|investigation|offering|halt|recall|fraud|lawsuit|inflation|payroll|fed\b|fomc|war\b|tariff",
            re.I,
        )
        for item in raw:
            at = news_time(item.published_at)
            if at > now:
                raise DataUnavailable("Future news timestamp rejected")
            if now - at <= timedelta(hours=24):
                headlines.append(
                    {
                        "title": item.title,
                        "published_at": at.isoformat(),
                        "source": "Longbridge news (unverified headline)",
                        "risk_flag": bool(risk_words.search(item.title)),
                    }
                )
        with self._lock:
            calendar_at = self._calendar_at
            if not calendar_at or now - calendar_at > timedelta(minutes=15):
                raise DataUnavailable("Event calendar is stale")
            reasons = self._calendar.get(symbol, []) + [h["title"] for h in headlines if h["risk_flag"]]
            self._events[symbol] = EventRisk(
                observed_at=now,
                valid_until=min(now + timedelta(minutes=15), calendar_at + timedelta(minutes=15)),
                status="blocked" if reasons else "clear",
                source="Longbridge US calendar + recent headlines",
                summary="; ".join(reasons)
                if reasons
                else "No scheduled event or keyword risk found in available coverage; not a guarantee of no news",
            )
            self._news[symbol] = headlines

    def _worker(self):
        try:
            while not self._stop.is_set():
                now = self.clock()
                day = now.astimezone(NY).date()
                if not session(day):
                    self._stop.wait(30)
                    continue
                if self._day != day:
                    self.warmup(day)
                if not self._calendar_at or now - self._calendar_at >= timedelta(minutes=10):
                    self.refresh_calendar(now)
                for symbol in ["MARKET", *sorted(self._universe)]:
                    if self._stop.is_set():
                        return
                    now = self.clock()
                    if not self._calendar_at or now - self._calendar_at >= timedelta(minutes=10):
                        self.refresh_calendar(now)
                    event = self._events.get(symbol)
                    if not event or event.valid_until - now < timedelta(minutes=5):
                        self.refresh_event(symbol, now)
                self._progress = "streaming stock bars; event coverage refreshed automatically"
                self._stop.wait(10)
        except Exception as exc:
            message = (
                str(exc)
                if isinstance(exc, DataUnavailable)
                else "Longbridge collector failed; inspect permissions/data and restart"
            )
            with self._lock:
                self._errors.append(message)
                self._progress = "collector stopped after failure; no automatic provider-error retries"

    def status(self):
        with self._lock:
            return {
                "provider": "Longbridge",
                "progress": self._progress,
                "constituents": len(self._universe),
                "bar_symbols": len(self._bars),
                "event_symbols": len(self._events),
                "problems": self._errors + ([self._options_error] if self._options_error else []),
            }

    def research_context(self):
        with self._lock:
            return {
                "headlines": dict(self._news),
                "events": {s: e.model_dump(mode="json") for s, e in self._events.items()},
            }

    def check_access(self, now):
        """A small read-only probe; never spends a full-universe history quota."""
        result = {"provider": "Longbridge", "execution": "local_simulator", "credentials": "configured"}
        self.api.call("quote", "quote", ["SPY.US"])
        result["stock_quote"] = "accessible"
        dates = self.api.call("quote", "option_chain_expiry_date_list", "AAPL.US")
        if dates:
            listed = self._listed("AAPL", dates[0])
            if listed:
                self.api.call("quote", "option_quote", listed[:1])
                self.api.call("quote", "depth", listed[0])
                result["option_quote_and_depth"] = "accessible; freshness/liquidity still checked at each decision"
        if "option_quote_and_depth" not in result:
            raise DataUnavailable("No listed AAPL contracts available for access probe")
        self.refresh_calendar(now)
        self.refresh_event("MARKET", now)
        result["calendar_and_news"] = "accessible"
        result["full_universe"] = "not verified; warm-up requires quota for every constituent plus SPY and sector ETFs"
        return result

    def snapshot(self, now, *, include_stocks=True):
        self.start()
        with self._lock:
            problems = self._errors + ([self._options_error] if self._options_error else [])
            return Snapshot(
                observed_at=now,
                membership_at=self._membership_at,
                membership_source="Wikipedia current S&P 500 list; observed, not historical membership",
                universe=dict(self._universe),
                bars={s: sorted(rows.values(), key=lambda b: b.end) for s, rows in self._bars.items()},
                events=dict(self._events),
                source="Longbridge OpenAPI; unadjusted confirmed minute bars",
                feed="realtime",
                problems=list(problems),
            )

    def _listed(self, symbol, expiry):
        key = (symbol, expiry)
        if key not in self._chains:
            available = self.api.call("quote", "option_chain_expiry_date_list", symbol_us(symbol))
            if expiry not in available:
                self._chains[key] = []
            else:
                rows = self.api.call("quote", "option_chain_info_by_date", symbol_us(symbol), expiry)
                self._chains[key] = [s for r in rows if r.standard for s in (r.call_symbol, r.put_symbol) if s]
        return self._chains[key]

    def _contracts(self, symbols, now, deadline, held):
        sdk = self.api.sdk
        contracts = []
        for offset in range(0, len(symbols), 500):
            if time.monotonic() >= deadline:
                break
            batch = symbols[offset : offset + 500]
            quotes = self.api.call("quote", "option_quote", batch)
            greeks = {
                g.symbol: g
                for g in self.api.call(
                    "quote",
                    "calc_indexes",
                    batch,
                    [sdk.CalcIndex.Delta, sdk.CalcIndex.Gamma, sdk.CalcIndex.Theta, sdk.CalcIndex.Vega],
                )
            }
            eligible = []
            for q in quotes:
                g = greeks.get(q.symbol)
                if (
                    q.symbol not in batch
                    or g is None
                    or any(getattr(g, k) is None for k in ("delta", "gamma", "theta", "vega"))
                ):
                    continue
                if q.trade_status != sdk.TradeStatus.Normal or q.contract_multiplier != 100 or q.contract_size != 100:
                    continue
                if q.symbol not in held and (
                    not self.cfg.minimum_delta <= abs(float(g.delta)) <= self.cfg.maximum_delta
                    or q.open_interest < self.cfg.minimum_oi
                    or q.volume < self.cfg.minimum_option_volume
                ):
                    continue
                eligible.append((q, g))
            eligible.sort(key=lambda pair: (pair[0].symbol not in held, abs(abs(float(pair[1].delta)) - 0.5)))
            underlyings = sorted({symbol_us(q.underlying_symbol.removesuffix(".US")) for q, _ in eligible})
            if not underlyings:
                continue
            underlying = {q.symbol: q for q in self.api.call("quote", "quote", underlyings)}
            for q, g in eligible:
                if time.monotonic() >= deadline:
                    break
                u = underlying.get(symbol_us(q.underlying_symbol.removesuffix(".US")))
                if u is None or u.trade_status != sdk.TradeStatus.Normal:
                    continue
                book = self.api.call("quote", "depth", q.symbol)
                received = self.clock()
                bids, asks = [b for b in book.bids if b.position == 1], [a for a in book.asks if a.position == 1]
                if len(bids) != 1 or len(asks) != 1 or bids[0].price is None or asks[0].price is None:
                    continue
                bid, ask = bids[0], asks[0]
                fingerprint = (str(bid.price), str(ask.price), bid.volume, ask.volume)
                prior = self._depth.get(q.symbol)
                # No exchange timestamp is supplied for depth. Preserve observation
                # time for an unchanged book; polling cannot create new fill liquidity.
                if prior is None or prior[0] != fingerprint:
                    self._depth[q.symbol] = (fingerprint, received)
                    self._depth_path.parent.mkdir(parents=True, exist_ok=True)
                    temp = self._depth_path.with_suffix(".tmp")
                    temp.write_text(
                        json.dumps({s: [list(v[0]), v[1].isoformat()] for s, v in self._depth.items()}),
                        encoding="utf-8",
                    )
                    temp.replace(self._depth_path)
                observed = self._depth[q.symbol][1]
                try:
                    contracts.append(
                        Contract(
                            symbol=occ_symbol(q.symbol),
                            underlying=q.underlying_symbol.removesuffix(".US"),
                            right="CALL" if q.direction == sdk.OptionDirection.Call else "PUT",
                            expiry=q.expiry_date,
                            strike=q.strike_price,
                            multiplier=int(q.contract_multiplier),
                            bid=bid.price,
                            ask=ask.price,
                            bid_size=bid.volume,
                            ask_size=ask.volume,
                            quote_at=observed,
                            quote_time_basis="changed_depth_receipt",
                            underlying_at=utc(u.timestamp),
                            underlying_price=u.last_done,
                            volume_at=utc(q.timestamp),
                            volume=q.volume,
                            open_interest=q.open_interest,
                            delta=g.delta,
                            gamma=g.gamma,
                            theta=g.theta,
                            vega=g.vega,
                            iv=q.implied_volatility,
                            greek_units="longbridge_raw",
                            source="Longbridge OPRA; depth receipt time (exchange depth timestamp unavailable)",
                            feed="realtime",
                        )
                    )
                except (ValueError, TypeError):
                    continue
        return contracts

    def enrich(self, snap, symbols, now):
        if self._options_error:
            return snap.model_copy(update={"problems": snap.problems + [self._options_error]})
        deadline = time.monotonic() + self.cfg.scan_deadline_seconds
        contracts = []
        try:
            held = {vendor_symbol(c.symbol) for c in self._held}
            # Exact held contracts are refreshed even when their expiry is no longer next-session.
            if held:
                contracts.extend(self._contracts(sorted(held), now, deadline, held))
            for symbol in dict.fromkeys(symbols):
                if time.monotonic() >= deadline:
                    break
                listed = [s for s in self._listed(symbol, next_session(now.astimezone(NY).date())) if s not in held]
                contracts.extend(self._contracts(listed, now, deadline, held))
        except Exception as exc:
            self._options_error = (
                str(exc)
                if isinstance(exc, DataUnavailable)
                else "Longbridge options collection failed; fix data access and restart"
            )
        return snap.model_copy(
            update={
                "contracts": contracts,
                "problems": snap.problems + ([self._options_error] if self._options_error else []),
            }
        )
