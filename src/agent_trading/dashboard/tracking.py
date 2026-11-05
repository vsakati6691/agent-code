"""Forward performance of past weekly research lists (spec.TRACKING_METHOD).

Only prices AFTER a snapshot's as-of close are used to judge it, and each
snapshot's list is taken exactly as it was saved, so there is no look-ahead and
no hindsight reselection. Candidates whose prices stop are reported as
unavailable (possible delisting) instead of being dropped.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import pandas as pd

from ..market_calendar import is_trading_day
from . import spec

BANDS = {b.key: b for b in spec.BANDS}


class _Legacy:
    """A list retired by a later spec version, still tracked from old snapshots."""

    def __init__(self, info: dict) -> None:
        self.benchmark = info["benchmark"]
        self.friction_bps_per_side = info["friction_bps_per_side"]


ALL_BANDS = {**{k: _Legacy(v) for k, v in spec.LEGACY_BANDS.items()}, **BANDS}


def weekly_sample(manifests: list[dict]) -> list[str]:
    """As-of dates that tracking and evidence use (spec SNAPSHOT_CADENCE_RULE): for each methodology version and
    ISO week, the latest stored session. Other daily snapshots are stored and shown, never tracked, so overlapping
    daily baskets cannot inflate the record."""
    latest: dict[tuple, str] = {}
    for m in manifests:
        day = date.fromisoformat(str(m["as_of"]))
        key = (str(m.get("spec_version")), *day.isocalendar()[:2])
        latest[key] = max(latest.get(key, ""), str(m["as_of"]))
    return sorted(set(latest.values()))


# Computation revision (code, not a registered rule): the registered TRACKING_METHOD and TRACK_HORIZONS are unchanged.
# Before this revision, an entry close missing on the snapshot day made a not-yet-matured horizon "unavailable", a
# missing bar moved an endpoint to a later session, partial baskets entered the averages, and summaries, turnover and
# weekly chains pooled methodology versions. No horizon had completed when it was introduced.
MEASUREMENT_REVISION = {
    "date": "2026-11-04",
    "rule": (
        "Every stock and its benchmark are measured between the same two NYSE sessions: the snapshot's as-of close "
        "and exactly N sessions later (TRACK_HORIZONS). A horizon is pending until that session has passed and its "
        "closes are published. A missing entry or exit close is reported as missing, never bridged to another "
        "session. A basket counts as complete only when every published pick and the benchmark have both closes; "
        "incomplete baskets are shown with their measurable count and left out of the completed-basket averages. "
        "Summaries, turnover and weekly chains are computed separately for each methodology version. Prices pass the "
        "same validation as ranking (PRICE_BAR_RULE, including the close-verified end-of-session quote bar when the "
        "history file lags)."
    ),
    "previous": (
        "Before 2026-11-04 the tracking file used unvalidated provider history, positional session counts and "
        "category aggregates across versions. No 1-, 3-, 6- or 12-month result had completed under it."
    ),
}
PENDING, MISSING_ENTRY, MISSING_EXIT = "pending", "missing entry price", "missing exit price"
BENCHMARK_UNAVAILABLE, INCOMPLETE, UNAVAILABLE = "benchmark unavailable", "incomplete", "unavailable"


@lru_cache(maxsize=4096)
def sessions_elapsed(start: date, as_of: date) -> int:
    """NYSE sessions after `start` up to and including `as_of` (spec.TRACK_HORIZONS count trading days).

    Weekday counting (np.busday_count) overstates this by one for every exchange holiday in the window, which
    used to mark every complete series as a possible delisting on the day a horizon fell due in a holiday week."""
    n, d = 0, start
    while d < as_of:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n


@lru_cache(maxsize=4096)
def session_after(start: date, bars: int) -> date:
    """The NYSE session exactly `bars` sessions after `start`: the registered endpoint of a horizon."""
    n, d = 0, start
    while n < bars:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return d


def kind(status: str) -> str:
    """The class of a forward_return status: ok, pending, missing entry price or missing exit price."""
    return status.split(":", 1)[0]


def forward_return(close: pd.Series | None, start: date, bars: int, as_of: date) -> tuple[float | None, str]:
    """(price return from the `start` close to the close exactly `bars` NYSE sessions later, status).

    Statuses: "ok"; "pending" until the endpoint session has passed (on the endpoint session itself, also while
    its close is not yet published); "missing entry price: ..." without a close on `start`; "missing exit
    price: ..." without a close on the endpoint session. A missing bar never moves the endpoint to another session."""
    end = session_after(start, bars)
    if end > as_of:
        return None, PENDING
    if close is None or close.empty:
        return None, f"{MISSING_ENTRY}: no validated price data"
    if pd.Timestamp(start) not in close.index:
        return None, f"{MISSING_ENTRY}: no close on {start}"
    te = pd.Timestamp(end)
    if te in close.index:
        return float(close.loc[te] / close.loc[pd.Timestamp(start)] - 1), "ok"
    last = close.index[-1].date()
    if end == as_of and sessions_elapsed(last, as_of) == 1:
        return None, f"{PENDING}: the {end} close is not yet published"
    if last < end:
        return None, f"{MISSING_EXIT}: prices stop on {last} (possible delisting or ticker change)"
    return None, f"{MISSING_EXIT}: no close on the {end} session"


def _basket(tickers: list[str], prices: dict, benchmark: str, start: date, bars: int, as_of: date, fric: float) -> dict:
    end = session_after(start, bars)
    base = {"entry_session": start.isoformat(), "exit_session": end.isoformat(), "n": len(tickers)}
    if end > as_of:
        return {"status": PENDING, **base, "measured": 0, "unavailable": []}
    results = [(t, *forward_return(prices.get(t), start, bars, as_of)) for t in tickers]
    b, b_status = forward_return(prices.get(benchmark), start, bars, as_of)
    if any(kind(st) == PENDING for _, _, st in results) or kind(b_status) == PENDING:
        return {"status": PENDING, **base, "measured": 0, "unavailable": [], "note": "closing prices not yet published"}
    rets = [r for _, r, _ in results if r is not None]
    missing = [{"ticker": t, "status": st} for t, r, st in results if r is None]
    row = {
        **base,
        "measured": len(rets),
        "unavailable": missing,
        "missing_entry": sum(kind(m["status"]) == MISSING_ENTRY for m in missing),
        "missing_exit": sum(kind(m["status"]) == MISSING_EXIT for m in missing),
        "benchmark_status": b_status,
    }
    if not rets:
        return {"status": UNAVAILABLE, **row}
    gross = float(np.mean(rets))
    net = gross - fric
    complete = not missing and b is not None
    row.update(
        status="ok" if complete else (INCOMPLETE if missing else BENCHMARK_UNAVAILABLE),
        gross=gross,
        net=net,
        benchmark=b,
        excess_net=None if b is None else net - b,
        hit_rate=float(np.mean([r > b for r in rets])) if b is not None else None,
    )
    if not complete:  # a partial basket is not the registered equal-weighted basket of every published pick
        row["note"] = "not counted in completed-basket averages"
    return row


def track(snapshots: list[dict], prices: dict[str, pd.Series], as_of: date, price_source: dict | None = None) -> dict:
    """Per spec version, band and horizon: basket returns net of friction vs the benchmark."""
    out: dict = {
        "method": spec.TRACKING_METHOD,
        "measurement_revision": MEASUREMENT_REVISION,
        "as_of": as_of.isoformat(),
        "by_snapshot": [],
        "by_version": [],
        "evidence_note": "",
    }
    if price_source:
        out["prices"] = price_source
    versions: dict[str, dict] = {}
    for snap in snapshots:
        s_date = date.fromisoformat(str(snap["as_of"]))
        version = str(snap.get("spec_version", "?"))
        vb = versions.setdefault(version, {"snapshots": [], "prev": {}, "chain": {}, "skipped": {}, "turnover": {}})
        vb["snapshots"].append(s_date.isoformat())
        for key, band in snap.get("bands", {}).items():
            tickers = [c["ticker"] for c in band.get("candidates", [])]
            cfg = ALL_BANDS.get(key)
            if cfg is None or not tickers:
                continue
            fric = 2 * cfg.friction_bps_per_side / 1e4
            row = {
                "as_of": s_date.isoformat(),
                "spec_version": version,
                "band": key,
                "n": len(tickers),
                "benchmark": cfg.benchmark,
                "horizons": {
                    h: _basket(tickers, prices, cfg.benchmark, s_date, bars, as_of, fric)
                    for h, bars in spec.TRACK_HORIZONS.items()
                },
            }
            prev = vb["prev"].get(key)
            cur = set(tickers)
            to = 1.0
            if prev is not None:  # turnover only against the previous weekly list of the same version
                to = 1 - len(prev & cur) / max(len(prev), 1)
                vb["turnover"].setdefault(key, []).append({"as_of": s_date.isoformat(), "turnover": to})
            vb["prev"][key] = cur
            # one-week holding chain (each week's basket held five sessions), full baskets only
            week = [forward_return(prices.get(t), s_date, 5, as_of) for t in tickers]
            vals = [r for r, _ in week if r is not None]
            if len(vals) == len(tickers):
                vb["chain"].setdefault(key, []).append((s_date.isoformat(), float(np.mean(vals)) - to * fric))
            elif not any(kind(st) == PENDING for _, st in week):
                vb["skipped"].setdefault(key, []).append(s_date.isoformat())
            out["by_snapshot"].append(row)
    for version, vb in versions.items():
        rows = [r for r in out["by_snapshot"] if r["spec_version"] == version]
        summary = {}
        for key in sorted({r["band"] for r in rows}):
            band_rows = [r for r in rows if r["band"] == key]
            summ: dict = {}
            for h in spec.TRACK_HORIZONS:
                hs = [r["horizons"][h] for r in band_rows]
                ex = [x["excess_net"] for x in hs if x["status"] == "ok"]
                summ[h] = {
                    "snapshots_measured": len(ex),
                    "incomplete": sum(x["status"] in (INCOMPLETE, BENCHMARK_UNAVAILABLE, UNAVAILABLE) for x in hs),
                    "pending": sum(x["status"] == PENDING for x in hs),
                    "mean_excess_net": float(np.mean(ex)) if ex else None,
                    "share_beating_benchmark": float(np.mean([e > 0 for e in ex])) if ex else None,
                }
            to = [t["turnover"] for t in vb["turnover"].get(key, [])]
            summ["mean_weekly_turnover"] = float(np.mean(to)) if to else None
            summary[key] = summ
        chains = {}
        for key, pts in vb["chain"].items():
            eq = np.cumprod([1 + r for _, r in pts])
            peak = np.maximum.accumulate(eq)
            chains[key] = {
                "weeks": len(pts),
                "first": pts[0][0],
                "last": pts[-1][0],
                "cumulative_net": float(eq[-1] - 1),
                "max_drawdown": float((eq / peak - 1).min()),
                "skipped_incomplete": vb["skipped"].get(key, []),
                "note": "Each week's list held five sessions, friction charged on turnover within this version.",
            }
        for key, skipped in vb["skipped"].items():
            chains.setdefault(key, {"weeks": 0, "skipped_incomplete": skipped})
        out["by_version"].append(
            {
                "spec_version": version,
                "first_as_of": vb["snapshots"][0],
                "last_as_of": vb["snapshots"][-1],
                "weekly_snapshots": len(vb["snapshots"]),
                "summary": summary,
                "turnover": vb["turnover"],
                "weekly_chain": chains,
                "evidence_note": _evidence_note(len(vb["snapshots"])),
            }
        )
    note = _evidence_note(len(snapshots))
    out["evidence_note"] = note + (
        " Results are never pooled across methodology versions." if len(versions) > 1 else ""
    )
    out["friction"] = {k: b.friction_bps_per_side for k, b in ALL_BANDS.items()}
    out["limitations"] = [
        "Price returns only: dividends are excluded, which understates returns of dividend payers and benchmarks.",
        "Delisting returns are not available from the data sources; affected names are listed as unavailable.",
        "Friction is an assumption (bps per side), not measured execution cost.",
    ]
    out["decision_desk"] = track_desk(snapshots, prices, as_of)
    return _finite(out)


def _evidence_note(n: int) -> str:
    return (
        f"{n} weekly snapshot(s). No edge is claimed: at least {spec.MIN_SNAPSHOTS_FOR_EVIDENCE} snapshots and a "
        "statistical test are needed first."
        if n < spec.MIN_SNAPSHOTS_FOR_EVIDENCE
        else f"{n} weekly snapshots. Overlapping holding periods make naive t-statistics overstate significance; "
        "treat these figures as descriptive."
    )


def version_blocks(tracking: dict | None) -> list[dict] | None:
    """Per-version results of a tracking file, or None for a file written before MEASUREMENT_REVISION."""
    if not tracking or "by_version" not in tracking:
        return None
    return list(tracking["by_version"])


def track_desk(snapshots: list[dict], prices: dict[str, pd.Series], as_of: date) -> dict:
    """Mean excess price return by Buy/Sell desk rating (spec.DESK_TRACKING). Only ratings stored in a snapshot
    count; previews computed while building the site are never stored, so they can never enter this record."""
    rated = [s for s in snapshots if (s.get("decision_desk") or {}).get("entries")]
    by_rating = {}
    for rating in reversed(spec.DESK_RATINGS):
        by_rating[rating] = {}
        for h, bars in spec.TRACK_HORIZONS.items():
            excess, pending, unavailable = [], 0, 0
            for snap in rated:
                start = date.fromisoformat(str(snap["as_of"]))
                for e in snap["decision_desk"]["entries"]:
                    if e.get("rating") != rating:
                        continue
                    r, status = forward_return(prices.get(e["ticker"]), start, bars, as_of)
                    b, _ = forward_return(prices.get(e.get("benchmark") or ""), start, bars, as_of)
                    if r is not None and b is not None:
                        excess.append(r - b)
                    elif kind(status) == PENDING:
                        pending += 1
                    else:
                        unavailable += 1
            by_rating[rating][h] = {
                "measured": len(excess),
                "pending": pending,
                "unavailable": unavailable,
                "mean_excess": float(np.mean(excess)) if excess else None,
                "share_beating_benchmark": float(np.mean([x > 0 for x in excess])) if excess else None,
            }
    return {
        "method": spec.DESK_TRACKING,
        "snapshots_with_ratings": len(rated),
        "first_rated": str(rated[0]["as_of"]) if rated else None,
        "by_rating": by_rating,
        "evidence_note": (
            f"{len(rated)} snapshot(s) with stored ratings. No edge is claimed: at least "
            f"{spec.MIN_SNAPSHOTS_FOR_EVIDENCE} are needed first."
            if len(rated) < spec.MIN_SNAPSHOTS_FOR_EVIDENCE
            else f"{len(rated)} snapshots with stored ratings; overlapping periods make these figures descriptive only."
        ),
    }


def _finite(x):
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_finite(v) for v in x]
    return x
