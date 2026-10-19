"""Company research panel: deterministic trends, evidence, forensics, events and thesis checks (spec 2026-10-14.5).

The section structure is adapted from cc-equity-research (Apache-2.0,
https://github.com/prof-little-bear/cc-equity-research at 7c428944a6718c35461f839c618ae66334b6371b):
* `anthropic-equity-research-skills/thesis-tracker` and `community-skills/monitor/thesis-check.md` -> the
  thesis is checked against the conditions recorded when the name first appeared, never a refreshed one;
* `community-skills/analyze/financial-forensics.md` -> the FCF-vs-net-income and SBC patterns with their
  thresholds (spec.FORENSIC_RULES); the four patterns that need data this project does not collect are listed
  as missing information instead of being guessed;
* `anthropic-equity-research-skills/catalyst-calendar` -> dated events, each marked verified, scheduled
  (unverified) or estimated.
Those templates are prompts for a language model; here every sentence is produced by fixed rules from stored
figures, and nothing is generated, so no figure, probability or price target can be invented.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta

from . import evidence as evidence_mod
from . import scenarios, spec
from .fmt import cap, metric, pct
from .fundamentals import consecutive, quarter_back

EDGAR_FILINGS = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=40"
)
SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def _year_back(quarters: list, years: int) -> int | None:
    try:
        return quarter_back(list(quarters), 0, years)
    except (TypeError, ValueError):
        return None


def _ttm(values: list, quarters: list, years: int = 0):
    """Four adjacent stored quarters starting about `years` before the newest (spec 2026-10-19.2)."""
    start = _year_back(quarters, years)
    if start is None or not consecutive(list(quarters), start):
        return None
    window = values[start : start + 4]
    return sum(window) if len(window) == 4 and all(_ok(v) for v in window) else None


def _direction(newest, older) -> str:
    if not (_ok(newest) and _ok(older)):
        return "not measurable"
    d = newest - older
    return "flat" if abs(d) <= spec.TREND_FLAT_BAND else ("rising" if d > 0 else "falling")


def trends(c: dict) -> list[dict]:
    """Quarterly observations, newest first, with the direction over the year (spec.TREND_FLAT_BAND)."""
    f = c.get("fundamentals") or {}
    q = f.get("quarters") or []
    rev = f.get("revenue") or []
    out = []
    yoy = scenarios.quarterly_yoy(rev, q)
    if yoy:
        out.append(
            {
                "label": "Revenue growth, year over year",
                "quarters": q[: len(yoy)],
                "values": yoy,
                "direction": _direction(yoy[0], yoy[-1]),
                "kind": "pct",
            }
        )

    def margin(key):
        vals = [(a / r if _ok(a) and _ok(r) and r > 0 else None) for a, r in zip(f.get(key) or [], rev, strict=False)]
        return vals[:4]

    for key, label in (("gross_profit", "Gross margin"), ("operating_income", "Operating margin")):
        vals = margin(key)
        if any(_ok(v) for v in vals):
            out.append(
                {
                    "label": f"{label} by quarter",
                    "quarters": q[: len(vals)],
                    "values": vals,
                    "direction": _direction(vals[0], vals[-1]),
                    "kind": "pct",
                }
            )
    ocf, capex = f.get("ocf") or [], f.get("capex") or []
    fcf = [
        (o - x if _ok(o) and _ok(x) else None) for o, x in zip(ocf, capex, strict=False)
    ]  # as scoring.compute_metrics
    now, before = _ttm(fcf, q), _ttm(fcf, q, 1)
    r_now, r_before = _ttm(rev, q), _ttm(rev, q, 1)
    prior = _year_back(q, 1)
    labels = [q[0] if q else "", q[prior] if prior is not None else ""]
    if _ok(now) and _ok(r_now) and r_now > 0:
        vals = [now / r_now] + ([before / r_before] if _ok(before) and _ok(r_before) and r_before > 0 else [])
        out.append(
            {
                "label": "Free-cash-flow margin, trailing 4 quarters (latest, year before)",
                "quarters": labels[: len(vals)],
                "values": vals,
                "direction": _direction(vals[0], vals[1]) if len(vals) == 2 else "not measurable",
                "kind": "pct",
            }
        )
    sbc = f.get("sbc") or []
    s_now = _ttm(sbc, q)
    if _ok(s_now) and _ok(r_now) and r_now > 0:
        s_before = _ttm(sbc, q, 1)
        vals = [s_now / r_now] + ([s_before / r_before] if _ok(s_before) and _ok(r_before) and r_before > 0 else [])
        out.append(
            {
                "label": "Stock-based pay as % of revenue, trailing 4 quarters (latest, year before)",
                "quarters": labels[: len(vals)],
                "values": vals,
                "direction": _direction(vals[0], vals[1]) if len(vals) == 2 else "not measurable",
                "kind": "pct",
            }
        )
    return out


def forensics(c: dict) -> list[dict]:
    """The two forensic patterns this project's data supports, scored Clean / Watch / Concerning."""
    f, m = c.get("fundamentals") or {}, c.get("metrics") or {}
    rules = spec.FORENSIC_RULES
    out = []
    ni = _ttm(f.get("net_income") or [], f.get("quarters") or [])
    fcf = m.get("fcf_ttm")
    r = rules["fcf_to_net_income"]
    if _ok(ni) and ni > 0 and _ok(fcf):
        ratio = fcf / ni
        verdict = (
            "Clean" if ratio >= r["clean_at_least"] else "Concerning" if ratio < r["concerning_below"] else "Watch"
        )
        out.append(
            {"pattern": "Free cash flow vs net income", "value": f"{ratio:.2f}x", "verdict": verdict, "note": r["note"]}
        )
    else:
        out.append(
            {"pattern": "Free cash flow vs net income", "value": "n/a", "verdict": "Not meaningful", "note": r["note"]}
        )
    s = rules["sbc_to_revenue"]
    v = m.get("sbc_to_revenue")
    if _ok(v):
        verdict = "Clean" if v < s["clean_below"] else "Concerning" if v > s["concerning_above"] else "Watch"
        dil = m.get("dilution")
        out.append(
            {
                "pattern": "Stock-based pay and dilution",
                "value": f"{pct(v)} of revenue" + (f"; shares {pct(dil, 1, True)} in a year" if _ok(dil) else ""),
                "verdict": verdict,
                "note": s["note"],
            }
        )
    else:
        out.append(
            {"pattern": "Stock-based pay and dilution", "value": "n/a", "verdict": "Not measurable", "note": s["note"]}
        )
    return out


def evidence(c: dict, profile: tuple) -> tuple[list[str], list[str]]:
    """(supporting, counter): the strongest and weakest scored components with their inputs."""
    comps = [(cp, c["components"].get(cp.key)) for cp in profile]
    scored = sorted([(cp, v) for cp, v in comps if _ok(v)], key=lambda x: -x[1])
    m = c.get("metrics") or {}

    def inputs(cp):
        return "; ".join(f"{k.replace('_', ' ')} {metric(k, m.get(k))}" for k in cp.metrics if _ok(m.get(k)))

    support = [
        f"{cp.title}: {round(v * 100)}/100 ({inputs(cp) or 'inputs missing'})." for cp, v in scored[:3] if v >= 0.5
    ]
    counter = [
        f"{cp.title}: {round(v * 100)}/100 ({inputs(cp) or 'inputs missing'})." for cp, v in scored[::-1][:2] if v < 0.5
    ]
    counter += [f"Missing {cp.title.lower()} (scored 0)." for cp, v in comps if not _ok(v)]
    if c.get("bear_case"):
        counter.append(c["bear_case"])
    counter += [r for r in c.get("risks") or [] if not r.startswith("No rule-based risk flag")]
    return support, counter


def assumptions(c: dict) -> list[str]:
    sc = c.get("scenarios")
    out = [
        f"Prices are the {c.get('price_date')} delayed close; returns exclude dividends.",
        "Fundamentals are SEC XBRL facts filed by the as-of date, in USD as reported; TTM = last four quarters.",
    ]
    if sc:
        a = sc["base"]["assumptions"]
        out.append(
            f"Base case: revenue growth starts at {pct(a['starting_revenue_growth'])} and fades "
            f"{pct(spec.SCENARIO_GROWTH_FADE)} of the way to {pct(spec.SCENARIO_TERMINAL_GROWTH)} each year; "
            f"EV/Sales moves to {a['exit_ev_to_sales']:.1f}x; shares change {pct(a['annual_dilution'], 1, True)} a year; "
            "net cash held flat."
        )
    else:
        out.append(c.get("scenario_note") or "No valuation scenario for this name.")
    m = c.get("metrics") or {}
    if _ok(m.get("implied_revenue_cagr")):
        out.append(
            scenarios.implied_growth_text(m["implied_revenue_cagr"], m.get("revenue_growth_ttm"))
            + " (under the dashboard's fixed valuation assumptions)."
        )
    return out


def events(c: dict, as_of: str, snap: dict | None = None) -> list[dict]:
    """Dated events: verified (SEC filing), scheduled (unverified) or estimated, newest information first."""
    out = []
    lookup_ok = snap is None or evidence_mod.earnings_state(snap)[0] == "available"
    ec = c.get("earnings_check") or {}
    if c.get("next_earnings"):
        from .earnings_cadence import BROKER_NOTE
        from .earnings_cadence import display as cadence_display
        from .earnings_verdicts import label, verdict_for

        v = verdict_for(snap, c.get("ticker", ""), c["next_earnings"])
        agreed = v is not None and v["status"] == "verified"
        cadence = (
            cadence_display(ec, BROKER_NOTE) if agreed and ec.get("cadence_check") else (ec.get("cadence_check") or "")
        )
        notes = ([] if v is None or agreed else [label(v)]) + [cadence]
        out.append(
            {
                "date": c["next_earnings"],
                "event": "Earnings report (scheduled)",
                "status": "verified (broker calendar)" if agreed else "unverified",
                "source": "Alpha Vantage earnings calendar" + (" + Robinhood calendar (read-only)" if agreed else ""),
                "note": "; ".join(n for n in notes if n),
            }
        )
    else:
        out.append(
            {
                "date": None,
                "event": "Next earnings report",
                "status": "unknown",
                "source": "Alpha Vantage earnings calendar",
                "note": (
                    "the calendar lookup succeeded but lists no date for this company"
                    if lookup_ok
                    else "the calendar lookup was unavailable for this snapshot (see the data status on the audit page)"
                ),
            }
        )
    if ec.get("last_results"):
        out.append(
            {
                "date": ec["last_results"],
                "event": "Last results release (8-K item 2.02)",
                "status": "verified",
                "source": "SEC EDGAR",
                "note": "",
            }
        )
    f = c.get("fundamentals") or {}
    if f.get("last_filed"):
        try:
            nxt = date.fromisoformat(f["last_filed"]) + timedelta(days=91)
            out.append(
                {
                    "date": nxt.isoformat(),
                    "event": "Next 10-Q/10-K (estimate)",
                    "status": "estimated",
                    "source": f"91 days after the {f.get('last_form') or 'last'} filed {f['last_filed']}",
                    "note": "overdue" if nxt.isoformat() < as_of else "",
                }
            )
        except ValueError:
            pass
    return out


def original_conditions(ticker: str, band: str, history: list[dict]) -> tuple[str | None, list[dict], dict | None]:
    """(snapshot date, conditions, candidate) from the first snapshot where `ticker` appeared on `band`."""
    for s in sorted(history, key=lambda s: str(s["as_of"])):
        for c in (s.get("bands") or {}).get(band, {}).get("candidates", []):
            if c["ticker"] == ticker:
                return str(s["as_of"]), scenarios.thesis_conditions(c.get("metrics") or {}, c.get("scenarios")), c
    return None, [], None


def thesis_check(c: dict, history: list[dict]) -> dict:
    """Conditions recorded when the name first appeared, checked against this snapshot (spec.THESIS_TRACKING_RULE)."""
    since, conds, _ = original_conditions(c["ticker"], c["band"], history)
    if since is None:
        since, conds = None, scenarios.thesis_conditions(c.get("metrics") or {}, c.get("scenarios"))
    rows = []
    for cond in conds:
        status, observed = scenarios.check_condition(cond, c.get("metrics") or {}, c.get("fundamentals"))
        if isinstance(observed, list):
            shown = ", ".join(pct(v, 0, True) for v in observed)
        elif cond["metric"] == "fcf_ttm":
            shown = cap(observed) if _ok(observed) else "n/a"
        else:
            shown = pct(observed, 1, True) if _ok(observed) else "n/a"
        text = cond["text"] if since is None else re.sub(r"today's (\S+?%)", rf"the \1 on {since}", cond["text"])
        rows.append({"text": text, "status": status, "observed": shown})
    first = since is None or since == str(c.get("price_date"))
    return {
        "since": since,
        "first_snapshot": first,
        "rows": rows,
        "breached": sum(1 for r in rows if r["status"] == "breached"),
    }


def missing_information(c: dict) -> list[str]:
    out = [f"{k.replace('_', ' ')} (input missing, scored 0)" for k in c.get("missing") or []]
    out += [f"{k.replace('_', ' ')}: not scored" for k in (c.get("not_scored") or {})]
    out += [f"{x}: not collected" for x in spec.FORENSIC_RULES["not_collected"]]
    return out


def sources(c: dict, as_of: str) -> list[dict]:
    cik = c.get("cik")
    f = c.get("fundamentals") or {}
    out = []
    if cik:
        out.append(
            {"label": "SEC company facts (XBRL)", "url": SEC_FACTS.format(cik=int(cik)), "date": f"filed by {as_of}"}
        )
        out.append(
            {
                "label": f"EDGAR filings ({f.get('last_form') or '10-Q/10-K'})",
                "url": EDGAR_FILINGS.format(cik=int(cik), form=f.get("last_form") or "10-Q"),
                "date": f"latest used: {f.get('last_filed') or 'n/a'}",
            }
        )
    out.append(
        {
            "label": (c.get("sources") or {}).get("price", "Cboe delayed quotes"),
            "url": None,
            "date": f"close of {c.get('price_date')}",
        }
    )
    if c.get("next_earnings"):
        out.append(
            {
                "label": "Alpha Vantage earnings calendar (scheduled dates, unverified)",
                "url": None,
                "date": f"as of {as_of}",
            }
        )
    return out


def panel(c: dict, snap: dict, history: list[dict], profile: tuple) -> dict:
    support, counter = evidence(c, profile)
    return {
        "trends": trends(c),
        "support": support,
        "counter": counter,
        "forensics": forensics(c),
        "assumptions": assumptions(c),
        "events": events(c, str(snap["as_of"]), snap),
        "thesis": thesis_check(c, history),
        "missing": missing_information(c),
        "sources": sources(c, str(snap["as_of"])),
    }
