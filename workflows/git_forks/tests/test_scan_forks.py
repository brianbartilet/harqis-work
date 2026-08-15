from datetime import datetime

import pytest

from workflows.git_forks.hfl import fleet_entry, fork_entry, persist_scan_entries
from workflows.git_forks.tasks.scan_forks import scan_fork_fleet


# ── Workflow (integration) ────────────────────────────────────────────────────

@pytest.mark.skip(reason="Manual only — scans live GitHub repositories and writes canonical HFL entries")
def test__scan_fork_fleet():
    scan_fork_fleet()


# ── Unit / function ───────────────────────────────────────────────────────────

def _report():
    return {
        "report_path": ".harqis-data/fork-fleet/latest.json",
        "summary": {"total": 1, "healthy": 1, "errors": 0, "missing_upstream_commits": 2, "fork_only_commits": 1},
        "repositories": [{
            "repository": "owner/fork", "status": "ok", "source_ref": "upstream/main",
            "missing_upstream_commits": 2, "fork_only_commits": 1,
            "branches": ["main"], "pull_requests": [], "ci_runs": [],
            "capabilities": {"apps": ["git"], "workflows": ["git_forks"]},
            "references": ["https://github.com/owner/fork"],
        }],
    }


def test__fork_entry_is_instance_specific():
    entry = fork_entry(_report()["repositories"][0], when=datetime(2026, 8, 16, 6, 0))
    assert entry.source == ""
    assert "owner/fork" in entry.moment
    assert "git-forks" in entry.tags
    assert entry.references == ("https://github.com/owner/fork",)


def test__fleet_entry_summarizes_all_instances():
    entry = fleet_entry(_report(), when=datetime(2026, 8, 16, 6, 0))
    assert "1 instance" in entry.moment
    assert "2 upstream commit" in entry.what_happened


def test__persist_scan_entries_writes_each_fork(monkeypatch):
    calls = []
    monkeypatch.setattr("workflows.git_forks.hfl.submit_hfl_entry", lambda entry, **kwargs: calls.append((entry, kwargs)) or {"delivery": "persisted"})
    result = persist_scan_entries(_report())
    assert result["entries"] == 2
    assert len(calls) == 2
    assert all(kwargs["source"] == "git" for _, kwargs in calls)
