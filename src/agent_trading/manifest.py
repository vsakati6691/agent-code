"""Reproducibility: a manifest for every daily run, and the frozen paper spec.

Each run writes data/runs/<as_of>_<label>_<time>.json with the code version,
a hash of the configuration, the time and source of every input snapshot, and
every signal the run produced (accepted and rejected) with its reason.

The paper-trading evaluation is only meaningful if the rules don't change
mid-test: the first paper run stores the configuration hash as the frozen
spec; any later run with a different hash is flagged in the report.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .config import Settings

RUNS_DIR = "runs"


def config_hash(settings: Settings, config_path: Path | None = None) -> str:
    """SHA-256 (first 12 hex chars) of the settings file actually in use."""
    path = config_path or settings.base_dir / "config" / "settings.yaml"
    data = Path(path).read_bytes() if Path(path).exists() else repr(settings).encode()
    return hashlib.sha256(data).hexdigest()[:12]


def code_version(base_dir: Path) -> dict:
    """Git commit and whether the working tree has uncommitted changes ('unknown' if git is unavailable)."""
    def git(*args):
        try:
            r = subprocess.run(["git", *args], cwd=base_dir, capture_output=True, text=True, timeout=10)
            return r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None
    commit = git("rev-parse", "--short", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=no")
    return {"commit": commit or "unknown", "dirty": None if status is None else bool(status)}


def _plain(obj):
    if is_dataclass(obj):
        return {k: _plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_plain(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, float) and obj != obj:
        return None
    if hasattr(obj, "item"):  # numpy scalars
        return obj.item()
    return obj


def write_manifest(settings: Settings, as_of: date, label: str, payload: dict) -> Path:
    d = settings.resolve(settings.data.cache_dir).parent / RUNS_DIR
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    path = d / f"{as_of.isoformat()}_{label or 'run'}_{now:%H%M%S}.json"
    path.write_text(json.dumps(_plain({"written_at": now.isoformat(timespec="seconds"), **payload}), indent=2),
                    encoding="utf-8")
    return path
