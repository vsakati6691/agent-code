"""Render public audit and integrity information from the snapshot store."""

from __future__ import annotations

import json

from . import (
    evidence,
)
from .fmt import (
    metric,
)
from .fmt import (
    sval as sval,
)
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


def audit_page(store: Store, snap: dict, integrity: list[str]) -> str:
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
    return f"""<h1>Audit trail</h1>{ok}<h2 id="data-status">Data status</h2>
<p class="small">One state per dataset behind the {E(str(snap["as_of"]))} snapshot. Nothing falls back to sample or
estimated data: anything not collected is shown as missing.</p>{datasets_table(evidence.datasets(snap))}<h2>Snapshots</h2><div class="table-wrap"><table aria-label="Stored snapshots"><thead><tr><th>As of</th><th>SHA-256</th>
<th>Spec</th><th>Code</th><th>Status</th></tr></thead><tbody>{"".join(man)}</tbody></table></div>
<h2>Latest run</h2><p class="small">Started {E(snap.get("run_started", ""))}, finished {E(snap.get("run_finished", ""))} UTC.
Requests by provider: {E(", ".join(f"{k} {v}" for k, v in usage.get("requests", {}).items()) or "none (all answered from cache)")};
cache hits {E(str(usage.get("cache_hits", 0)))}.
Problems: {E("; ".join(snap.get("problems", [])) or "none")}.</p>
<h2>Data sources and terms</h2><ul class="small">{"".join(f"<li><strong>{E(k)}</strong>: {E(v)}</li>" for k, v in snap.get("sources", {}).items())}</ul>
<h2>Machine-readable data</h2><ul class="small"><li><a href="data/schema.json">data/schema.json</a>: what every field means
(ratios are decimals, money is USD, times are UTC)</li><li><a href="data/latest.json">data/latest.json</a>: the latest snapshot</li>
{"".join(f'<li><a href="data/{E(d)}.json">data/{E(d)}.json</a>: week ending {E(d)}</li>' for d in reversed(store.dates()))}</ul>
<h2>Events</h2><div class="table-wrap"><table aria-label="Audit events"><thead><tr><th>At (UTC)</th><th>Event</th><th>Details</th></tr></thead><tbody>{rows}</tbody></table></div>"""
