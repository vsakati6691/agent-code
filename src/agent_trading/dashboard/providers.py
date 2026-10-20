"""Public provider facade; source parsing is isolated and re-exported for compatibility."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

import pandas as pd

from ..provider_budget import DailyBudgetExceeded
from . import spec
from .finra_schema import COLUMNS as FINRA_COLUMNS
from .http import CacheMiss, FetchError, HttpClient, OptionalDataDeferred
from .provider_parsers import AV_URL as AV_URL
from .provider_parsers import CBOE_BASE as CBOE_BASE
from .provider_parsers import COMMON as COMMON
from .provider_parsers import NASDAQ_LISTED_URL as NASDAQ_LISTED_URL
from .provider_parsers import NON_COMMON as NON_COMMON
from .provider_parsers import OCC_RE as OCC_RE
from .provider_parsers import OTHER_EXCHANGES as OTHER_EXCHANGES
from .provider_parsers import OTHER_LISTED_URL as OTHER_LISTED_URL
from .provider_parsers import SEC_FACTS_URL as SEC_FACTS_URL
from .provider_parsers import SEC_FRAME_URL as SEC_FRAME_URL
from .provider_parsers import SEC_SUBMISSIONS_URL as SEC_SUBMISSIONS_URL
from .provider_parsers import SEC_TICKERS_URL as SEC_TICKERS_URL
from .provider_parsers import SIC_SECTORS as SIC_SECTORS
from .provider_parsers import SOURCES as SOURCES
from .provider_parsers import WIKI_SP500_PARAMS as WIKI_SP500_PARAMS
from .provider_parsers import WIKI_SP500_URL as WIKI_SP500_URL
from .provider_parsers import Quote as Quote
from .provider_parsers import _num as _num
from .provider_parsers import _pipe_table as _pipe_table
from .provider_parsers import _TableParser as _TableParser
from .provider_parsers import canonical as canonical
from .provider_parsers import common_stock_reason as common_stock_reason
from .provider_parsers import parse_cboe_chain as parse_cboe_chain
from .provider_parsers import parse_cboe_history as parse_cboe_history
from .provider_parsers import parse_cboe_quote as parse_cboe_quote
from .provider_parsers import parse_earnings_8k as parse_earnings_8k
from .provider_parsers import parse_occ as parse_occ
from .provider_parsers import parse_sec_tickers as parse_sec_tickers
from .provider_parsers import parse_share_frames as parse_share_frames
from .provider_parsers import parse_sp500 as parse_sp500
from .provider_parsers import parse_symbol_directories as parse_symbol_directories
from .provider_parsers import sector_from_sic as sector_from_sic
from .provider_parsers import share_frame_periods as share_frame_periods

EXTERNAL_PROVIDERS = {
    "insiders": {"provider": "sec", "budget": 1800, "endpoint": "https://data.sec.gov/submissions/CIK{cik:010d}.json"},
    "institutions": {
        "provider": "sec",
        "budget": 24,
        "endpoint": "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets",
    },
    "risk_excerpts": {
        "provider": "sec",
        "budget": 120,
        "per_company": 2,
        "endpoint": "https://efts.sec.gov/LATEST/search-index",
    },
    "macro": {
        "provider": "fred",
        "budget": 42,
        "endpoint": "https://api.stlouisfed.org/fred/series/observations",
        "metadata_endpoint": "https://api.stlouisfed.org/fred/series",
    },
    "short_interest": {
        "provider": "finra",
        "budget": 9,
        "verified_on": "2026-10-16",
        "endpoint": "https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files",
        "verified_file": "https://cdn.finra.org/equity/otcmarket/biweekly/shrt20260930.csv",
        "columns": FINRA_COLUMNS,
    },
}
SOURCES.update(
    {
        "fred": "Federal Reserve Bank of St. Louis FRED, dated observations and series metadata",
        "finra": "FINRA consolidated equity short interest, twice-monthly settlement reports",
    }
)


class Providers:
    """Thin fetch layer. Every method raises FetchError (or BudgetExceeded) on failure."""

    def __init__(
        self,
        http: HttpClient,
        av_key: str | None = None,
        fred_key: str | None = None,
        *,
        massive_key: str | None = None,
        history_as_of: date | None = None,
        fmp_key: str | None = None,
    ) -> None:
        self.http = http
        self.av_key = av_key
        self.fred_key = fred_key
        self.massive_key = massive_key
        self.fmp_key = fmp_key
        if fmp_key:
            from ..logging_setup import register_secret

            register_secret(fmp_key)
        self.history_provider = "massive" if massive_key else "cboe"
        self.history_as_of = history_as_of
        self._submissions: dict[int, dict] = {}
        self._insider_requests = 0
        if fred_key:
            from ..logging_setup import register_secret

            register_secret(fred_key)
        if massive_key:
            from ..logging_setup import register_secret
            from .private_research import require_local

            require_local()
            register_secret(massive_key)
            if history_as_of is None:
                raise ValueError("Private history requires an explicit completed session")

    def sec_tickers(self) -> pd.DataFrame:
        return parse_sec_tickers(self.http.get_json(SEC_TICKERS_URL, max_age_hours=24))

    def share_frames(self, as_of: date) -> dict[int, tuple[float, str]]:
        frames = []
        for period in share_frame_periods(as_of):
            try:
                frames.append(self.http.get_json(SEC_FRAME_URL.format(period=period), max_age_hours=24))
            except FetchError as exc:
                if "HTTP 404" not in str(exc):  # a quarter with no filings yet is normal
                    raise
        return parse_share_frames(frames, as_of)

    def company_facts(self, cik: int) -> dict:
        return self.http.get_json(SEC_FACTS_URL.format(cik=int(cik)), max_age_hours=72, validate=self._object)

    def submissions(self, cik: int) -> dict:
        if int(cik) not in self._submissions:
            self._submissions[int(cik)] = self.http.get_json(
                SEC_SUBMISSIONS_URL.format(cik=int(cik)), max_age_hours=168, validate=self._object
            )
        return self._submissions[int(cik)]

    def fund_filing(self, metadata: dict, as_of: date) -> dict:
        from .etf_inputs import collect_filing

        return collect_filing(self, metadata, as_of)

    def symbol_directories(self) -> pd.DataFrame:
        return parse_symbol_directories(
            self.http.get_text(NASDAQ_LISTED_URL, max_age_hours=24),
            self.http.get_text(OTHER_LISTED_URL, max_age_hours=24),
        )

    def sp500(self) -> pd.DataFrame:
        return parse_sp500(self.http.get_json(WIKI_SP500_URL, WIKI_SP500_PARAMS, max_age_hours=24))

    def quote(self, symbol: str) -> Quote:
        def check(raw):
            quote = parse_cboe_quote(raw)
            if quote.symbol != canonical(symbol) or quote.close is None or quote.close <= 0:
                raise FetchError("Cboe quote missing or invalid")
            return quote

        try:
            return self._price_data(f"{CBOE_BASE}/quotes/{symbol}.json", check)
        except (FetchError, ValueError, TypeError, KeyError, AttributeError):
            return self.daily_quote(symbol)

    def _fmp(self, endpoint: str, symbol: str, validate=None) -> dict | list:
        from .fallbacks import FMP_BASE

        if not self.fmp_key:
            raise FetchError("FMP fallback key not configured (FMP_API_KEY)")
        return self.http.get_json(
            f"{FMP_BASE}/{endpoint}",
            {"symbol": symbol, "apikey": self.fmp_key},
            max_age_hours=24 if endpoint == "profile" else 0,
            validate=validate,
        )

    def daily_quote(self, symbol: str, as_of: date | None = None) -> Quote:
        """Alpha Vantage daily close, then optional FMP; quotas never disable the fallback."""
        from .fallbacks import daily_quote
        from .pipeline_context import as_of_for

        now = datetime.now(UTC)
        session = as_of or as_of_for(now)
        try:
            raw = self._overview_data(
                "GLOBAL_QUOTE", symbol, lambda raw: daily_quote(raw, symbol, session, now.isoformat(), "alphavantage")
            )
            return daily_quote(raw, symbol, session, now.isoformat(), "alphavantage")
        except FetchError:
            raw = self._fmp("quote", symbol, lambda raw: daily_quote(raw, symbol, session, now.isoformat(), "fmp"))
            return daily_quote(raw, symbol, session, now.isoformat(), "fmp")

    def history(self, symbol: str) -> pd.DataFrame:
        if self.massive_key:
            from .massive_history import fetch_history

            assert self.history_as_of is not None
            return fetch_history(self.http, self.massive_key, symbol, self.history_as_of)
        return self._price_data(f"{CBOE_BASE}/charts/historical/{symbol}.json", parse_cboe_history)

    def option_chain(self, symbol: str) -> tuple[dict, list[dict]]:
        return self._price_data(f"{CBOE_BASE}/options/{symbol}.json", parse_cboe_chain)

    def institutional_holders(self, symbol: str, as_of: date) -> dict:
        from . import institutional_fallback as fallback

        if not self.fmp_key:
            raise FetchError("FMP institutional fallback not configured")
        quarter = fallback.eligible_quarter(as_of)
        retrieved_at = datetime.now(UTC).isoformat()
        raw = self.http.get_json(
            fallback.ENDPOINT,
            {"symbol": symbol, "year": quarter.year, "quarter": (quarter.month + 2) // 3, "apikey": self.fmp_key},
            max_age_hours=0,
            validate=lambda data: fallback.parse(data, symbol, quarter, retrieved_at),
        )
        return fallback.parse(raw, symbol, quarter, retrieved_at)

    def _price_data(self, url: str, parser: Callable):
        """Parse once before caching, retaining the parsed history/chain for the caller."""
        parsed = None

        def validate(raw):
            nonlocal parsed
            parsed = parser(raw)

        self._price_json(url, validate)
        return parsed

    @staticmethod
    def _object(raw: object) -> None:
        if not isinstance(raw, dict):
            raise FetchError("provider response must be an object")

    def _price_json(self, url: str, validate: Callable | None = None) -> dict:
        from .pipeline_context import as_of_for

        # A new completed session must never reuse a cached response fetched before its close.
        session = as_of_for(datetime.now(UTC))
        return self.http.get_json(
            url, max_age_hours=12, cache_key_extra=f"completed-session-v1:{session}", validate=validate
        )

    def earnings_calendar(self) -> pd.DataFrame:
        if not self.av_key:
            raise FetchError("Alpha Vantage key not configured (ALPHAVANTAGE_API_KEY)")
        from ..data.alphavantage import AlphaVantageError, parse_earnings_csv
        from ..logging_setup import register_secret

        register_secret(self.av_key)
        df = pd.DataFrame()

        def validate(body):
            nonlocal df
            try:
                df = parse_earnings_csv(body.decode("utf-8"))
                df["symbol"] = df["symbol"].map(canonical)
            except (AlphaVantageError, UnicodeError, ValueError, TypeError, AttributeError):
                raise FetchError("Alpha Vantage earnings calendar is unreadable") from None

        self.http.get_bytes(
            AV_URL,
            {"function": "EARNINGS_CALENDAR", "horizon": "12month", "apikey": self.av_key},
            max_age_hours=24,
            validate=validate,
        )
        return df

    def _overview_data(self, function: str, symbol: str, validate=None) -> dict:
        if not self.av_key:
            raise FetchError("Alpha Vantage key not configured (ALPHAVANTAGE_API_KEY)")
        from ..logging_setup import register_secret

        register_secret(self.av_key)
        rules = spec.DASHBOARD_REFINEMENT_RULES
        params = {"function": function, "symbol": symbol, "apikey": self.av_key}

        def check(raw):
            self._check_company(raw, function, symbol)
            if validate:
                validate(raw)

        # Read the cache before inspecting either budget. A stopped provider must
        # not hide another symbol's valid daily observation.
        try:
            return self.http.get_json(
                AV_URL,
                params,
                max_age_hours=rules["insider_cache_hours"],
                validate=check,
                cache_only=True,
            )
        except CacheMiss:
            pass
        try:
            remaining = self.http.daily_budget.remaining()
        except DailyBudgetExceeded:
            remaining = 0
        if (
            remaining <= rules["av_optional_reserve"]
            or self.http.budget_left("alphavantage") <= 0
            or "alphavantage" in self.http.unavailable
        ):
            raise OptionalDataDeferred(
                "Optional Alpha Vantage enrichment deferred; daily capacity reserved, SEC activity remains independent"
            )
        if function == "INSIDER_TRANSACTIONS":
            if self._insider_requests >= rules["insider_max_requests"]:
                raise OptionalDataDeferred(
                    "Insider enrichment deferred after 2 new requests; SEC Form 4 remains primary"
                )
            self._insider_requests += 1
        return self.http.get_json(
            AV_URL, params, validate=check, max_attempts=1, av_reserve=rules["av_optional_reserve"]
        )

    @staticmethod
    def _check_company(raw: object, function: str, symbol: str) -> None:
        if not isinstance(raw, dict) or not raw:
            raise FetchError("Alpha Vantage returned no company data")
        if raw.get("Note") or raw.get("Information"):
            raise FetchError("Alpha Vantage quota or entitlement response; further enrichment stopped")
        if raw.get("Error Message"):
            raise FetchError("Alpha Vantage rejected company data request")
        if function == "OVERVIEW" and canonical(str(raw.get("Symbol", ""))) != canonical(symbol):
            raise FetchError("Alpha Vantage company symbol missing or mismatched")
        if function == "OVERVIEW":
            cap = _num(raw.get("MarketCapitalization"))
            if "MarketCapitalization" in raw and (cap is None or cap <= 0):
                raise FetchError("Alpha Vantage company capitalization invalid")
            if "Name" in raw and (not isinstance(raw["Name"], str) or not raw["Name"].strip()):
                raise FetchError("Alpha Vantage company name invalid")
        if function == "INSIDER_TRANSACTIONS":
            rows = raw.get("data")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise FetchError("Alpha Vantage insider transaction layout invalid")
            for row in rows:
                try:
                    date.fromisoformat(str(row.get("transaction_date")))
                except ValueError:
                    raise FetchError("Alpha Vantage insider transaction date invalid") from None
                if row.get("ticker") and canonical(str(row["ticker"])) != canonical(symbol):
                    raise FetchError("Alpha Vantage insider symbol mismatch")

    def overview(self, symbol: str) -> dict:
        try:
            return {
                **self._overview_data("OVERVIEW", symbol),
                "_source": "Alpha Vantage OVERVIEW; current estimate, not point-in-time history",
                "_observed_at": datetime.now(UTC).isoformat(),
            }
        except FetchError:
            if not self.fmp_key:
                raise
            from .fallbacks import profile

            observed = datetime.now(UTC).isoformat()
            return profile(self._fmp("profile", symbol, lambda raw: profile(raw, symbol, observed)), symbol, observed)

    def insider_transactions(self, symbol: str) -> dict:
        raw = self._overview_data("INSIDER_TRANSACTIONS", symbol)
        return {
            **raw,
            "_observed_at": datetime.fromtimestamp(self.http.last_observed_at, UTC).isoformat(),
        }

    def annual_filing(self, cik: int, as_of: date) -> dict:
        from .decision_sources import filing_excerpts, latest_10k

        filing = latest_10k(self.submissions(cik), cik, as_of)
        if filing is None:
            raise FetchError("No dated 10-K primary document in recent SEC submissions")
        url, filed = filing
        return filing_excerpts(self.http.get_text(url, max_age_hours=168), url, filed)
