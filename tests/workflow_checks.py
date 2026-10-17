"""Validate external action pins, including checked-in composite action steps."""

import re
from pathlib import Path

import yaml


def assert_pinned_action(root: Path, uses: str, visited: frozenset[str] = frozenset()) -> None:
    if not uses.startswith("./"):
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", uses), uses
        return
    assert uses not in visited, "recursive local action"
    path = (root / uses / "action.yml").resolve()
    assert path.is_relative_to((root / ".github" / "actions").resolve())
    action = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert action["runs"]["using"] == "composite"
    for step in action["runs"]["steps"]:
        if "uses" in step:
            assert_pinned_action(root, step["uses"], visited | {uses})
