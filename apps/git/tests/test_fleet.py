from __future__ import annotations

import subprocess
from pathlib import Path

from apps.git.fleet import (
    FleetConfig,
    RepositorySpec,
    _capability_summary,
    load_config,
    discover_repositories,
    scan_repository,
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _init(path: Path) -> None:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Fleet Tests")
    _git(path, "config", "user.email", "fleet@example.test")


def test_load_config_merges_local_repository_paths(tmp_path: Path):
    shared = tmp_path / "fork-fleet.toml"
    local = tmp_path / "fork-fleet.local.toml"
    shared.write_text(
        '[fleet]\nsource_repository = "owner/source"\ngithub_fallback = false\n'
        '[[repositories]]\nrepository = "owner/fork"\n', encoding="utf-8",
    )
    local.write_text(
        '[[repositories]]\nrepository = "owner/manual"\nlocal_path = "D:/manual"\n', encoding="utf-8",
    )
    config = load_config(shared, local)
    assert [repo.repository for repo in config.repositories] == ["owner/fork", "owner/manual"]
    assert config.repositories[1].local_path == "D:/manual"


def test_capability_summary_uses_harqis_structure():
    summary = _capability_summary([
        {"status": "A", "path": "apps/new_app/mcp.py"},
        {"status": "A", "path": "workflows/new_flow/tasks/run.py"},
        {"status": "M", "path": ".agents/skills/new-skill/SKILL.md"},
        {"status": "M", "path": "frontend/modules/git_forks/router.py"},
    ])
    assert summary["apps"] == ["new_app"]
    assert summary["workflows"] == ["new_flow"]
    assert summary["skills"] == ["new-skill"]
    assert summary["frontend_modules"] == ["git_forks"]


def test_github_fallback_adds_forks_and_manifest_derivatives(monkeypatch):
    config = FleetConfig(
        source_repository="owner/source", github_fallback=True,
        github_owners=["owner"], repositories=[RepositorySpec("owner/registered")],
    )
    monkeypatch.setattr("apps.git.fleet._gh_json", lambda args, **kwargs: [
        {"nameWithOwner": "owner/source", "isFork": False, "defaultBranchRef": {"name": "main"}, "isArchived": False},
        {"nameWithOwner": "owner/fork", "isFork": True, "defaultBranchRef": {"name": "trunk"}, "isArchived": False},
        {"nameWithOwner": "owner/derivative", "isFork": False, "defaultBranchRef": {"name": "main"}, "isArchived": False},
        {"nameWithOwner": "owner/unrelated", "isFork": False, "defaultBranchRef": {"name": "main"}, "isArchived": False},
        {"nameWithOwner": "owner/harqis-core", "isFork": False, "defaultBranchRef": {"name": "main"}, "isArchived": False, "description": "Core library used by harqis-work"},
    ])
    monkeypatch.setattr("apps.git.fleet._has_fork_manifest", lambda name: name.endswith("derivative"))
    monkeypatch.setattr("apps.git.fleet._has_legacy_source_marker", lambda name, source: False)
    repos, errors = discover_repositories(config)
    assert errors == []
    assert [repo.repository for repo in repos] == ["owner/derivative", "owner/fork", "owner/registered"]
    assert next(repo for repo in repos if repo.repository == "owner/fork").default_branch == "trunk"


def test_github_fallback_recognizes_legacy_readme_lineage(monkeypatch):
    config = FleetConfig(source_repository="owner/harqis-work", github_owners=["owner"])
    monkeypatch.setattr("apps.git.fleet._gh_json", lambda args, **kwargs: [{
        "nameWithOwner": "owner/harqis-work-client", "isFork": False,
        "defaultBranchRef": {"name": "main"}, "isArchived": False,
        "description": "A harqis-work client derivative",
    }])
    monkeypatch.setattr("apps.git.fleet._has_fork_manifest", lambda name: False)
    monkeypatch.setattr("apps.git.fleet._has_legacy_source_marker", lambda name, source: True)
    repos, errors = discover_repositories(config)
    assert errors == []
    assert repos[0].fork_kind == "legacy-derivative"


def test_scan_repository_finds_missing_and_fork_only_commits(tmp_path: Path):
    source = tmp_path / "source"
    _init(source)
    (source / "README.md").write_text("base\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "chore: base")

    fork = tmp_path / "fork"
    _git(tmp_path, "clone", source.as_uri(), str(fork))
    _git(fork, "config", "user.name", "Fleet Tests")
    _git(fork, "config", "user.email", "fleet@example.test")
    (fork / "apps" / "fork_app").mkdir(parents=True)
    (fork / "apps" / "fork_app" / "__init__.py").write_text("", encoding="utf-8")
    _git(fork, "add", ".")
    _git(fork, "commit", "-m", "feat: fork app")

    (source / "workflows" / "upstream_flow").mkdir(parents=True)
    (source / "workflows" / "upstream_flow" / "__init__.py").write_text("", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "feat: upstream workflow")

    config = FleetConfig(
        source_repository=source.as_uri(), github_fallback=False,
        cache_dir=str(tmp_path / "cache"), report_path=str(tmp_path / "report.json"),
    )
    report = scan_repository(
        RepositorySpec(fork.as_uri(), default_branch="main", fork_kind="manual-clone"), config,
    )
    assert report["missing_upstream_commits"] == 1
    assert report["fork_only_commits"] == 1
    assert report["capabilities"]["apps"] == ["fork_app"]
    assert report["capabilities"]["workflows"] == ["upstream_flow"]
