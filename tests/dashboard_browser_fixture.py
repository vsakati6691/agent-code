"""Build synthetic data covering browser interactions, including a partial refresh.

Run ``python -m tests.dashboard_browser_fixture <new-directory>`` before the
optional Playwright script. No current production snapshot is required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_trading.dashboard import bets, spec
from agent_trading.dashboard.refresh_store import RefreshStore
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.store import Store
from tests.dashboard_clock import frozen_dashboard_clock
from tests.dashboard_fixtures import AS_OF, demo_site
from tests.test_dashboard_bets import chain_rows, under


def build(root: Path) -> Path:
    if root.exists():
        raise ValueError("browser fixture needs a new output directory")
    with frozen_dashboard_clock():
        data, site = demo_site(root)
        snap = Store(data).load(str(AS_OF))
        contracts = chain_rows(1)
        for contract in contracts:
            contract["underlying"] = "AIL6"
            contract["root"] = "AIL6"
            contract["option"] = contract["option"].replace("AAA", "AIL6", 1)
        explorer = bets.build({"AIL6": (under("AIL6"), contracts)}, AS_OF, {})
        assert explorer["selected_count"] > 0
        RefreshStore(data).write(
            {
                "as_of": str(AS_OF),
                "weekly_as_of": str(AS_OF),
                "spec_version": spec.SPEC_VERSION,
                "collected_at": f"{AS_OF}T22:00:00+00:00",
                "status": "partial",
                "quotes": {},
                "chain_status": {"AIL6": {"status": "unavailable", "reason": "stale chain"}},
                "options": snap["options"],
                "explorer": explorer,
                "usage": {},
            },
            "fixture",
        )
        build_site(data, site)
    (site / "browser-fixture.json").write_text(
        json.dumps(
            {
                "ticker": "AIL6",
                "query": "AIL6 Inc.",
                "dailyMissingTicker": "AIL6",
                "unavailableTicker": "AIGONE",
                "unavailableReason": "not listed",
                "firstAiHref": "stock/ai_large-AIL1.html",
                "minimumLeaders": 20,
            }
        ),
        encoding="utf-8",
    )
    return site


if __name__ == "__main__":
    print(build(Path(sys.argv[1])))
