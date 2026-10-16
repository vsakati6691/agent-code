"""Display-only daily context; never edit the weekly snapshot passed to a renderer."""

from __future__ import annotations

import html
import shutil
from pathlib import Path

from . import spec
from .fmt import money, num, pct, sval
from .refresh_store import RefreshStore

E = html.escape


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
    return {"data": latest, "reason": reason if latest is None else ""}


def banner(snap: dict, context: dict | None) -> str:
    weekly_date = str(snap.get("as_of") or "unavailable")
    data = (context or {}).get("data")
    if not data:
        reason = (context or {}).get("reason") or "Daily data missing: no daily refresh available."
        return (
            f'<p class="small muted daily-status">{E(reason)} Showing weekly data; '
            f"weekly snapshot {E(weekly_date)}.</p>"
        )
    stamp = str(data["collected_at"]).replace("T", " ").replace("+00:00", "").removesuffix("Z")
    return (
        f'<div class="banner info small daily-status"><strong>Daily refresh, {E(stamp)} UTC, delayed, not live</strong>'
        f"Session {E(data['as_of'])} · weekly snapshot {E(weekly_date)} · "
        f"refresh status: {E(data['status'])}. Scores, ranks and trailing returns remain weekly. "
        "Change since weekly is an unadjusted price comparison; splits and dividends can affect it.</div>"
    )


def price(symbol: str, weekly, context: dict | None) -> tuple[float | None, str]:
    data = (context or {}).get("data")
    if data is None:
        return weekly, "Weekly close"
    quote = data.get("quotes", {}).get(symbol) or {}
    if quote.get("status") != "available":
        return None, "Daily unavailable: " + (quote.get("reason") or "not collected")
    value = quote["close"]
    delta = value / weekly - 1 if isinstance(weekly, (int, float)) and weekly > 0 else None
    return value, f"Daily close · {pct(delta, 1, True)} since weekly"


def options_section(snap: dict, context: dict) -> str:
    head = '<section id="daily-options"><h2>Daily view</h2>' + banner(snap, context)
    data = context.get("data")
    if data is None:
        return head + '<p class="small">The weekly tracked lists appear below.</p></section>'
    options = data.get("options") or {}
    if not options.get("enabled"):
        return head + "<p>Daily options unavailable: collection disabled.</p></section>"
    parts = [
        head,
        '<p class="small">Existing eligibility and ranking rules, recomputed on daily delayed chains. '
        "These lists are not added to weekly performance tracking. Premium and maximum loss = ask × 100; "
        "fees are not deducted. Buying an option can lose the entire premium. "
        f"{E(spec.PROBABILITY_NOT_ESTABLISHED)} Delta is not a probability.</p>",
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
    failed = "".join(
        f"<li>{E(symbol)}: unavailable — {E(item['reason'])}</li>"
        for symbol, item in data.get("chain_status", {}).items()
        if item["status"] != "available"
    )
    if failed:
        parts.append(f"<details><summary>Unavailable daily chains</summary><ul>{failed}</ul></details>")
    parts.append(
        f'<p class="small"><a href="data/daily/{E(data["as_of"])}/refresh.json">Daily data and quote timestamps (JSON)</a></p></section>'
    )
    return "".join(parts)
