"""Display-only daily context; never edit the weekly snapshot passed to a renderer."""

from __future__ import annotations

import html
import shutil
from pathlib import Path

from . import spec
from .fmt import money, num, pct, sval
from .price_integrity import SHORT_NOTE, preclose
from .refresh_store import RefreshStore

E = html.escape


def partial_details(data: dict) -> str:
    if data.get("status") != "partial":
        return ""
    missing = []
    for key, title in (("quotes", "Quote"), ("chain_status", "Options chain")):
        for symbol, item in sorted((data.get(key) or {}).items()):
            item = item or {}
            if item.get("status") != "available":
                missing.append(f"{title} {symbol}: {item.get('reason') or 'reason not recorded'}")
    options = data.get("options") or {}
    if options.get("enabled") and not options.get("events_known"):
        missing.append("Earnings calendar: " + (options.get("earnings_reason") or "unavailable"))
    if not missing:
        missing.append("Incomplete refresh; the stored record did not provide dataset-level reasons.")
    usage = data.get("usage") or {}
    request_counts, budgets = (usage.get(k) or {} for k in ("requests", "budgets"))
    counts = [
        f"{provider}: {request_counts.get(provider, 0)} requests / {budgets.get(provider, 'unknown')} budget"
        for provider in sorted(set(request_counts) | set(budgets))
    ]
    return (
        f'<details class="refresh-missing"><summary>Not refreshed ({len(missing)})</summary><ul>'
        + "".join(f"<li>{E(str(reason))}</li>" for reason in missing)
        + "</ul>"
        + (
            f"<p>Request usage: {E('; '.join(counts))}. Total cache hits: {E(str(usage.get('cache_hits', 0)))}.</p>"
            if counts
            else ""
        )
        + "</details>"
    )


def load_context(data: Path, snap: dict, out: Path) -> dict:
    store = RefreshStore(data)
    valid, problems = [], []
    for session in store.dates():
        try:
            record = store.load(session)
            valid.append(record)
        except (OSError, ValueError, KeyError, TypeError):
            problems.append(session)
    for record in valid[-30:]:
        dest = out / "data" / "daily" / record["as_of"]
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("refresh.json", "manifest.json"):
            shutil.copyfile(store.folder(record["as_of"]) / name, dest / name)
    latest = valid[-1] if valid else None
    reason = "Daily data missing: no verified daily refresh has been stored."
    if latest and latest["as_of"] < snap["as_of"]:
        reason = f"Daily data ({latest['as_of']}) is older than the weekly snapshot."
        latest = None
    elif latest and latest["weekly_as_of"] != snap["as_of"]:
        reason = "Daily data belongs to a different weekly candidate set."
        latest = None
    if problems and (not latest or max(problems) > latest["as_of"]):
        reason = "Latest daily data failed its integrity check."
        latest = None
    return {"data": latest, "reason": reason if latest is None else "", "weekly_preclose": preclose(snap)}


def banner(snap: dict, context: dict | None) -> str:
    weekly_date = str(snap.get("as_of") or "unavailable")
    data = (context or {}).get("data")
    if not data:
        reason = (context or {}).get("reason") or "Daily data missing: no daily refresh available."
        return (
            f'<p class="small muted daily-status" title="{E(reason)}">Daily refresh unavailable · weekly {E(weekly_date)} · '
            '<a href="audit.html#daily-context">Details</a>.</p>'
        )
    stamp = str(data["collected_at"]).replace("T", " ").replace("+00:00", "").removesuffix("Z")
    state_class = "warn" if data.get("status") == "partial" else "info"
    return (
        f'<div class="banner {state_class} small daily-status" role="note" aria-label="Daily data status" title="Collected {E(stamp)} UTC">'
        f"Daily: {E(data['as_of'])} · delayed · {E(data['status'])} · "
        '<a href="audit.html#daily-context">Refresh details</a></div>'
    )


def audit_context(snap: dict, context: dict | None) -> str:
    data = (context or {}).get("data") or {}
    text = (
        f"Collected {data.get('collected_at', 'time not stored')}; session {data.get('as_of', 'date not stored')}; "
        f"refresh status: {data.get('status', 'not stored')}."
        if data
        else (context or {}).get("reason") or "Daily data missing: no daily refresh available."
    )
    return (
        '<section id="daily-context"><h2>Daily refresh details</h2>'
        f"<p>{E(text)} Weekly snapshot {E(snap['as_of'])}. Scores, ranks and trailing returns remain weekly. "
        "Change since weekly is an unadjusted price comparison; splits and dividends can affect it. "
        "Quotes are delayed, never live.</p>"
        + partial_details(data).replace(
            '<details class="refresh-missing"><summary>', '<details class="refresh-missing" open><summary>'
        )
        + "</section>"
    )


def price(symbol: str, weekly, context: dict | None) -> tuple[float | None, str]:
    data = (context or {}).get("data")
    if data is None:
        return weekly, SHORT_NOTE if (context or {}).get("weekly_preclose") else "Weekly close"
    quote = data.get("quotes", {}).get(symbol) or {}
    if quote.get("status") != "available":
        return None, "Daily unavailable: " + (quote.get("reason") or "not collected")
    value = quote["close"]
    delta = value / weekly - 1 if isinstance(weekly, (int, float)) and weekly > 0 else None
    if (context or {}).get("weekly_preclose"):
        return value, f"Daily close · {pct(delta, 1, True)} vs stored intraday input (correction 2026-10-16)"
    return value, f"Daily close · {pct(delta, 1, True)} since weekly"


def options_section(snap: dict, context: dict) -> str:
    head = '<section id="daily-options"><h2>Daily view</h2>' + banner(snap, context)
    data = context.get("data")
    if data is None:
        return (
            '<details class="empty-data" id="daily-options"><summary>Daily options unavailable</summary>'
            + banner(snap, context)
            + '<p class="small">The weekly tracked lists appear above.</p></details>'
        )
    options = data.get("options") or {}
    if not options.get("enabled"):
        return '<details class="empty-data" id="daily-options"><summary>Daily options unavailable</summary><p>Collection disabled.</p></details>'
    parts = [
        head,
        '<details><summary>Daily list basis</summary><p class="small">Existing eligibility and ranking rules, recomputed on daily delayed chains. '
        "These lists are not added to weekly performance tracking. Premium and maximum loss = ask × 100; "
        "fees are not deducted. Buying an option can lose the entire premium. "
        f"{E(spec.PROBABILITY_NOT_ESTABLISHED)} Delta is not a probability.</p></details>",
    ]
    for h in spec.HORIZONS:
        for kind in spec.OPTION_TYPES:
            lst = (options.get(h.key) or {}).get(kind + "s") or {}
            rows = []
            for row in lst.get("rows", []):
                rows.append(
                    f'<tr><td>{E(row["underlying"])} {kind}<div class="small">{E(row["expiration"])} · {row["dte"]}d</div></td>'
                    f'<td class="num">{money(row["strike"])}</td>'
                    f'<td class="num" data-v="{sval(row["premium_per_contract_ask"])}">{money(row["premium_per_contract_ask"])}</td>'
                    f'<td class="num crit">{money(row["max_loss_per_contract"])}</td>'
                    f'<td class="num">{money(row["breakeven"])}</td>'
                    f'<td class="num">{num((row.get("rank_components") or {}).get("total"), 1)}</td>'
                    f'<td class="small">{E(row.get("events_status") or "unknown")}</td></tr>'
                )
            parts.append(f"<details><summary>{E(h.title)} · {kind}s · {len(rows)} of up to 5</summary>")
            if rows:
                parts.append(
                    f'<div class="table-wrap"><table id="daily-{h.key}-{kind}" data-table>'
                    f'<caption class="sr-only">Daily {h.key} {kind}s</caption><thead><tr>'
                    '<th>Contract</th><th>Strike</th><th data-sort="num">Premium</th><th>Max loss</th>'
                    "<th>Breakeven</th><th>Research score</th><th>Earnings before expiry</th></tr></thead>"
                    f"<tbody>{''.join(rows)}</tbody></table></div>"
                )
            if lst.get("shortfall"):
                parts.append(f'<p class="small">{E(lst["shortfall"])}</p>')
            parts.append("</details>")
    if any(item["status"] != "available" for item in data.get("chain_status", {}).values()):
        parts.append('<p class="small"><a href="audit.html#daily-context">Unavailable daily chains and reasons</a></p>')
    parts.append(
        f'<p class="small"><a href="data/daily/{E(data["as_of"])}/refresh.json">Daily data and quote timestamps (JSON)</a></p></section>'
    )
    return "".join(parts)
