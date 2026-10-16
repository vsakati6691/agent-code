"""Public build provenance, separate from immutable research snapshots."""

import re
from datetime import UTC, datetime
from html import escape

from . import spec


def metadata(code_commit: str = "", data_commit: str = "", snapshot: dict | None = None) -> dict:
    for value in (code_commit, data_commit):
        if value and not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ValueError("Build provenance requires full lowercase Git commit hashes")
    snapshot = snapshot or {}
    return {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "code_commit": code_commit or None,
        "data_commit": data_commit or None,
        "registered_spec_version": spec.SPEC_VERSION,
        "registered_spec_hash": spec.spec_hash(),
        "spec_freeze_date": spec.SPEC_FREEZE_DATE,
        "snapshot_as_of": snapshot.get("as_of"),
        "snapshot_spec_version": snapshot.get("spec_version"),
        "snapshot_spec_hash": snapshot.get("spec_hash"),
    }


def section(info: dict) -> str:
    rows = (
        ("Built at (UTC)", info["built_at"]),
        ("Site code commit", info["code_commit"]),
        ("Stored data commit", info["data_commit"]),
        ("Current registered methodology", info["registered_spec_version"]),
        ("Stored snapshot methodology", info["snapshot_spec_version"]),
    )
    return (
        '<section id="site-build"><h2>Site build</h2><dl class="small">'
        + "".join(f"<dt>{escape(label)}</dt><dd>{escape(value or 'unavailable')}</dd>" for label, value in rows)
        + '</dl><p class="small">Rebuilding the site does not rescore or rewrite stored snapshots. '
        'New methodology inputs apply to future collections. <a href="build.json">Build metadata (JSON)</a>.</p></section>'
    )
