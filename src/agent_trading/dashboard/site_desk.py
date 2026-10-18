"""Buy/Sell desk page (spec 2026-10-17.5): the rating table, one trace page per stock, the track record and CSV."""

from __future__ import annotations

import csv
import io
from html import escape as E

from . import desk, spec
from .fmt import csv_value, money, ok, pct, sval
from .site_list_common import filter_select
from .site_scan import pin_button

TRADING_AGENTS = "https://github.com/TauricResearch/TradingAgents"
PAPER = "https://arxiv.org/abs/2412.20138"
STAGES = (
    (
        "Analysts",
        "Four analysts vote bullish, neutral or bearish: fundamentals, technical, sentiment & positioning, "
        "and news & events.",
    ),
    ("Bull vs bear", "Bull and bear researchers list the evidence on each side; the net vote decides the debate."),
    ("Trader", "Turns the net vote into Buy, Overweight, Hold, Underweight or Sell."),
    ("Risk team", "Aggressive, neutral and conservative reviewers step positive calls down when risk flags appear."),
    ("Portfolio manager", "Takes the middle review and caps it at Hold when the evidence is weak."),
)
SHORT = {"fundamentals": "F", "technical": "T", "positioning": "P", "events": "N"}
GLYPH = {1: "▲", 0: "–", -1: "▼", None: "·"}
DIFFERENCES = (
    "No language model: every stage is a fixed rule, so a rating can be recomputed from the published JSON.",
    "No social media or news headlines: the dashboard only reads public filings and market data, so sentiment "
    "comes from SEC insider filings, FINRA short interest and analyst targets, and news from the latest 10-Q/10-K.",
    "One debate round: the net analyst vote settles it, instead of rounds of model-written argument.",
    "No position sizing or portfolio context: the dashboard never reads account data.",
    "The same five rating labels, from Buy to Sell.",
)


def payload_for(snap: dict) -> tuple[dict, bool]:
    """(desk payload, stored). A snapshot collected before the desk existed gets an untracked build-time preview."""
    stored = snap.get("decision_desk")
    if stored and stored.get("entries") is not None:
        return stored, True
    return desk.build(snap.get("bands") or {}, snap["as_of"]), False


def rating_tag(rating: str | None) -> str:
    if rating is None:
        return '<span class="rating none">Not rated</span>'
    return f'<span class="rating {rating.lower()}">{E(rating)}</span>'


def trace_path(ticker: str) -> str:
    return f"desk/{ticker}.html"


def _provenance(payload: dict, stored: bool, snap: dict) -> str:
    if stored:
        return (
            f'<p class="small">Ratings stored with the {E(payload["as_of"])} snapshot under methodology '
            f"{E(payload.get('spec_version') or '?')}. Stored ratings are tracked below.</p>"
        )
    return (
        '<div class="banner info"><strong>Preview, not tracked</strong>'
        f"The {E(str(snap['as_of']))} snapshot was collected under methodology {E(snap.get('spec_version') or '?')}, "
        f"before this desk existed. These ratings were computed when the site was built, from that snapshot's stored "
        f"figures, under {E(spec.SPEC_VERSION)}. Tracked ratings start with the first weekly snapshot collected under "
        f"{E(spec.SPEC_VERSION)}.</div>"
    )


def _votes(entry: dict) -> str:
    cells = []
    for a in entry["analysts"]:
        label = f"{a['title']}: {a['stance']}"
        cells.append(f'<span class="vote" title="{E(label)}">{SHORT[a["key"]]}{GLYPH[a["vote"]]}</span>')
    words = "; ".join(f"{a['title']} {a['stance']}" for a in entry["analysts"])
    return " ".join(cells) + f'<span class="sr-only">{E(words)}</span>'


def _track_record(tracking: dict | None) -> str:
    record = (tracking or {}).get("decision_desk") or {}
    first = (
        f"Tracking starts with the first weekly snapshot collected under {spec.SPEC_VERSION}; its first 1-month "
        f"results arrive {spec.TRACK_HORIZONS['1m']} trading sessions later."
    )
    if not record.get("snapshots_with_ratings"):
        return f'<h2 id="track-record">Track record by rating</h2><p class="small">{E(first)}</p>'
    head = "".join(f'<th class="num">{E(h)}</th>' for h in spec.TRACK_HORIZONS)
    rows = []
    for rating in reversed(spec.DESK_RATINGS):
        cells = []
        for h in spec.TRACK_HORIZONS:
            r = record["by_rating"].get(rating, {}).get(h, {})
            value = r.get("mean_excess")
            note = f"{r.get('measured', 0)} measured, {r.get('pending', 0)} pending"
            cells.append(
                f'<td class="num" title="{E(note)}">{pct(value, 1, sign=True) if ok(value) else "—"}'
                f'<div class="small muted">{E(note)}</div></td>'
            )
        rows.append(f"<tr><td>{rating_tag(rating)}</td>{''.join(cells)}</tr>")
    return (
        '<h2 id="track-record">Track record by rating</h2>'
        f'<p class="small">{E(record.get("evidence_note") or "")} First stored ratings: '
        f"{E(record.get('first_rated') or 'none')}.</p>"
        '<div class="table-wrap"><table aria-label="Mean price return minus benchmark by rating and horizon">'
        f"<thead><tr><th>Rating</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        f'<p class="small muted">{E(spec.DESK_TRACKING)}</p>'
    )


def desk_page(snap: dict, tracking: dict | None, payload: dict, stored: bool) -> str:
    entries = payload["entries"]
    out = [
        "<h1>Buy/Sell desk</h1>",
        '<p class="lede">Every research-list stock goes through the five stages '
        f'<a href="{TRADING_AGENTS}">TradingAgents</a> uses. Here each stage is a fixed, published rule instead of an '
        "AI model, so the same data always gives the same rating.</p>",
        '<div class="banner warn"><strong>Rule-based research rating, not advice</strong>'
        "Not a recommendation or an instruction to buy, sell or hold. No edge is established: ratings are tracked "
        f"against benchmarks and no edge is claimed before {spec.MIN_SNAPSHOTS_FOR_EVIDENCE} weekly snapshots. Every "
        "rated stock is already on a research list chosen for strong scores, so ratings lean positive by construction."
        "</div>",
        _provenance(payload, stored, snap),
        '<ol class="desk-flow">'
        + "".join(f'<li><strong>{E(name)}</strong><span class="small">{E(text)}</span></li>' for name, text in STAGES)
        + "</ol>",
        '<div class="grid desk-counts">'
        + "".join(
            f'<div class="card stat"><div class="label">{rating_tag(None if r == "Not rated" else r)}</div>'
            f'<div class="value">{n}</div></div>'
            for r, n in payload["counts"].items()
        )
        + "</div>",
    ]
    if not entries:
        out.append('<p class="scan-empty">No stock is on a research list in this snapshot, so nothing was rated.</p>')
    else:
        sectors = sorted({e["sector"] for e in entries if e.get("sector")})
        ratings = [*reversed(spec.DESK_RATINGS), "Not rated"]
        out.append(
            '<div class="controls"><input type="search" data-search="t-desk" placeholder="Search ticker, name, rating" '
            'aria-label="Search the desk">'
            '<button class="action" type="button" data-reset="t-desk">Reset filters</button>'
            '<span class="small muted" data-count="t-desk" aria-live="polite"></span></div>'
            '<details class="filter-details"><summary>Filter ratings</summary><div class="controls">'
            + filter_select("t-desk", "rating", "All ratings", [(r, r) for r in ratings])
            + filter_select("t-desk", "sector", "All sectors", [(s, s) for s in sectors])
            + filter_select("t-desk", "pinned", "All tickers", [("yes", "Pinned")])
            + "</div></details>"
        )
        head = "".join(
            f"<th{attrs}>{label}</th>"
            for label, attrs in [
                ("Ticker / name", ' class="tk" data-sort="text"'),
                ("Rating", ' data-sort="num"'),
                ("Analyst votes", ""),
                ("Net vote", ' class="num" data-sort="num"'),
                ("Trader", ' class="hide-sm" data-sort="num"'),
                ("Risk flags", ' class="num" data-sort="num"'),
                ("Price", ' class="num hide-sm" data-sort="num"'),
                ("Lists", ' class="hide-sm" data-sort="text"'),
            ]
        )
        out.append(
            '<div class="table-wrap"><table id="t-desk" data-table><caption>Rating for each research-list stock, '
            f"best first. Votes: F fundamentals, T technical, P positioning, N news & events</caption><thead><tr>{head}"
            "</tr></thead><tbody>"
        )
        for e in entries:
            rank = desk.RATINGS.index(e["rating"]) if e["rating"] else None
            debate = e.get("debate") or {}
            flags = (e.get("risk") or {}).get("flags")
            trader = e.get("trader")
            net = f"{debate['net']:+d}" if ok(debate.get("net")) else "—"
            out.append(
                f'<tr data-ticker="{E(e["ticker"])}" data-sector="{E(e.get("sector") or "")}" '
                f'data-rating="{E(e["rating"] or "Not rated")}">'
                f'<td class="tk" data-v="{E(e["ticker"])}">{pin_button(e["ticker"])}<strong>{E(e["ticker"])}</strong>'
                f'<div class="small muted">{E(e.get("name") or "")}</div>'
                f'<a class="small" href="{E(trace_path(e["ticker"]))}">How it was rated</a></td>'
                f'<td data-v="{sval(rank)}">{rating_tag(e["rating"])}</td>'
                f"<td>{_votes(e)}</td>"
                f'<td class="num" data-v="{sval(debate.get("net"))}">{net}</td>'
                f'<td class="hide-sm" data-v="{sval(desk.RATINGS.index(trader) if trader else None)}">{E(trader or "—")}</td>'
                f'<td class="num" data-v="{sval(len(flags) if flags is not None else None)}">'
                f"{len(flags) if flags is not None else '—'}</td>"
                f'<td class="num hide-sm" data-v="{sval(e.get("price"))}">{money(e.get("price"))}</td>'
                f'<td class="small hide-sm">{E(", ".join(spec.BAND_TITLES_SHORT.get(k, k) for k in e["lists"]))}</td></tr>'
            )
        out.append(
            '</tbody></table></div><p data-empty="t-desk" hidden>No rows match these filters.</p>'
            '<p class="small muted" data-pin-status>Pins are saved only on this device.</p>'
        )
        out.append(
            f'<p><a class="action" href="downloads/{E(payload["as_of"])}_buy_sell_desk.csv" download>'
            "Download desk CSV ↓</a></p>"
        )
    out.append(_track_record(tracking))
    out.append(
        '<h2 id="desk-method">How this differs from TradingAgents</h2><ul>'
        + "".join(f"<li>{E(t)}</li>" for t in DIFFERENCES)
        + f'</ul><p class="small">Structure adapted from <a href="{TRADING_AGENTS}">TauricResearch/TradingAgents</a> '
        f'(Apache-2.0) and its paper, <a href="{PAPER}">arXiv 2412.20138</a>. No code or prompt was copied.</p>'
        f"<details><summary>Exact rules (methodology {E(spec.SPEC_VERSION)})</summary><p>{E(spec.DESK_RULE)}</p>"
        '<p><a href="methodology.html#buy-sell-desk">Methodology page</a></p></details>'
    )
    return "".join(out)


def _points(points: list[dict]) -> str:
    sign = {"bull": "▲", "bear": "▼", "neutral": "–"}
    return (
        "<ul>"
        + "".join(
            f'<li><span aria-hidden="true">{sign[p["side"]]}</span> {E(p["text"])}'
            + (f' <span class="small muted">({p["vote"]:+d})</span>' if p["vote"] else "")
            + "</li>"
            for p in points
        )
        + "</ul>"
    )


def trace_page(e: dict, payload: dict, stored: bool) -> str:
    t = spec.DESK_RULES["trader"]
    out = [
        f"<h1>{E(e['ticker'])}: {rating_tag(e['rating'])}</h1>",
        f'<p><a href="../desk.html">Back to the Buy/Sell desk</a> · {E(e.get("name") or "")} · '
        f"price {money(e.get('price'))} on {E(payload['as_of'])}"
        + ("" if stored else " · build-time preview, not tracked")
        + "</p>",
        f'<p class="lede">{E(e["summary"])}</p>',
        '<p class="small">Rule-based research rating, not advice.</p>',
        "<h2>1. Analysts</h2>",
    ]
    for a in e["analysts"]:
        score = f" (score {a['score']:+d})" if isinstance(a.get("score"), int) else ""
        out.append(f'<div class="card"><h3>{E(a["title"])}: {E(a["stance"])}{E(score)}</h3>')
        out.append(_points(a["points"]) if a["points"] else "")
        if a.get("reason"):
            out.append(
                f'<p class="small muted">{"Abstains: " if a["vote"] is None else "Missing: "}{E(a["reason"])}</p>'
            )
        out.append("</div>")
    if e["rating"] is None:
        out.append(f"<p>{E(e['summary'])}</p>")
        return "".join(out)
    debate, risk = e["debate"], e["risk"]
    out += [
        "<h2>2. Bull vs bear debate</h2>",
        '<div class="grid"><div class="card"><h3>Bull researcher</h3>'
        + (
            "<ul>" + "".join(f"<li>{E(x)}</li>" for x in debate["bull"]) + "</ul>"
            if debate["bull"]
            else "<p>No bullish evidence.</p>"
        )
        + '</div><div class="card"><h3>Bear researcher</h3>'
        + (
            "<ul>" + "".join(f"<li>{E(x)}</li>" for x in debate["bear"]) + "</ul>"
            if debate["bear"]
            else "<p>No bearish evidence.</p>"
        )
        + "</div></div>",
        f"<p>Net analyst vote {debate['net']:+d}: <strong>{E(debate['verdict'])}</strong>.</p>",
        "<h2>3. Trader</h2>",
        f"<p>Net {debate['net']:+d} → <strong>{E(e['trader'])}</strong>. Rule: {t['buy_at_least']:+d} or more Buy, "
        f"{t['overweight_at_least']:+d} Overweight, {t['underweight_at_most']:+d} Underweight, "
        f"{t['sell_at_most']:+d} or less Sell, otherwise Hold.</p>",
        "<h2>4. Risk team</h2>",
        ("<ul>" + "".join(f"<li>{E(f['text'])}</li>" for f in risk["flags"]) + "</ul>")
        if risk["flags"]
        else "<p>No risk flags.</p>",
        (f'<p class="small muted">Not checked: {E("; ".join(risk["unchecked"]))}.</p>' if risk["unchecked"] else ""),
        '<div class="table-wrap"><table aria-label="Risk reviewers"><thead><tr><th>Reviewer</th><th>Rule</th>'
        "<th>Review</th></tr></thead><tbody>"
        + "".join(
            f'<tr><td>{E(name.title())}</td><td class="small">'
            + E(
                "; ".join(
                    f"{n}+ flags: {s} step{'s' if s > 1 else ''} down" for n, s in spec.DESK_RULES["reviewers"][name]
                )
            )
            + f"</td><td>{rating_tag(r)}</td></tr>"
            for name, r in risk["reviews"].items()
        )
        + "</tbody></table></div>",
        "<h2>5. Portfolio manager</h2>",
        f"<p>Middle review: {rating_tag(e['manager']['median'])}. "
        + (
            f"Capped at {E(spec.DESK_RULES['low_confidence_cap'])} because evidence confidence is low. "
            if e["manager"]["capped"]
            else ""
        )
        + f"Final rating: {rating_tag(e['rating'])}.</p>",
    ]
    return "".join(out)


def desk_csv(payload: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    keys = tuple(SHORT)
    w.writerow(
        [
            "ticker",
            "name",
            "rating",
            "net_vote",
            "trader",
            *[f"{k}_vote" for k in keys],
            "risk_flags",
            "lists",
            "benchmark",
            "price",
            "as_of",
            "spec_version",
        ]
    )
    for e in payload["entries"]:
        votes = {a["key"]: a["vote"] for a in e["analysts"]}
        flags = (e.get("risk") or {}).get("flags")
        w.writerow(
            [
                csv_value(v)
                for v in (
                    e["ticker"],
                    e.get("name"),
                    e["rating"] or "Not rated",
                    (e.get("debate") or {}).get("net"),
                    e.get("trader"),
                    *[votes.get(k) for k in keys],
                    "; ".join(f["text"] for f in flags) if flags else "",
                    " ".join(e["lists"]),
                    e.get("benchmark"),
                    e.get("price"),
                    payload["as_of"],
                    payload.get("spec_version"),
                )
            ]
        )
    return buf.getvalue()
