"""Bounded public-data refresh of weekly candidates; no rescoring or performance tracking."""

from __future__ import annotations

import logging
import math
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..calendar_dates import calendar_day
from ..market_calendar import is_trading_day
from . import bets, options, spec, speculative
from .earnings_cadence import future_schedule
from .earnings_cadence import validate as validate_earnings
from .http import BudgetExceeded, FetchError, HttpClient
from .providers import Providers, canonical
from .refresh_store import RefreshStore
from .store import Store

NY = ZoneInfo("America/New_York")
CBOE_BUDGET = 80
SECONDS_BUDGET = 14 * 60
BENCHMARKS = ("SPY", "IJH", "IWM")
log = logging.getLogger(__name__)
# No duplicated prose, payoff grids or raw chains in the daily record. All numbers retain their precision.
ROW_FIELDS = (
    "option",
    "underlying",
    "type",
    "horizon",
    "expiration",
    "dte",
    "strike",
    "spot",
    "bid",
    "ask",
    "premium_per_contract_ask",
    "max_loss_per_contract",
    "breakeven",
    "breakeven_move",
    "required_move",
    "implied_move_1sd",
    "delta",
    "theta",
    "iv",
    "spread_pct",
    "open_interest",
    "volume",
    "rank",
    "rank_components",
    "events_status",
    "events_before_expiry",
    "quote_time_utc",
    "quote_status",
)


def compact_options(payload: dict) -> dict:
    for horizon in spec.HORIZONS:
        for kind in spec.OPTION_TYPES:
            rows = payload[horizon.key][kind + "s"]["rows"]
            payload[horizon.key][kind + "s"]["rows"] = [
                {**{k: row.get(k) for k in ROW_FIELDS}, "status": "available", "reason": "passed existing eligibility"}
                for row in rows
            ]
            for row in payload[horizon.key][kind + "s"]["rows"]:
                row["events_before_expiry"] = [
                    {**event, "date": event["date"].isoformat()} for event in row["events_before_expiry"]
                ]
    return payload


def constrain(http: HttpClient) -> None:
    """Tighten this run only, never alter the weekly client's defaults."""
    for name, limits in http.limits.items():
        limits.budget = min(
            limits.budget,
            CBOE_BUDGET if name == "cboe" else 1 if name == "alphavantage" else 20 if name == "fmp" else 0,
        )
    http.timeout = min(http.timeout, 10)
    deadline = http.clock() + SECONDS_BUDGET
    http.deadline = min(http.deadline, deadline) if http.deadline is not None else deadline
    http.fresh_only = True


def session_date(value) -> date | None:
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return (dt.astimezone(NY) if dt.tzinfo else dt).date()
    except (ValueError, TypeError):
        return None


def valid_price(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def fetch(fn, *args):
    try:
        return fn(*args), None
    except BudgetExceeded:
        return None, "request or time budget spent"
    except FetchError:
        return None, "provider request failed (unavailable or rate limited)"
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return None, "provider response unreadable"


def collect(
    providers: Providers,
    snap: dict,
    as_of: date,
    options_enabled: bool,
    started: str,
    iv_history: dict | None = None,
    earnings_verdicts=None,
    prior_earnings_checks: dict | None = None,
) -> dict:
    candidates = {c["ticker"] for b in snap.get("bands", {}).values() for c in b.get("candidates", [])}
    quotes, chain_states, chains = {}, {}, {}
    # Reserve the single refresh AV request for the calendar before optional quote fallbacks.
    calendar, earn_reason = fetch(providers.earnings_calendar) if options_enabled else (None, None)
    for symbol in sorted(candidates | set(BENCHMARKS)):
        quote, reason = fetch(providers.quote, symbol)
        if quote is None:
            reason = reason or "provider returned no quote"
        else:
            name = getattr(quote, "symbol", None)
            if not isinstance(name, str) or canonical(name) != symbol:
                reason = "symbol does not match requested ticker"
            elif session_date(getattr(quote, "last_trade", None)) != as_of:
                reason = "stale quote: last trade date does not equal the refresh session"
            elif not valid_price(getattr(quote, "close", None)):
                reason = "closing price missing or invalid"
        quotes[symbol] = {
            "status": "unavailable" if reason else "available",
            "reason": reason or "session verified",
            "close": None if reason else quote.close,
            "last_trade": str(quote.last_trade) if getattr(quote, "last_trade", None) else None,
            "source": getattr(quote, "source", options.QUOTE_SOURCE),
        }
    events, events_known = {}, False
    earnings_validation = {}
    stored_checks = {
        c["ticker"]: c.get("earnings_check") or {}
        for b in snap.get("bands", {}).values()
        for c in b.get("candidates", [])
    }
    stored_checks.update(prior_earnings_checks or {})
    option_payload = {"enabled": options_enabled, "status": "unavailable", "reason": "option collection disabled"}
    if options_enabled:
        schedules = None
        if calendar is not None:
            schedules, earn_reason = fetch(
                future_schedule, calendar, as_of, candidates | set(speculative.targets(snap))
            )
            events_known = schedules is not None
        for symbol in sorted(candidates | set(speculative.targets(snap))):
            old = stored_checks.get(symbol, {})
            scheduled = (schedules or {}).get(symbol)
            prior_day = calendar_day(old.get("next_scheduled"))
            retained = not scheduled and old.get("outlier") and prior_day and prior_day > as_of
            if retained:
                scheduled = prior_day.isoformat()
            if not scheduled:
                continue
            expected = old.get("expected_date")
            if expected is None and old.get("cadence_check"):
                import re

                match = re.search(r"expected about (\d{4}-\d{2}-\d{2})", old["cadence_check"])
                expected = match[1] if match else None
            manual = earnings_verdicts.check(symbol, scheduled, as_of) if earnings_verdicts else None
            checked = validate_earnings(scheduled, expected, as_of, manual)
            earnings_validation[symbol] = {"next_scheduled": scheduled, **checked}
            if checked["event_eligible"]:
                events[symbol] = [{"date": date.fromisoformat(scheduled), "event": "earnings (scheduled, unverified)"}]
        core_underlyings = {c["ticker"] for c in snap.get("bands", {}).get("large", {}).get("candidates", [])}
        underlyings = {
            c["ticker"] for key in spec.EXPLORER_BANDS for c in snap.get("bands", {}).get(key, {}).get("candidates", [])
        }
        for symbol in sorted(underlyings | set(speculative.targets(snap))):
            if earnings_validation.get(symbol, {}).get("event_eligible") is False:
                reason = earnings_validation[symbol]["validation_status"]
                chains[symbol] = reason
                chain_states[symbol] = {"status": "unavailable", "reason": reason}
                continue
            chain, reason = fetch(providers.option_chain, symbol)
            info = {}
            if chain is None:
                reason = reason or "provider returned no option chain"
            elif (
                not isinstance(chain, tuple)
                or len(chain) != 2
                or not isinstance(chain[0], dict)
                or not isinstance(chain[1], list)
            ):
                chain, reason = None, "provider response unreadable"
            if chain is not None:
                under, _ = chain
                info = options.quote_info(under, as_of)
                reason = options.chain_status(under, as_of)
                if canonical(under.get("symbol", "")) != symbol:
                    reason = "chain symbol does not match requested ticker"
                elif session_date(under.get("last_trade_time")) != as_of:
                    reason = "stale chain: last trade date does not equal the refresh session"
                elif not valid_price(under.get("close")):
                    reason = "chain closing price missing or invalid"
            chains[symbol] = reason if reason else chain
            chain_states[symbol] = {
                "status": "unavailable" if reason else "available",
                "reason": reason or "session verified",
                **info,
            }
        # The existing daily top-five view retains only the weekly large-list universe.
        core_chains = {s: chain for s, chain in chains.items() if s in core_underlyings}
        option_payload = compact_options(options.build_horizons(core_chains, as_of, events, events_known=events_known))
        option_payload.update(
            enabled=True,
            status="available" if option_payload["underlyings"] else "unavailable",
            reason="eligible contracts only; lists are not padded",
            earnings_reason=earn_reason,
        )
    partial = any(x["status"] != "available" for x in [*quotes.values(), *chain_states.values()])
    partial |= options_enabled and not events_known
    return {
        "as_of": as_of.isoformat(),
        "weekly_as_of": snap["as_of"],
        "weekly_spec_version": snap.get("spec_version"),
        "spec_version": spec.SPEC_VERSION,
        "spec_hash": spec.spec_hash(),
        "started_at": started,
        "collected_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "partial" if partial else "ok",
        "quotes": quotes,
        "earnings_validation": earnings_validation,
        "chain_status": chain_states,
        "options": option_payload,
        "explorer": bets.build({s: ch for s, ch in chains.items() if s in underlyings}, as_of, events, events_known)
        if options_enabled
        else None,
        "speculative": speculative.build(
            {s: chains[s] for s in speculative.targets(snap)}, as_of, events, iv_history, events_known
        )
        if options_enabled
        else None,
        "usage": providers.http.usage(),
    }


def run(
    data: Path,
    providers: Providers,
    as_of: date | None = None,
    *,
    options_enabled: bool = True,
    commit: str = "",
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(UTC)
    session = as_of or now.astimezone(NY).date()
    store, daily = Store(data), RefreshStore(data)
    started = now.astimezone(UTC).isoformat(timespec="seconds")
    reason = None
    if not is_trading_day(session):
        reason = "not an NYSE trading day"
    elif session > now.astimezone(NY).date() or (session == now.astimezone(NY).date() and now.astimezone(NY).hour < 17):
        reason = "session has not completed the post-close delay window (17:00 New York)"
    if reason:
        store.audit("refresh_skipped", as_of=str(session), reason=reason)
        return {"status": "skipped", "reason": reason}
    store.audit("refresh_started", as_of=str(session), commit=commit)
    try:
        if daily.folder(str(session)).exists():
            daily.load(str(session))
            store.audit("refresh_skipped", as_of=str(session), reason="first refresh kept unchanged")
            return {"status": "skipped", "reason": "first refresh kept unchanged"}
        snap = store.latest()
        if snap is None or snap["as_of"] > str(session):
            raise ValueError("no weekly snapshot at or before the refresh session")
        constrain(providers.http)
        iv_history = speculative.stored_history(daily, session) if options_enabled else {}
        from .earnings_verdicts import EarningsVerdicts

        prior_checks = {}
        for day in reversed(daily.dates()):
            if day < snap["as_of"]:
                break
            if day < str(session):
                for symbol, check in daily.load(day).get("earnings_validation", {}).items():
                    prior_checks.setdefault(symbol, check)
        payload = collect(
            providers,
            snap,
            session,
            options_enabled,
            started,
            iv_history,
            EarningsVerdicts.load(store.root),
            prior_checks,
        )
        if not any(
            r["status"] == "available" for r in (*payload["quotes"].values(), *payload["chain_status"].values())
        ):
            log.warning("Refresh has no verified quotes or chains; retaining last published state")
            raise FetchError("refresh has no usable market data")
        written = daily.write(payload, commit)
        store.audit(
            "refresh_finished" if written else "refresh_skipped",
            as_of=str(session),
            status=payload["status"],
            reason="saved" if written else "first refresh kept unchanged",
            usage=payload["usage"],
        )
        return payload
    except Exception as exc:  # preserve the last published data; never log provider payloads or secret values
        store.audit("refresh_failed", as_of=str(session), reason=type(exc).__name__)
        return {"status": "failed", "reason": type(exc).__name__}
