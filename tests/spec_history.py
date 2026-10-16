"""Read the preserved registration prose independently of the concise runtime list."""

import re
from pathlib import Path


def full_changelog() -> list[tuple[str, str]]:
    text = (Path(__file__).resolve().parents[1] / "docs" / "SPEC_CHANGELOG.md").read_text(encoding="utf-8")
    return [
        (version, reason.strip())
        for version, reason in re.findall(r"^## (\d{4}-\d{2}-\d{2}\.\d+)\n\n(.*?)(?=\n## |\Z)", text, re.M | re.S)
    ]


def historical_reason(version: str) -> str:
    return dict(full_changelog())[version]
