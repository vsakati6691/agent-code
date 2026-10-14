"""HTML for the company research panel, 'What changed', the scenario calculator and data states (spec 2026-10-14.5)."""
from __future__ import annotations

import html
import json

from . import spec
from .changes import KIND_LABELS
from .fmt import money, num, pct

E = html.escape
VERDICT_CLASS = {"Clean": "ok", "Watch": "warn", "Concerning": "bad", "Not meaningful": "muted", "Not measurable": "muted"}
STATUS_CLASS = {"breached": "bad", "holding": "ok", "not measurable": "muted"}
STATE_CLASS = {"available": "ok", "partial": "warn", "stale": "warn", "missing": "muted", "provider_error": "bad"}


def _link(label: str, url: str | None) -> str:
    return f'<a href="{E(url)}" rel="noopener">{E(label)}</a>' if url else E(label)


def quality_badge(level: str, label: str | None, missing: int | None = None) -> str:
    """The same evidence badge everywhere: level, the source's own label, and the count of missing inputs."""
    tail = "" if missing is None else f' · {missing} missing input{"s" if missing != 1 else ""}'
    shown = label if label and label != level else level
    return (f'<span class="pill q-{E(level)}" title="Evidence quality: {E(level)}{E(tail)}">evidence: '
            f'{E(shown)}{E(tail)}</span>')


def quality_block(chk: dict) -> str:
    li = lambda xs: "".join(f"<li>{E(x)}</li>" for x in xs) or '<li class="muted">none</li>'  # noqa: E731
    return f"""<section class="card" aria-labelledby="eq-h"><h2 id="eq-h">Evidence quality</h2>
<p>{quality_badge(chk["level"], chk.get("label"), chk.get("missing_count"))}</p>
<div class="evidence"><div><h4>Checks passed</h4><ul class="tight small">{li(chk["passed"])}</ul></div>
<div><h4>Warnings</h4><ul class="tight small">{li(chk["warnings"])}</ul></div>
<div><h4>Next checks</h4><ul class="tight small">{li(chk["next_checks"])}</ul></div></div></section>"""


def research_section(p: dict) -> str:
    def trend_row(t):
        fmt = (lambda v: pct(v, 1)) if t["kind"] == "pct" else (lambda v: num(v, 2))
        cells = " · ".join(f"{E(q or '')}: {fmt(v)}" for q, v in zip(t["quarters"], t["values"]))
        return f'<li><strong>{E(t["label"])}</strong> ({E(t["direction"])}): <span class="small">{cells}</span></li>'
    trends = "".join(trend_row(t) for t in p["trends"]) or '<li class="muted">No quarterly series stored.</li>'
    fx = "".join(f'<tr><td>{E(r["pattern"])}</td><td class="num">{E(r["value"])}</td>'
                 f'<td><span class="pill {VERDICT_CLASS.get(r["verdict"], "")}">{E(r["verdict"])}</span></td>'
                 f'<td class="small muted">{E(r["note"])}</td></tr>' for r in p["forensics"])
    ev = "".join(f'<tr><td>{E(e["date"] or "unknown")}</td><td>{E(e["event"])}</td>'
                 f'<td><span class="pill {"ok" if e["status"] == "verified" else "warn" if e["status"] in ("unverified", "estimated") else "muted"}">'
                 f'{E(e["status"])}</span></td><td class="small">{E(e["source"])}{(" · " + E(e["note"])) if e["note"] else ""}</td></tr>'
                 for e in p["events"])
    th = p["thesis"]
    since = (f'recorded in the first snapshot where this name appeared on the list ({E(th["since"])})'
             if th["since"] else "recorded in this snapshot")
    first = (' This is that first snapshot, so every condition holds by construction; the first real check comes '
             'with the next snapshot.') if th["first_snapshot"] else ""
    trows = "".join(f'<tr><td>{E(r["text"])}</td><td><span class="pill {STATUS_CLASS[r["status"]]}">{E(r["status"])}</span></td>'
                    f'<td class="num">{E(r["observed"])}</td></tr>' for r in th["rows"])
    li = lambda xs: "".join(f"<li>{E(x)}</li>" for x in xs) or '<li class="muted">none</li>'  # noqa: E731
    src = "".join(f'<li>{_link(s["label"], s["url"])} <span class="muted">({E(s["date"])})</span></li>' for s in p["sources"])
    return f"""<section aria-labelledby="rp-h"><h2 id="rp-h">Company research panel</h2>
<p class="small muted">Every line below is produced by fixed rules from the stored figures; nothing is generated
or estimated beyond the stated assumptions, and nothing here is a recommendation or a probability.</p>
<div class="evidence">
<div><h4>Observed financial trends</h4><ul class="tight small">{trends}</ul></div>
<div><h4>Supporting evidence</h4><ul class="tight small">{li(p["support"])}</ul></div>
<div><h4>Counter-evidence and risks</h4><ul class="tight small">{li(p["counter"])}</ul></div>
<div><h4>Assumptions</h4><ul class="tight small">{li(p["assumptions"])}</ul></div>
</div>
<h3>Earnings-quality checks</h3>
<div class="table-wrap"><table aria-label="Earnings-quality checks"><thead><tr><th>Pattern</th><th class="num">Value</th><th>Reading</th><th>Definition</th></tr></thead>
<tbody>{fx}</tbody></table></div>
<p class="small muted">Two of six forensic patterns can be checked with the data collected here; the others need
{E(", ".join(spec.FORENSIC_RULES["not_collected"]))}, which are not collected.</p>
<h3>Upcoming and recent events</h3>
<div class="table-wrap"><table aria-label="Upcoming and recent events"><thead><tr><th>Date</th><th>Event</th><th>Status</th><th>Source</th></tr></thead>
<tbody>{ev}</tbody></table></div>
<h3>Thesis conditions</h3><p class="small">Conditions {since}, checked against this snapshot.{first}</p>
<div class="table-wrap"><table aria-label="Thesis conditions and their status"><thead><tr><th>Condition</th><th>Status</th><th class="num">Now</th></tr></thead>
<tbody>{trows}</tbody></table></div>
<div class="evidence"><div><h4>Missing information</h4><ul class="tight small">{li(p["missing"])}</ul></div>
<div><h4>Sources and dates</h4><ul class="tight small">{src}</ul></div></div>
</section>"""


def changes_section(r: dict) -> str:
    notes = "".join(f"<p class=\"small\">{E(n)}</p>" for n in r["notes"])
    if r["status"] != "compared":
        return f'<section aria-labelledby="wc-h"><h2 id="wc-h">What changed since the previous snapshot?</h2>{notes}</section>'
    rows = "".join(f'<tr><td><span class="pill">{E(KIND_LABELS[i["kind"]])}</span></td><td>{E(i["text"])}</td>'
                   f'<td>{_link(i["date"] or "", i["source"]) if i["source"] else E(i["date"] or "")}</td></tr>' for i in r["items"])
    table = (f'<div class="table-wrap"><table aria-label="Changes since the previous snapshot"><thead><tr><th>Kind</th>'
             f'<th>What changed</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table></div>') if rows else ""
    return (f'<section aria-labelledby="wc-h"><h2 id="wc-h">What changed since the previous snapshot?</h2>'
            f'<p class="small">Compared with the snapshot of {E(r["previous"])}.</p>{table}{notes}</section>')


def lab_section(inp: dict | None) -> str:
    if not inp:
        return ('<section aria-labelledby="lab-h"><h2 id="lab-h">Try your own assumptions</h2><p class="small muted">'
                'Not available: no published scenario for this name, so there are no assumptions to start from.</p></section>')
    p, b = inp["published"], inp["bounds"]
    data = json.dumps(inp)

    def field(key, label, step, scale, unit):
        val = p.get(key)
        lo, hi = b[key]
        shown = "" if val is None else f"{val * scale:.2f}"
        return (f'<label class="lab-field"><span>{E(label)}</span><span class="lab-input"><input type="number" '
                f'id="lab-{key}" data-key="{key}" data-scale="{scale}" data-shown="{shown}" step="{step}" min="{lo * scale:.2f}" '
                f'max="{hi * scale:.2f}" value="{shown}" inputmode="decimal"><span class="muted">{unit}</span></span>'
                f'<span class="small muted">published: {"n/a" if val is None else f"{val * scale:.2f}{unit}"}</span></label>')
    years = "".join(f'<th class="num">{y} yr</th>' for y in inp["years"])
    return f"""<section aria-labelledby="lab-h" class="card lab" data-lab='{E(data)}'>
<h2 id="lab-h">Try your own assumptions</h2>
<p class="banner warn small"><strong>Your experiment</strong>{E(inp["note"])}</p>
<div class="lab-grid">
{field("starting_revenue_growth", "Starting revenue growth", "0.5", 100, "%")}
{field("exit_ev_to_sales", "Exit EV / Sales", "0.1", 1, "x")}
{field("annual_dilution", "Share count change a year", "0.1", 100, "%")}
{field("fcf_margin", "Free-cash-flow margin by the last year", "0.5", 100, "%")}
</div>
<p><button type="button" class="lab-reset">Reset to published assumptions</button>
<span class="small muted lab-status" role="status" aria-live="polite"></span></p>
<div class="table-wrap"><table aria-label="Your experiment compared with the published cases"><thead><tr><th>Value per share</th>{years}</tr></thead>
<tbody class="lab-out"></tbody></table></div>
<p class="small muted">Formula: {E(inp["formula"])}. Margins do not change this value; they show the free cash flow
the value would imply (EV / FCF). Price {money(inp["price"])} at the {E(str(inp["price_date"]))} close.</p>
</section>"""


def datasets_table(records: list[dict]) -> str:
    rows = "".join(f'<tr><td>{E(r["dataset"])}</td><td><span class="pill {STATE_CLASS[r["state"]]}" title="{E(r["meaning"])}">'
                   f'{E(r["label"])}</span></td><td class="small">{E(r["detail"])}</td><td class="small">{E(r["coverage"] or "")}</td>'
                   f'<td class="small">{E(r["source"])}</td><td class="small">{E(str(r["retrieved_at"] or "").replace("+00:00", " UTC"))}</td></tr>'
                   for r in records)
    legend = " · ".join(f'<span class="pill {STATE_CLASS[k]}">{E(k.replace("_", " "))}</span> {E(v)}' for k, v in spec.DATASET_STATES.items())
    return (f'<div class="table-wrap"><table aria-label="Data status by dataset"><thead><tr><th>Dataset</th><th>State</th>'
            f'<th>Detail</th><th>Coverage</th><th>Source</th><th>Retrieved</th></tr></thead><tbody>{rows}</tbody></table></div>'
            f'<p class="small muted">{legend}</p>')


def datasets_line(records: list[dict]) -> str:
    """Compact one-line status for the overview panel."""
    return " · ".join(f'{E(r["dataset"])} <span class="pill {STATE_CLASS[r["state"]]}">{E(r["label"])}</span>' for r in records)
