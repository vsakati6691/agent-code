"""Display-only methodology continuity, derived from immutable snapshots."""

from collections import defaultdict
from datetime import date, timedelta
from html import escape

from . import spec


def version_counts(snapshots: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for snapshot in snapshots:
        grouped[str(snapshot.get("spec_version") or "unknown")].append(snapshot)
    grouped.setdefault(spec.SPEC_VERSION, [])
    rows = []
    for version, records in sorted(grouped.items()):
        dates = sorted({date.fromisoformat(s["as_of"]) for s in records})
        weeks = len({d.isocalendar()[:2] for d in dates})
        remaining = max(0, spec.MIN_SNAPSHOTS_FOR_EVIDENCE - weeks)
        estimate = dates[-1] + timedelta(weeks=remaining) if dates else None
        hashes = {s.get("spec_hash") for s in records if s.get("spec_hash")}
        rows.append(
            {
                "version": version,
                "snapshots": len(dates),
                "weeks": weeks,
                "first": dates[0].isoformat() if dates else None,
                "last": dates[-1].isoformat() if dates else None,
                "estimate": estimate.isoformat() if estimate else None,
                "hash_conflict": len(hashes) > 1,
            }
        )
    return rows


def progress(snapshots: list[dict]) -> str:
    current = next(r for r in version_counts(snapshots) if r["version"] == spec.SPEC_VERSION)
    freeze = spec.SPEC_FREEZE_DATE or "pending owner choice"
    return (
        f'<p class="small methodology-progress">{current["weeks"]} of '
        f"{spec.MIN_SNAPSHOTS_FOR_EVIDENCE} snapshots under the current version "
        f"({escape(spec.SPEC_VERSION)}), counted in distinct ISO weeks. "
        f'Freeze date: {escape(freeze)}. <a href="history.html#methodology-counts">Version history</a>. '
        "Reaching this count alone does not establish an edge.</p>"
    )


def history_table(snapshots: list[dict]) -> str:
    rows = []
    for row in version_counts(snapshots):
        estimate = row["estimate"] or "Unavailable until first snapshot"
        if row["hash_conflict"]:
            estimate = "Unavailable: different hashes under one version"
        cells = (
            row["version"],
            str(row["snapshots"]),
            str(row["weeks"]),
            row["first"] or "—",
            row["last"] or "—",
            estimate,
        )
        rows.append("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in cells) + "</tr>")
    return (
        '<section id="methodology-counts"><h2>Snapshots per methodology version</h2>'
        '<div class="table-wrap"><table><caption>Methodology continuity and conditional 52-week dates</caption>'
        "<thead><tr><th>Version</th><th>Stored snapshots</th><th>Distinct weeks</th><th>First</th><th>Latest</th>"
        "<th>Estimated 52nd weekly observation</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        "<details><summary>Version counts and estimated collection dates</summary><p>Counts are separate by version; multiple snapshots in one ISO week count once toward "
        "52 weekly observations. Estimated dates assume one additional snapshot per week after the latest stored date "
        "under that same version, with no gaps. Retired versions would have to resume. "
        "These are collection dates, not validation or claim dates; outcomes also need time to mature.</p></details></section>"
    )
