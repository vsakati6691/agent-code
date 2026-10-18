"""Render public audit and integrity information from the snapshot store."""

from __future__ import annotations

import json

from . import (
    evidence,
    spec,
)
from .fmt import (
    metric,
)
from .fmt import (
    sval as sval,
)
from .render_context import customer
from .site_layout import E
from .site_research import datasets_table
from .store import Store


def _readable(d) -> str:
    """Audit details as 'key: value' text (no raw JSON on the page)."""
    if isinstance(d, dict):
        return "; ".join(
            f"{str(k).replace('_', ' ')}: {_readable(v)}" for k, v in d.items() if v not in (None, "", {}, [])
        )
    if isinstance(d, (list, tuple)):
        return ", ".join(_readable(v) for v in d)
    if isinstance(d, float):
        return metric("", d)
    return str(d)


def audit_page(
    store: Store,
    snap: dict,
    integrity: list[str],
    daily: dict | None = None,
    status: dict | None = None,
    published: list[str] | None = None,
) -> str:
    from .site_external import rate_note
    from .site_options_status import status_html, version_line
    from .site_refresh import audit_context

    rows = "".join(
        f'<tr><td class="small">{E(str(e.get("at")).replace("+00:00", ""))}</td><td>{E(str(e.get("event")).replace("_", " "))}</td>'
        f'<td class="small">{E(_readable({k: v for k, v in e.items() if k not in ("at", "event")})[:400])}</td></tr>'
        for e in reversed(store.audit_log()[-300:])
    )
    man = []
    for d in reversed(store.dates()):
        m = json.loads((store.root / "snapshots" / d / "manifest.json").read_text(encoding="utf-8"))
        man.append(
            f'<tr><td>{E(d)}</td><td class="small"><code>{E(m["sha256"][:16])}…</code></td><td>{E(str(m.get("spec_version")))}</td>'
            f'<td class="small">{E(str(m.get("code_commit") or "local build")[:10])}</td><td>{E(str(m.get("status")))}</td></tr>'
        )
    ok = (
        '<div class="banner info"><strong>Integrity</strong>Every stored snapshot matches its manifest hash.</div>'
        if not integrity
        else '<div class="banner bad"><strong>Integrity problems</strong>' + E("; ".join(integrity)) + "</div>"
    )
    usage = snap.get("usage", {})
    rate_details = rate_note(snap).replace('<details class="small">', '<details class="small" open>', 1)
    options_section = (
        ""
        if customer()
        else f"""<section id="options-data"><h2>Options collection</h2>{status_html(snap)}{version_line(snap)}{rate_details}
<p>{E(_readable((snap.get("options") or {}).get("chain_problems") or {}))}</p></section>"""
    )
    return f"""<h1>Audit trail</h1><p>Stored data coverage, integrity and collection history.</p>
<section id="data-status">{datasets_table(evidence.datasets(snap))}</section>{ok}
<p class="small">One state per dataset behind the {E(str(snap["as_of"]))} snapshot. Nothing falls back to sample or
estimated data: anything not collected is shown as missing.</p><h2>Snapshots</h2><div class="table-wrap"><table aria-label="Stored snapshots"><thead><tr><th>As of</th><th>SHA-256</th>
<th>Spec</th><th>Code</th><th>Status</th></tr></thead><tbody>{"".join(man)}</tbody></table></div>
<h2 id="latest-run">Latest run</h2><p>Snapshot methodology: {E(str(snap.get("spec_version") or "unavailable"))}.
Status: {E(str(snap.get("status") or "unavailable"))}. Latest attempt: {E(_readable(status or {}))}.</p>
<p class="small">Started {E(snap.get("run_started", ""))}, finished {E(snap.get("run_finished", ""))} UTC.
Requests by provider: {E(", ".join(f"{k} {v}" for k, v in usage.get("requests", {}).items()) or "none (all answered from cache)")};
cache hits {E(str(usage.get("cache_hits", 0)))}.
Provider caps: {E(_readable(usage.get("budgets", {})))}. Dataset attempts: {E(_readable(usage.get("dataset_requests", {})))}.
Dataset caps: {E(_readable(usage.get("dataset_budgets", {})))}.
Problems: {E("; ".join(snap.get("problems", [])) or "none")}.</p>
<p>Leaders index completion: {E(_readable(snap.get("leaders_2030_collection") or {})) or "Not stored in this snapshot"}.</p>
{audit_context(snap, daily)}
{options_section}
<h2>Data sources and terms</h2><ul class="small">{"".join(f"<li><strong>{E(k)}</strong>: {E(v)}</li>" for k, v in snap.get("sources", {}).items())}</ul>
<h2>Machine-readable data</h2><ul class="small"><li><a href="data/schema.json">data/schema.json</a>: what every field means
(ratios are decimals, money is USD, times are UTC)</li><li><a href="data/latest.json">data/latest.json</a>: the latest snapshot</li>
<li><a href="downloads/{E(str(snap["as_of"]))}_external.csv">Company public-dataset CSV</a></li><li><a href="downloads/{E(str(snap["as_of"]))}_macro.csv">Macro CSV</a></li>
{"".join(f'<li><a href="data/{E(d)}.json">data/{E(d)}.json</a>: session {E(d)}</li>' for d in reversed(store.dates() if published is None else published))}</ul>
<p class="small">Published here: the snapshot tracked for each ISO week and the latest {spec.PUBLISHED_RECENT_SNAPSHOTS} sessions.
Every stored snapshot, listed above with its hash, stays unchanged in the repository's <code>research-data</code> branch.</p>
<h2>Events</h2><div class="table-wrap"><table aria-label="Audit events"><thead><tr><th>At (UTC)</th><th>Event</th><th>Details</th></tr></thead><tbody>{rows}</tbody></table></div>"""
