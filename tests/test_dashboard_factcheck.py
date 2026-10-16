"""Regressions from the immutable October 2026 dashboard snapshots. No network."""

import json
from pathlib import Path

from agent_trading.dashboard.site_briefing import panels

FIXTURES = Path(__file__).parent / "fixtures" / "dashboard_factcheck"


def test_overview_names_methodology_change_on_real_nvda_rank_move():
    previous, current = json.loads((FIXTURES / "rank-changes.json").read_text(encoding="utf-8"))["snapshots"]
    before = json.dumps(current, sort_keys=True)
    page = panels(current, None, [previous["as_of"], current["as_of"]], previous)
    assert "NVDA up 7 to #3" in page
    assert "methodology version changed (2026-10-14.8 → 2026-10-14.9)" in page
    assert "score +9.2; component scores unchanged" in page
    assert json.dumps(current, sort_keys=True) == before

    previous["spec_version"], previous["spec_hash"] = current["spec_version"], current["spec_hash"]
    assert "methodology version changed" not in panels(current, None, [], previous)
