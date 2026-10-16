"""Compact, escaped display of optional public datasets, including old-snapshot gaps."""

from __future__ import annotations

from .fmt import cap, num, pct
from .macro import SERIES, rate_input
from .pipeline_external import OLD
from .sec_insiders import CLASSIFICATION, LABEL
from .short_interest import LABEL as SHORT_LABEL
from .site_layout import E
from .site_status import notice


def source(url: str | None, label: str = "Source") -> str:
    return (
        f'<a href="{E(url)}" rel="noopener">{E(label)}</a>'
        if url and url.startswith("https://")
        else "Source unavailable"
    )


def gap(record: dict, fallback: str = OLD) -> str:
    return E(record.get("reason") or fallback)


def company(c: dict) -> str:
    data = c.get("external") or {}
    insider, holders, short, risk = (
        data.get(k) or {} for k in ("insiders", "institutions", "short_interest", "risk_excerpt")
    )
    activity = []
    for key, label in (("90d", "90 days"), ("12m", "12 months")):
        row = insider.get("windows", {}).get(key, {})
        activity.append(
            f"<tr><td>{label}<br><small>{E(row.get('start') or 'n/a')} to {E(row.get('end') or 'n/a')}</small></td>"
            f"<td>{num(row.get('net_shares'), 0)} shares</td><td>{cap(row.get('net_dollars'))}"
            f"<small>{E(row.get('dollars_reason') or '')}</small></td>"
            f"<td>{num(row.get('buyers'), 0)} / {num(row.get('sellers'), 0)}</td></tr>"
        )
    insider_sources = " ".join(source(f.get("url"), f["accession"]) for f in insider.get("filings", [])[:5])
    holders_body = "<p>Unavailable · " + gap(holders) + "</p>"
    if holders.get("holder_count") is not None:
        top = "".join(f"<li>{E(h['name'])}: {num(h['shares'], 0)} shares</li>" for h in holders.get("top_holders", []))
        holders_body = (
            f"<p>{num(holders['holder_count'], 0)} holders · {num(holders.get('reported_shares'), 0)} reported shares. "
            f"Quarter ended {E(holders.get('report_quarter_end') or 'n/a')} · lag {num(holders.get('filing_lag_days'), 0)} days. "
            f"QoQ holders {num(holders.get('holder_count_change'), 0)}; shares {num(holders.get('reported_shares_change'), 0)}.</p>"
            f'<p class="small">{E(holders.get("change_reason") or "")} {E(holders.get("note") or "")} '
            f"{source(holders.get('source'), 'SEC 13F archive')} · {source(holders.get('mapping_url'), 'CUSIP mapping')} "
            f"file {E(holders.get('mapping_date') or 'n/a')}.</p><ol>{top}</ol>"
        )
    short_body = "<p>Unavailable · " + gap(short) + "</p>"
    if short.get("shares_short") is not None:
        short_body = (
            f"<p>{num(short['shares_short'], 0)} shares short · settlement {E(short.get('settlement_date') or 'n/a')} · "
            f"change {num(short.get('change_shares'), 0)} shares versus prior report {E(short.get('prior_settlement_date') or 'date unavailable')}.</p>"
            f"<p>{SHORT_LABEL}: {pct(short.get('percent_of_diluted_shares'), 2)}. "
            f"{E(short.get('percent_reason') or '')} Basis: {num(short.get('diluted_shares'), 0)} "
            f"quarterly diluted weighted-average shares dated {E(short.get('shares_date') or 'n/a')}.</p>"
            f"<p>Days to cover: {num(short.get('days_to_cover'), 2)} · {E(short.get('days_to_cover_reason') or '')}. "
            f"{source(short.get('source'), 'FINRA settlement report')}</p>"
        )
    risk_body = "<p>Unavailable · " + gap(risk) + "</p>"
    if risk.get("excerpt"):
        bounds = risk.get("character_range")
        location = (
            f"characters {bounds[0]}–{bounds[1]} (end exclusive)"
            if bounds
            else risk.get("range_reason", "Character range unavailable")
        )
        risk_body = (
            f'<blockquote>{E(risk["excerpt"])}</blockquote><p class="small">{source(risk.get("url"), "Issuer filing")} · '
            f"{E(risk.get('form') or 'n/a')} filed {E(risk.get('filed') or 'n/a')} · "
            f"{E(risk.get('accession') or 'accession unavailable')} · {E(location)}. "
            f"{E(risk.get('range_basis') or '')} Issuer quotation, not independent analysis.</p>"
        )
    return f"""<section class="external-research"><h2>Insider activity</h2><p>{E(LABEL)}</p>
<p class="small">{E(insider.get("classification_basis") or CLASSIFICATION)}. Latest transaction: {E(insider.get("latest_transaction_date") or "unavailable")}.</p>
<div class="table-wrap"><table aria-label="Dated insider P/S activity"><thead><tr><th>Window</th><th>Net shares</th><th>Net dollars</th><th>Distinct buyers / sellers</th></tr></thead><tbody>{"".join(activity)}</tbody></table></div>
<p class="small">{gap(insider) if insider.get("state") != "available" else "Complete retrieved filing window."} {insider_sources}</p>
<h2>Institutional holders</h2><p class="small">Status: {E(holders.get("state") or "missing")} · {E(holders.get("reason") or "")}</p>{holders_body}
<h2>Short interest</h2>{short_body}
<h2>Risk-factor quotation</h2><p class="small">{E(risk.get("reason") or "")}</p>{risk_body}</section>"""


def macro_context(snap: dict) -> str:
    series = (snap.get("macro") or {}).get("series") or {}
    items, gaps = [], []
    for key, label in (
        ("DGS1MO", "1M Treasury"),
        ("DGS2", "2Y Treasury"),
        ("DGS10", "10Y Treasury"),
        ("FEDFUNDS", "Fed funds"),
        ("CPIAUCSL", "CPI YoY"),
        ("UNRATE", "Unemployment"),
    ):
        r = series.get(key) or {}
        value = r.get("yoy") if key == "CPIAUCSL" else r.get("value")
        value_text = "Unavailable" if value is None else pct(value, 2) if key == "CPIAUCSL" else num(value, 2) + "%"
        reason = (r.get("yoy_reason") if key == "CPIAUCSL" else r.get("reason")) or OLD
        if value is None:
            gaps.append(f"{label}: {reason}")
        items.append(
            f'<div class="card macro-card"><strong>{source(f"https://fred.stlouisfed.org/series/{key}", label)}</strong><div>{value_text}</div>'
            f"<small>{E(r.get('observation_date') or 'No observation stored')}</small></div>"
        )
    warning = (
        notice(
            "Macro inputs unavailable",
            f"{len(gaps)} of {len(items)} displayed series lack a usable observation. Available values retain their recorded dates.",
            gaps,
        )
        if gaps
        else ""
    )
    return f'<section><h2>Macro context</h2>{warning}<div class="grid">{"".join(items)}</div><p class="small"><a href="downloads/{E(str(snap["as_of"]))}_macro.csv">Macro CSV</a></p></section>'


def rate_note(snap: dict) -> str:
    try:
        rate = (snap.get("options") or {}).get("rate_input") or rate_input(snap.get("macro"))
    except (AttributeError, KeyError, TypeError):
        rate = {"value": None, "reason": "Stored Treasury observation is incomplete; dated rate unavailable."}
    value = rate.get("value")
    text = (
        f"DGS1MO {value:.3%}, observation {rate.get('date') or 'date unavailable'}"
        if value is not None
        else "Unavailable · " + (rate.get("reason") or OLD)
    )
    warning = notice("Treasury rate unavailable", rate.get("reason") or OLD) if value is None else ""
    return (
        warning
        + f'<p class="small">Dated Black-Scholes rate input: {E(text)}. {source(rate.get("source"), "FRED DGS1MO")}. Previously stored estimates retain their recorded assumptions.</p>'
    )


def csv_fields(c: dict) -> dict:
    data = c.get("external") or {}
    out = {}
    for name in ("insiders", "institutions", "short_interest", "risk_excerpt"):
        r = data.get(name) or {}
        out[name + "_state"] = r.get("state", "missing")
        out[name + "_reason"] = r.get("reason", OLD if not r else None)
    insider = data.get("insiders") or {}
    out["insider_classification_basis"] = insider.get("classification_basis")
    out["insider_latest_transaction_date"] = insider.get("latest_transaction_date")
    out["insider_accessions"] = ";".join(insider.get("accessions", []))
    out["insider_filings"] = "; ".join(
        f"{f['accession']} filed {f['filed']} {f.get('url', '')} 10b5-1: "
        + ("unknown" if f.get("plan_10b5_1") is None else "yes" if f["plan_10b5_1"] else "no")
        for f in insider.get("filings", [])
    )
    out["insider_excluded_rows"] = "; ".join(f"{k}: {v}" for k, v in insider.get("excluded_rows", {}).items())
    for window in ("90d", "12m"):
        row = insider.get("windows", {}).get(window, {})
        for key in ("start", "end", "net_shares", "net_dollars", "buyers", "sellers", "reason", "dollars_reason"):
            out[f"insider_{window}_{key}"] = row.get(key)
    for name, keys in (
        (
            "institutions",
            (
                "report_quarter_end",
                "holder_count",
                "reported_shares",
                "holder_count_change",
                "reported_shares_change",
                "change_reason",
                "mapping_date",
                "mapping_url",
                "source",
                "top_holders",
            ),
        ),
        (
            "short_interest",
            (
                "settlement_date",
                "shares_short",
                "change_shares",
                "prior_settlement_date",
                "days_to_cover",
                "days_to_cover_reason",
                "percent_of_diluted_shares",
                "percent_label",
                "diluted_shares",
                "shares_date",
                "shares_basis",
                "percent_reason",
                "source",
            ),
        ),
        (
            "risk_excerpt",
            ("filed", "form", "accession", "url", "excerpt", "character_range", "range_basis", "text_sha256"),
        ),
    ):
        row = data.get(name) or {}
        for key in keys:
            value = row.get(key)
            if key == "top_holders":
                value = "; ".join(f"{h['name']} (CIK {h['cik']}): {h['shares']} shares" for h in value or [])
            elif isinstance(value, list):
                value = ";".join(str(v) for v in value)
            out[f"{name}_{key}"] = value
    return out


def macro_rows(snap: dict) -> list[dict]:
    series = (snap.get("macro") or {}).get("series", {})
    return [
        {
            "series": key,
            **{
                field: series.get(key, {}).get(field)
                for field in (
                    "state",
                    "reason",
                    "value",
                    "observation_date",
                    "last_updated",
                    "vintage_date",
                    "source",
                    "yoy",
                )
            },
            "yoy_dates": ";".join(series.get(key, {}).get("yoy_dates", [])),
            "state": series.get(key, {}).get("state", "missing"),
            "reason": series.get(key, {}).get("reason", OLD if key not in series else None),
        }
        for key in SERIES
    ]
