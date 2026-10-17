"""AI navigation, data-basis labels and touch-accessible context from stored inputs."""

import json
import re
from pathlib import Path

from agent_trading.dashboard import site_ai, site_layout, spec
from agent_trading.dashboard.fmt import sval

FIXTURE = Path(__file__).parent / "fixtures/dashboard_factcheck/ai-display.json"


def snapshot():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshot"]


def test_ai_copy_names_the_real_profile_and_preclose_basis_without_changing_rules():
    snap = snapshot()
    original = json.dumps(snap, sort_keys=True)
    spec_before = spec.spec_hash()
    page = site_ai.ai_page(snap)
    assert "Stored AI profile: standard" in page
    assert "momentum 10%" in page and "benchmark-relative performance 10%" in page
    assert "separate fundamental-growth profile" in page
    assert "same fixed rules as the growth lists" not in page and "same weights" not in page
    assert "Stored intraday inputs; correction 2026-10-16" in page
    assert "Quotes are end-of-session" not in page
    assert "stored intraday price x SEC cover-page shares" in page
    assert "Snapshot market cap" in page and "Snapshot bar" in page
    assert "same weights" not in site_ai.methodology_ai()
    assert json.dumps(snap, sort_keys=True) == original and spec.spec_hash() == spec_before


def test_ai_jump_links_only_target_sections_present_in_that_snapshot():
    snap = snapshot()
    for value in (snap, {**snap, "bands": {}, "ai": None}):
        page = site_ai.ai_page(value)
        nav = re.search(r'<nav class="section-nav"[^>]*>(.*?)</nav>', page, re.S).group(1)
        targets = re.findall(r'href="#([^"]+)"', nav)
        assert targets
        for target in targets:
            assert f'id="{target}"' in page
        assert ("ai_large" in targets) == bool(value["bands"])
        assert ("top20" in targets) == bool(value["bands"])


def test_real_arm_reason_is_expandable_and_ranked_names_link_to_their_evidence():
    snap = snapshot()
    page = site_ai.ai_page(snap)
    universe = page.split('id="universe"')[1].split('id="private"')[0]
    assert '<details class="ai-unavailable"><summary>ARM · Unavailable</summary>' in universe
    assert snap["ai"]["universe"]["unresolved"]["ARM"] in universe
    assert 'href="stock/ai_large-MU.html">MU · #1' in universe
    assert 'href="stock/ai_mid-PATH.html">PATH · #1' in universe
    assert "reason on hover" not in universe


def test_scenario_sort_keys_keep_the_recorded_values_and_allow_reset():
    snap = snapshot()
    page = site_layout.page("AI", site_ai.ai_page(snap), "ai.html")
    table = re.search(r'<table id="t-ai-scenarios".*?</table>', page, re.S).group(0)
    assert table.count('class="sortbtn"') == 8
    assert table.count("<tr>") == 10  # header and nine published companies
    assert 'data-reset="t-ai-scenarios"' in page
    for band in snap["bands"].values():
        for candidate in band["candidates"]:
            # The same raw scenario numbers drive sorting, rather than rounded $B/$T strings.
            for row in candidate["top20_test"]["rows"]:
                if row["case"] in {"base", "bull"}:
                    assert f'data-v="{sval(row["market_cap"])}"' in table
