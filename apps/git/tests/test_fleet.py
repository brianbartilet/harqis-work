from __future__ import annotations

import json
import subprocess
from pathlib import Path

from apps.git.fleet import (
    FleetError,
    FleetConfig,
    RepositorySpec,
    _capability_summary,
    _feature_plan_id,
    _readiness_summary,
    load_config,
    discover_repositories,
    load_feature_plan,
    plan_feature_shipping,
    resolve_feature_commits,
    scan_repository,
    ship_feature_plan,
)
import pytest


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _init(path: Path) -> None:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Fleet Tests")
    _git(path, "config", "user.email", "fleet@example.test")


def _write_empty_plan(plan_dir: Path) -> str:
    payload = {
        "schema_version": 1,
        "generated_at": "2026-08-16T07:00:00+08:00",
        "source": {"commits": []},
        "feature_slug": "test-feature",
        "squash": False,
        "candidate_changes": [],
        "candidate_capabilities": {},
        "filters": {"include": [], "exclude": []},
        "discovery_errors": [],
        "targets": [],
    }
    plan_id = _feature_plan_id(payload)
    payload["plan_id"] = plan_id
    (plan_dir / f"{plan_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return plan_id


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


def test_readiness_flags_fork_only_work_and_failed_ci():
    readiness = _readiness_summary({
        "fork_only_commits": 2,
        "missing_upstream_commits": 1,
        "conflicts": [],
        "ci_summary": {"failure": 1},
    })
    assert readiness["level"] == "review"
    assert any("fork-only" in reason for reason in readiness["reasons"])


def test_plan_feature_shipping_persists_compatible_local_plan(tmp_path: Path):
    source = tmp_path / "source-plan"
    _init(source)
    (source / "README.md").write_text("base\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "chore: base")

    fork = tmp_path / "fork-plan"
    _git(tmp_path, "clone", source.as_uri(), str(fork))
    _git(fork, "config", "user.name", "Fleet Tests")
    _git(fork, "config", "user.email", "fleet@example.test")

    (source / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(source, "add", "feature.txt")
    _git(source, "commit", "-m", "feat: portable feature")
    feature_sha = _git(source, "rev-parse", "HEAD")

    config_path = tmp_path / "fork-fleet.toml"
    config_path.write_text(
        "[fleet]\n"
        f'source_repository = "{source.as_uri()}"\n'
        "github_fallback = false\n"
        f'cache_dir = "{(tmp_path / "cache-plan").as_posix()}"\n'
        f'worktree_dir = "{(tmp_path / "worktrees-plan").as_posix()}"\n'
        f'plan_dir = "{(tmp_path / "plans").as_posix()}"\n'
        "[[repositories]]\n"
        f'repository = "{fork.as_uri()}"\n',
        encoding="utf-8",
    )
    report = plan_feature_shipping(commits=[feature_sha], config_path=config_path)
    assert report["summary"]["compatible"] == 1
    assert report["targets"][0]["trial"]["status"] == "clean"
    assert Path(report["plan_path"]).exists()
    assert load_feature_plan(report["plan_id"], config_path=config_path)["plan_id"] == report["plan_id"]
    tampered = json.loads(Path(report["plan_path"]).read_text(encoding="utf-8"))
    tampered["targets"][0]["status"] = "compatible-with-warnings"
    Path(report["plan_path"]).write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(FleetError, match="integrity"):
        load_feature_plan(report["plan_id"], config_path=config_path)


def test_ship_feature_plan_rejects_wrong_approval(tmp_path: Path):
    config_path = tmp_path / "fork-fleet.toml"
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    config_path.write_text(
        '[fleet]\nsource_repository = "owner/source"\ngithub_fallback = false\n'
        f'plan_dir = "{plan_dir.as_posix()}"\n', encoding="utf-8",
    )
    plan_id = _write_empty_plan(plan_dir)
    with pytest.raises(FleetError, match="approval"):
        ship_feature_plan(plan_id, approval="wrong", config_path=config_path)


def test_resolve_feature_commits_supports_contiguous_range_and_source_pr(tmp_path: Path, monkeypatch):
    source = tmp_path / "source-resolve"
    _init(source)
    (source / "base.txt").write_text("base\n", encoding="utf-8")
    _git(source, "add", "base.txt")
    _git(source, "commit", "-m", "chore: base")
    base_sha = _git(source, "rev-parse", "HEAD")
    (source / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(source, "add", "feature.txt")
    _git(source, "commit", "-m", "feat: range and PR")
    feature_sha = _git(source, "rev-parse", "HEAD")
    config_path = tmp_path / "fork-fleet.toml"
    config_path.write_text(
        "[fleet]\n"
        f'source_repository = "{source.as_uri()}"\n'
        "github_fallback = false\n"
        f'cache_dir = "{(tmp_path / "cache-resolve").as_posix()}"\n',
        encoding="utf-8",
    )
    ranged = resolve_feature_commits(commit_range=f"{base_sha}..{feature_sha}", config_path=config_path)
    assert ranged["commits"] == [feature_sha]
    with pytest.raises(FleetError, match="contiguous"):
        resolve_feature_commits(commit_range=f"{base_sha}...{feature_sha}", config_path=config_path)

    monkeypatch.setattr("apps.git.fleet._gh_json", lambda args, **kwargs: {
        "number": 7, "title": "PR feature", "url": "https://github.com/owner/source/pull/7",
        "commits": [{"oid": feature_sha}],
    })
    from_pr = resolve_feature_commits(pull_request="7", config_path=config_path)
    assert from_pr["commits"] == [feature_sha]
    assert from_pr["title"] == "PR feature"


def test_ship_feature_plan_requires_separate_direct_main_confirmation(tmp_path: Path):
    config_path = tmp_path / "fork-fleet.toml"
    plan_dir = tmp_path / "plans"
    plan_dir.mkdir()
    config_path.write_text(
        '[fleet]\nsource_repository = "owner/source"\ngithub_fallback = false\n'
        f'plan_dir = "{plan_dir.as_posix()}"\n', encoding="utf-8",
    )
    plan_id = _write_empty_plan(plan_dir)
    with pytest.raises(FleetError, match="DIRECT-MAIN"):
        ship_feature_plan(
            plan_id, approval=plan_id, repositories=["owner/fork"],
            direct_main=["owner/fork"], config_path=config_path,
        )
