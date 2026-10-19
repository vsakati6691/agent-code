"""Small write-once intraday observations, isolated from weekly and daily datasets."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .store import find_private_keys

KEY = re.compile(r"\d{8}T\d{12}Z")


class ShortTermStore:
    def __init__(self, root: Path):
        self.root = Path(root) / "short-term"

    def keys(self) -> list[str]:
        return sorted(p.name for p in self.root.glob("*") if p.is_dir() and KEY.fullmatch(p.name))

    def folder(self, key: str) -> Path:
        if not KEY.fullmatch(key):
            raise ValueError("invalid short-term observation key")
        return self.root / key

    @staticmethod
    def key(payload: dict) -> str:
        stamp = datetime.fromisoformat(payload["collected_at"])
        if stamp.tzinfo is None:
            raise ValueError("observation must be timezone-aware")
        return stamp.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")

    def write(self, payload: dict, commit: str = "") -> bool:
        if payload.get("status") == "failed":
            return False  # preserve the last good observation; caller appends an audit event
        key = self.key(payload)
        target = self.folder(key)
        if target.exists():
            self.load(key)
            return False
        if find_private_keys(payload):
            raise ValueError("private-looking fields in short-term scan")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if len(raw) > 100_000:
            raise ValueError("short-term observation exceeds 100 KB")
        manifest = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "code_commit": commit}
        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / (".pending-" + uuid4().hex)
        staging.mkdir()
        try:
            (staging / "scan.json").write_bytes(raw)
            (staging / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            try:
                staging.rename(target)
            except FileExistsError:
                self.load(key)
                return False
        finally:
            if staging.exists():
                for name in ("scan.json", "manifest.json"):
                    (staging / name).unlink(missing_ok=True)
                staging.rmdir()
        return True

    def load(self, key: str) -> dict:
        folder = self.folder(key)
        raw = (folder / "scan.json").read_bytes()
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if len(raw) != manifest["bytes"] or hashlib.sha256(raw).hexdigest() != manifest["sha256"]:
            raise ValueError("short-term observation integrity failure")
        payload = json.loads(raw)
        if self.key(payload) != key or find_private_keys(payload):
            raise ValueError("short-term observation identity or privacy failure")
        return payload

    def latest(self) -> dict | None:
        keys = self.keys()
        return self.load(keys[-1]) if keys else None

    def verify_all(self) -> list[str]:
        problems = []
        for key in self.keys():
            try:
                self.load(key)
            except (ValueError, TypeError, KeyError, OSError):
                problems.append(f"short-term {key}: integrity check failed")
        return problems
