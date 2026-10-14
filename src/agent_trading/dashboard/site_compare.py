"""Comparison page: pick 2-4 companies from one snapshot and see them side by side (spec 2026-10-14.5)."""
from __future__ import annotations

import html
import json

from . import spec
from .compare import pack

E = html.escape


def compare_page(data: dict) -> str:
    entries = data["entries"]
    opts = "".join(f'<option value="{E(e["ticker"])}">{E(e["ticker"])} · {E(e["name"] or "")} '
                   f'({E(", ".join(e["lists"]))})</option>' for e in sorted(entries, key=lambda e: e["ticker"]))
    # "</" cannot appear inside the inline JSON block
    blob = json.dumps(pack(data), separators=(",", ":")).replace("</", "<\\/")
    if len(entries) < spec.COMPARE_RULES["min_names"]:
        body = '<div class="banner warn"><strong>Not enough companies</strong>This snapshot has fewer than two companies with stored figures.</div>'
    else:
        body = f"""<div class="card controls cmp-controls">
<label for="cmp-pick">Add a company</label>
<div class="cmp-row"><select id="cmp-pick"><option value="">Choose…</option>{opts}</select>
<button type="button" id="cmp-add">Add</button></div>
<ul class="cmp-chips" id="cmp-chips" aria-label="Selected companies"></ul>
<p class="small muted" id="cmp-hint" role="status" aria-live="polite"></p>
</div>
<div id="cmp-flags"></div>
<div class="table-wrap cmp-wrap" id="cmp-table-wrap"></div>
<h2>Price paths on common dates</h2>
<div class="tabs" data-cmp-window role="group" aria-label="Chart window">
<button type="button" data-win="1" aria-pressed="true">1 year</button><button type="button" data-win="3" aria-pressed="false">3 years</button>
<button type="button" data-win="5" aria-pressed="false">5 years</button></div>
<div id="cmp-chart" class="chart"></div>
<p class="small muted" id="cmp-chart-note"></p>"""
    return f"""<h1>Compare companies</h1>
<p class="lede">Choose 2 to 4 companies from the {E(data["as_of"])} snapshot. Every figure comes from that snapshot:
prices at its close, fundamentals from SEC filings made by that date, in USD as reported.</p>
<p class="small">{E(spec.COMPARE_RULES["note"])}</p>
{body}
<script type="application/json" id="cmp-data">{blob}</script>"""
