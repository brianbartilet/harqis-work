from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "create_fork.py"
SPEC = importlib.util.spec_from_file_location("create_fork", SCRIPT)
assert SPEC and SPEC.loader
create_fork = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = create_fork
SPEC.loader.exec_module(create_fork)


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, text=True, capture_output=True)


def _write(root: Path, relative: str, text: str = "placeholder\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _source_repo(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    _run("git", "init", "-b", "main", cwd=source)
    _run("git", "config", "user.email", "tests@example.invalid", cwd=source)
    _run("git", "config", "user.name", "Fork Tests", cwd=source)
    _write(source, ".gitignore", ".env/*\n**/.env\n**/.env.*\nmachines.local.toml\n.venv/\nnode_modules/\n")
    for filename in create_fork.ROOT_FILES - {".gitignore", "README.md"}:
        _write(source, filename)
    _write(source, "README.md", "# HARQIS Work\n")
    _write(source, "docs/MANIFESTO.md", "# HARQIS Work Manifesto\n")
    _write(source, "docs/info/guide.md", "HARQIS Work guide\nHARQIS-work reference\nHARQIS-Work title\n")
    (source / "docs/images").mkdir(parents=True)
    for app in create_fork.DEFAULT_APPS:
        _write(source, f"apps/{app}/README.md", f"# {app}\n")
    _write(source, "apps/apps_config.py")
    _write(source, "apps/config_loader.py")
    _write(source, "workflows/.template/tasks_config.py", "WORKFLOW_TEMPLATE = {'template': {}}\n")
    _write(source, "workflows/.template/README.md")
    _write(source, "workflows/__init__.py")
    _write(source, "workflows/config.py")
    _write(source, "workflows/queues.py")
    for skill in set(create_fork.DEFAULT_SKILLS) | {"sync-host", "update-docs"}:
        _write(source, f".agents/skills/{skill}/SKILL.md", f"---\nname: {skill}\ndescription: test\n---\n")
    _write(source, "agents/projects/profiles/examples/base.yaml", "tools:\n  mcp_apps:\n    - trello\nsecrets:\n  required:\n    - TRELLO_API_KEY\n")
    _write(source, "frontend/main.py", "from modules.hfl_corpus.router import router as hfl_corpus_router\napp.include_router(hfl_corpus_router)\n")
    _write(source, "frontend/modules/registry.py")
    _write(source, "frontend/tests/conftest.py", "import pytest\n")
    _write(source, "frontend/README.md")
    _write(source, "mcp/README.md")
    _write(source, "mcp/server.py", 'NAME = "harqis-work"\n')
    _write(source, "tools/README.md")
    _write(
        source,
        "tools/catalog.py",
        'APP_CATALOG = (\n'
        '    AppToolSpec("trello", "Trello", "apps.trello.mcp.register_trello_tools"),\n'
        '    AppToolSpec("missing", "Missing", "apps.missing.mcp.register_missing_tools"),\n'
        ')\n',
    )
    _write(source, "docker-compose.yml", "services:\n  rabbitmq:\n    image: rabbitmq\n  n8n:\n    image: n8n\n  elasticsearch:\n    image: elasticsearch\n")
    _run("git", "add", "-A", cwd=source)
    _run("git", "commit", "-m", "fixture", cwd=source)
    return source


def test_dependency_resolution_keeps_hfl_conditional():
    apps, skills, workflows = create_fork.resolve_dependencies(
        create_fork.DEFAULT_APPS,
        create_fork.DEFAULT_SKILLS + ("create-new-ingest-source-hfl",),
        (".template",),
        hfl=False,
    )
    assert "antropic" in apps
    assert "create-new-ingest-source-hfl" not in skills
    assert "update-docs" in skills
    assert "sync-host" in skills
    assert workflows == (".template",)

    apps, skills, workflows = create_fork.resolve_dependencies(
        create_fork.DEFAULT_APPS, create_fork.DEFAULT_SKILLS, (".template",), hfl=True,
    )
    assert create_fork.HFL_APPS <= set(apps)
    assert create_fork.HFL_WORKFLOWS <= set(workflows)
    assert "create-new-ingest-source-hfl" in skills


def test_full_local_generation_is_fresh_and_secret_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = _source_repo(tmp_path)
    _write(source, ".env/apps.env", "SECRET_VALUE=local-only\n")
    _write(source, "frontend/.env", "APP_PASSWORD=local-only\n")
    _write(source, "machines.local.toml", "[hostnames]\ntest = 'default'\n")
    target = tmp_path / "target-repo"
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Fork Tests")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "tests@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Fork Tests")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "tests@example.invalid")

    code = create_fork.main([
        "--source", str(source),
        "--repo-name", "target-repo",
        "--brand-name", "Acme Automation",
        "--description", "A generated test fork.",
        "--target-dir", str(target),
        "--no-publish", "--yes",
        "--skip-build", "--skip-tests", "--skip-docker-build",
    ])

    assert code == 0
    assert (target / ".git").is_dir()
    assert _run("git", "rev-list", "--count", "HEAD", cwd=target).stdout.strip() == "1"
    assert not (target / "apps/missing").exists()
    assert "apps.missing" not in (target / "tools/catalog.py").read_text(encoding="utf-8")
    assert "Acme Automation" in (target / "README.md").read_text(encoding="utf-8")
    guide = (target / "docs/info/guide.md").read_text(encoding="utf-8")
    assert "HARQIS-work" not in guide and "HARQIS-Work" not in guide
    assert guide.count("Acme Automation") == 3
    assert 'status = "passed"' in (target / "fork-manifest.toml").read_text(encoding="utf-8")
    assert (target / ".env/apps.env").read_text(encoding="utf-8") == "SECRET_VALUE=local-only\n"
    assert (target / "frontend/.env").is_file()
    assert (target / "machines.local.toml").is_file()
    assert _run("git", "status", "--porcelain", cwd=target).stdout == ""
    tracked = _run("git", "ls-files", cwd=target).stdout.splitlines()
    assert not any(path.startswith(".env/") for path in tracked)
    assert "frontend/.env" not in tracked
    assert "machines.local.toml" not in tracked


def test_secret_verification_rejects_unignored_file(tmp_path: Path):
    target = tmp_path / "target"
    target.mkdir()
    _run("git", "init", "-b", "main", cwd=target)
    secret = target / "frontend/.env"
    _write(target, "frontend/.env", "TOKEN=x\n")
    plan = create_fork.ForkPlan(
        source=target, target=target, repo_name="target", brand_name="Target",
        description="test", owner=None, visibility="private", apps=(), skills=(),
        workflows=(), hfl=False, timestamp="2026-01-01T00:00:00+00:00",
        source_sha="0" * 40, publish=False, copy_secrets=True,
    )
    with pytest.raises(create_fork.ForkError, match="not ignored"):
        create_fork.verify_secrets_ignored(plan, [secret])
