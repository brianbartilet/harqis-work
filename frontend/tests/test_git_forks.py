def test_git_forks_requires_authentication():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        response = client.get("/git-forks", follow_redirects=False)
    assert response.status_code == 302


def test_git_forks_renders_latest_topology(authenticated_client, monkeypatch):
    monkeypatch.setattr(
        "modules.git_forks.router.load_latest_report",
        lambda: {
            "summary": {"total": 1, "healthy": 1, "errors": 0, "missing_upstream_commits": 2},
            "repositories": [{
                "repository": "owner/fork", "status": "ok", "fork_kind": "github-fork",
                "default_branch": "main", "target_sha": "abcdef123456", "missing_upstream_commits": 2,
                "fork_only_commits": 1, "patch_equivalent_upstream_commits": 0,
                "capabilities": {"apps": ["git"]}, "branches": ["main"],
                "pull_requests": [], "ci_runs": [],
            }],
        },
    )
    response = authenticated_client.get("/git-forks")
    assert response.status_code == 200
    assert "owner/fork" in response.text
    assert "One source. Many deliberate departures." in response.text


def test_scan_can_write_per_fork_hfl_entries(authenticated_client, monkeypatch):
    report = {"summary": {"total": 1, "healthy": 1, "errors": 0, "missing_upstream_commits": 0}, "repositories": []}
    monkeypatch.setattr("modules.git_forks.router.scan_fleet", lambda: report)
    monkeypatch.setattr("workflows.git_forks.hfl.persist_scan_entries", lambda value: {"entries": 2})
    response = authenticated_client.post("/git-forks/scan", data={"write_hfl": "true"})
    assert response.status_code == 200
    assert "scan-complete" in response.text
