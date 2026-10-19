"""Visible short-expiry desk, including uncollected and unavailable states."""

from __future__ import annotations

from . import spec
from .fmt import money, num, pct
from .site_layout import E


def navigation(short: bool = False) -> str:
    return (
        '<nav class="hero-actions" aria-label="Options desks">'
        f'<a class="action" href="options.html" {"" if short else 'aria-current="page"'}>Longer expiries</a>'
        f'<a class="action" href="options-short-term.html" {'aria-current="page"' if short else ""}>0DTE / next expiry lottery desk</a></nav>'
    )


def desk(payload: dict | None) -> str:
    head = (
        navigation(True)
        + "<h1>0DTE / next expiry lottery desk</h1><p>NVDA · PLTR · MU · AVGO — delayed contract research.</p>"
    )
    head += '<div class="banner warn"><strong>The entire premium can be lost</strong>“Lottery” describes speculative short-expiry risk, not an estimated chance of profit. Quotes are delayed observations; this page cannot execute orders.</div>'
    guide = "<details><summary>Scanner rules and timing</summary><p>Uses actual listed dates: 0DTE expires today, 1DTE tomorrow (calendar days), and next listed expiry is the earliest later date within 7 days. A tomorrow contract can appear in both latter views. Missing daily expiries stay empty.</p><p>Regular session only, including 13:00 ET early-close cutoffs. Chain and underlying timestamps must be from this session and within 25 minutes. Open interest ≥ 100, volume ≥ 10, bid &gt; 0, spread ≤ 20% of midpoint, strike within 10% of spot. Standard OCC roots only. Ranked by spread, volume and open interest; at most 2 per symbol, type and window. No probability or price-target model.</p><p>Premium and maximum premium loss use ask × 100 shares; fees excluded. Exercise-related stock exposure and broker deadlines are outside this research calculation. OI is a reported outstanding count, not intraday flow.</p></details>"
    if not payload:
        return (
            head
            + '<p class="scan-empty">No short-term scan collected yet. Run the research-dashboard-short-term workflow during the regular US session. This desk collects separately from the post-close stock rankings.</p>'
            + guide
        )
    head += f'<p>Collected {E(payload["collected_at"])} · {E(payload["source"])} · methodology {E(payload["spec_version"])} · collection status: {E(payload["status"])}</p><p class="small">Static observation: it does not refresh automatically. Contract status below updates from your device clock. A failed collection retains the prior observation with its original timestamp.</p>'
    links = (
        '<nav class="hero-actions" aria-label="Short-term expiry windows">'
        + "".join(
            f'<a class="action" href="#st-{i}">{E(window)}</a>'
            for i, window in enumerate(spec.LIVE_GAP_RULES["short_term"]["windows"])
        )
        + "</nav>"
    )
    sections = []
    for i, window in enumerate(spec.LIVE_GAP_RULES["short_term"]["windows"]):
        rows = []
        gaps = []
        for record in payload["symbols"]:
            selected = [r for r in record["rows"] if r["window"] == window]
            if not selected:
                gaps.append(
                    f"{record['symbol']}: {record.get('reason') or 'No qualifying listed contracts in this window'}"
                )
            for row in selected:
                rows.append(
                    f'<tr data-short-expiry="{E(row["cutoff"])}" data-short-valid="{E(row["valid_until"])}">'
                    f"<td><strong>{E(row['symbol'])}</strong><br>{E(row['type'])} {money(row['strike'])}</td>"
                    f"<td>{E(row['expiry'])}<br>{row['dte']} calendar DTE at scan</td>"
                    f"<td>{money(row['bid'])} / {money(row['ask'])}</td><td>{money(row['premium'])}</td>"
                    f'<td class="bad">{money(row["max_premium_loss"])}</td><td>{pct(row["spread"], 1)}</td>'
                    f"<td>{num(row['volume'], 0)} / {num(row['open_interest'], 0)}</td>"
                    f"<td><span data-short-status>Stored observation — freshness unchecked</span><br><small>{E(row['quote_time'])}<br>{E(row['option'])}</small></td></tr>"
                )
        table = (
            (
                '<div class="table-wrap"><table><thead><tr><th>Contract</th><th>Expiry</th><th>Bid / ask</th><th>Premium</th><th>Max premium loss</th><th>Spread</th><th>Volume / OI</th><th>Quote status</th></tr></thead><tbody>'
                + "".join(rows)
                + "</tbody></table></div>"
            )
            if rows
            else '<p class="scan-empty">No qualifying contracts in this window.</p>'
        )
        sections.append(
            f'<section id="st-{i}"><h2>{E(window)}</h2>{table}<ul>'
            + "".join(f"<li>{E(gap)}</li>" for gap in gaps)
            + "</ul></section>"
        )
    return head + links + "".join(sections) + guide


JS = """'use strict';
(() => {
  const update = () => document.querySelectorAll('[data-short-expiry]').forEach(row => {
    const now = Date.now(), cutoff = Date.parse(row.dataset.shortExpiry), valid = Date.parse(row.dataset.shortValid);
    const label = !Number.isFinite(cutoff) || !Number.isFinite(valid) ? 'Timestamp unavailable' :
      now >= cutoff ? 'Expired / research cutoff passed' : now > valid ? 'Stale observation — refresh required' : 'Within delayed quote age limit';
    row.querySelector('[data-short-status]').textContent = label;
  });
  update();
  setInterval(update, 15000);
})();
"""
