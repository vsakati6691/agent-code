"""Overview panels for recorded changes, earnings, concentration and research risks."""

from __future__ import annotations

from . import changes as changes_mod
from . import evidence, spec
from .changes import KIND_LABELS
from .earnings_cadence import display as cadence_display
from .fmt import pct, tracking_schedule
from .site_list_common import E, band_title, ordered
from .site_research import datasets_line

RISK_GROUPS = (
    "25%+ below the 52-week high",
    "5-year drawdown worse than -50%",
    "Negative free cash flow",
    "Dilution above 5% a year",
    "EV/Sales above 15x",
)


def _risk_flags(c: dict) -> list[str]:
    """Downside-risk groups this candidate falls into (names from RISK_GROUPS)."""
    m = c.get("metrics") or {}
    dd = (c.get("history") or {}).get("drawdowns", {})
    hits = [
        (dd.get("from_52w_high") or 0) <= -0.25,
        ((dd.get("max_5y") or {}).get("value") or 0) <= -0.5,
        (m.get("fcf_ttm") or 0) < 0,
        (m.get("dilution") or 0) > 0.05,
        (m.get("ev_to_sales") or 0) > 15,
    ]
    return [g for g, hit in zip(RISK_GROUPS, hits, strict=False) if hit]


def move_cause(ch: dict, list_name: str, methodology_note: str = "") -> str:
    """'S04 up 4 to #1 (Large cap): score +5.3; growth +12.0, valuation -1.5' (older snapshots: stored text)."""
    d = ch["change"]
    head = f"{ch['ticker']} {'up' if d > 0 else 'down'} {abs(d)} to #{ch.get('to')} ({list_name})"
    if methodology_note:
        head += f": {methodology_note}"
    comps = ch.get("component_changes")
    if comps is None:
        return f"{head}: {ch.get('explanation', '')}"
    sc = ch.get("score_change")
    if not comps and (not isinstance(sc, (int, float)) or abs(sc) < 0.05):
        why = "other stocks scored higher this week" if d < 0 else "stocks above it fell back or left the list"
        return f"{head}: its own score was unchanged; {why}"
    parts = ([f"score {sc:+.1f}"] if isinstance(sc, (int, float)) else []) + [
        ", ".join(f"{k} {v:+.1f}" for k, v in comps.items()) or "component scores unchanged"
    ]
    return f"{head}: " + "; ".join(parts)


FLAG_LIST_MAX = 8  # longer flag lists collapse to a count, so a flag shared by most names doesn't bury the rest


EARNINGS_SHOWN = 5  # the earnings panel shows the next five dates; the rest fold behind "N more"


def _flag_item(group: str, tickers: list[str], total: int) -> str:
    if len(tickers) <= FLAG_LIST_MAX:
        return f'<li class="small"><strong>{E(group)}:</strong> {E(", ".join(tickers))}</li>'
    return (
        f'<li class="small"><details><summary><strong>{E(group)}:</strong> {len(tickers)} of {total} listed '
        f"names</summary>{E(', '.join(tickers))}</details></li>"
    )


def _last_results(i: dict) -> str:
    if i.get("last_results"):
        return (
            f'<br><span class="small">last results {E(i["last_results"])}, {E(i.get("last_results_status") or "")}'
            f"{'; ' + E(cadence_display(i)) if i.get('cadence_check') else ''}</span>"
        )
    if i.get("last_results_status"):
        return f'<br><span class="small muted">{E(i["last_results_status"])}</span>'
    return ""


def panels(snap: dict, tracking: dict | None, dates: list[str] | None = None, prev_snap: dict | None = None) -> str:
    bands = snap["bands"]
    ev = snap.get("events") or {}
    items = ev.get("items")
    if items is None:
        earn = '<p class="small muted">Not collected in this snapshot.</p>'
    elif not items and evidence.earnings_state(snap)[0] != "available":
        earn = (
            '<p class="small">Earnings dates could not be collected for this snapshot, so upcoming reports are '
            "not listed (this does not mean none are due).</p>"
            f'<p class="small muted">{E(ev.get("note", ""))}</p>'
        )
    else:
        rows = [
            f'<li><strong>{E(i["ticker"])}</strong> {E(i["date"])} <span class="muted">(scheduled, unverified; '
            f"{E(i['list'])})</span>{_last_results(i)}</li>"
            for i in items[:12]
        ]
        earn = "".join(rows[:EARNINGS_SHOWN]) or '<li class="muted">No earnings scheduled in the next 45 days.</li>'
        more = (
            f'<details class="small"><summary>{len(rows) - EARNINGS_SHOWN} more</summary><ul class="tight">'
            f"{''.join(rows[EARNINGS_SHOWN:])}</ul></details>"
            if len(rows) > EARNINGS_SHOWN
            else ""
        )
        earn = f'<ul class="tight small">{earn}</ul>{more}<p class="small muted">{E(ev.get("note", ""))}</p>'
    new, gone, moves = [], [], []
    methodology_note = ""
    if prev_snap and prev_snap.get("spec_version") != snap.get("spec_version"):
        methodology_note = (
            f"methodology version changed ({prev_snap.get('spec_version', 'unavailable')} → "
            f"{snap.get('spec_version', 'unavailable')}); ranks and scores are not like-for-like"
        )
    elif prev_snap and prev_snap.get("spec_hash") != snap.get("spec_hash"):
        methodology_note = "methodology hash changed; ranks and scores are not like-for-like"
    for k in ordered(bands):
        short = band_title(k, bands[k])
        for ch in bands[k].get("rank_changes", []):
            if ch["change"] in ("new", "new (first snapshot)"):
                new.append(f"{ch['ticker']} (#{ch.get('to')}, {short})")
            elif ch["change"] == "dropped":
                gone.append(f"{ch['ticker']} (was #{ch.get('from')}, {short})")
            elif isinstance(ch["change"], int) and ch["change"]:
                moves.append((abs(ch["change"]), move_cause(ch, short, methodology_note)))
    first = all(ch["change"] == "new (first snapshot)" for b in bands.values() for ch in b.get("rank_changes", []))
    summ = changes_mod.summary(snap, prev_snap)
    if prev_snap is None:
        what = (
            '<p class="small muted">No earlier snapshot is stored, so filings, deterioration, dilution, thesis '
            "conditions and data availability cannot be compared yet.</p>"
        )
    else:
        counts = " · ".join(f"{KIND_LABELS[k]}: {n}" for k, n in summ["counts"].items() if n) or "nothing listed"
        top = "".join(
            f'<li><a href="stock/{E(r["band"])}-{E(r["ticker"])}.html">{E(r["ticker"])}</a>: {E(r["text"])}</li>'
            for r in [r for r in summ["rows"] if r["kind"] in ("thesis", "deterioration", "filing", "dilution")][:6]
        )
        what = (
            f'<p class="small"><strong>Since {E(summ["previous"])}</strong> ({E(counts)}; names on both '
            f'snapshots only)</p><ul class="tight small">{top}</ul>'
        )
    move_items = "".join(f"<li>{E(t)}</li>" for _, t in sorted(moves, key=lambda m: -m[0])[:6])
    changes = (
        '<p class="small muted">First snapshot: no previous week to compare.</p>'
        if first
        else f'<p class="small"><strong>New:</strong> {E(", ".join(new) or "none")}<br><strong>Departed:</strong> '
        f'{E(", ".join(gone) or "none")}</p><p class="small"><strong>Biggest moves and why</strong> '
        f"(change in the 0-100 score, then the component scores that moved most):</p>"
        f'<ul class="tight small">{move_items or "<li>none</li>"}</ul>'
    )
    conc = [f"{band_title(k, bands[k])}: {w}" for k in ordered(bands) for w in bands[k].get("concentration", [])]
    groups: dict[str, list[str]] = {g: [] for g in RISK_GROUPS}
    for k in ordered(bands):
        for c in bands[k]["candidates"]:
            for g in _risk_flags(c):
                groups[g].append(c["ticker"])
    total = len({c["ticker"] for k in ordered(bands) for c in bands[k]["candidates"]})
    risk = "".join(f'<li class="small">{E(w)}</li>' for w in conc) + "".join(
        _flag_item(g, list(dict.fromkeys(ts)), total) for g, ts in groups.items() if ts
    )
    measured = any(
        v.get(h, {}).get("snapshots_measured")
        for v in ((tracking or {}).get("summary") or {}).values()
        for h in spec.TRACK_HORIZONS
    )
    perf = f'<p class="small muted">{E(tracking_schedule(dates or [snap["as_of"]]))}</p>'
    if tracking and tracking.get("summary") and measured:
        rows = "".join(
            f"<tr><td>{E(k)}</td>"
            + "".join(
                f'<td class="num">{pct((v.get(h) or {}).get("mean_excess_net"), 1, True)}</td>'
                for h in spec.TRACK_HORIZONS
            )
            + "</tr>"
            for k, v in tracking["summary"].items()
        )
        perf = (
            '<div class="table-wrap"><table class="small" aria-label="Mean excess return by list and horizon"><thead><tr><th>List</th>'
            + "".join(f'<th class="num">{h}</th>' for h in spec.TRACK_HORIZONS)
            + f'</tr></thead><tbody>{rows}</tbody></table></div><p class="small muted">Mean excess return vs benchmark, net of '
            f"assumed friction, from immutable prior snapshots. {E(tracking.get('evidence_note', ''))}</p>"
        )
    u = snap["universe"]
    tr = snap.get("tradability") or {}
    cov = (
        f'<p class="small">S&amp;P 500 price coverage {pct(u.get("sp500_price_coverage"))} of {u.get("sp500_count")} · broad '
        f"universe {u.get('broad_eligible')} eligible, {u.get('broad_prescreen')} pre-screened · Robinhood verdicts "
        f"{tr.get('verdicts_stored', 'n/a')}, {tr.get('to_check', 'n/a')} to check · snapshot "
        f"{E(str(snap.get('run_finished', '')).replace('+00:00', ''))} UTC.</p>"
        f'<p class="small">{E("; ".join(snap.get("problems", []) + snap.get("notes", [])) or "No missing-data warnings.")}</p>'
        f'<p class="small">{datasets_line(evidence.datasets(snap))}</p>'
        '<p class="small"><a href="audit.html#data-status">Data status, sources and audit trail →</a></p>'
    )
    return f"""<div class="panels">
<section class="card"><h3>Upcoming earnings (45 days)</h3>{earn}</section>
<section class="card"><h3>What changed since the previous snapshot?</h3>{what}{changes}</section>
<section class="card"><h3>Concentration and downside flags</h3><ul class="tight">{risk or '<li class="small muted">None triggered.</li>'}</ul></section>
<section class="card"><h3>Performance vs benchmarks</h3>{perf}</section>
<section class="card"><h3>Data coverage and freshness</h3>{cov}</section></div>"""
