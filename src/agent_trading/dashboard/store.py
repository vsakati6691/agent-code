"""Immutable weekly snapshots, an append-only audit trail and the last-run status.

Layout under the data directory (the `research-data` branch in CI):

    snapshots/<as_of>/snapshot.json   written once, never modified
    snapshots/<as_of>/manifest.json   SHA-256 of snapshot.json, spec version/hash, code commit
    tracking.json                     forward returns, recomputed each run from the snapshots
    audit.jsonl                       one JSON line per event; lines are only ever appended
    status.json                       the latest run's outcome (ok / partial / failed)

A second run for an as-of date that already has a snapshot keeps the existing
one (and says so in the audit trail); it never overwrites it.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from ..logging_setup import redact_details

PRIVATE_KEYS = {
    "account_number",
    "account_last4",
    "positions",
    "orders",
    "cash",
    "buying_power",
    "total_value",
    "unsettled_funds",
    "tickets",
    "journal",
    "api_key",
    "apikey",
    "token",
}


class SnapshotExists(RuntimeError):
    pass


class IntegrityError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_private_keys(obj, path: str = "") -> list[str]:
    """Key paths that look like brokerage or credential data (must never be published)."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            if str(k).lower() in PRIVATE_KEYS:
                hits.append(p)
            hits += find_private_keys(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += find_private_keys(v, f"{path}[{i}]")
    return hits


class Store:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        (self.root / "snapshots").mkdir(parents=True, exist_ok=True)

    # --- audit and status ---------------------------------------------------------------------
    def audit(self, event: str, **details) -> None:
        line = json.dumps(redact_details({"at": _now(), "event": event, **details}), sort_keys=True, default=str)
        with open(self.root / "audit.jsonl", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def audit_log(self) -> list[dict]:
        p = self.root / "audit.jsonl"
        if not p.exists():
            return []
        return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def write_status(self, status: str, message: str, as_of: str | None = None, **extra) -> None:
        (self.root / "status.json").write_text(
            json.dumps(
                redact_details({"status": status, "message": message, "as_of": as_of, "at": _now(), **extra}),
                indent=1,
                default=str,
            ),
            encoding="utf-8",
        )

    def status(self) -> dict | None:
        p = self.root / "status.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    # --- snapshots ----------------------------------------------------------------------------
    def dates(self) -> list[str]:
        return sorted(
            p.name
            for p in (self.root / "snapshots").iterdir()
            if (p / "snapshot.json").exists() and (p / "manifest.json").exists()
        )

    def write_snapshot(self, payload: dict, code_commit: str = "") -> Path:
        hits = find_private_keys(payload)
        if hits:
            raise IntegrityError(f"snapshot contains private-looking fields: {hits[:5]}")
        as_of = str(payload["as_of"])
        d = self.root / "snapshots" / as_of
        if (d / "snapshot.json").exists():
            raise SnapshotExists(f"a snapshot for {as_of} already exists and is immutable")
        d.mkdir(parents=True, exist_ok=True)
        snap = d / "snapshot.json"
        tmp = d / "snapshot.json.tmp"
        tmp.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(snap)
        manifest = {
            "as_of": as_of,
            "sha256": _sha(snap),
            "bytes": snap.stat().st_size,
            "spec_version": payload.get("spec_version"),
            "spec_hash": payload.get("spec_hash"),
            "code_commit": code_commit,
            "created_at": _now(),
            "status": payload.get("status"),
        }
        (d / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        self.audit(
            "snapshot_written",
            as_of=as_of,
            sha256=manifest["sha256"],
            spec_version=manifest["spec_version"],
            code_commit=code_commit,
        )
        return snap

    def load(self, as_of: str, verify: bool = True) -> dict:
        d = self.root / "snapshots" / as_of
        if verify:
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            if _sha(d / "snapshot.json") != m["sha256"]:
                raise IntegrityError(f"snapshot {as_of} does not match its manifest hash")
        return json.loads((d / "snapshot.json").read_text(encoding="utf-8"))

    def verify_all(self) -> list[str]:
        problems = []
        for a in self.dates():
            try:
                self.load(a)
            except (IntegrityError, OSError, ValueError) as exc:
                problems.append(str(exc))
        for p in (self.root / "source_aggregates").glob("*/*/aggregate.json"):
            try:
                self.source_aggregate(p.parent.parent.name, p.parent.name)
            except (IntegrityError, OSError, ValueError) as exc:
                problems.append(str(exc))
        return problems

    def source_aggregate(self, kind: str, key: str) -> dict | None:
        """Quarter/file-date aggregates have their own immutable integrity manifest."""
        if not all(re.fullmatch(r"[a-zA-Z0-9_-]+", v) for v in (kind, key)):
            raise ValueError("invalid aggregate cache key")
        folder = self.root / "source_aggregates" / kind / key
        if not folder.exists():
            return None
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            body = folder / "aggregate.json"
            if _sha(body) != manifest["sha256"]:
                raise IntegrityError(f"{kind}/{key}: aggregate hash mismatch")
            return json.loads(body.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            raise IntegrityError(f"{kind}/{key}: incomplete or invalid aggregate manifest") from None

    def write_source_aggregate(self, kind: str, key: str, payload: dict) -> dict:
        previous = self.source_aggregate(kind, key)
        if previous is not None:
            return previous
        if find_private_keys(payload):
            raise IntegrityError("aggregate contains private-looking fields")
        folder = self.root / "source_aggregates" / kind / key
        folder.mkdir(parents=True, exist_ok=False)
        body = folder / "aggregate.json"
        body.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "sha256": _sha(body),
                    "archive_sha256": payload.get("archive_sha256"),
                    "source": payload.get("source"),
                    "created_at": _now(),
                    "bytes": body.stat().st_size,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        return payload

    def latest(self, before: str | None = None) -> dict | None:
        ds = [d for d in self.dates() if before is None or d < before]
        return self.load(ds[-1]) if ds else None

    # --- derived files ----------------------------------------------------------------------------
    def write_json(self, name: str, obj) -> None:
        (self.root / name).write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")

    def read_json(self, name: str):
        p = self.root / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
