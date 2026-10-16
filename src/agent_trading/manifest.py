"""Reproducibility: a manifest for every daily run, and the frozen paper spec.

Each run writes data/runs/<as_of>_<label>_<time>.json with the code version,
a hash of the configuration, the time and source of every input snapshot, and
every signal the run produced (accepted and rejected) with its reason.
The pre-market run checks that the previous trading day's post-close run
log exists, so a missed scheduled run is reported instead of going unnoticed.

The paper-trading evaluation is only meaningful if the rules don't change
mid-test: the first paper run stores the configuration hash as the frozen
spec; any later run with a different hash is flagged in the report.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .config import Settings
from .market_calendar import previous_trading_day

RUNS_DIR = "runs"
# git is often not on PATH on Windows; the run log must still record the commit
GIT_FALLBACKS = ("C:/Program Files/Git/cmd/git.exe", "C:/Program Files/Git/bin/git.exe")


def config_hash(settings: Settings, config_path: Path | None = None) -> str:
    """SHA-256 (first 12 hex chars) of the settings file actually in use."""
    path = config_path or settings.base_dir / "config" / "settings.yaml"
    data = Path(path).read_bytes() if Path(path).exists() else repr(settings).encode()
    return hashlib.sha256(data).hexdigest()[:12]


def code_version(base_dir: Path) -> dict:
    """Git commit and whether the working tree has uncommitted changes ('unknown' if git is unavailable)."""
    exe = shutil.which("git") or next((p for p in GIT_FALLBACKS if Path(p).exists()), "git")

    def git(*args):
        try:
            r = subprocess.run([exe, *args], cwd=base_dir, capture_output=True, text=True, timeout=10)
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


def runs_dir(settings: Settings) -> Path:
    return settings.resolve(settings.data.cache_dir).parent / RUNS_DIR


def missed_postclose(settings: Settings, as_of: date) -> date | None:
    """The previous NYSE trading day if it has no post-close run log, else None."""
    prev = previous_trading_day(as_of)
    return None if any(runs_dir(settings).glob(f"{prev.isoformat()}_postclose_*.json")) else prev


def write_manifest(settings: Settings, as_of: date, label: str, payload: dict) -> Path:
    d = runs_dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    path = d / f"{as_of.isoformat()}_{label or 'run'}_{now:%H%M%S}.json"
    path.write_text(
        json.dumps(_plain({"written_at": now.isoformat(timespec="seconds"), **payload}), indent=2), encoding="utf-8"
    )
    return path
