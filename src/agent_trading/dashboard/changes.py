"""'What changed since the previous snapshot?' for one listed company (spec 2026-10-14.5, CHANGE_RULES).

Compares two immutable snapshots: new filings, deterioration in reported figures, dilution, breaches of the
thesis conditions recorded in the earlier snapshot, and changes in which inputs were available. When no
comparable earlier record exists it says why instead of comparing different things.
"""
from __future__ import annotations

import math

from . import scenarios, spec
from .fmt import pct
from .research import EDGAR_FILINGS


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def find(snap: dict | None, ticker: str, band: str) -> tuple[dict | None, str | None]:
    """The ticker's candidate record in `snap`: the same list first, else any list (and which one)."""
    if not snap:
        return None, None
    bands = snap.get("bands") or {}
    for c in (bands.get(band) or {}).get("candidates", []):
        if c["ticker"] == ticker:
            return c, band
    for key, b in bands.items():
        for c in b.get("candidates", []):
            if c["ticker"] == ticker:
                return c, key
    return None, None


def compare(c: dict, snap: dict, prev_snap: dict | None) -> dict:
    """{"status": "compared" | "first_snapshot" | "not_listed_before", "previous", "notes", "items"}."""
    if not prev_snap:
        return {"status": "first_snapshot", "previous": None, "items": [],
                "notes": ["This is the first stored snapshot, so there is nothing earlier to compare with."]}
    prev, prev_band = find(prev_snap, c["ticker"], c["band"])
    p_date = str(prev_snap["as_of"])
    if prev is None:
        return {"status": "not_listed_before", "previous": p_date, "items": [],
                "notes": [f"{c['ticker']} was not on any list in the previous snapshot ({p_date}), and snapshots "
                          "store details only for listed names, so there is no earlier record to compare with."]}
    notes = []
    if prev_band != c["band"]:
        notes.append(f"In {p_date} it was on the {prev_band} list; figures are compared, list ranks are not.")
    if prev_snap.get("spec_version") != snap.get("spec_version"):
        notes.append(f"The rules version changed from {prev_snap.get('spec_version')} to {snap.get('spec_version')}; "
                     "score moves may partly reflect that change.")
    items = []
    m, pm = c.get("metrics") or {}, prev.get("metrics") or {}
    f, pf = c.get("fundamentals") or {}, prev.get("fundamentals") or {}
    rules = spec.CHANGE_RULES
    cik = c.get("cik")

    def link(form):
        return EDGAR_FILINGS.format(cik=int(cik), form=form) if cik else None

    # filings
    if f.get("last_filed") and f.get("last_filed") != pf.get("last_filed"):
        items.append({"kind": "filing", "text": f"New {f.get('last_form') or 'filing'} filed {f['last_filed']} "
                      f"(previous snapshot used {pf.get('last_form') or 'a filing'} filed {pf.get('last_filed') or 'n/a'}).",
                      "source": link(f.get("last_form") or "10-Q"), "date": f["last_filed"]})
    q, pq = (f.get("quarters") or [None])[0], (pf.get("quarters") or [None])[0]
    if q and pq and q != pq:
        items.append({"kind": "filing", "text": f"A new fiscal quarter (ending {q}) is now in the trailing figures.",
                      "source": link("10-Q"), "date": q})
    ec, pec = c.get("earnings_check") or {}, prev.get("earnings_check") or {}
    if ec.get("last_results") and ec.get("last_results") != pec.get("last_results"):
        items.append({"kind": "filing", "text": f"New results release (8-K item 2.02) filed {ec['last_results']}.",
                      "source": link("8-K"), "date": ec["last_results"]})

    # deterioration in reported figures
    for key, label, limit in (("revenue_growth_ttm", "Trailing revenue growth", rules["revenue_growth_drop"]),
                              ("operating_margin", "Operating margin", rules["operating_margin_drop"]),
                              ("fcf_margin", "Free-cash-flow margin", rules["fcf_margin_drop"])):
        a, b = m.get(key), pm.get(key)
        if _ok(a) and _ok(b) and b - a >= limit:
            items.append({"kind": "deterioration", "text": f"{label} fell from {pct(b, 1)} to {pct(a, 1)} "
                          f"({pct(a - b, 1, True)}; listed when down {pct(limit, 0)} or more).", "source": link("10-Q"),
                          "date": q})
    if _ok(m.get("fcf_ttm")) and _ok(pm.get("fcf_ttm")) and m["fcf_ttm"] < 0 <= pm["fcf_ttm"]:
        items.append({"kind": "deterioration", "text": "Trailing free cash flow turned negative.", "source": link("10-Q"),
                      "date": q})
    a, b = m.get("dilution"), pm.get("dilution")
    if _ok(a) and _ok(b) and a - b >= rules["dilution_rise"]:
        items.append({"kind": "dilution", "text": f"One-year share-count change rose from {pct(b, 1, True)} to "
                      f"{pct(a, 1, True)}.", "source": link("10-Q"), "date": q})
    elif _ok(a) and not _ok(b):
        items.append({"kind": "dilution", "text": f"Share-count change is now measurable ({pct(a, 1, True)}).",
                      "source": link("10-Q"), "date": q})

    # thesis conditions recorded in the previous snapshot, checked against this one
    for cond in scenarios.thesis_conditions(pm, prev.get("scenarios")):
        status, observed = scenarios.check_condition(cond, m, f)
        if status == "breached":
            items.append({"kind": "thesis", "text": f"Condition from {p_date} breached: {cond['text']}",
                          "source": link("10-Q"), "date": str(snap["as_of"])})

    # data availability
    now_missing, was_missing = set(c.get("missing") or []), set(prev.get("missing") or [])
    for k in sorted(now_missing - was_missing):
        items.append({"kind": "data", "text": f"{k.replace('_', ' ')} is no longer available (scored 0).",
                      "source": None, "date": str(snap["as_of"])})
    for k in sorted(was_missing - now_missing):
        items.append({"kind": "data", "text": f"{k.replace('_', ' ')} is now available.", "source": None,
                      "date": str(snap["as_of"])})
    if c.get("confidence_label") != prev.get("confidence_label"):
        items.append({"kind": "data", "text": f"Data confidence changed from {prev.get('confidence_label')} to "
                      f"{c.get('confidence_label')}.", "source": None, "date": str(snap["as_of"])})

    # score and rank
    sc, psc = c.get("composite"), prev.get("composite")
    if _ok(sc) and _ok(psc) and abs(sc - psc) >= rules["score_move"]:
        items.append({"kind": "score", "text": f"Score moved from {psc:.1f} to {sc:.1f}.", "source": None,
                      "date": str(snap["as_of"])})
    if not items:
        notes.append("No new filing, listed deterioration, dilution change, thesis breach or data-availability "
                     "change since the previous snapshot.")
    return {"status": "compared", "previous": p_date, "items": items, "notes": notes}


KIND_LABELS = {"filing": "New filing", "deterioration": "Deterioration", "dilution": "Dilution", "thesis": "Thesis",
               "data": "Data", "score": "Score"}


def summary(snap: dict, prev_snap: dict | None) -> dict:
    """Counts and items across every listed name, for the overview."""
    rows = []
    for key, band in (snap.get("bands") or {}).items():
        for c in band.get("candidates", []):
            r = compare(c, snap, prev_snap)
            for it in r["items"]:
                rows.append({**it, "ticker": c["ticker"], "band": key})
    counts = {k: sum(1 for r in rows if r["kind"] == k) for k in KIND_LABELS}
    return {"previous": str(prev_snap["as_of"]) if prev_snap else None, "rows": rows, "counts": counts}
