"""Focused growth and multibagger pages, using the snapshot's unchanged lists."""
from __future__ import annotations

import html

from .site_overview import band_title, growth_section, list_page, multibagger_section, ordered
from .site_scan import candidate_scan

E = html.escape


def growth_page(snap: dict, daily: dict | None = None) -> str:
    bands = snap.get("bands") or {}
    keys = [k for k in ordered(bands) if list_page(k) == "growth.html"]
    links = "".join(f'<a class="action" href="#{E(k)}">{E(band_title(k, bands[k]))} →</a>' for k in keys)
    detail = (f'<details class="context-details" id="growth-details"><summary>Research detail by list · evidence, '
              f'financial trends and CSV downloads</summary>{growth_section(snap)}</details>') if keys else \
             '<p class="scan-empty">Growth lists are not available in this snapshot.</p>'
    return f'''<header class="watch-heading"><p class="eyebrow">RANKED COMPANY RESEARCH</p>
<h1>Growth Stocks</h1><p class="lede">Find candidates across large, mid and small caps. Filter the scan, pin a ticker,
then open its evidence and risks.</p><div class="hero-actions">{links}</div></header>
{candidate_scan(snap, keys, daily)}
{detail}'''


def multibaggers_page(snap: dict) -> str:
    band = (snap.get("bands") or {}).get("multibagger")
    content = multibagger_section(snap) if band is not None else (
        '<p class="scan-empty">The multibagger list is not available in this snapshot. '
        'This snapshot predates the list or did not include it.</p>')
    if band is None and "spec" in (snap.get("bands") or {}):
        content += '<p><a href="growth.html#spec">View the legacy speculative list →</a></p>'
    return f'''<header class="watch-heading"><p class="eyebrow">LONG-TERM, SPECULATIVE RESEARCH</p>
<h1>Multibaggers</h1><p class="lede">Study what would need to happen over 5–10 years: sustained growth,
cash generation, valuation and dilution. Passing the screen does not predict a multibagger outcome.</p>
<p class="small muted" data-pin-status>Pin a ticker to keep it on this device. Pins are shared with Growth Stocks and Watchlist 2030.</p></header>
{content}'''
