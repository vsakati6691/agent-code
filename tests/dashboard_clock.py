"""Test-only frozen clocks and complete output manifests for offline refactor checks."""

import hashlib
import importlib
from contextlib import ExitStack, contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

MODULES = (
    "store",
    "site_build",
    "site_layout",
    "site_goal",
    "site",
    "earnings_verdicts",
    "pipeline_assemble",
    "pipeline_phases",
    "pipeline_context",
    "pipeline_details",
    "providers",
    "provider_parsers",
    "refresh",
    "tradability",
)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 17, 20, 0, 0, tzinfo=UTC)
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


class FrozenDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 17)


@contextmanager
def frozen_dashboard_clock():
    from unittest.mock import patch

    with ExitStack() as stack:
        for name in MODULES:
            module = importlib.import_module("agent_trading.dashboard." + name)
            if getattr(module, "datetime", None) is datetime:
                stack.enter_context(patch.object(module, "datetime", FrozenDateTime))
            if getattr(module, "date", None) is date:
                stack.enter_context(patch.object(module, "date", FrozenDate))
        yield


def file_hashes(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
