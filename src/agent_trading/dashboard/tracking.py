"""Forward performance of past weekly research lists (spec.TRACKING_METHOD).

Only prices AFTER a snapshot's as-of close are used to judge it, and each
snapshot's list is taken exactly as it was saved, so there is no look-ahead and
no hindsight reselection. Candidates whose prices stop are reported as
unavailable (possible delisting) instead of being dropped.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from . import spec

BANDS = {b.key: b for b in spec.BANDS}


class _Legacy:
    """A list retired by a later spec version, still tracked from old snapshots."""

    def __init__(self, info: dict) -> None:
        self.benchmark = info["benchmark"]
        self.friction_bps_per_side = info["friction_bps_per_side"]


ALL_BANDS = {**{k: _Legacy(v) for k, v in spec.LEGACY_BANDS.items()}, **BANDS}


def forward_return(close: pd.Series | None, start: date, bars: int, as_of: date) -> tuple[float | None, str]:
    """(price return from the `start` close to `bars` sessions later, status)."""
    if close is None or close.empty:
        return None, "no price data"
    ts = pd.Timestamp(start)
    if ts not in close.index:
        return None, "no close on the snapshot date"
    i = close.index.get_loc(ts)
    j = i + bars
    if j < len(close):
        return float(close.iloc[j] / close.iloc[i] - 1), "ok"
    sessions_elapsed = int(np.busday_count(start, as_of))
    if sessions_elapsed >= bars:
        return None, f"prices stop on {close.index[-1].date()} (possible delisting or ticker change)"
    return None, "pending"


def track(snapshots: list[dict], prices: dict[str, pd.Series], as_of: date) -> dict:
    """Per spec version, band and horizon: basket returns net of friction vs the benchmark."""
    out = {"method": spec.TRACKING_METHOD, "as_of": as_of.isoformat(), "by_snapshot": [], "summary": {},
           "turnover": {}, "weekly_chain": {}, "evidence_note": ""}
    prev_lists: dict[str, set] = {}
    chain: dict[str, list[tuple[str, float]]] = {}
    for snap in snapshots:
        s_date = date.fromisoformat(str(snap["as_of"]))
        version = snap.get("spec_version", "?")
        for key, band in snap.get("bands", {}).items():
            tickers = [c["ticker"] for c in band.get("candidates", [])]
            cfg = ALL_BANDS.get(key)
            if cfg is None or not tickers:
                continue
            fric = 2 * cfg.friction_bps_per_side / 1e4
            row = {"as_of": s_date.isoformat(), "spec_version": version, "band": key, "n": len(tickers),
                   "horizons": {}}
            for h, bars in spec.TRACK_HORIZONS.items():
                rets, unavailable, pending = [], [], 0
                for t in tickers:
                    r, status = forward_return(prices.get(t), s_date, bars, as_of)
                    if r is not None:
                        rets.append(r)
                    elif status == "pending":
                        pending += 1
                    else:
                        unavailable.append({"ticker": t, "status": status})
                b, b_status = forward_return(prices.get(cfg.benchmark), s_date, bars, as_of)
                if pending or not rets:
                    row["horizons"][h] = {"status": "pending" if pending else "unavailable",
                                          "unavailable": unavailable}
                    continue
                gross = float(np.mean(rets))
                net = gross - fric
                row["horizons"][h] = {"status": "ok", "gross": gross, "net": net, "benchmark": b,
                                      "excess_net": None if b is None else net - b, "measured": len(rets),
                                      "unavailable": unavailable,
                                      "hit_rate": float(np.mean([r > (b or 0) for r in rets])) if b is not None else None}
            prev = prev_lists.get(key)
            cur = set(tickers)
            if prev is not None:
                to = 1 - len(prev & cur) / max(len(prev), 1)
                out["turnover"].setdefault(key, []).append({"as_of": s_date.isoformat(), "turnover": to})
            prev_lists[key] = cur
            # one-week holding chain (each week's basket held to the next session five days later)
            r1, _ = zip(*[forward_return(prices.get(t), s_date, 5, as_of) for t in tickers]) if tickers else ((), ())
            vals = [r for r in r1 if r is not None]
            if vals and len(vals) == len(tickers):
                to = out["turnover"].get(key, [{}])[-1].get("turnover", 1.0) if prev is not None else 1.0
                chain.setdefault(key, []).append((s_date.isoformat(), float(np.mean(vals)) -
                                                  to * fric))
            out["by_snapshot"].append(row)
    for key, pts in chain.items():
        eq = np.cumprod([1 + r for _, r in pts])
        peak = np.maximum.accumulate(eq)
        out["weekly_chain"][key] = {"weeks": len(pts), "cumulative_net": float(eq[-1] - 1),
                                    "max_drawdown": float((eq / peak - 1).min()),
                                    "note": "Each week's list held five sessions, friction charged on turnover."}
    for key in sorted({r["band"] for r in out["by_snapshot"]} | set(BANDS)):
        rows = [r for r in out["by_snapshot"] if r["band"] == key]
        summ = {}
        for h in spec.TRACK_HORIZONS:
            done = [r["horizons"][h] for r in rows if r["horizons"].get(h, {}).get("status") == "ok"]
            ex = [d["excess_net"] for d in done if d["excess_net"] is not None]
            summ[h] = {"snapshots_measured": len(done),
                       "mean_excess_net": float(np.mean(ex)) if ex else None,
                       "share_beating_benchmark": float(np.mean([e > 0 for e in ex])) if ex else None}
        to = [t["turnover"] for t in out["turnover"].get(key, [])]
        summ["mean_weekly_turnover"] = float(np.mean(to)) if to else None
        out["summary"][key] = summ
    n = len(snapshots)
    out["evidence_note"] = (
        f"{n} weekly snapshot(s). No edge is claimed: at least {spec.MIN_SNAPSHOTS_FOR_EVIDENCE} snapshots and a "
        "statistical test are needed first." if n < spec.MIN_SNAPSHOTS_FOR_EVIDENCE else
        f"{n} weekly snapshots. Overlapping holding periods make naive t-statistics overstate significance; "
        "treat these figures as descriptive.")
    out["friction"] = {k: b.friction_bps_per_side for k, b in ALL_BANDS.items()}
    out["limitations"] = [
        "Price returns only: dividends are excluded, which understates returns of dividend payers and benchmarks.",
        "Delisting returns are not available from the data sources; affected names are listed as unavailable.",
        "Friction is an assumption (bps per side), not measured execution cost.",
    ]
    return _finite(out)


def _finite(x):
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _finite(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_finite(v) for v in x]
    return x
