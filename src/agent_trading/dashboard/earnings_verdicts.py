"""Robinhood earnings-calendar verdicts for scheduled report dates (owner check, display only).

The weekly run takes scheduled report dates from Alpha Vantage's calendar and labels them "not independently
verified", because no second calendar is reachable from GitHub Actions. A Claude session can compare them with
the READ-ONLY Robinhood `get_earnings_calendar` tool (windows of at most 31 days, by default high-market-cap
names only), save the JSON responses and import them here, the same pattern as the tradability verdicts:

* the site build reads the stored file and labels a scheduled date "verified (broker calendar)" when both
  sources name the same day, shows both dates when they differ, and says when a name is missing from a window
  that was checked;
* a check older than MAX_AGE_DAYS no longer verifies anything (companies move dates), so the label falls back
  to "not independently verified" with the age of the check;
* stored snapshots are never changed: the comparison is attached to the in-memory snapshot at build time under
  BUILD_KEY and stripped again from the machine-readable copies (`data/*.json`).

Only symbols, report dates, timing, the broker's own confirmed flag and check dates are stored; never EPS
figures, account fields or anything else from the response. No rule in spec.py changes: this is presentation.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .providers import canonical
from .tradability import has_account_keys

FILE = "robinhood_earnings_calendar.json"
BUILD_KEY = "broker_calendar"  # attached to the snapshot in memory at build time only, never stored
MAX_AGE_DAYS = 14  # a broker calendar check older than this no longer verifies a date
WINDOW_MAX_DAYS = 31  # get_earnings_calendar refuses wider windows
DEFAULT_FILTER = "high_market_cap"  # the documented call: names above $1B; smaller names need filter 'all'
SOURCE = "Robinhood MCP get_earnings_calendar (read-only), checked from a Claude session"
UNVERIFIED = "not independently verified"
STATUSES = ("verified", "differs", "not_listed", "unverified")


class EarningsVerdictError(ValueError):
    pass


def parse_calendar(
    raw: dict,
    checked_at: str,
    *,
    start: str | None = None,
    days: int | None = None,
    calendar_filter: str = DEFAULT_FILTER,
) -> tuple[dict[str, dict], dict]:
    """(symbols, window) from one saved get_earnings_calendar response.

    `symbols`: {SYM: {"reports": [{"date", "timing", "confirmed"}], "checked_at"}}; `confirmed` is the broker's
    own report.verified flag (false = tentative). `window`: the dates the response covered, from `start`/`days`
    when given, otherwise the first to the last report date in the response."""
    if has_account_keys(raw):
        raise EarningsVerdictError("payload contains account fields; save only the tool's `data` results")
    data = raw.get("data", raw) if isinstance(raw, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise EarningsVerdictError("not a get_earnings_calendar response (no results list)")
    out: dict[str, dict] = {}
    dates: list[str] = []
    for r in data["results"]:
        rep = r.get("report") if isinstance(r, dict) else None
        if not isinstance(rep, dict) or not r.get("symbol") or not rep.get("date"):
            raise EarningsVerdictError("a row has no symbol or report.date; is this a get_earnings_calendar response?")
        d = date.fromisoformat(str(rep["date"])[:10]).isoformat()
        dates.append(d)
        entry = out.setdefault(canonical(str(r["symbol"])), {"reports": [], "checked_at": checked_at})
        if all(x["date"] != d for x in entry["reports"]):
            entry["reports"].append(
                {"date": d, "timing": rep.get("timing") or None, "confirmed": rep.get("verified") is True}
            )
    for entry in out.values():
        entry["reports"].sort(key=lambda x: x["date"])
    if start and days:
        first = date.fromisoformat(start)
        last = first + timedelta(days=days - 1) if days > 0 else first
        first = first + timedelta(days=days + 1) if days < 0 else first
        window = {"start": first.isoformat(), "end": last.isoformat()}
    elif dates:
        window = {"start": min(dates), "end": max(dates)}
    else:
        raise EarningsVerdictError("empty response; pass --start and --days to record which window was empty")
    window.update({"filter": calendar_filter, "rows": len(data["results"]), "checked_at": checked_at})
    return out, window


def _age_days(checked_at: str, today: date) -> int | None:
    try:
        return (today - datetime.fromisoformat(str(checked_at)).date()).days
    except (TypeError, ValueError):
        return None


@dataclass
class EarningsVerdicts:
    symbols: dict[str, dict] = field(default_factory=dict)
    windows: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, data_dir: Path) -> EarningsVerdicts:
        p = Path(data_dir) / FILE
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls(dict(raw.get("symbols", {})), list(raw.get("windows", [])))

    def save(self, data_dir: Path) -> Path:
        p = Path(data_dir) / FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "source": SOURCE,
                    "max_age_days": MAX_AGE_DAYS,
                    "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "windows": self.windows,
                    "symbols": dict(sorted(self.symbols.items())),
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        return p

    @property
    def stored(self) -> bool:
        return bool(self.symbols or self.windows)

    def newest_check(self) -> str | None:
        checks = [v.get("checked_at", "") for v in self.symbols.values()]
        checks += [w.get("checked_at", "") for w in self.windows]
        return max(checks, default=None) or None

    def merge(self, symbols: dict[str, dict], window: dict) -> int:
        """Newer checks replace older ones; same-day checks (a second window) add their dates. Returns changes."""
        n = 0
        for s, v in symbols.items():
            old = self.symbols.get(s)
            if old is None or v["checked_at"] > old.get("checked_at", ""):
                self.symbols[s] = v
                n += 1
            elif v["checked_at"] == old.get("checked_at"):
                known = {r["date"] for r in old["reports"]}
                new = [r for r in v["reports"] if r["date"] not in known]
                if new:
                    old["reports"] = sorted(old["reports"] + new, key=lambda x: x["date"])
                    n += 1
        if window not in self.windows:
            self.windows.append(window)
        return n

    def _fresh_window(self, scheduled: str, today: date) -> dict | None:
        covering = [w for w in self.windows if w["start"] <= scheduled <= w["end"]]
        fresh = [w for w in covering if (_age_days(w["checked_at"], today) or 0) <= MAX_AGE_DAYS]
        return max(fresh, key=lambda w: w["checked_at"]) if fresh else None

    def check(self, symbol: str, scheduled: str, today: date) -> dict:
        """One verdict for a scheduled (Alpha Vantage) date; `status` is one of STATUSES."""
        v = self.symbols.get(canonical(symbol))
        if v is not None:
            age = _age_days(v["checked_at"], today)
            if age is None or age > MAX_AGE_DAYS:
                return {
                    "status": "unverified",
                    "stale": True,
                    "checked_at": v["checked_at"],
                    "reason": f"the broker calendar check is {age} days old (max {MAX_AGE_DAYS})",
                }
            if age < -1:
                return {
                    "status": "unverified",
                    "checked_at": v["checked_at"],
                    "reason": "the broker calendar check is dated after today",
                }
            hit = next((r for r in v["reports"] if r["date"] == scheduled), None)
            if hit:
                return {
                    "status": "verified",
                    "broker_dates": [scheduled],
                    "timing": hit.get("timing"),
                    "confirmed": bool(hit.get("confirmed")),
                    "checked_at": v["checked_at"],
                }
            return {
                "status": "differs",
                "broker_dates": [r["date"] for r in v["reports"]],
                "confirmed": any(r.get("confirmed") for r in v["reports"]),
                "checked_at": v["checked_at"],
            }
        w = self._fresh_window(scheduled, today)
        if w:
            return {"status": "not_listed", "window": w, "checked_at": w["checked_at"]}
        return {"status": "unverified", "reason": "no broker calendar check covers this date"}


def label(v: dict | None) -> str:
    """Plain-language verdict for a scheduled date; without a verdict the existing wording is kept."""
    if not v:
        return UNVERIFIED
    s = v.get("status")
    if s == "verified":
        tail = "" if v.get("confirmed") else "; the broker lists the date as tentative"
        return f"verified (broker calendar, checked {v['checked_at']}{tail})"
    if s == "differs":
        listed = ", ".join(v["broker_dates"])
        return f"differs from the broker calendar, which lists {listed} (checked {v['checked_at']})"
    if s == "not_listed":
        w = v["window"]
        scope = " among high-market-cap names" if w.get("filter") == DEFAULT_FILTER else ""
        return f"not listed in the broker calendar for {w['start']} to {w['end']}{scope} (checked {w['checked_at']})"
    return UNVERIFIED + (f" ({v['reason']})" if v.get("reason") else "")


def _key(ticker: str, scheduled: str) -> str:
    return f"{canonical(str(ticker))} {scheduled}"


def attach(snap: dict, verdicts: EarningsVerdicts, today: date) -> dict:
    """Compare every scheduled date in the snapshot with the stored broker calendar; attach the result in memory.

    Verdicts cover the overview's event items and every candidate's next date; the summary counts the event
    items, which is what the owner checks. Nothing is written to the store."""
    pairs = [(i["ticker"], i["date"]) for i in (snap.get("events") or {}).get("items") or [] if i.get("date")]
    event_keys = {_key(t, d) for t, d in pairs}
    for b in (snap.get("bands") or {}).values():
        pairs += [(c["ticker"], c["next_earnings"]) for c in b.get("candidates") or [] if c.get("next_earnings")]
    out: dict[str, dict] = {}
    for t, d in pairs:
        k = _key(t, d)
        if k not in out:
            out[k] = (
                verdicts.check(t, d, today)
                if verdicts.stored
                else {"status": "unverified", "reason": "no broker calendar check is stored"}
            )
    counts = Counter(out[k]["status"] for k in event_keys)
    snap[BUILD_KEY] = {
        "source": SOURCE,
        "max_age_days": MAX_AGE_DAYS,
        "stored": verdicts.stored,
        "checked_on": today.isoformat(),
        "newest_check": verdicts.newest_check(),
        "windows": list(verdicts.windows),
        "verdicts": out,
        "summary": {
            "total": len(event_keys),
            "verified": counts["verified"],
            "differs": counts["differs"],
            "not_listed": counts["not_listed"],
            "unchecked": counts["unverified"],
            "stale": sum(1 for k in event_keys if out[k].get("stale")),
        },
    }
    return snap[BUILD_KEY]


def verdict_for(snap: dict | None, ticker: str, scheduled: str | None) -> dict | None:
    bc = snap.get(BUILD_KEY) if isinstance(snap, dict) else None
    if not bc or not scheduled:
        return None
    return bc.get("verdicts", {}).get(_key(ticker, scheduled))


def without_overlay(snap: dict) -> dict:
    """The snapshot as stored: the build-time comparison is not part of the immutable data."""
    return {k: v for k, v in snap.items() if k != BUILD_KEY}


def summary_text(snap: dict) -> str:
    """One sentence for the overview's earnings panel."""
    bc = snap.get(BUILD_KEY)
    if not bc:
        return ""
    if not bc["stored"]:
        return "No Robinhood calendar check is stored, so every date stays unverified (owner step: see the audit page)."
    s = bc["summary"]
    return (
        f"Broker calendar check (Robinhood, read-only, latest {bc['newest_check']}): {s['verified']} of {s['total']} "
        f"dates verified, {s['differs']} differ (both dates shown), {s['not_listed']} not listed in the checked "
        f"windows, {s['unchecked']} unchecked; checks older than {MAX_AGE_DAYS} days do not count."
    )


def dataset_state(bc: dict) -> tuple[str, str, str]:
    """(state, detail, coverage) for the audit page's data-status table."""
    s = bc["summary"]
    n, checked = s["total"], s["verified"] + s["differs"]
    if not bc["stored"]:
        return "missing", "no stored read-only Robinhood calendar check; scheduled dates stay labelled unverified", ""
    if n == 0:
        return "available", "no scheduled report dates in this snapshot to compare", ""
    cov = f"{checked} of {n}"
    if checked == n:
        detail = f"{s['verified']} of {n} scheduled date(s) agree with the broker calendar; {s['differs']} differ"
        return "available", detail + " (both dates shown)", cov
    if checked == 0 and s["stale"] == n:
        return "stale", f"every stored broker check is older than {bc['max_age_days']} days", cov
    if checked == 0:
        detail = f"none of the {n} scheduled date(s) has a fresh broker check"
        return "missing", f"{detail} ({s['not_listed']} not listed in the checked windows)", cov
    detail = (
        f"{checked} of {n} checked: {s['verified']} agree, {s['differs']} differ; "
        f"{s['not_listed']} not listed in the checked windows, {s['unchecked']} unchecked"
    )
    return "partial", detail, cov


def fetch_windows(today: date, last: date, calendar_filter: str = DEFAULT_FILTER) -> list[dict]:
    """The get_earnings_calendar calls (at most 31 days each) that cover today through `last`."""
    out, start = [], today
    while start <= last:
        days = min(WINDOW_MAX_DAYS, (last - start).days + 1)
        out.append({"start_date": start.isoformat(), "days": days, "filter": calendar_filter})
        start += timedelta(days=days)
    return out
