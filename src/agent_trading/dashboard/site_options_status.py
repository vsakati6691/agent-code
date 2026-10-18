"""Options page and overview watchlist: Calls/Puts control x 3M/6M/1Y tabs, six lists of up to 5 contracts.

Everything shown comes from the stored snapshot. Observed facts (delayed quotes), assumptions (premium at the
ask, no fees), unknown or missing data, and the research score are kept in separate blocks. The page is built
and linked whatever the state of option collection, and explains that state in plain language.
"""

from __future__ import annotations

import html

from . import evidence, spec

E = html.escape
HZ_SHORT = {"3m": "3M", "6m": "6M", "12m": "1Y"}
STATE_CLASS = {"available": "ok", "partial": "warn", "stale": "warn", "missing": "muted", "provider_error": "bad"}
STATE_LABEL = {
    "available": "Available",
    "partial": "Partial",
    "stale": "Stale",
    "missing": "Not collected",
    "provider_error": "Collection failed",
}
MISSING_FLAG_WORDS = ("unavailable", "unknown", "unreadable")


def lists_of(hz: dict) -> dict:
    """{'calls': {...}, 'puts': {...}} for both the current and the older calls-only snapshot shape."""
    if "calls" in hz or "puts" in hz:
        return {k: hz.get(k) for k in ("calls", "puts")}
    old = {
        "rows": hz.get("rows", []),
        "count": len(hz.get("rows", [])),
        "considered": hz.get("considered", 0),
        "rejections": hz.get("rejections", {}),
        "status": hz.get("status", "unknown"),
    }
    return {
        "calls": old,
        "puts": {
            "rows": [],
            "count": 0,
            "considered": 0,
            "rejections": {},
            "status": "puts were not collected in this snapshot (before spec 2026-10-14.2)",
        },
    }


def distance_text(kind: str, signed) -> str:
    """Signed distance from the stock price to the breakeven at expiry, in words a reader parses in one pass."""
    if not isinstance(signed, (int, float)):
        return "n/a"
    if kind == "call":
        return (
            f"{signed:+.1%} (stock must rise)"
            if signed > 0
            else f"already past breakeven (breakeven {abs(signed):.1%} below the stock)"
        )
    return (
        f"{signed:+.1%} (stock must fall)"
        if signed < 0
        else f"already past breakeven (breakeven {abs(signed):.1%} above the stock)"
    )


def list_limit(snap: dict, data: dict | None) -> int:
    """The per-list limit the snapshot was built with (stored from 2026-10-14.6; by version before that)."""
    if data and isinstance(data.get("limit"), int):
        return data["limit"]
    return spec.option_list_limit(snap.get("spec_version"))


def events_status(x: dict, o: dict) -> tuple[str, str]:
    """('scheduled' | 'none scheduled' | 'unknown', text). Older snapshots carry no status: when the calendar
    was unavailable (earnings_note) the status is 'unknown', never 'none scheduled'."""
    st = x.get("events_status")
    if st is None:
        if o.get("earnings_note") or o.get("events_known") is False:
            st = "unknown"
        else:
            st = "scheduled" if x.get("events_before_expiry") else "none scheduled"
    if st == "scheduled":
        dates = ", ".join(str(e.get("date")) for e in x.get("events_before_expiry", []))
        return st, f"scheduled {dates} (unverified)"
    if st == "none scheduled":
        return st, "none scheduled (collected calendar, unverified)"
    return "unknown", "unknown (calendar not collected)"


def probability_text(x: dict) -> str:
    p = x.get("probability") or {}
    if p.get("status") == "calibrated" and isinstance(p.get("probability_of_profit"), (int, float)):
        return p.get("statement") or spec.PROBABILITY_NOT_ESTABLISHED
    return spec.PROBABILITY_NOT_ESTABLISHED


def version_line(snap: dict) -> str:
    v = snap.get("spec_version") or "unknown"
    same = v == spec.SPEC_VERSION
    tail = (
        ""
        if same
        else " The rules in force when this snapshot was collected (including its list size) are the snapshot's; "
        "this page only renders what was stored and never re-ranks or re-filters it."
    )
    return (
        f'<p class="small muted">Snapshot methodology <strong>{E(str(v))}</strong> (the rules the data was collected '
        f"and ranked under) · page renderer <strong>{E(spec.SPEC_VERSION)}</strong>.{tail}</p>"
    )


def status_block(snap: dict) -> dict:
    """{'state', 'label', 'class', 'headline', 'detail', 'action'}: the option dataset's state in plain language."""
    o = snap.get("options") or {}
    state, detail = evidence.options_state(snap)
    action = ""
    if state == "missing":
        headline = "Options data unavailable: option chains were not collected for this snapshot."
        detail = (
            "Collection is switched off for the weekly run (the owner's stocks-only choice on 2026-10-14, because "
            "of Cboe's terms for republishing delayed quotes). Nothing is invented: no contracts, prices or Greeks "
            "are shown."
        )
        action = (
            "Owner setup to enable it: set the repository variable DASHBOARD_OPTIONS to true (and review the "
            "data-source terms in docs/RESEARCH_DASHBOARD.md). The six lists then appear in the first weekly "
            "snapshot collected afterwards; earlier snapshots stay as published."
        )
    elif state == "provider_error":
        headline = "Options data unavailable: collection ran but produced no usable chain."
        detail = f"{detail}. No contracts, prices or Greeks are shown rather than inventing them."
        action = "The next scheduled run retries automatically; the audit page lists the request counts and errors."
    elif state == "stale":
        headline = "Options data unavailable: every option chain was rejected as stale."
        detail = (
            f"{detail}. A chain is used only when the underlying traded in the as-of session and the chain's "
            "snapshot is not older than that session."
        )
        action = "The next scheduled run retries automatically."
    elif state == "partial":
        headline = "Options collected with gaps: some chains could not be used."
        detail = f"{detail}. The lists below rank only the contracts from usable chains; nothing is filled in."
    else:
        headline = "Options collected and validated for this snapshot."
    short = []
    if o.get("enabled") and o.get("status") == "ok":
        for h in spec.HORIZONS:
            for kind, lst in lists_of(o.get(h.key) or {}).items():
                lim = list_limit(snap, lst)
                n = len((lst or {}).get("rows", []))
                if n < lim:
                    short.append(f"{kind} {HZ_SHORT[h.key]}: {n} of {lim}")
    if short:
        detail += (
            f" Lists with fewer than the limit (each one says why): {', '.join(short)}. A short list is not "
            "padded and no rule is relaxed."
        )
    return {
        "state": state,
        "label": STATE_LABEL[state],
        "class": STATE_CLASS[state],
        "headline": headline,
        "detail": detail,
        "action": action,
        "as_of": str(snap.get("as_of")),
        "collected_at": o.get("collected_at") or snap.get("run_finished"),
    }


def status_html(snap: dict, compact: bool = False) -> str:
    s = status_block(snap)
    kind = (
        "bad" if s["state"] in ("missing", "provider_error", "stale") else "warn" if s["state"] == "partial" else "info"
    )
    act = f' <span class="small">{E(s["action"])}</span>' if s["action"] and not compact else ""
    audit = ' <a href="audit.html#data-status">Data status</a>.' if not compact else ""
    return (
        f'<div class="banner {kind} small" id="options-status" data-state="{E(s["state"])}"><strong>'
        f'<span class="pill {E(s["class"])}">{E(s["label"])}</span> {E(s["headline"])}</strong>{E(s["detail"])}{act}{audit}</div>'
    )
