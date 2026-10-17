"""Deployment provenance and guards against stale code or data writes."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from agent_trading.dashboard import spec
from agent_trading.dashboard.site import build_site
from agent_trading.dashboard.site_build import metadata
from tests.dashboard_ci import check_links
from tests.dashboard_fixtures import demo_site


def test_build_records_code_and_data_without_relabeling_or_mutating_snapshots(tmp_path, monkeypatch):
    data, _ = demo_site(tmp_path / "fixture", two_weeks=False)
    before = {p.relative_to(data): hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob("*") if p.is_file()}
    stored_version = spec.SPEC_VERSION
    monkeypatch.setattr(spec, "SPEC_VERSION", "future-renderer")
    out = tmp_path / "published"
    build_site(data, out, code_commit="a" * 40, data_commit="b" * 40)
    info = json.loads((out / "build.json").read_text())
    assert info["code_commit"] == "a" * 40 and info["data_commit"] == "b" * 40
    assert info["registered_spec_version"] == "future-renderer"
    assert info["snapshot_spec_version"] == stored_version
    assert info["snapshot_as_of"] == "2026-10-09"
    assert info["registered_spec_hash"] == spec.spec_hash()
    assert info["spec_freeze_date"] == "2026-10-16"
    assert before == {
        p.relative_to(data): hashlib.sha256(p.read_bytes()).hexdigest() for p in data.rglob("*") if p.is_file()
    }
    audit = (out / "audit.html").read_text(encoding="utf-8")
    assert 'id="site-build"' in audit and 'href="build.json"' in audit
    assert "a" * 40 in audit and "b" * 40 in audit
    overview = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="audit.html#latest-run"' in overview
    assert f"Snapshot methodology: {stored_version}." in audit
    assert "page renderer <strong>future-renderer</strong>" in audit
    assert check_links(out) == []


def test_empty_build_reports_missing_data_and_unknown_commits(tmp_path):
    out = tmp_path / "site"
    build_site(tmp_path / "empty-data", out)
    info = json.loads((out / "build.json").read_text())
    assert info["code_commit"] is None and info["data_commit"] is None
    assert info["snapshot_as_of"] is None and info["snapshot_spec_version"] is None


@pytest.mark.parametrize("value", ["main", "abc123", "<script>bad</script>", "A" * 40])
def test_build_provenance_accepts_only_full_commit_ids(value):
    with pytest.raises(ValueError, match="full lowercase Git commit hashes"):
        metadata(code_commit=value)
    with pytest.raises(ValueError, match="full lowercase Git commit hashes"):
        metadata(data_commit=value)


def test_publish_workflow_rebuilds_main_with_read_only_data_access():
    root = Path(__file__).resolve().parents[1]
    raw = (root / ".github/workflows/research-dashboard-publish.yml").read_text()
    workflow = yaml.safe_load(raw)
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["push"]["branches"] == ["main"] and "workflow_dispatch" in triggers
    assert workflow["permissions"] == {"contents": "read"}
    build = workflow["jobs"]["build"]
    assert "github.ref == 'refs/heads/main'" in build["if"]
    assert "vars.DASHBOARD_PUBLISH == 'true'" in build["if"]
    assert "permissions" not in build
    checkouts = [s for s in build["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 2
    assert all(s["with"]["persist-credentials"] is False for s in checkouts)
    assert checkouts[1]["with"]["ref"] == "research-data"
    runs = "\n".join(s.get("run", "") for s in build["steps"])
    for command in (
        "pytest -q",
        "ruff check",
        "ruff format --check",
        "dashboard verify",
        "dashboard build",
        "dashboard_ci check",
    ):
        assert command in runs
    assert "status --porcelain" in runs
    for command in ("dashboard run", "dashboard refresh", "git push", "git commit", "secrets."):
        assert command not in raw


def test_all_publish_workflows_guard_main_check_links_and_pin_actions():
    root = Path(__file__).resolve().parents[1] / ".github/workflows"
    for name in ("research-dashboard.yml", "research-dashboard-daily.yml", "research-dashboard-publish.yml"):
        workflow = yaml.safe_load((root / name).read_text())
        assert workflow["concurrency"] == {"group": "research-dashboard", "cancel-in-progress": False}
        deploy = workflow["jobs"]["deploy"]
        assert "github.ref == 'refs/heads/main'" in deploy["if"]
        assert deploy["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
        assert "git/ref/heads/main" in deploy["steps"][0]["run"]
        assert '"$current" != "$GITHUB_SHA"' in deploy["steps"][0]["run"]
        assert "exit 1" in deploy["steps"][0]["run"]
        steps = [step for job in workflow["jobs"].values() for step in job["steps"]]
        assert any("dashboard_ci check --site site" in s.get("run", "") for s in steps)
        assert any('--data-commit "$(git -C research-data rev-parse HEAD)"' in s.get("run", "") for s in steps)
        for step in steps:
            if "uses" in step:
                from tests.workflow_checks import assert_pinned_action

                assert_pinned_action(root.parent.parent, step["uses"])
