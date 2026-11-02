"""Read-only Longbridge SDK boundary. No trading or account contexts are constructed."""

import os
import threading
import time
from datetime import UTC, date, datetime
from types import SimpleNamespace
from urllib.parse import urlencode

from ..logging_setup import register_secret


class DataUnavailable(RuntimeError):
    """A deliberately public diagnostic, never the SDK's raw exception text."""


class CalendarReader:
    """Fixed official GET route; SDK 4.5 lacks the calendar's count/offset arguments."""

    def __init__(self, client, sdk):
        self.client, self.sdk = client, sdk

    def finance_calendar(self, category, start, end, market, offset=0):
        categories = [
            (self.sdk.CalendarCategory.Report, "report"),
            (self.sdk.CalendarCategory.Dividend, "dividend"),
            (self.sdk.CalendarCategory.Split, "split"),
            (self.sdk.CalendarCategory.MacroData, "macrodata"),
        ]
        name = next((name for value, name in categories if category == value), None)
        if name is None or market != "US" or not 0 <= offset < 2000:
            raise DataUnavailable("Invalid calendar query")
        params = {
            "date": date.fromisoformat(start).isoformat(),
            "date_end": date.fromisoformat(end).isoformat(),
            "types[]": name,
            "markets[]": "US",
            "count": 100,
            "offset": offset,
            "next": "later",
        }
        raw = self.client.request("GET", "/v1/quote/finance_calendar?" + urlencode(params))
        # The SDK HttpClient unwraps the successful response's data object.
        if not isinstance(raw, dict) or not isinstance(raw.get("list"), list):
            raise DataUnavailable("Calendar response has no event list")
        groups = []
        for group in raw["list"]:
            if not isinstance(group.get("infos"), list):
                raise DataUnavailable("Calendar response has no event details")
            infos = []
            for row in group["infos"]:
                symbol = row.get("symbol", "")
                star = row.get("star", 0)
                if not isinstance(symbol, str) or not isinstance(star, int):
                    raise DataUnavailable("Calendar event fields are missing")
                infos.append(
                    SimpleNamespace(
                        symbol=symbol,
                        star=star,
                        content=row.get("content", ""),
                        id=row.get("id", ""),
                        datetime=row.get("datetime", ""),
                    )
                )
            groups.append(SimpleNamespace(date=group["date"], count=group.get("count"), infos=infos))
        return SimpleNamespace(list=groups, next_date=raw.get("next_date") or "")


def utc(value: datetime) -> datetime:
    # Longbridge documents SDK timestamps as UTC; some SDK versions return naive UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class LongbridgeAPI:
    """Restrict the SDK to an explicit set of market-data reads and subscriptions.

    Errors latch per context until an explicit process restart. In particular, a
    denied entitlement is never retried in the service's five-second loop.
    """

    READS = {
        "quote": {
            "quote",
            "option_quote",
            "depth",
            "calc_indexes",
            "option_chain_expiry_date_list",
            "option_chain_info_by_date",
            "history_candlesticks_by_date",
            "subscribe_candlesticks",
            "quote_package_details",
        },
        "calendar": {"finance_calendar"},
        "content": {"news"},
    }

    def __init__(self):
        import longbridge.openapi as sdk

        self.sdk = sdk
        names = ("APP_KEY", "APP_SECRET", "ACCESS_TOKEN")
        values = [os.getenv(f"LONGBRIDGE_{n}") or os.getenv(f"LONGPORT_{n}") for n in names]
        if not all(v and v != "replace-me" for v in values):
            raise DataUnavailable("Longbridge credentials missing: configure the three LONGBRIDGE_* values in .env")
        for value in values:
            register_secret(value)
        # Do not allow environment redirects or SDK diagnostic files to leak credentials.
        if any(
            os.getenv(f"{prefix}_{suffix}")
            for prefix in ("LONGPORT", "LONGBRIDGE")
            for suffix in ("HTTP_URL", "QUOTE_WS_URL", "TRADE_WS_URL", "LOG_PATH")
        ):
            raise DataUnavailable(
                "Remove Longbridge endpoint/log-path overrides; only fixed official data endpoints are allowed"
            )
        try:
            config = sdk.Config.from_apikey(
                *values,
                http_url="https://openapi.longbridge.com",
                quote_ws_url="wss://openapi-quote.longbridge.com/v2",
                enable_print_quote_packages=False,
                push_candlestick_mode=sdk.PushCandlestickMode.Confirmed,
            )
            self.contexts = {
                "quote": sdk.QuoteContext(config),
                "calendar": CalendarReader(
                    sdk.HttpClient.from_apikey(*values, http_url="https://openapi.longbridge.com"), sdk
                ),
                "content": sdk.ContentContext(config),
            }
        except Exception:
            raise DataUnavailable("Longbridge connection failed; check credentials and data permissions") from None
        self.failed: dict[str, str] = {}
        self._locks = {name: threading.Lock() for name in self.contexts}
        self._last = {name: 0.0 for name in self.contexts}

    def call(self, context: str, method: str, *args):
        if method not in self.READS.get(context, set()):
            raise DataUnavailable("Method is outside the read-only Longbridge adapter")
        with self._locks[context]:
            if context in self.failed:
                raise DataUnavailable(self.failed[context])
            # Historical API allows 60 requests / 30 seconds. Apply the stricter
            # pacing to every quote read, across collector and option monitor.
            time.sleep(max(0, 0.55 - (time.monotonic() - self._last[context])))
            self._last[context] = time.monotonic()
            try:
                return getattr(self.contexts[context], method)(*args)
            except Exception as exc:
                code = getattr(exc, "code", None)
                reason = {
                    301604: "market-data permission denied (options require OPRA OpenAPI)",
                    301607: "monthly symbol quota exhausted; full-universe coverage unavailable",
                    301606: "provider rate limit reached",
                }.get(code, "data request failed")
                self.failed[context] = f"Longbridge {context}: {reason}; fix the cause and restart explicitly"
                raise DataUnavailable(self.failed[context]) from None

    def on_candle(self, callback):
        self.contexts["quote"].set_on_candlestick(callback)
