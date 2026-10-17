"""Keep personal-use market data out of the public data branch and Pages build."""

from __future__ import annotations

import os
from pathlib import Path

from .store import Store

MARKER = ".private-research"


def require_local() -> None:
    if os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        raise ValueError("Private research is local only; GitHub Actions publication is prohibited")


def mark_private(root: Path) -> None:
    require_local()
    root = root.resolve()
    if root.name == "research-data" or (root / ".git").exists():
        raise ValueError("Use a separate ignored local directory, never the research-data checkout")
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text(
        "Private personal research. Do not publish or commit this directory.\n", encoding="utf-8"
    )


def check_publication(store: Store, private: bool = False) -> bool:
    """Check every stored week, including an older private week behind a public one."""
    restricted = (store.root / MARKER).exists()
    for day in store.dates():
        snap = store.load(day)
        restricted |= (
            snap.get("publication") == "private" or (snap.get("price_history") or {}).get("provider") == "massive"
        )
    if restricted and not private:
        raise ValueError("Private market data cannot be published; use build --private for local viewing")
    if restricted or private:
        require_local()
    return restricted or private
