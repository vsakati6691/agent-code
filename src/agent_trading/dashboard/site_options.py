"""Options page assembly; original helper imports remain compatible."""

from __future__ import annotations

from . import spec
from .fmt import money, num
from .site_options_rows import _missing_items as _missing_items
from .site_options_rows import _row as _row
from .site_options_rows import _score_cells as _score_cells
from .site_options_status import HZ_SHORT as HZ_SHORT
from .site_options_status import MISSING_FLAG_WORDS as MISSING_FLAG_WORDS
from .site_options_status import STATE_CLASS as STATE_CLASS
from .site_options_status import STATE_LABEL as STATE_LABEL
from .site_options_status import E as E
from .site_options_status import distance_text as distance_text
from .site_options_status import events_status as events_status
from .site_options_status import list_limit as list_limit
from .site_options_status import lists_of as lists_of
from .site_options_status import probability_text as probability_text
from .site_options_status import status_block as status_block
from .site_options_status import status_html as status_html
from .site_options_status import version_line as version_line


def _list(snap: dict, h, kind: str, data: dict | None, o: dict, fragments: dict | None = None) -> str:
    plural = f"{kind}s"
    if not data:
        return f'<div class="banner warn"><strong>No {plural} listed</strong>Not collected in this snapshot.</div>'
    limit = list_limit(snap, data)
    rows = data.get("rows", [])
    rej = "; ".join(f"{E(k)} ({v})" for k, v in sorted(data.get("rejections", {}).items(), key=lambda kv: -kv[1]))
    count = (
        f'<p class="small"><strong>{len(rows)} of up to {limit}</strong> {plural} qualified · {data.get("considered", 0)} '
        f"{plural} in the {h.min_dte}-{h.max_dte} day window were checked.</p>"
    )
    why = data.get("shortfall")
    if not rows:
        why = why or f"{data.get('status', '')}."
        return count + (
            f'<div class="banner warn"><strong>No {kind} qualified</strong>{E(why)} Filters are not weakened and no '
            "contracts are invented to fill the list.</div>"
        )
    short = (
        f'<details class="small"><summary>Why fewer than {limit} qualified</summary><p>{E(why)}</p></details>'
        if len(rows) < limit and why
        else ""
    )
    tid = f"o-{h.key}-{kind}"
    body = "".join(_row(x, kind, f"{tid}-{i}", o, fragments) for i, x in enumerate(rows))
    head = (
        "<th class='num' data-sort='num'>#</th><th class='tk' data-sort='text'>Underlying</th>"
        "<th class='num' data-sort='text' title='Actual expiration date and calendar days remaining'>Expiry</th>"
        "<th class='num' data-sort='num'>Strike</th><th class='num hide-sm' data-sort='num' title='Underlying stock price at the "
        "as-of close'>Stock price</th><th class='num hide-sm' title='Delayed bid and ask per share'>Bid / ask</th>"
        "<th class='num' data-sort='num' title='Ask x 100 shares: the illustrative cost of one contract'>Premium*</th>"
        "<th class='num' data-sort='num' title='Stock price at expiry where the contract breaks even, and the move needed to get there'>Breakeven at expiry</th>"
        "<th class='num crit' data-sort='num' title='Most a buyer can lose: the entire premium paid'>Max loss</th>"
        "<th class='num hide-sm' data-sort='num' title='Ask minus bid, as a share of the mid price'>Spread</th>"
        "<th class='num hide-sm' data-sort='num' title='Contracts traded in the last session'>Volume</th>"
        "<th class='num hide-sm' data-sort='num' title='Open interest: contracts outstanding'>Open int.</th>"
        "<th class='num hide-sm' data-sort='num' title='Implied volatility: the yearly move the option price assumes'>IV</th>"
        "<th class='num hide-sm' data-sort='num' title='Price change per $1 move in the stock (model). Not a probability "
        "of profit'>Delta</th>"
        "<th class='num hide-sm' data-sort='num' title='Value lost per day from time decay, per share (model)'>Theta</th>"
        "<th class='hide-sm' title='Scheduled earnings before expiry; unknown when the calendar was not collected'>Earnings before expiry</th>"
        "<th class='num' data-sort='num' title='Liquidity, breakeven vs implied move and time decay (0-100); not a "
        "prediction of profit'>Research score</th>"
        "<th class='hide-sm' title='Shown as a percentage only with documented out-of-sample calibration'>Probability of profit</th>"
    )
    exclusions = (
        f'<details class="small"><summary>Why other {plural} in this window were left out</summary><p>{rej or "none left out"}.</p>'
        f'<p class="muted">Exclusion reasons apply the fixed rules: open interest ≥ {spec.OPTION_RULES["min_open_interest"]}, '
        f"volume ≥ {spec.OPTION_RULES['min_volume']}, spread ≤ {spec.OPTION_RULES['max_spread_pct']:.0%}, |delta| "
        f"{spec.OPTION_RULES['min_delta']}-{spec.OPTION_RULES['max_delta']}, implied volatility and theta present, standard "
        f"contracts, at most {spec.OPTION_RULES['max_per_underlying_per_horizon']} per underlying; the list limit keeps the "
        f"highest research scores.</p></details>"
    )
    return (
        count
        + f"""<div class="table-wrap wide"><table id="{tid}" data-table data-grouped><caption class="sr-only">{E(h.title)} {plural}</caption>
<thead><tr>{head}</tr></thead>{body}</table></div>
<p class="small">Select an underlying to show every fact, assumption, risk and payoff for that contract. <a href="downloads/{E(snap["as_of"])}_options_{h.key}_{plural}.csv" download>Download {plural} (CSV)</a></p>{short}{exclusions}"""
    )


def options_page(
    snap: dict, daily: dict | None = None, fragments: dict | None = None, horizon: str | None = None
) -> str:
    from .site_refresh import options_section
    from .site_short_term import navigation
    from .site_speculative import section as speculative_section

    o = snap.get("options") or {}
    horizons = [h for h in spec.HORIZONS if horizon is None or h.key == horizon]
    r = spec.OPTION_RULES
    state = status_block(snap)
    head = (
        navigation()
        + f"""<h1>Options</h1><p>Stored calls and puts by expiry, premium and maximum loss.</p>
<p class="small bad" id="options-critical">Buying an option can lose the entire premium.</p>
<p class="small" id="options-status" data-state="{E(state["state"])}" title="{E(state["headline"])}">Options: {E(STATE_LABEL[state["state"]])} · <a href="audit.html#options-data">Data details</a>.</p>"""
    )
    guide = f"""<details class="card small"><summary>Eligibility, pricing and probability limits</summary>
<p>{E(spec.OPTION_UNIVERSE_TEXT)}</p><p>{E(spec.OPTION_TOP_DEFINITION)}</p><p>{E(spec.OPTION_RANKING_NOTE)}</p>
<p>Eligibility (fixed in advance): open interest ≥ {r["min_open_interest"]}, volume ≥ {r["min_volume"]}, spread ≤
{r["max_spread_pct"]:.0%} of mid, |delta| {r["min_delta"]}-{r["max_delta"]} (calls positive, puts negative), implied volatility and
theta present, standard 100-share contracts, at most {r["max_per_underlying_per_horizon"]} per underlying per list, up to
{r["max_per_type_per_horizon"]} per list. Expiry windows: {E(", ".join(f"{h.title.lower()} = {h.min_dte}-{h.max_dte} days" for h in spec.HORIZONS))}.</p>
<p>{E(spec.OPTION_THETA_RULE)} {E(spec.OPTION_QUOTE_RULE)} {E(spec.OPTION_EVENT_RULE)}</p>
<div class="banner warn small"><strong>Delta is not a probability of profit</strong>{E(spec.DELTA_STATEMENT)}</div>
<div class="banner info small"><strong>* Premium assumption and fees</strong>{E(spec.PREMIUM_ASSUMPTION)} {E(spec.FEE_TREATMENT)}
Quotes are delayed, end-of-session data from Cboe for {E(str(snap["as_of"]))}; payoffs at expiration are exact arithmetic on that
premium, while before-expiration values are Black-Scholes MODEL estimates.</div>
<div class="banner info small"><strong>Probability of profit: {E(spec.PROBABILITY_NOT_ESTABLISHED)}</strong>{E(spec.PROBABILITY_OF_PROFIT_DEFINITION)}
{E(spec.ITM_PROBABILITY_DEFINITION)} {E(spec.PROBABILITY_NEVER_SUBSTITUTED)} <a href="methodology.html#probability">Validation gate and missing data</a>.</div></details>"""
    extra = guide + speculative_section(snap, daily) + options_section(snap, daily or {})
    if not o.get("enabled") or o.get("status") != "ok" or not o.get("underlyings"):
        return head + (
            '<details class="empty-data"><summary>Options lists unavailable</summary><p class="small">Top 5 calls and top 5 puts for about 3 months, 6 months and 1 year '
            "to expiry will appear here once option chains are collected and validated for a snapshot (see the "
            'status above). The <a href="methodology.html">methodology</a> page has every rule.</p></details>' + extra
        )
    # ARIA tabs pattern over two dimensions: a type tab controls that type's three panels, a horizon tab the two
    # panels in that window, and each panel names both tabs; the ids never collide with the #call-3m view hashes
    if horizon:
        head += (
            '<nav aria-label="Option expiry lists">'
            + " ".join(f'<a class="action" href="options-{h.key}.html">{E(h.title)}</a>' for h in spec.HORIZONS)
            + "</nav><p>These larger historical lists are split by expiry. Every stored contract remains available.</p>"
        )
    hz_tabs = "".join(
        f'<button role="tab" id="otab-hz-{h.key}" aria-controls="{" ".join(f"opanel-{k}-{h.key}" for k in spec.OPTION_TYPES)}" '
        f'data-dim="hz" data-val="{h.key}" aria-selected="false" title="{E(h.title)} · {h.min_dte}-{h.max_dte} days">{E(HZ_SHORT[h.key])}</button>'
        for h in horizons
    )
    type_tabs = "".join(
        f'<button role="tab" id="otab-type-{k}" aria-controls="{" ".join(f"opanel-{k}-{h.key}" for h in horizons)}" '
        f'data-dim="type" data-val="{k}" aria-selected="false">{k.capitalize()}s</button>'
        for k in spec.OPTION_TYPES
    )
    panels = []
    for h in horizons:
        ls = lists_of(o.get(h.key) or {})
        for kind in spec.OPTION_TYPES:
            panels.append(
                f'<section data-hz="{h.key}" data-type="{kind}" id="opanel-{kind}-{h.key}" role="tabpanel" '
                f'aria-labelledby="otab-type-{kind} otab-hz-{h.key}" hidden><h2 class="sr-only">{E(h.title)} · {kind}s · '
                f"{h.min_dte}-{h.max_dte} days to expiry</h2>{_list(snap, h, kind, ls.get(f'{kind}s'), o, fragments)}</section>"
            )
    quotes = o.get("quotes") or {}
    qrows = "".join(
        f"<li>{E(s)}: {E(q.get('quote_status', ''))}; snapshot {E(str(q.get('quote_time_utc') or 'not stored').replace('+00:00', ''))} UTC; "
        f"underlying last trade {E(str(q.get('underlying_last_trade') or 'not stored'))}</li>"
        for s, q in sorted(quotes.items())
    )
    earn = (
        f'<div class="banner warn small"><strong>Earnings dates</strong>{E(o["earnings_note"])} Every contract\'s earnings status reads "unknown".</div>'
        if o.get("earnings_note")
        else ""
    )
    return (
        head
        + f"""<div data-matrix><div class="tabs seg" role="tablist" aria-label="Option type">{type_tabs}</div>
<div class="tabs" role="tablist" aria-label="Expiry horizon">{hz_tabs}</div>{"".join(panels)}</div>
{summary_strip(snap)}
<details><summary>Underlying coverage and controls</summary><p class="small">Underlyings with a valid chain: {E(", ".join(o.get("underlyings", [])) or "none")}. Use the controls to choose calls or puts and an expiry window; arrow keys move between tabs.</p>{earn}</details>
<details><summary>Quote snapshot times by underlying ({len(quotes)})</summary><ul class="small">{qrows or '<li class="muted">not stored in this snapshot</li>'}</ul></details>
{extra}"""
    )


def summary_strip(snap: dict) -> str:
    """One line per option type: how many contracts each horizon list holds, linking to that view."""
    o = snap.get("options") or {}
    parts = []
    for kind in spec.OPTION_TYPES:
        cells = []
        for h in spec.HORIZONS:
            lst = lists_of(o.get(h.key) or {}).get(f"{kind}s") or {}
            n, lim = len(lst.get("rows", [])), list_limit(snap, lst)
            cells.append(f'<a href="#{kind}-{h.key}">{E(HZ_SHORT[h.key])} <strong>{n}</strong>/{lim}</a>')
        parts.append(f'<span class="chip"><strong>{kind.capitalize()}s</strong> {" · ".join(cells)}</span>')
    return f'<div class="strip" aria-label="Contracts per list">{"".join(parts)}</div>'


# --- overview: the options watchlist block --------------------------------------------------------------


def watchlist_cards(snap: dict) -> str:
    """Prominent overview block: six compact lists (or the plain-language status when none can be shown)."""
    o = snap.get("options") or {}
    intro = '<p class="small">Long options can lose the entire premium. <a href="options.html">Lists, eligibility and payoff details</a>.</p>'
    state = status_block(snap)
    status = f'<p class="small" data-state="{E(state["state"])}">Options: {E(state["label"])} · <a href="audit.html#options-data">Collection details</a>.</p>'
    if not o.get("enabled") or o.get("status") != "ok":
        return f'<details class="empty-data" id="options-watchlist"><summary>Options watchlist unavailable</summary>{intro}{status}</details>'
    cards = []
    for kind in spec.OPTION_TYPES:
        for h in spec.HORIZONS:
            lst = lists_of(o.get(h.key) or {}).get(f"{kind}s") or {}
            rows = lst.get("rows", [])
            lim = list_limit(snap, lst)
            items = "".join(
                f'<li><a href="symbol/{E(x["underlying"])}.html"><strong>{E(x["underlying"])}</strong></a> {money(x["strike"])} {kind} · '
                f"exp {E(x['expiration'])} ({x['dte']}d) · premium {money(x['premium_per_contract_ask'], 0)} · "
                f'{E(distance_text(kind, x.get("breakeven_move")).split(" (")[0])} to breakeven · <span class="crit">max loss '
                f"{money(x['max_loss_per_contract'], 0)}</span> · score {num((x.get('rank_components') or {}).get('total'), 1)}</li>"
                for x in rows
            )
            body = (
                f'<ol class="tight small">{items}</ol>'
                if items
                else f'<p class="small muted">{E(lst.get("shortfall") or lst.get("status") or "none qualified")}</p>'
            )
            short = (
                f'<p class="small muted">{len(rows)} of up to {lim}: {E(lst.get("shortfall") or "")}</p>'
                if items and len(rows) < lim
                else ""
            )
            cards.append(
                f'<section class="card"><h3>{kind.capitalize()}s · {E(h.title.lower())} <span class="small muted">'
                f"({h.min_dte}-{h.max_dte} days)</span></h3>{body}{short}"
                f'<p class="small"><a href="options.html#{kind}-{h.key}">Details, risks and payoffs →</a></p></section>'
            )
    return (
        f'<h2 id="options-watchlist">Options watchlist</h2>{intro}{status}<div class="ow-grid">{"".join(cards)}</div>'
    )
