"""Write-once light-refresh files. Weekly snapshots and tracking are never written here."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

from .store import find_private_keys

MAX_DAY_BYTES = 400_000


class RefreshStore:
    def __init__(self, root: Path):
        self.root = Path(root) / "daily"

    def folder(self, session: str) -> Path:
        if date.fromisoformat(session).isoformat() != session:
            raise ValueError("invalid session date")
        return self.root / session

    def dates(self) -> list[str]:
        return sorted(p.name for p in self.root.glob("????-??-??") if p.is_dir())

    def write(self, payload: dict, commit: str = "") -> bool:
        target = self.folder(payload["as_of"])
        if target.exists():
            self.load(payload["as_of"])  # a damaged first record fails closed; never silently replace it
            return False
        if find_private_keys(payload):
            raise ValueError("private-looking fields in refresh")
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False).encode("utf-8")
        manifest = json.dumps({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                               "as_of": payload["as_of"], "weekly_as_of": payload["weekly_as_of"],
                               "spec_version": payload["spec_version"], "code_commit": commit},
                              separators=(",", ":"), sort_keys=True).encode("utf-8")
        if len(raw) + len(manifest) >= MAX_DAY_BYTES:
            raise ValueError("refresh exceeds the 400 KB storage limit")
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / (".pending-" + uuid4().hex)
        staging.mkdir()
        try:
            (staging / "refresh.json").write_bytes(raw)
            (staging / "manifest.json").write_bytes(manifest)
            # Directory rename is atomic; an existing nonempty session directory is never replaced.
            try:
                staging.rename(target)
            except FileExistsError:
                self.load(payload["as_of"])
                return False
        finally:
            if staging.exists():
                for name in ("refresh.json", "manifest.json"):
                    (staging / name).unlink(missing_ok=True)
                staging.rmdir()
        return True

    def load(self, session: str) -> dict:
        folder = self.folder(session)
        raw = (folder / "refresh.json").read_bytes()
        manifest = json.loads((folder / "manifest.json").read_bytes())
        if hashlib.sha256(raw).hexdigest() != manifest["sha256"] or len(raw) != manifest["bytes"]:
            raise ValueError("daily integrity check failed")
        data = json.loads(raw)
        if data["as_of"] != session or find_private_keys(data):
            raise ValueError("daily identity or privacy check failed")
        return data

    def verify_all(self) -> list[str]:
        problems = []
        for session in self.dates():
            try:
                self.load(session)
            except (OSError, ValueError, KeyError, TypeError):
                problems.append(f"daily {session}: integrity check failed")
        return problems
