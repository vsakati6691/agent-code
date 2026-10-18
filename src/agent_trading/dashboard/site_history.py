"""Methodology-aware history, weekly reports and the Atom feed."""

from __future__ import annotations

from . import (
    site_methodology,
    spec,
)
from .fmt import (
    money,
    num,
    pct,
    tracking_schedule,
)
from .fmt import (
    sval as sval,
)
from .render_context import customer
from .site_layout import E, brand
from .site_options import lists_of
from .site_overview import band_title


def history_page(
    dates: list[str], tracking: dict | None, snapshots: list[dict] | None = None, reports: list[str] | None = None
) -> str:
    """`snapshots` may be manifests (version counts only); `reports` are the dates whose report pages are published."""
    items = "".join(
        f'<li><a href="reports/{d}.html">Snapshot {d}</a></li>' for d in reversed(dates if reports is None else reports)
    )
    if not tracking:
        trk = f'<p class="small">{E(tracking_schedule(dates))}</p>'
    else:
        rows = []
        for r in reversed(tracking["by_snapshot"]):
            cells = []
            for h in spec.TRACK_HORIZONS:
                x = r["horizons"].get(h, {})
                if x.get("status") == "ok":
                    cells.append(
                        f'<td class="num">{pct(x["net"], 1, True)}<div class="small muted">vs {pct(x["benchmark"], 1, True)}'
                        f"{f' · {len(x["unavailable"])} n/a' if x['unavailable'] else ''}</div></td>"
                    )
                else:
                    cells.append(f'<td class="num muted">{E(x.get("status", "pending"))}</td>')
            rows.append(
                f'<tr><td>{E(r["as_of"])}</td><td>{E(r["band"])}</td><td class="small">{E(r["spec_version"])}</td>{"".join(cells)}</tr>'
            )
        summ = "".join(
            f"<tr><td>{E(k)}</td>"
            + "".join(
                f'<td class="num">{pct(v[h]["mean_excess_net"], 1, True)}<div class="small muted">{v[h]["snapshots_measured"]} measured</div></td>'
                for h in spec.TRACK_HORIZONS
            )
            + f'<td class="num">{pct(v.get("mean_weekly_turnover"))}</td></tr>'
            for k, v in tracking["summary"].items()
        )
        chain = "".join(
            f"<li>{E(k)}: {v['weeks']} weeks, cumulative {pct(v['cumulative_net'], 1, True)}, max drawdown "
            f"{pct(v['max_drawdown'], 1)}</li>"
            for k, v in tracking.get("weekly_chain", {}).items()
        )
        hh = "".join(f'<th class="num">{h}</th>' for h in spec.TRACK_HORIZONS)
        trk = f"""<div class="banner warn"><strong>Evidence status</strong>{E(tracking["evidence_note"])}</div>
<p class="small">{E(tracking_schedule(dates))}</p>
<p class="small">Legacy category aggregates below can span methodology versions; they are not evidence for any single version. Use the per-snapshot version column and continuity table when interpreting them.</p>
<h3>Average excess return net of friction, by category</h3><div class="table-wrap"><table aria-label="Average excess return by list"><thead><tr><th>Category</th>{hh}
<th class="num">Weekly turnover</th></tr></thead><tbody>{summ}</tbody></table></div>
<h3>Weekly one-week chain</h3><ul class="small">{chain or '<li class="muted">Appears once a weekly list has been held for 5 trading sessions with prices for every name.</li>'}</ul>
<h3>Each snapshot</h3><div class="table-wrap"><table aria-label="Tracking result for each snapshot"><thead><tr><th>As of</th><th>Category</th><th>Spec</th>{hh}</tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p class="small">{E(tracking["method"])}</p><ul class="small">{"".join(f"<li>{E(x)}</li>" for x in tracking["limitations"])}</ul>
<p class="small">Assumed trading friction per side: {E(", ".join(f"{k} {v:g} bps" for k, v in tracking["friction"].items()))}
(bps = hundredths of a percent).</p>"""
    return f"""<h1>History and performance tracking</h1><p class="lede">Every snapshot is stored unchanged; tracking uses one per ISO week. Later prices
measure each list as it was published.</p>{site_methodology.history_table(snapshots or [])}<h2>Snapshot reports</h2><ul>{items}</ul><h2>Tracking</h2>{trk}"""


def weekly_report(snap: dict) -> str:
    parts = [
        f'<p class="small"><a href="../history.html">&larr; all snapshots</a></p><h1>Snapshot {E(snap["as_of"])}</h1>'
        f'<p class="lede">Status {E(snap.get("status", "?"))} · methodology {E(snap.get("spec_version", "?"))}.</p>'
    ]
    for k, b in snap["bands"].items():
        rows = "".join(
            f'<tr><td class="num">{c["rank"]}</td><td>{E(c["ticker"])}</td><td>{E(c["name"] or "")}</td>'
            f'<td class="num">{num(c["composite"], 1)}</td><td>{E(c["confidence_label"])}</td>'
            f'<td class="num">{money(c["price"])}</td><td class="small">{E(c["counterargument"])}</td></tr>'
            for c in b["candidates"]
        )
        parts.append(
            f'<h2>{E(band_title(k, b))}</h2><div class="table-wrap"><table aria-label="Weekly list"><thead><tr><th class="num">#</th><th>Ticker</th><th>Company</th>'
            f'<th class="num">Score</th><th>Confidence</th><th class="num">Price</th><th>Counterargument</th></tr></thead>'
            f"<tbody>{rows or '<tr><td colspan=7>none qualified</td></tr>'}</tbody></table></div>"
            f'<p class="small"><a href="../downloads/{E(snap["as_of"])}_{k}.csv" download>CSV</a></p>'
        )
    o = snap.get("options") or {}
    for h in () if customer() else spec.HORIZONS:  # the customer edition carries no option research
        for kind, lst in lists_of(o.get(h.key) or {}).items():
            rows = "".join(
                f"<li>{E(x['option'])}: ask {money(x['ask'])}, breakeven {money(x['breakeven'])}, score "
                f"{num(x['rank_components']['total'], 1)}</li>"
                for x in (lst or {}).get("rows", [])
            )
            parts.append(
                f'<h3>Options, {E(h.title.lower())}, {kind}</h3><ul class="small">{rows or "<li>none / unavailable</li>"}</ul>'
            )
    return "".join(parts)


def atom_feed(snaps: list[dict]) -> str:
    """Static Atom feed of the weekly reports (newest first). Links are relative to the site root."""
    from xml.sax.saxutils import escape as x

    def stamp(s):
        t = str(s.get("run_finished") or f"{s['as_of']}T21:00:00+00:00")
        return t if ("+" in t[10:] or t.endswith("Z")) else t + "Z"

    entries = []
    for s in sorted(snaps, key=lambda s: str(s["as_of"]), reverse=True):
        d = str(s["as_of"])
        counts = "; ".join(f"{band_title(k, b)}: {len(b.get('candidates', []))}" for k, b in s.get("bands", {}).items())
        entries.append(
            f"<entry><title>Week ending {x(d)}</title><id>urn:agent-code:research-dashboard:{x(d)}</id>"
            f'<link rel="alternate" type="text/html" href="reports/{x(d)}.html"/><updated>{x(stamp(s))}</updated>'
            f"<summary>{x(counts)}. Status {x(str(s.get('status', '?')))}; methodology {x(str(s.get('spec_version', '?')))}. "
            f"Research comparisons only, not advice.</summary></entry>"
        )
    updated = stamp(max(snaps, key=lambda s: str(s["as_of"]))) if snaps else "1970-01-01T00:00:00Z"
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
        f"<title>{x(brand())}: weekly reports</title>"
        '<id>urn:agent-code:research-dashboard</id><link rel="self" href="feed.xml"/>'
        '<link rel="alternate" type="text/html" href="history.html"/>'
        f"<updated>{x(updated)}</updated><author><name>agent-code research dashboard</name></author>"
        + "".join(entries)
        + "</feed>\n"
    )
