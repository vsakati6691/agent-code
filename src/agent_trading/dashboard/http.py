"""The dashboard's only network access: GET requests to allow-listed public data hosts.

* GET only, to the hosts in ALLOWED_HOSTS; anything else raises before a request is made.
* Per-host minimum spacing between requests (SEC fair-access policy: at most 10/s).
* Per-provider request budgets; once spent, further calls raise BudgetExceeded so
  the pipeline marks the remaining items "not evaluated: request budget spent".
* Bounded retries (3 attempts, exponential backoff) for timeouts, connection
  errors and 5xx; HTTP 429 gets up to 5 attempts, honours Retry-After, and
  permanently slows that provider (adaptive throttling, capped at MAX_INTERVAL).
  Other errors fail immediately.
* An on-disk cache keyed by URL with a maximum age, so a rerun inside the same
  week does not refetch everything.
* Query strings are never logged (API keys travel there); errors carry the host only.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

ALLOWED_HOSTS = {
    "www.sec.gov": "sec",
    "data.sec.gov": "sec",
    "cdn.cboe.com": "cboe",
    "cdn-api.cboe.com": "cboe",
    "www.nasdaqtrader.com": "nasdaqtrader",
    "en.wikipedia.org": "wikipedia",
    "www.alphavantage.co": "alphavantage",
}
RETRY_STATUS = {429, 500, 502, 503, 504}
RATE_LIMIT_ATTEMPTS = 5
MAX_INTERVAL = 3.0           # slowest pacing adaptive throttling will go to (seconds between requests)


class FetchError(RuntimeError):
    """A request failed after its retries, or returned an unusable response."""


class BudgetExceeded(FetchError):
    """The provider's request budget for this run is spent."""


@dataclass
class ProviderLimits:
    min_interval: float          # seconds between requests to the same provider
    budget: int                  # maximum network requests per run


DEFAULT_LIMITS = {
    "sec": ProviderLimits(0.15, 4000),          # ~6.7 requests/s, under the SEC's 10/s
    "cboe": ProviderLimits(0.5, 7000),         # undocumented limit; HTTP 429 seen at 4 requests/s
    "nasdaqtrader": ProviderLimits(1.0, 10),
    "wikipedia": ProviderLimits(1.0, 10),
    "alphavantage": ProviderLimits(13.0, 3),    # free key: 25/day; the dashboard needs 1
}


@dataclass
class HttpClient:
    cache_dir: Path | None
    user_agent: str
    limits: dict[str, ProviderLimits] = field(   # copied: throttling changes a client's own pacing only
        default_factory=lambda: {k: ProviderLimits(v.min_interval, v.budget) for k, v in DEFAULT_LIMITS.items()})
    timeout: float = 30.0
    attempts: int = 3
    backoff: float = 2.0
    session: requests.Session | None = None
    sleep: callable = time.sleep
    clock: callable = time.monotonic
    used: dict[str, int] = field(default_factory=dict)
    throttled: dict[str, int] = field(default_factory=dict)
    cache_hits: int = 0
    _last: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.session = self.session or requests.Session()
        if self.cache_dir is not None:
            self.cache_dir = Path(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # --- public -----------------------------------------------------------------------
    def get_bytes(self, url: str, params: dict | None = None, max_age_hours: float = 0.0,
                  cache_key_extra: str = "") -> bytes:
        provider = self._provider(url)
        key = self._key(url, params, cache_key_extra)
        cached = self._read_cache(key, max_age_hours)
        if cached is not None:
            self.cache_hits += 1
            return cached
        body = self._fetch(provider, url, params)
        self._write_cache(key, body)
        return body

    def get_json(self, url: str, params: dict | None = None, max_age_hours: float = 0.0,
                 cache_key_extra: str = "") -> dict | list:
        body = self.get_bytes(url, params, max_age_hours, cache_key_extra)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise FetchError(f"{urlsplit(url).hostname}: response is not JSON") from None

    def get_text(self, url: str, params: dict | None = None, max_age_hours: float = 0.0) -> str:
        return self.get_bytes(url, params, max_age_hours).decode("utf-8", errors="replace")

    def budget_left(self, provider: str) -> int:
        return self.limits[provider].budget - self.used.get(provider, 0)

    def usage(self) -> dict:
        return {"requests": dict(self.used), "cache_hits": self.cache_hits, "rate_limited": dict(self.throttled),
                "budgets": {k: v.budget for k, v in self.limits.items()},
                "final_interval_s": {k: round(v.min_interval, 2) for k, v in self.limits.items()}}

    # --- internals ---------------------------------------------------------------------
    @staticmethod
    def _provider(url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
            raise FetchError(f"host not allowed: {parts.hostname!r}")
        return ALLOWED_HOSTS[parts.hostname]

    def _fetch(self, provider: str, url: str, params: dict | None) -> bytes:
        host = urlsplit(url).hostname
        last_error = ""
        attempt, limit = 0, self.attempts
        while attempt < limit:
            attempt += 1
            if self.used.get(provider, 0) >= self.limits[provider].budget:
                raise BudgetExceeded(f"{provider}: request budget of {self.limits[provider].budget} spent")
            self._pace(provider)
            self.used[provider] = self.used.get(provider, 0) + 1
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout, allow_redirects=False,
                                        headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"})
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = type(exc).__name__
            except requests.RequestException as exc:
                raise FetchError(f"{host}: {type(exc).__name__}") from None
            else:
                if resp.status_code == 200:
                    return resp.content
                if resp.status_code in (301, 302, 303, 307, 308):
                    # redirects are followed only to another allow-listed host, and only once
                    target = resp.headers.get("Location", "")
                    if self._provider(target) != provider or target == url:
                        raise FetchError(f"{host}: redirect to a different provider refused")
                    url, host = target, urlsplit(target).hostname
                    continue
                if resp.status_code not in RETRY_STATUS:
                    raise FetchError(f"{host}: HTTP {resp.status_code}")
                last_error = f"HTTP {resp.status_code}"
            wait = self.backoff * 2 ** (attempt - 1)
            if last_error == "HTTP 429":
                limit = max(limit, RATE_LIMIT_ATTEMPTS)
                self.throttled[provider] = self.throttled.get(provider, 0) + 1
                lim = self.limits[provider]
                lim.min_interval = min(MAX_INTERVAL, lim.min_interval * 1.5 + 0.1)
                try:
                    wait = max(wait, float(resp.headers.get("Retry-After", 0)))
                except (TypeError, ValueError):
                    pass
                wait = max(wait, 5.0)
            if attempt < limit:
                log.info("%s: %s, retry %d/%d in %.0fs", host, last_error, attempt, limit - 1, wait)
                self.sleep(wait)
        raise FetchError(f"{host}: {last_error} after {attempt} attempts")

    def _pace(self, provider: str) -> None:
        wait = self.limits[provider].min_interval - (self.clock() - self._last.get(provider, -1e9))
        if wait > 0:
            self.sleep(wait)
        self._last[provider] = self.clock()

    @staticmethod
    def _key(url: str, params: dict | None, extra: str) -> str:
        # API keys are excluded from the cache key so they never reach a file name
        safe = sorted((k, v) for k, v in (params or {}).items() if k.lower() not in ("apikey", "api_key", "token"))
        return hashlib.sha256(json.dumps([url, safe, extra]).encode()).hexdigest()

    def _read_cache(self, key: str, max_age_hours: float) -> bytes | None:
        if self.cache_dir is None or max_age_hours <= 0:
            return None
        path = self.cache_dir / f"{key}.gz"
        if not path.exists() or time.time() - path.stat().st_mtime > max_age_hours * 3600:
            return None
        try:
            return gzip.decompress(path.read_bytes())
        except (OSError, EOFError):
            return None

    def _write_cache(self, key: str, body: bytes) -> None:
        if self.cache_dir is None:
            return
        tmp = self.cache_dir / f"{key}.tmp"
        tmp.write_bytes(gzip.compress(body))
        tmp.replace(self.cache_dir / f"{key}.gz")
