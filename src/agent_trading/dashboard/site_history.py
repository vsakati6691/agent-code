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
from .tracking import version_blocks


def history_page(
    dates: list[str], tracking: dict | None, snapshots: list[dict] | None = None, reports: list[str] | None = None
) -> str:
    """`snapshots` may be manifests (version counts only); `reports` are the dates whose report pages are published."""
    items = "".join(
        f'<li><a href="reports/{d}.html">Snapshot {d}</a></li>' for d in reversed(dates if reports is None else reports)
    )
    trk = tracking_section(tracking, dates)
    return f"""<h1>History and performance tracking</h1><p class="lede">Every snapshot is stored unchanged; tracking uses one per ISO week. Later prices
measure each list as it was published.</p>{site_methodology.history_table(snapshots or [])}<h2>Snapshot reports</h2><ul>{items}</ul><h2>Tracking</h2>{trk}"""


def _cell(x: dict) -> str:
    """One basket and horizon: the result only for a complete basket, otherwise its state and measurable count."""
    st = x.get("status", "pending")
    n, m = x.get("n"), x.get("measured", 0)
    count = f"{m} of {n} picks measurable" if n is not None else ""
    if st == "ok":
        return (
            f'<td class="num">{pct(x["net"], 1, True)}<div class="small muted">vs {pct(x["benchmark"], 1, True)} · '
            f"{E(count)}</div></td>"
        )
    if st == "pending":
        due = x.get("exit_session")
        detail = x.get("note") or (f"result after the {due} close" if due else "")
        return f'<td class="num muted">pending<div class="small">{E(detail)}</div></td>'
    parts = [count]
    if x.get("missing_entry"):
        parts.append(f"{x['missing_entry']} missing entry price")
    if x.get("missing_exit"):
        parts.append(f"{x['missing_exit']} missing exit price")
    if x.get("benchmark") is None and x.get("benchmark_status"):
        parts.append("benchmark unavailable")
    title = "; ".join(f"{u['ticker']}: {u['status']}" for u in x.get("unavailable", []))
    return (
        f'<td class="num muted" title="{E(title)}">{E(st)}<div class="small">{E(" · ".join(p for p in parts if p))}'
        "</div></td>"
    )


def _version_block(v: dict) -> str:
    hh = "".join(f'<th class="num">{h}</th>' for h in spec.TRACK_HORIZONS)
    summ = "".join(
        f"<tr><td>{E(k)}</td>"
        + "".join(
            f'<td class="num">{pct(s[h]["mean_excess_net"], 1, True)}<div class="small muted">'
            f"{s[h]['snapshots_measured']} complete · {s[h].get('incomplete', 0)} incomplete · "
            f"{s[h].get('pending', 0)} pending</div></td>"
            for h in spec.TRACK_HORIZONS
        )
        + f'<td class="num">{pct(s.get("mean_weekly_turnover"))}</td></tr>'
        for k, s in v["summary"].items()
    )
    chain = "".join(
        (
            f"<li>{E(k)}: {c['weeks']} weeks ({E(c['first'])} to {E(c['last'])}), cumulative "
            f"{pct(c['cumulative_net'], 1, True)}, max drawdown {pct(c['max_drawdown'], 1)}"
            if c.get("weeks")
            else f"<li>{E(k)}: no complete week yet"
        )
        + (
            f"; {len(c['skipped_incomplete'])} week(s) left out because a pick had no 5-session return"
            if c.get("skipped_incomplete")
            else ""
        )
        + "</li>"
        for k, c in v.get("weekly_chain", {}).items()
    )
    return f"""<h3>Methodology {E(v["spec_version"])}</h3><p class="small">{v["weekly_snapshots"]} weekly snapshot(s),
{E(v["first_as_of"])} to {E(v["last_as_of"])}. {E(v["evidence_note"])}</p>
<div class="table-wrap"><table aria-label="Average excess return by list, methodology {E(v["spec_version"])}"><thead><tr><th>Category</th>{hh}
<th class="num">Weekly turnover</th></tr></thead><tbody>{summ}</tbody></table></div>
<p class="small">Averages use complete baskets only: every published pick and the benchmark priced on both sessions.</p>
<ul class="small">{chain or '<li class="muted">Weekly one-week chain: appears once a weekly list has been held for 5 sessions with prices for every name.</li>'}</ul>"""


def _price_line(src: dict | None) -> str:
    if not src:
        return ""
    rejected = src.get("rejected") or {}
    quote = src.get("as_of_bar_from_quote") or []
    text = (
        f"Tracking prices: {src.get('provider', '?')} daily closes collected {src.get('collected_at', '?')}, "
        f"validated as for ranking; {src.get('validated', 0)} of {src.get('symbols', 0)} symbols usable"
        + (f"; {len(quote)} as-of close(s) from the close-verified end-of-session quote" if quote else "")
        + (f"; rejected: {', '.join(f'{t} ({why})' for t, why in sorted(rejected.items()))}" if rejected else "")
        + "."
    )
    return f'<p class="small">{E(text)}</p>'


def tracking_section(tracking: dict | None, dates: list[str]) -> str:
    schedule = f'<p class="small">{E(tracking_schedule(dates))}</p>'
    if not tracking:
        return schedule
    blocks = version_blocks(tracking)
    if blocks is None:  # written before the measurement revision: pooled versions and unvalidated prices
        return (
            schedule + '<div class="banner warn"><strong>Tracking is being recomputed</strong>The stored tracking file '
            f"(as of {E(str(tracking.get('as_of', '?')))}) predates the 2026-11-04 measurement revision: it pooled "
            "methodology versions and read an unvalidated price file, so it is not shown. The next scheduled run "
            "recomputes it from the immutable snapshots.</div>"
        )
    rev = tracking.get("measurement_revision") or {}
    rows = []
    for r in reversed(tracking["by_snapshot"]):
        cells = "".join(_cell(r["horizons"].get(h, {})) for h in spec.TRACK_HORIZONS)
        rows.append(
            f'<tr><td>{E(r["as_of"])}</td><td>{E(r["band"])}</td><td class="small">{E(r["spec_version"])}</td>{cells}</tr>'
        )
    hh = "".join(f'<th class="num">{h}</th>' for h in spec.TRACK_HORIZONS)
    return f"""<div class="banner warn"><strong>Evidence status</strong>{E(tracking["evidence_note"])}</div>{schedule}
<p class="small"><strong>Measurement revision {E(rev.get("date", ""))}.</strong> {E(rev.get("rule", ""))} {E(rev.get("previous", ""))}
The registered tracking method below is unchanged.</p>{_price_line(tracking.get("prices"))}
{"".join(_version_block(v) for v in reversed(blocks))}
<h3>Each snapshot</h3><div class="table-wrap"><table aria-label="Tracking result for each snapshot"><thead><tr><th>As of</th><th>Category</th><th>Spec</th>{hh}</tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p class="small">{E(tracking["method"])}</p><ul class="small">{"".join(f"<li>{E(x)}</li>" for x in tracking["limitations"])}</ul>
<p class="small">Assumed trading friction per side: {E(", ".join(f"{k} {v:g} bps" for k, v in tracking["friction"].items()))}
(bps = hundredths of a percent).</p>"""


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
