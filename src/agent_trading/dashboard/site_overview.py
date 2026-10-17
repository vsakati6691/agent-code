"""Overview composition and compatible imports for focused list renderers."""

from __future__ import annotations

from .fmt import num
from .site_briefing import EARNINGS_SHOWN as EARNINGS_SHOWN
from .site_briefing import FLAG_LIST_MAX as FLAG_LIST_MAX
from .site_briefing import RISK_GROUPS as RISK_GROUPS
from .site_briefing import _flag_item as _flag_item
from .site_briefing import _last_results as _last_results
from .site_briefing import _risk_flags as _risk_flags
from .site_briefing import move_cause as move_cause
from .site_briefing import panels as panels
from .site_exclusions import NOT_CHECKED as NOT_CHECKED
from .site_exclusions import NUMBER as NUMBER
from .site_exclusions import REASON_RULES as REASON_RULES
from .site_exclusions import excluded_page as excluded_page
from .site_exclusions import excluded_summary as excluded_summary
from .site_exclusions import group_exclusions as group_exclusions
from .site_exclusions import reason_group as reason_group
from .site_external import macro_context
from .site_growth_tables import CAP_BUCKETS as CAP_BUCKETS
from .site_growth_tables import _earn_growth as _earn_growth
from .site_growth_tables import _ret as _ret
from .site_growth_tables import _valuation as _valuation
from .site_growth_tables import distribution_strip as distribution_strip
from .site_growth_tables import evidence_block as evidence_block
from .site_growth_tables import evidence_fragments as evidence_fragments
from .site_growth_tables import fragment_path as fragment_path
from .site_growth_tables import growth_section as growth_section
from .site_growth_tables import growth_table as growth_table
from .site_growth_tables import missing_note as missing_note
from .site_growth_tables import row_spark as row_spark
from .site_growth_tables import short_risk as short_risk
from .site_growth_tables import spark_window as spark_window
from .site_growth_tables import sparkline as sparkline
from .site_list_common import GROWTH_KEYS as GROWTH_KEYS
from .site_list_common import ORDER as ORDER
from .site_list_common import TIME_GUIDE as TIME_GUIDE
from .site_list_common import E as E
from .site_list_common import band_title as band_title
from .site_list_common import definition_line as definition_line
from .site_list_common import list_page as list_page
from .site_list_common import ordered as ordered
from .site_multibaggers import multibagger_needs as multibagger_needs
from .site_multibaggers import multibagger_section as multibagger_section
from .site_multibaggers import scenario_flags_html as scenario_flags_html
from .site_options import watchlist_cards
from .site_scan import market_context, scan_header


def ai_teaser(snap: dict) -> str:
    """Overview block: the top 5 of each AI list, linking to the AI page (nothing for a snapshot without AI lists)."""
    bands = {k: snap["bands"][k] for k in ("ai_large", "ai_mid") if k in (snap.get("bands") or {})}
    if not bands:
        return ""
    cards = []
    for key, b in bands.items():
        items = "".join(
            f'<li><a href="stock/{key}-{E(c["ticker"])}.html"><strong>{E(c["ticker"])}</strong></a> {E(c.get("name") or "")} '
            f'<span class="muted">· {E(c.get("ai_role") or "")} · score {num(c.get("composite"), 1)}</span></li>'
            for c in b["candidates"]
        )
        cards.append(
            f'<section class="card"><h3>{E(band_title(key, b))}</h3>'
            f'<ol class="tight small">{items or "<li>none met every rule this week</li>"}</ol></section>'
        )
    return (
        f'<h2 id="ai-stocks">AI stocks</h2><p class="small">Up to 5 AI-exposed stocks per list under the registered AI scoring profile, a scenario test '
        f"of whether any could reach the largest market caps, and private AI companies for context. Not forecasts, "
        f'and no probabilities. <a href="ai.html">Open the AI page</a>.</p><div class="ow-grid">{"".join(cards)}</div>'
    )


def overview(
    snap: dict,
    status: dict | None,
    dates: list[str],
    tracking: dict | None,
    prev_snap: dict | None = None,
    daily: dict | None = None,
) -> str:
    bands = snap["bands"]
    growth_count = len(
        {c["ticker"] for k, b in bands.items() if list_page(k) == "growth.html" for c in b["candidates"]}
    )
    multi = bands.get("multibagger")
    multi_count = f"{len(multi['candidates'])} candidates" if multi is not None else "Not available in this snapshot"
    ai_summary = ai_teaser(snap)
    if ai_summary:
        ai_summary = f'<details class="context-details"><summary>AI stocks summary</summary>{ai_summary}</details>'
    return f"""{scan_header(snap, prev_snap)}
{market_context(snap, daily)}
{macro_context(snap)}
<section aria-label="Choose a research list" class="research-paths">
<a class="research-path" href="growth.html"><span class="eyebrow">LARGE · MID · SMALL CAP</span>
<strong>Growth Stocks <span aria-hidden="true">↗</span></strong><span>Scan, filter and compare the ranked growth lists.</span>
<small>{growth_count} unique candidates</small></a>
<a class="research-path" href="multibaggers.html"><span class="eyebrow">5–10 YEAR RESEARCH</span>
<strong>Multibaggers <span aria-hidden="true">↗</span></strong><span>Examine the growth path, assumptions and failure risks.</span>
<small>{multi_count}</small></a></section>
<section id="research-briefing" aria-labelledby="briefing-title">
<div class="section-heading"><h2 id="briefing-title">Research briefing</h2><span class="small muted">Changes, earnings, risks and data coverage</span></div>
{panels(snap, tracking, dates, prev_snap)}</section>
{ai_summary}
<details class="context-details"><summary>Options research summary</summary>{watchlist_cards(snap)}</details>
<details class="context-details small"><summary>How to read time horizons</summary><p>{E(TIME_GUIDE)}</p></details>
<p class="small muted">{len(dates)} weekly snapshot(s) stored. <a href="history.html">History and tracking</a>.</p>"""
