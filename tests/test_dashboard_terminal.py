"""Shared UI contracts using the immutable snapshot and real daily failure reasons."""

import json
from datetime import UTC, datetime
from pathlib import Path

from agent_trading.dashboard import site_command, site_external, site_layout, site_refresh, site_tables

FIXTURES = Path(__file__).parent / "fixtures" / "dashboard_factcheck"


def test_scroll_regions_keep_real_prices_and_pre_render_sort_buttons():
    row = json.loads((FIXTURES / "preclose.json").read_text())["candidate"]
    markup = (
        '<div class="table-wrap wide"><table><caption>Stored NVDA input</caption>'
        '<thead><tr><th data-sort="num">Price</th></tr></thead>'
        f'<tbody><tr><td data-v="{row["price"]}">{row["price"]}</td></tr></tbody></table></div>'
    )
    rendered = site_tables.enhance(site_layout.column_headers(markup))
    assert f'data-v="{row["price"]}"' in rendered
    assert 'role="region" aria-label="Stored NVDA input; scroll for more"' in rendered
    assert 'tabindex="0"' in rendered and 'scope="col"' in rendered
    assert '<button type="button" class="sortbtn">Price</button>' in rendered
    assert site_tables.enhance(rendered) == rendered  # no nested buttons or duplicate landmarks


def test_command_catalog_is_escaped_and_preserves_nested_destinations():
    catalog = {"NVDA": "NVIDIA", "<script>": '<img src=x onerror="alert(1)">'}
    rendered = site_command.search(catalog, "../symbol/")
    assert 'data-base="../symbol/"' in rendered and '<option value="NVDA">NVIDIA</option>' in rendered
    assert "<script>" not in rendered and "<img" not in rendered
    assert 'aria-keyshortcuts="Control+k Meta+k"' in rendered
    assert site_command.search({}, "symbol/") == ""
    dialog = site_command.dialog()
    assert 'role="combobox"' in dialog and 'role="listbox"' in dialog
    assert 'aria-labelledby="command-title"' in dialog


def test_real_partial_chains_are_compact_without_hiding_their_status():
    data = json.loads((FIXTURES / "partial-refresh.json").read_text())
    before = json.dumps(data, sort_keys=True)
    snap = json.loads((FIXTURES / "preclose.json").read_text())["snapshot"]
    markup = site_refresh.banner(snap, {"data": data["refresh"]})
    assert 'class="banner warn small daily-status"' in markup and "refresh status: partial" in markup
    assert '<details class="refresh-missing"><summary>Not refreshed (5)</summary>' in markup
    for ticker in ("COCO", "MAMA", "QNST", "SEZL", "WT"):
        assert f"Options chain {ticker}: stale chain" in markup
    assert "Request usage:" in markup and " open" not in markup
    assert json.dumps(data, sort_keys=True) == before


def test_old_snapshot_macro_absence_stays_explicit_and_does_not_invent_a_rate():
    snap = json.loads((FIXTURES / "preclose.json").read_text())["snapshot"]
    markup = site_external.macro_context(snap) + site_external.rate_note(snap)
    assert "6 of 6 displayed series" in markup and "Treasury rate unavailable" in markup
    assert markup.count('class="card macro-card"') == 6
    assert "None" not in markup and "NaN" not in markup
    assert "Previously stored estimates retain their recorded assumptions" in markup
    # Missing optional branches can be null in legacy data; the display must not crash.
    assert "6 of 6 displayed series" in site_external.macro_context({**snap, "macro": {"series": None}})
    assert "Treasury observation is incomplete" in site_external.rate_note(
        {**snap, "macro": {"series": {"DGS1MO": None}}}
    )


def test_partial_snapshot_reasons_are_escaped_and_all_recoverable():
    snap = json.loads((FIXTURES / "preclose.json").read_text())["snapshot"]
    reasons = ["XBRL input unavailable", "<script>alert(1)</script>", "Third reason", "Fourth reason"]
    rendered = site_layout.freshness_banner(
        {**snap, "status": "partial", "problems": reasons}, None, datetime(2026, 10, 16, 18, tzinfo=UTC)
    )
    assert "Data availability details (4)" in rendered and "Fourth reason" in rendered
    assert "<script>" not in rendered and "&lt;script&gt;" in rendered


def test_default_calculator_horizon_exists_before_javascript():
    from datetime import date

    from agent_trading.dashboard.site_goal import goal_page

    snap = json.loads((FIXTURES / "preclose.json").read_text())["snapshot"]
    markup = goal_page(snap, date(2026, 10, 16))
    years = (date(2030, 12, 31) - date(2026, 10, 16)).days / 365.25
    assert f"{years:.2f} years; {int(years * 12)} end-of-month contributions." in markup
