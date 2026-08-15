"""Discovery, drift analysis, and guarded operations for harqis-work forks."""

from __future__ import annotations

import json
import hashlib
import base64
import os
import re
import shlex
import shutil
import subprocess
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "fork-fleet.toml"
DEFAULT_LOCAL_CONFIG = REPO_ROOT / "fork-fleet.local.toml"
CAPABILITY_ROOTS = {
    "apps": "apps/",
    "workflows": "workflows/",
    "skills": ".agents/skills/",
    "frontend_modules": "frontend/modules/",
    "mcp": "mcp/",
}


class FleetError(RuntimeError):
    """A safe, user-actionable fleet operation failure."""


@dataclass(frozen=True)
class RepositorySpec:
    repository: str
    local_path: str = ""
    default_branch: str = "main"
    discovery: str = "registry"
    fork_kind: str = "registered"

    @property
    def slug(self) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.repository).strip("-").lower()
        if len(normalized) <= 72:
            return normalized
        digest = hashlib.sha256(self.repository.encode("utf-8")).hexdigest()[:12]
        tail = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.repository.rstrip("/").split("/")[-1]).strip("-").lower()
        return f"{tail[:40] or 'repository'}-{digest}"

    @property
    def url(self) -> str:
        if "://" in self.repository or self.repository.startswith("git@"):
            return self.repository
        return f"https://github.com/{self.repository}.git"


@dataclass
class FleetConfig:
    source_repository: str
    default_branch: str = "main"
    github_fallback: bool = True
    github_owners: list[str] = field(default_factory=list)
    report_path: str = ".harqis-data/fork-fleet/latest.json"
    cache_dir: str = ".harqis-data/fork-fleet/repos"
    worktree_dir: str = ".harqis-data/fork-fleet/worktrees"
    repositories: list[RepositorySpec] = field(default_factory=list)

    def resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _run(
    args: Sequence[str], *, cwd: Path | str | None = None, timeout: int = 120,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args), cwd=str(cwd) if cwd else None, capture_output=True,
        text=True, timeout=timeout, env=os.environ,
    )
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()[:600]
        raise FleetError(f"{' '.join(args[:3])} failed: {detail}")
    return result


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_config(
    path: Path | str = DEFAULT_CONFIG,
    local_path: Path | str = DEFAULT_LOCAL_CONFIG,
) -> FleetConfig:
    shared = _load_toml(Path(path))
    local = _load_toml(Path(local_path))
    fleet = {**shared.get("fleet", {}), **local.get("fleet", {})}
    if not fleet.get("source_repository"):
        raise FleetError("fork-fleet.toml must define fleet.source_repository")

    raw_repos: list[Any] = []
    raw_repos.extend(shared.get("repositories", []))
    raw_repos.extend(local.get("repositories", []))
    # Also accept the compact fleet.repositories = ["owner/name"] form.
    raw_repos.extend(shared.get("fleet", {}).get("repositories", []))
    raw_repos.extend(local.get("fleet", {}).get("repositories", []))
    repos: list[RepositorySpec] = []
    for raw in raw_repos:
        if isinstance(raw, str):
            repos.append(RepositorySpec(raw, default_branch=fleet.get("default_branch", "main")))
        elif isinstance(raw, dict) and raw.get("repository"):
            repos.append(RepositorySpec(
                repository=str(raw["repository"]),
                local_path=str(raw.get("local_path", "")),
                default_branch=str(raw.get("default_branch", fleet.get("default_branch", "main")),),
                discovery="registry",
                fork_kind=str(raw.get("fork_kind", "registered")),
            ))
    return FleetConfig(
        source_repository=str(fleet["source_repository"]),
        default_branch=str(fleet.get("default_branch", "main")),
        github_fallback=bool(fleet.get("github_fallback", True)),
        github_owners=[str(v) for v in fleet.get("github_owners", [])],
        report_path=str(fleet.get("report_path", ".harqis-data/fork-fleet/latest.json")),
        cache_dir=str(fleet.get("cache_dir", ".harqis-data/fork-fleet/repos")),
        worktree_dir=str(fleet.get("worktree_dir", ".harqis-data/fork-fleet/worktrees")),
        repositories=repos,
    )


def _gh_json(args: Sequence[str], *, timeout: int = 120) -> Any:
    result = _run(["gh", *args], timeout=timeout)
    if result.returncode:
        raise FleetError((result.stderr or result.stdout).strip() or "GitHub CLI failed")
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        raise FleetError("GitHub CLI returned invalid JSON") from exc


def _has_fork_manifest(repository: str) -> bool:
    result = _run(["gh", "api", f"repos/{repository}/contents/fork-manifest.toml"], timeout=30)
    return result.returncode == 0


def _has_legacy_source_marker(repository: str, source_repository: str) -> bool:
    """Recognize pre-manifest fresh-history derivatives through README lineage."""
    result = _run(["gh", "api", f"repos/{repository}/readme"], timeout=30)
    if result.returncode:
        return False
    try:
        payload = json.loads(result.stdout)
        content = base64.b64decode(str(payload.get("content") or "")).decode(
            "utf-8", errors="replace",
        ).casefold()
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    return any(marker in content for marker in {source_repository.casefold(), "harqis-work"} if marker)


def discover_repositories(config: FleetConfig) -> tuple[list[RepositorySpec], list[str]]:
    """Merge explicit repositories with GitHub fork/manifest discovery."""
    found = {repo.repository.casefold(): repo for repo in config.repositories}
    errors: list[str] = []
    if config.github_fallback:
        owners = list(config.github_owners)
        if not owners:
            try:
                owners = [str(_gh_json(["api", "user"]).get("login", ""))]
            except FleetError as exc:
                errors.append(f"GitHub identity: {exc}")
        for owner in filter(None, owners):
            try:
                rows = _gh_json([
                    "repo", "list", owner, "--limit", "300", "--json",
                    "nameWithOwner,isFork,defaultBranchRef,url,isArchived,description",
                ])
            except FleetError as exc:
                errors.append(f"GitHub discovery for {owner}: {exc}")
                continue
            manifest_candidates = [
                str(row.get("nameWithOwner") or "") for row in (rows or [])
                if row.get("nameWithOwner")
                and not row.get("isFork")
                and not row.get("isArchived")
                and str(row.get("nameWithOwner")).casefold() != config.source_repository.casefold()
            ]
            derivative_kinds: dict[str, str] = {}
            if manifest_candidates:
                workers = min(8, len(manifest_candidates))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    checks = pool.map(_has_fork_manifest, manifest_candidates)
                    derivative_kinds = {
                        name: "manifest-derivative"
                        for name, has_manifest in zip(manifest_candidates, checks)
                        if has_manifest
                    }
                source_leaf = config.source_repository.rsplit("/", 1)[-1].casefold()
                legacy_candidates = [
                    name for name in manifest_candidates
                    if name not in derivative_kinds
                    and (
                        source_leaf in name.casefold()
                        or (
                            "fork" in name.casefold()
                            and "harqis" in name.casefold()
                        )
                    )
                ]
                if legacy_candidates:
                    with ThreadPoolExecutor(max_workers=min(8, len(legacy_candidates))) as pool:
                        legacy_checks = pool.map(
                            _has_legacy_source_marker,
                            legacy_candidates,
                            [config.source_repository] * len(legacy_candidates),
                        )
                        derivative_kinds.update({
                            name: "legacy-derivative"
                            for name, is_legacy in zip(legacy_candidates, legacy_checks)
                            if is_legacy
                        })
            for row in rows or []:
                name = str(row.get("nameWithOwner") or "")
                if not name or name.casefold() == config.source_repository.casefold() or row.get("isArchived"):
                    continue
                is_fork = bool(row.get("isFork"))
                if not is_fork and name not in derivative_kinds:
                    continue
                branch = ((row.get("defaultBranchRef") or {}).get("name") or config.default_branch)
                found.setdefault(name.casefold(), RepositorySpec(
                    repository=name,
                    default_branch=str(branch),
                    discovery="github",
                    fork_kind="github-fork" if is_fork else derivative_kinds[name],
                ))
    return sorted(found.values(), key=lambda value: value.repository.casefold()), errors


def _ensure_cache(repo: RepositorySpec, config: FleetConfig) -> Path:
    cache = config.resolve(config.cache_dir) / repo.slug
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not (cache / ".git").exists():
        _run(["git", "clone", "--filter=blob:none", "--no-checkout", repo.url, str(cache)], timeout=600, check=True)
    _run(["git", "remote", "set-url", "origin", repo.url], cwd=cache, check=True)
    upstream_url = RepositorySpec(config.source_repository).url
    remotes = _run(["git", "remote"], cwd=cache, check=True).stdout.split()
    if "upstream" not in remotes:
        _run(["git", "remote", "add", "upstream", upstream_url], cwd=cache, check=True)
    else:
        _run(["git", "remote", "set-url", "upstream", upstream_url], cwd=cache, check=True)
    _run(["git", "fetch", "--prune", "origin"], cwd=cache, timeout=600, check=True)
    _run(["git", "fetch", "--prune", "upstream"], cwd=cache, timeout=600, check=True)
    return cache


def _git_lines(cache: Path, args: Sequence[str]) -> list[str]:
    result = _run(["git", *args], cwd=cache)
    if result.returncode:
        raise FleetError((result.stderr or result.stdout).strip()[:500])
    return [line for line in result.stdout.splitlines() if line.strip()]


def _git_count(cache: Path, expression: str) -> int:
    lines = _git_lines(cache, ["rev-list", "--count", expression])
    return int(lines[0]) if lines else 0


def _manifest(cache: Path, target_ref: str) -> dict[str, Any]:
    result = _run(["git", "show", f"{target_ref}:fork-manifest.toml"], cwd=cache)
    if result.returncode:
        return {}
    try:
        return tomllib.loads(result.stdout)
    except tomllib.TOMLDecodeError:
        return {"error": "invalid fork-manifest.toml"}


def _capability_summary(changes: Iterable[dict[str, str]]) -> dict[str, list[str]]:
    summary: dict[str, set[str]] = {key: set() for key in CAPABILITY_ROOTS}
    for change in changes:
        path = change["path"]
        for key, prefix in CAPABILITY_ROOTS.items():
            if path.startswith(prefix):
                rest = path[len(prefix):]
                name = rest.split("/", 1)[0] if rest else ""
                if name:
                    summary[key].add(name)
    return {key: sorted(values) for key, values in summary.items()}


def _source_components(cache: Path, source_ref: str, root: str) -> set[str]:
    result = _run(["git", "ls-tree", "-d", "--name-only", f"{source_ref}:{root}"], cwd=cache)
    return set(result.stdout.splitlines()) if result.returncode == 0 else set()


def _intentional_exclusions(cache: Path, source_ref: str, selection: dict[str, Any]) -> dict[str, list[str]]:
    exclusions: dict[str, list[str]] = {}
    for key, root in (("apps", "apps"), ("workflows", "workflows"), ("skills", ".agents/skills")):
        selected = selection.get(key)
        if isinstance(selected, list):
            exclusions[key] = sorted(_source_components(cache, source_ref, root) - {str(value) for value in selected})
    return exclusions


def _repo_links(repo: RepositorySpec, report: dict[str, Any]) -> list[str]:
    base = repo.repository.removesuffix(".git")
    if "://" in base or base.startswith("git@"):
        return [base]
    links = [f"https://github.com/{base}"]
    for pr in report.get("pull_requests", [])[:10]:
        if pr.get("url"):
            links.append(str(pr["url"]))
    for run in report.get("ci_runs", [])[:5]:
        if run.get("url"):
            links.append(str(run["url"]))
    return list(dict.fromkeys(links))


def scan_repository(repo: RepositorySpec, config: FleetConfig) -> dict[str, Any]:
    cache = _ensure_cache(repo, config)
    source_ref = f"upstream/{config.default_branch}"
    target_ref = f"origin/{repo.default_branch}"
    _git_lines(cache, ["rev-parse", "--verify", source_ref])
    _git_lines(cache, ["rev-parse", "--verify", target_ref])
    missing = _git_count(cache, f"{target_ref}..{source_ref}")
    fork_only = _git_count(cache, f"{source_ref}..{target_ref}")
    missing_cherry = _git_lines(cache, ["cherry", target_ref, source_ref])
    fork_cherry = _git_lines(cache, ["cherry", source_ref, target_ref])
    raw_changes = _git_lines(cache, ["diff", "--name-status", source_ref, target_ref])
    changes = []
    for line in raw_changes:
        parts = line.split("\t")
        status = parts[0]
        if status.startswith(("R", "C")) and len(parts) >= 3:
            changes.append({"status": status, "path": parts[1], "side": "source"})
            changes.append({"status": status, "path": parts[2], "side": "target"})
        else:
            changes.append({"status": status, "path": parts[-1]})

    branches = [line.removeprefix("origin/") for line in _git_lines(
        cache, ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]
    ) if not line.endswith("/HEAD")]
    pull_requests: list[dict[str, Any]] = []
    ci_runs: list[dict[str, Any]] = []
    if "://" not in repo.repository and not repo.repository.startswith("git@"):
        try:
            pull_requests = _gh_json([
                "pr", "list", "-R", repo.repository, "--state", "all", "--limit", "50",
                "--json", "number,title,state,isDraft,headRefName,baseRefName,url,mergeStateStatus,statusCheckRollup",
            ]) or []
        except FleetError:
            pull_requests = []
        try:
            ci_runs = _gh_json([
                "run", "list", "-R", repo.repository, "--limit", "20",
                "--json", "databaseId,name,status,conclusion,headBranch,url,createdAt",
            ]) or []
        except FleetError:
            ci_runs = []

    manifest = _manifest(cache, target_ref)
    selection = manifest.get("selection", {}) if isinstance(manifest, dict) else {}
    conflicts = [
        pr for pr in pull_requests
        if str(pr.get("mergeStateStatus") or "").upper() in {"DIRTY", "BLOCKED"}
    ]
    ci_summary: dict[str, int] = {}
    for run in ci_runs:
        state = str(run.get("conclusion") or run.get("status") or "unknown").lower()
        ci_summary[state] = ci_summary.get(state, 0) + 1
    result = {
        "repository": repo.repository,
        "local_path": repo.local_path,
        "discovery": repo.discovery,
        "fork_kind": repo.fork_kind,
        "default_branch": repo.default_branch,
        "source_ref": source_ref,
        "target_ref": target_ref,
        "source_sha": _git_lines(cache, ["rev-parse", source_ref])[0],
        "target_sha": _git_lines(cache, ["rev-parse", target_ref])[0],
        "missing_upstream_commits": missing,
        "fork_only_commits": fork_only,
        "patch_equivalent_upstream_commits": sum(line.startswith("-") for line in missing_cherry),
        "patch_equivalent_fork_commits": sum(line.startswith("-") for line in fork_cherry),
        "missing_commit_summaries": _git_lines(cache, ["log", "--format=%h %s", "--max-count=50", f"{target_ref}..{source_ref}"]),
        "fork_commit_summaries": _git_lines(cache, ["log", "--format=%h %s", "--max-count=50", f"{source_ref}..{target_ref}"]),
        "file_changes": changes,
        "capabilities": _capability_summary(changes),
        "intentional_selection": selection,
        "intentional_exclusions": _intentional_exclusions(cache, source_ref, selection),
        "branches": branches,
        "pull_requests": pull_requests,
        "conflicts": conflicts,
        "ci_runs": ci_runs,
        "ci_summary": ci_summary,
        "cache_path": str(cache),
        "status": "ok",
    }
    result["references"] = _repo_links(repo, result)
    return result


def scan_fleet(
    *, config_path: Path | str = DEFAULT_CONFIG,
    local_config_path: Path | str = DEFAULT_LOCAL_CONFIG,
    write_report: bool = True,
) -> dict[str, Any]:
    config = load_config(config_path, local_config_path)
    repos, discovery_errors = discover_repositories(config)
    reports: list[dict[str, Any]] = []
    for repo in repos:
        try:
            reports.append(scan_repository(repo, config))
        except (FleetError, OSError, subprocess.SubprocessError) as exc:
            reports.append({
                "repository": repo.repository, "discovery": repo.discovery,
                "fork_kind": repo.fork_kind, "local_path": repo.local_path,
                "default_branch": repo.default_branch, "status": "error",
                "error": str(exc)[:800], "references": _repo_links(repo, {}),
            })
    report = {
        "schema_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_repository": config.source_repository,
        "discovery_errors": discovery_errors,
        "repositories": reports,
        "summary": {
            "total": len(reports),
            "healthy": sum(r.get("status") == "ok" for r in reports),
            "errors": sum(r.get("status") != "ok" for r in reports),
            "missing_upstream_commits": sum(int(r.get("missing_upstream_commits", 0)) for r in reports),
            "fork_only_commits": sum(int(r.get("fork_only_commits", 0)) for r in reports),
        },
    }
    if write_report:
        path = config.resolve(config.report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
        report["report_path"] = str(path)
    return report


def load_latest_report(config_path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    config = load_config(config_path)
    path = config.resolve(config.report_path)
    if not path.exists():
        return {"summary": {"total": 0, "healthy": 0, "errors": 0}, "repositories": [], "report_path": str(path)}
    return json.loads(path.read_text(encoding="utf-8"))


def _registered_repo(repository: str, config: FleetConfig) -> RepositorySpec:
    repos, _ = discover_repositories(config)
    for repo in repos:
        if repo.repository.casefold() == repository.casefold():
            return repo
    raise FleetError(f"repository is not managed: {repository}")


def create_worktree(repository: str, branch: str, *, base_branch: str = "", config_path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or branch.startswith("-") or ".." in branch:
        raise FleetError("invalid worktree branch name")
    config = load_config(config_path)
    repo = _registered_repo(repository, config)
    cache = _ensure_cache(repo, config)
    base = base_branch or repo.default_branch
    target = config.resolve(config.worktree_dir) / repo.slug / re.sub(r"[^A-Za-z0-9_.-]", "-", branch)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FleetError(f"worktree already exists: {target}")
    _run(["git", "worktree", "add", "-b", branch, str(target), f"origin/{base}"], cwd=cache, check=True)
    _copy_local_configuration(repo, target)
    return {"repository": repository, "branch": branch, "base_branch": base, "path": str(target)}


def _copy_local_configuration(repo: RepositorySpec, target: Path) -> None:
    """Materialize only ignored fork configuration into an isolated worktree."""
    if not repo.local_path:
        return
    source = Path(repo.local_path).expanduser().resolve()
    if not source.is_dir():
        raise FleetError(f"registered local_path is unavailable: {source}")
    candidates = (Path(".env"), Path("frontend/.env"), Path("machines.local.toml"))
    for relative in candidates:
        origin = source / relative
        if not origin.exists():
            continue
        check_name = relative.as_posix() + ("/apps.env" if relative == Path(".env") else "")
        ignored = _run(["git", "check-ignore", "-q", "--", check_name], cwd=target)
        if ignored.returncode != 0:
            raise FleetError(f"refusing to copy fork config that is not ignored: {relative.as_posix()}")
        destination = target / relative
        if origin.is_dir():
            shutil.copytree(origin, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, destination)


def _python_for(repo: RepositorySpec, worktree: Path) -> str:
    suffix = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    candidates = [worktree / ".venv" / suffix]
    if repo.local_path:
        candidates.append(Path(repo.local_path).expanduser().resolve() / ".venv" / suffix)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return os.environ.get("PYTHON", "python")


def cherry_pick_to_worktree(
    repository: str, commits: Sequence[str], *, branch: str,
    run_tests: bool = True, test_paths: Sequence[str] = (), publish_pr: bool = False,
    pr_title: str = "", pr_body: str = "", config_path: Path | str = DEFAULT_CONFIG,
) -> dict[str, Any]:
    if not commits:
        raise FleetError("at least one commit is required")
    worktree = create_worktree(repository, branch, config_path=config_path)
    path = Path(worktree["path"])
    config = load_config(config_path)
    repo = _registered_repo(repository, config)
    result: dict[str, Any] = {**worktree, "commits": list(commits), "status": "created"}
    for commit in commits:
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit):
            raise FleetError(f"invalid commit id: {commit}")
        picked = _run(["git", "cherry-pick", commit], cwd=path, timeout=300)
        if picked.returncode:
            result.update(status="conflict", conflict=(picked.stderr or picked.stdout).strip()[:1200])
            return result
    result["status"] = "cherry-picked"
    if run_tests:
        executable = _python_for(repo, path)
        targets = list(test_paths) or ["-q"]
        test = _run([executable, "-m", "pytest", *targets], cwd=path, timeout=3600)
        result["tests"] = {"success": test.returncode == 0, "output": (test.stdout + test.stderr)[-5000:]}
        if test.returncode:
            result["status"] = "tests-failed"
            return result
    pushed = _run(["git", "push", "--set-upstream", "origin", branch], cwd=path, timeout=600)
    result["push"] = {"success": pushed.returncode == 0, "output": (pushed.stderr or pushed.stdout).strip()[-1200:]}
    if pushed.returncode:
        result["status"] = "push-failed"
        return result
    result["status"] = "pushed"
    if publish_pr:
        if not pr_title or not pr_body:
            raise FleetError("PR title and body are required when publish_pr is true")
        pr = _run(["gh", "pr", "create", "--repo", repository, "--head", branch, "--base", worktree["base_branch"], "--title", pr_title, "--body", pr_body], cwd=path, timeout=180)
        result["pull_request"] = {"success": pr.returncode == 0, "url": pr.stdout.strip(), "error": pr.stderr.strip()}
        result["status"] = "pr-created" if pr.returncode == 0 else "pr-failed"
    return result


def run_fork_tests(repository: str, *, branch: str, test_paths: Sequence[str] = (), config_path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    worktree = create_worktree(repository, f"fleet-test/{datetime.now():%Y%m%d-%H%M%S}", base_branch=branch, config_path=config_path)
    path = Path(worktree["path"])
    config = load_config(config_path)
    repo = _registered_repo(repository, config)
    executable = _python_for(repo, path)
    targets = list(test_paths) or ["-q"]
    test = _run([executable, "-m", "pytest", *targets], cwd=path, timeout=3600)
    return {**worktree, "success": test.returncode == 0, "output": (test.stdout + test.stderr)[-10000:]}


def deploy_fork(repository: str, *, branch: str, role: str = "host", config_path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    if role not in {"host", "worker"}:
        raise FleetError("deploy role must be host or worker")
    worktree = create_worktree(repository, f"fleet-deploy/{datetime.now():%Y%m%d-%H%M%S}", base_branch=branch, config_path=config_path)
    path = Path(worktree["path"])
    config = load_config(config_path)
    repo = _registered_repo(repository, config)
    deploy = _run([_python_for(repo, path), "scripts/deploy.py", "--role", role], cwd=path, timeout=3600)
    return {**worktree, "success": deploy.returncode == 0, "output": (deploy.stdout + deploy.stderr)[-10000:]}


def shell_preview(command: Sequence[str]) -> str:
    """Render a command for reports without executing it."""
    return " ".join(shlex.quote(value) for value in command)
