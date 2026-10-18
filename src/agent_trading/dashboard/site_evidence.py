"""Public research excerpts from checked-in reports, parsed at build time.

Only research metric columns and acceptance rules are selected. Operational and
account-specific sections of the source reports are not published.
"""

import re
from html import escape
from pathlib import Path

from .render_context import customer

ROOT = Path(__file__).resolve().parents[3]
TOURNAMENT = "research/TOURNAMENT_2026-10-12.md"
FINAL = "docs/FINAL_REPORT_2026-10-12.md"
REPO = "https://github.com/vsakati6691/agent-code/blob/main/"


def plain(text: str) -> str:
    return text.replace("**", "").replace("`", "").strip()


def tables(text: str) -> list[tuple[str, list[list[str]]]]:
    result, heading, rows = [], "", []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            cells = [plain(c) for c in line.strip().strip("|").split("|")]
            if not all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
                rows.append(cells)
        else:
            if rows:
                result.append((heading, rows))
                rows = []
            if line.startswith("#"):
                heading = line.lstrip("# ")
            elif plain(line).startswith(("Train + validation (", "Final test, 2022")):
                heading = plain(line).rstrip(":")
    return result


def read_evidence(root: Path = ROOT) -> dict:
    try:
        tournament = (root / TOURNAMENT).read_text(encoding="utf-8")
        final = (root / FINAL).read_text(encoding="utf-8")
    except OSError:
        return {"available": False, "reason": "Source research reports were not packaged with this build."}
    verdict = next(
        (
            plain(line)
            for line in final.splitlines()
            if "No candidate passed the pre-registered acceptance rules" in line
        ),
        "",
    )
    acceptance = next(
        (
            plain(line.removeprefix("- "))
            for line in tournament.splitlines()
            if "Acceptance rules (all must hold)" in line
        ),
        "",
    )
    selected = []
    for source, text in ((TOURNAMENT, tournament), (FINAL, final)):
        for heading, rows in tables(text):
            if not {"Strategy", "CAGR", "Sharpe", "Max DD"}.issubset(rows[0]):
                continue
            idx = [rows[0].index(key) for key in ("Strategy", "CAGR", "Sharpe", "Max DD")]
            filtered = [
                [row[i] for i in idx]
                for row in rows[1:]
                if row
                and (
                    row[0].startswith("BENCH_")
                    or "GTAA" in row[0]
                    or row[0] in ("SPY", "BIL", "60/40", "SPY buy & hold", "60/40 SPY/IEF")
                )
            ]
            selected.append({"source": source, "heading": heading, "rows": filtered})
    caveat = next(
        (
            plain(line.removeprefix("> "))
            for line in tournament.splitlines()
            if "test period was not untouched by the researcher" in line
        ),
        "",
    )
    return {
        "available": bool(verdict and acceptance and selected),
        "verdict": verdict,
        "acceptance": acceptance,
        "tables": selected,
        "caveat": caveat,
        "reason": "Required research excerpts were not found in the source reports.",
    }


def summary(data: dict) -> str:
    verdict = data.get("verdict") if data.get("available") else data["reason"]
    return (
        '<section id="evidence"><h2>What the evidence says</h2>'
        f'<p>{escape(verdict)}</p><p><a href="evidence.html">Read the benchmark and GTAA results, '
        "acceptance rules and limitations</a>."
        + (
            ""
            if customer()
            else ' Compare them with the <a href="goal.html#required-rate">return required by the Plan 2030 arithmetic</a>.'
        )
        + "</p></section>"
    )


def evidence_page(data: dict) -> str:
    head = "<h1>What the evidence says</h1>"
    if not data.get("available"):
        return head + f"<p>{escape(data['reason'])}</p>"
    parts = [
        head,
        f'<p class="lede">{escape(data["verdict"])}</p>',
        "<details><summary>Evidence limits: the final test was not untouched</summary><p>These are historical research results, not forward return assumptions. The selection data and final "
        "test are separate. Price-only series, trading costs and prior researcher exposure limit interpretation.</p>",
        f"<p>{escape(data['caveat'])}</p></details>",
    ]
    for table in data["tables"]:
        rows = "".join(
            "<tr>" + "".join(f"<td>{escape(cell or 'unavailable')}</td>" for cell in row) + "</tr>"
            for row in table["rows"]
        )
        parts.append(
            f'<h2>{escape(table["heading"])}</h2><p class="small">Source: '
            f'<a href="{REPO}{table["source"]}">{escape(table["source"])}</a></p>'
            '<div class="table-wrap"><table><caption>Reported benchmarks and GTAA research results</caption>'
            "<thead><tr><th>Strategy</th><th>CAGR</th><th>Sharpe</th><th>Max drawdown</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )
    parts.extend(
        [
            "<details><summary>Pre-registered acceptance rules</summary>",
            f"<p>{escape(data['acceptance'])}</p>",
            "<p>The statistical threshold in these historical acceptance rules is not a probability of achieving "
            "a future scenario or return. No candidate passed all rules. No new holdout evaluation was run for this page.</p>",
            "</details>"
            + (
                ""
                if customer()
                else '<p><a href="goal.html#required-rate">Compare the required return in Plan 2030</a>.</p>'
            ),
        ]
    )
    return "".join(parts)
