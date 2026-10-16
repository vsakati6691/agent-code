"""Persistent kill switch for live tickets.

The switch is a file (`account_limits.kill_switch_file`). While it exists, no
live ticket of any kind is written, and it survives restarts because it lives
on disk. Code may ENGAGE it, e.g. when the drawdown review limit is reached,
but code never releases it: release needs the `kill-switch release` command
with an explicit confirmation from the owner. A file that cannot be read
counts as engaged (fail closed). Every change is appended to a log file next
to it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings

RELEASE_PHRASE = "I have reviewed the account"


@dataclass(frozen=True)
class KillSwitchState:
    engaged: bool
    reason: str = ""
    engaged_at: str = ""
    by: str = ""


def _path(settings: Settings) -> Path:
    return settings.resolve(settings.account_limits.kill_switch_file)


def _log(settings: Settings, event: dict) -> None:
    path = _path(settings).with_name("kill_switch_log.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event) + "\n")


def status(settings: Settings) -> KillSwitchState:
    path = _path(settings)
    if not path.exists():
        return KillSwitchState(False)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return KillSwitchState(True, str(raw.get("reason", "")), str(raw.get("engaged_at", "")), str(raw.get("by", "")))
    except (OSError, ValueError, AttributeError):
        return KillSwitchState(True, "kill-switch file is unreadable (treated as engaged)")


def engage(settings: Settings, reason: str, by: str = "system", now: datetime | None = None) -> KillSwitchState:
    """Engage (idempotent: an already engaged switch keeps its original reason)."""
    current = status(settings)
    if current.engaged:
        return current
    when = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    path = _path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"reason": reason, "engaged_at": when, "by": by}, indent=2), encoding="utf-8")
    _log(settings, {"event": "engaged", "at": when, "by": by, "reason": reason})
    return status(settings)


def release(settings: Settings, confirmation: str, now: datetime | None = None) -> KillSwitchState:
    if confirmation.strip() != RELEASE_PHRASE:
        raise ValueError(f'release needs the exact confirmation "{RELEASE_PHRASE}"')
    current = status(settings)
    if not current.engaged:
        return current
    _path(settings).unlink()
    when = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    _log(settings, {"event": "released", "at": when, "by": "owner", "previous_reason": current.reason})
    return status(settings)
