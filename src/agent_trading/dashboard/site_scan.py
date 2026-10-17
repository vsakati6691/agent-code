"""Fast, snapshot-based market and candidate scan. No new scores or market signals."""

from __future__ import annotations

import html

from . import evidence, site_decisions, site_refresh, spec
from .fmt import money, num, ok, pct, sval

E = html.escape
LIST_ORDER = ("large", "mid", "small", "multibagger")
BENCHMARKS = (("SPY", "S&P 500"), ("IJH", "US mid cap"), ("IWM", "US small cap"))


def pin_button(ticker: str) -> str:
    return (
        f'<button class="pinbtn" type="button" data-pin="{E(ticker)}" aria-pressed="false" '
        f'aria-label="Pin {E(ticker)}" title="Pin on this device">☆</button>'
    )


def _label(key: str, band: dict) -> str:
    return band.get("short_title") or spec.BAND_TITLES_SHORT.get(key) or band.get("title", key)


def benchmark_return(snap: dict, ticker: str, window: str) -> float | None:
    """Reuse the recorded benchmark return only when all available copies agree.

    Older snapshots anchor their trailing returns to the candidate's verified
    price date. Require that endpoint when the explicit window end is absent.
    """
    values = set()
    for band in (snap.get("bands") or {}).values():
        if band.get("benchmark") != ticker:
            continue
        for c in band.get("candidates", []):
            r = ((c.get("history") or {}).get("returns") or {}).get(window) or {}
            if r.get("end", c.get("price_date")) == snap.get("as_of") and ok(r.get("benchmark")):
                values.add(r["benchmark"])
    return next(iter(values)) if len(values) == 1 else None


def market_context(snap: dict, daily: dict | None = None) -> str:
    cards = []
    available = False
    for ticker, name in BENCHMARKS:
        b = (snap.get("benchmarks") or {}).get(ticker) or {}
        current = b.get("date") == snap.get("as_of")
        close, note = site_refresh.price(ticker, b.get("close") if current else None, daily)
        if close is None and note == "Weekly close":
            note = "No dated benchmark close stored for this snapshot"
        available |= close is not None
        value = money(close) if close is not None else f'<span title="{E(note)}">—</span>'
        r = benchmark_return(snap, ticker, "1y") if current else None
        direction = "positive" if ok(r) and r >= 0 else "negative" if ok(r) else "muted"
        cards.append(
            f'<article class="market-tile"><div class="market-label"><strong>{ticker}</strong>'
            f'<span>{E(name)}</span></div><div class="market-value">{value}</div>'
            f'<div class="market-foot"><span class="{direction}">{pct(r, 1, True)} · 1Y price return</span>'
            f"<span>{E(note)}</span><span>Weekly: {E(str(b.get('date') or 'Date unavailable'))}</span></div></article>"
        )
    body = (
        '<section aria-label="Market context"><div class="section-heading"><h2>Market context</h2>'
        '<span class="small muted">ETF benchmarks · stored closing prices</span></div>'
        f'{site_refresh.banner(snap, daily)}<div class="market-grid">{"".join(cards)}</div></section>'
    )
    return (
        body
        if available
        else '<details class="empty-data"><summary>Benchmark prices unavailable</summary>' + body + "</details>"
    )


def scan_header(snap: dict, prev_snap: dict | None) -> str:
    bands = snap.get("bands") or {}
    candidates = [c for b in bands.values() for c in b.get("candidates", [])]
    unique = len({c["ticker"] for c in candidates})
    new = {ch["ticker"] for b in bands.values() for ch in b.get("rank_changes", []) if ch.get("change") == "new"}
    missing = {c["ticker"] for c in candidates if c.get("missing")}
    state, _ = evidence.earnings_state(snap)
    events = (snap.get("events") or {}).get("items") or []
    dates = {(e["ticker"], e["date"]) for e in events}
    earnings = str(len(dates)) if state == "available" else "Unknown"
    new_text = str(len(new)) if prev_snap else "—"
    new_note = f"Since {E(prev_snap['as_of'])}" if prev_snap else "First stored snapshot"
    window = (snap.get("events") or {}).get("window_days", 45)
    stats = (
        (str(unique), "Research candidates", f"Across {len(bands)} research lists"),
        (new_text, "New to a list", new_note),
        (str(len(missing)), "With missing inputs", "Review evidence before comparing"),
        (
            earnings,
            "Scheduled earnings",
            f"Next {window} days from snapshot" if state == "available" else "Calendar data unavailable",
        ),
    )
    tiles = "".join(
        f'<div class="scan-stat"><span>{label}</span><strong>{value}</strong><small>{note}</small></div>'
        for value, label, note in stats
    )
    return (
        '<header class="compact-heading" data-overview><h1>Overview</h1>'
        "<p>Market context and the latest stored research lists.</p></header>"
        f'<div class="scan-stats" aria-label="Snapshot summary">{tiles}</div>'
    )


def candidate_scan(snap: dict, band_keys: list[str] | None = None, daily: dict | None = None) -> str:
    bands = snap.get("bands") or {}
    keys = [k for k in LIST_ORDER if k in bands] + sorted(k for k in bands if k not in LIST_ORDER)
    if band_keys is not None:
        keys = [k for k in keys if k in band_keys]
    rows, sectors = [], set()
    for key in keys:
        band = bands[key]
        for c in band.get("candidates", []):
            ticker = c["ticker"]
            sector = c.get("sector") or "Unknown"
            sectors.add(sector)
            quality = evidence.quality_level(c.get("confidence_label"))
            missing = len(c.get("missing") or [])
            ret = (((c.get("history") or {}).get("returns") or {}).get("1y") or {}).get("stock")
            risk = c.get("counterargument") or "Weakest evidence not recorded"
            close, price_note = site_refresh.price(ticker, c.get("price"), daily)
            research = site_decisions.flattened(c)
            momentum = research["momentum"]["text"]
            extension = research["extended"]["text"]
            rows.append(f'''<tr data-ticker="{E(ticker)}" data-sector="{E(sector)}" data-list="{E(key)}"
data-quality="{E(quality)}" data-gaps="{"yes" if missing else "no"}">
<td class="tk">{pin_button(ticker)}<a href="stock/{E(key)}-{E(ticker)}.html"><strong>{E(ticker)}</strong></a>
<span class="scan-company">{E(c.get("name") or ticker)}</span></td>
<td class="small">{E(_label(key, band))}<span class="scan-company">Rank #{c.get("rank", "—")} · {E(sector)}</span></td>
<td class="num" data-v="{sval(close)}" title="{E(price_note)}">{money(close) if close is not None else "—"}<span class="scan-company">{E(str(c.get("price_date") or ""))}</span></td>
<td class="num" data-label="Within-list score" data-v="{sval(c.get("composite"))}"><strong>{num(c.get("composite"), 1)}</strong><span class="scan-company">{"quality" if band.get("profile") == "fundamental_growth" else "recorded score"} / 100</span></td>
<td data-label="Momentum">{E(momentum)}<span class="scan-company">/ 100 · separate</span></td>
<td class="num {"positive" if ok(ret) and ret >= 0 else "negative" if ok(ret) else ""}" data-v="{sval(ret)}">{pct(ret, 1, True)}<span class="scan-company">{E(extension)}</span>{site_decisions.spark(c)}</td>
<td class="small"><span class="pill {E(quality)}">{E(quality)} evidence</span><span class="scan-company">{missing} missing input{"s" if missing != 1 else ""}</span></td>
<td class="small scan-risk">{E(risk)}</td><td class="research-value" data-research-value data-v="" title="Select a research field">—</td></tr>''')
    lists = "".join(f'<option value="{E(k)}">{E(_label(k, bands[k]))}</option>' for k in keys)
    sector_options = "".join(f'<option value="{E(s)}">{E(s)}</option>' for s in sorted(sectors))
    return f"""<section id="candidate-scan" aria-labelledby="scan-title">
<div class="section-heading"><div><h2 id="scan-title" class="sr-only">Candidate scanner</h2></div>
<a class="small" href="compare.html">Compare companies →</a></div>
{site_refresh.banner(snap, daily)}
<div class="scan-toolbar controls">
<label class="scan-search">Search candidates<input type="search" data-search="t-scan" placeholder="Ticker, company, sector or risk…" aria-label="Search candidates"></label>
<button class="action" type="button" data-reset="t-scan">Reset filters</button></div>
<details class="filter-details"><summary>Filters and research fields</summary><div class="controls">
<label>Research list<select data-filter="t-scan" data-field="list"><option value="">All lists</option>{lists}</select></label>
<label>Sector<select data-sector="t-scan"><option value="">All sectors</option>{sector_options}</select></label>
<label>Evidence<select data-filter="t-scan" data-field="quality"><option value="">All evidence</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option><option value="none">Unavailable</option></select></label>
<label>Inputs<select data-filter="t-scan" data-field="gaps"><option value="">All inputs</option><option value="yes">Has missing inputs</option><option value="no">No missing inputs</option></select></label>
<label>View<select data-filter="t-scan" data-field="pinned"><option value="">All candidates</option><option value="yes">Pinned tickers</option></select></label>
</div>{site_decisions.scanner_controls()}</details>
<div class="scan-meta"><span class="small" data-count="t-scan" aria-live="polite">{len(rows)} list entries</span>
<span class="small muted" data-pin-status>Pins are saved only on this device. Press / to search.</span></div>
<div class="table-wrap"><table id="t-scan" class="decision-scan" data-table><caption class="sr-only">Research candidate scanner</caption><thead><tr>
<th class="tk">Ticker / company</th><th>Research list / sector</th><th class="num" data-sort="num">Price</th>
<th class="num" data-sort="num" title="Within-list score; fundamental quality for new growth snapshots">Quality / recorded score</th><th data-sort="num">Momentum</th><th class="num" data-sort="num">1Y</th>
<th>Evidence</th><th>Main risk / weakest evidence</th><th data-sort="num" data-research-heading>Research field</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<p class="scan-empty" data-empty="t-scan" hidden>No candidates match these filters. Clear the search or reset filters.
To use Pinned tickers, first select a star beside a ticker.</p>
{site_decisions.scanner_payload(snap, keys)}
<noscript><p class="small">Open company pages for all decision fields. All candidates are shown. Enable JavaScript to search, filter, sort or pin tickers.</p></noscript>
<details><summary>How to read scores and returns</summary><p>Scores and ranks apply within each list, not across lists. A ticker may appear in more than one list.
1Y is a trailing price return; research scores are not probabilities.</p></details>
</section>"""
