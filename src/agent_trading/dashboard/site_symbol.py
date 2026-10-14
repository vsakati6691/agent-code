"""Per-symbol pages: everything the stored snapshots know about one ticker, on one page."""
from __future__ import annotations

import html

from . import spec
from .fmt import money, num, pct
from .site_options import lists_of
from .site_overview import band_title, ordered

E = html.escape


def symbol_index(snap: dict) -> dict[str, str]:
    """{ticker: display name} for every symbol the latest snapshot mentions (lists, options, watchlist)."""
    out: dict[str, str] = {}
    for b in snap.get("bands", {}).values():
        for c in b.get("candidates", []):
            out.setdefault(c["ticker"], c.get("name") or "")
    for t in (snap.get("options") or {}).get("underlyings", []):
        out.setdefault(t, "")
    for e in (snap.get("watchlist") or {}).get("entries", []):
        out.setdefault(e["ticker"], e.get("name") or "")
    return dict(sorted(out.items()))


def _contracts(snap: dict, ticker: str) -> list[tuple[str, str, dict]]:
    o = snap.get("options") or {}
    rows = []
    for h in spec.HORIZONS:
        for kind, lst in lists_of(o.get(h.key) or {}).items():
            for x in (lst or {}).get("rows", []):
                if x.get("underlying") == ticker:
                    rows.append((h.title, kind[:-1], x))
    return rows


def symbol_page(ticker: str, snap: dict, history: list[dict]) -> str:
    bands = snap.get("bands", {})
    name, sector = "", ""
    ranks = []
    for k in ordered(bands):
        for c in bands[k].get("candidates", []):
            if c["ticker"] == ticker:
                name, sector = c.get("name") or name, c.get("sector") or sector
                ranks.append(f'<tr><td>{E(band_title(k, bands[k]))}</td><td class="num">{c["rank"]}</td>'
                             f'<td class="num">{num(c.get("composite"), 1)}</td><td class="num">{money(c.get("price"))}</td>'
                             f'<td><a href="../stock/{E(k)}-{E(ticker)}.html">Full research page</a></td></tr>')
    lists = (f'<div class="table-wrap"><table aria-label="Ranks in this week\'s lists"><thead><tr><th>List</th>'
             f'<th class="num">Rank</th><th class="num">Score</th><th class="num">Price</th><th></th></tr></thead>'
             f'<tbody>{"".join(ranks)}</tbody></table></div>' if ranks else
             '<p class="small muted">Not in any of this week\'s ranked lists.</p>')
    cons = _contracts(snap, ticker)
    opt_rows = "".join(
        f'<tr><td>{E(h)}</td><td>{E(kind)}</td><td class="num">{E(x["expiration"])}</td><td class="num">{money(x["strike"])}</td>'
        f'<td class="num">{money(x.get("premium_per_contract_ask"), 0)}</td><td class="num">{money(x.get("breakeven"))}</td>'
        f'<td class="num">{num((x.get("rank_components") or {}).get("total"), 1)}</td></tr>' for h, kind, x in cons)
    options = (f'<div class="table-wrap"><table aria-label="Option contracts listed for this symbol"><thead><tr><th>Horizon</th>'
               f'<th>Type</th><th class="num">Expiry</th><th class="num">Strike</th><th class="num">Premium (ask x 100)</th>'
               f'<th class="num">Breakeven</th><th class="num">Research score</th></tr></thead><tbody>{opt_rows}</tbody></table></div>'
               f'<p class="small"><a href="../options.html">All option comparisons</a></p>' if cons else
               '<p class="small muted">No listed option contracts for this symbol this week.</p>')
    w = next((e for e in (snap.get("watchlist") or {}).get("entries", []) if e["ticker"] == ticker), None)
    if w is None:
        watch = '<p class="small muted">Not on the watchlist.</p>'
    else:
        name = name or w.get("name") or ""
        sector = sector or w.get("sector") or ""
        sc = w.get("scenarios")
        watch = ('<p class="small">' + (" · ".join(f'{k} {money(sc[k]["price"])} ({pct(sc[k]["change"], 0, True)})'
                                                 for k in ("bear", "base", "bull")) if sc else
                                        f'Scenario unavailable: {E(w.get("unavailable_reason") or "")}') +
                 f' <a href="../watchlist.html">Watchlist 2030 page</a></p>')
    hist = []
    for s in history:
        for k in ordered(s.get("bands", {})):
            for c in s["bands"][k].get("candidates", []):
                if c["ticker"] == ticker:
                    hist.append(f'<tr><td>{E(str(s["as_of"]))}</td><td>{E(band_title(k, s["bands"][k]))}</td>'
                                f'<td class="num">{c["rank"]}</td><td class="num">{num(c.get("composite"), 1)}</td></tr>')
    history_html = (f'<div class="table-wrap"><table aria-label="Ranks in earlier weekly snapshots"><thead><tr><th>Week ending</th>'
                    f'<th>List</th><th class="num">Rank</th><th class="num">Score</th></tr></thead><tbody>{"".join(hist)}</tbody>'
                    f'</table></div>' if hist else '<p class="small muted">Not in any stored weekly list yet.</p>')
    return (f'<h1>{E(ticker)}{" · " + E(name) if name else ""}</h1><p class="lede">{E(sector) + " · " if sector else ""}Everything the '
            f'stored snapshots know about this symbol, as of {E(str(snap["as_of"]))}.</p>'
            f'<h2>This week\'s lists</h2>{lists}<h2>Option contracts</h2>{options}<h2>Watchlist 2030</h2>{watch}'
            f'<h2>History across snapshots</h2>{history_html}')
