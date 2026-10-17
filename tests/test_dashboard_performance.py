import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from agent_trading.dashboard.assets import CSS
from agent_trading.dashboard.site import freshness_banner
from agent_trading.dashboard.site_performance import budget_problems, external_json


def test_external_payload_roundtrips_escaped_text_and_preserves_other_scripts():
    files = {}
    markup = (
        '<script type="application/json" id="decision-data">{"text":"<\\/script> & Ω"}</script><script>other()</script>'
    )
    out = external_json(markup, "growth", files)
    assert json.loads(files["data/growth-decision-data.json"]) == {"text": "</script> & Ω"}
    assert 'data-src="data/growth-decision-data.json"' in out and "<script>other()</script>" in out
    assert "Ω" not in out


def test_budget_counts_utf8_bytes_and_includes_nested_pages(tmp_path):
    (tmp_path / "option").mkdir()
    page = tmp_path / "option" / "test.html"
    page.write_text("Ω" * 75_001, encoding="utf-8")
    assert len(budget_problems(tmp_path)) == 1
    page.write_text("x" * 150_000, encoding="utf-8")
    assert not budget_problems(tmp_path)


def test_sparklines_keep_points_and_accessible_labels_in_separate_svg():
    from xml.etree import ElementTree

    files = {}
    original = '<svg class="spark" viewBox="0 0 120 28" width="120" height="28" role="img" aria-label="AAA &amp; SPY"><polyline points="0,1 2,3" stroke="var(--series-1)"/></svg>'
    markup = external_json(original, "growth", files)
    assert '<img class="spark"' in markup and 'alt="AAA &amp; SPY"' in markup and "<svg" not in markup
    tree = ElementTree.fromstring(next(iter(files.values())))
    assert tree.find("{http://www.w3.org/2000/svg}polyline").get("points") == "0,1 2,3"


def test_server_freshness_counts_sessions_before_and_after_close_without_js():
    snap = {"as_of": "2026-10-09", "status": "ok"}
    zone = ZoneInfo("America/New_York")
    before = freshness_banner(snap, None, datetime(2026, 10, 12, 15, 59, tzinfo=zone))
    after = freshness_banner(snap, None, datetime(2026, 10, 12, 16, 0, tzinfo=zone))
    assert "latest session" in before and "1 session old" in after
    old = freshness_banner(snap, None, datetime(2026, 10, 23, 17, tzinfo=zone))
    assert "10 sessions old" in old
    assert 'id="stale-client"><strong>This page may be out of date.' in old
    assert 'id="stale-client" hidden' in after


def _luminance(color):
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


def test_muted_tokens_meet_aa_on_every_theme_surface_and_motion_is_optional():
    themes = re.findall(r"--bg:.*?--info-bg:.*?;", CSS, re.S)
    assert len(themes) == 3  # light, system dark, explicit dark
    for theme in themes:
        values = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-f]{6})", theme))
        foreground = _luminance(values["text-muted"])
        for key in ("bg", "surface-1", "surface-2", "warn-bg", "bad-bg", "info-bg"):
            background = _luminance(values[key])
            assert (max(foreground, background) + 0.05) / (min(foreground, background) + 0.05) >= 4.5, key
    assert "prefers-reduced-motion: reduce" in CSS and "scroll-behavior: auto !important" in CSS
