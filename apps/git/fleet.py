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
import uuid
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
    plan_dir: str = ".harqis-data/fork-fleet/plans"
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
        plan_dir=str(fleet.get("plan_dir", ".harqis-data/fork-fleet/plans")),
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


def _readiness_summary(report: dict[str, Any]) -> dict[str, Any]:
    """Classify general shipping readiness without applying a candidate feature."""
    reasons: list[str] = []
    level = "ready"
    manifest = report.get("intentional_selection")
    if isinstance(manifest, dict) and report.get("manifest_error"):
        level = "blocked"
        reasons.append("fork manifest is invalid")
    if report.get("conflicts"):
        level = "review" if level != "blocked" else level
        reasons.append("existing pull requests are blocked or conflicted")
    failed_ci = sum(
        count for state, count in report.get("ci_summary", {}).items()
        if state in {"failure", "failed", "cancelled", "timed_out", "action_required"}
    )
    if failed_ci:
        level = "review" if level != "blocked" else level
        reasons.append(f"{failed_ci} recent CI run(s) require review")
    if report.get("fork_only_commits"):
        level = "review" if level != "blocked" else level
        reasons.append("fork-only commits may overlap candidate changes")
    if report.get("missing_upstream_commits"):
        reasons.append("outstanding upstream commits are available for planning")
    if not reasons:
        reasons.append("no general drift blockers detected")
    return {"level": level, "reasons": reasons}


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
        "manifest_error": manifest.get("error", "") if isinstance(manifest, dict) else "",
        "intentional_exclusions": _intentional_exclusions(cache, source_ref, selection),
        "branches": branches,
        "pull_requests": pull_requests,
        "conflicts": conflicts,
        "ci_runs": ci_runs,
        "ci_summary": ci_summary,
        "cache_path": str(cache),
        "status": "ok",
    }
    result["feature_readiness"] = _readiness_summary(result)
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
            "feature_ready": sum(r.get("feature_readiness", {}).get("level") == "ready" for r in reports),
            "feature_review": sum(r.get("feature_readiness", {}).get("level") == "review" for r in reports),
            "feature_blocked": sum(r.get("feature_readiness", {}).get("level") == "blocked" for r in reports),
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


def _ensure_source_cache(config: FleetConfig) -> Path:
    cache = config.resolve(config.cache_dir) / "_source"
    cache.parent.mkdir(parents=True, exist_ok=True)
    source = RepositorySpec(config.source_repository)
    if not (cache / ".git").exists():
        _run(["git", "clone", "--filter=blob:none", "--no-checkout", source.url, str(cache)], timeout=600, check=True)
    _run(["git", "remote", "set-url", "origin", source.url], cwd=cache, check=True)
    _run(["git", "fetch", "--prune", "origin"], cwd=cache, timeout=600, check=True)
    return cache


def _commit_sha(cache: Path, value: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{7,64}", value):
        raise FleetError(f"invalid commit id: {value}")
    result = _run(["git", "rev-parse", "--verify", f"{value}^{{commit}}"], cwd=cache)
    if result.returncode:
        raise FleetError(f"commit is unavailable from the source repository: {value}")
    return result.stdout.strip()


def resolve_feature_commits(
    *, commits: Sequence[str] = (), commit_range: str = "", pull_request: str = "",
    config_path: Path | str = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Resolve explicit SHAs, one range, or one source PR to ordered source commits."""
    supplied = sum(bool(value) for value in (commits, commit_range, pull_request))
    if supplied != 1:
        raise FleetError("provide exactly one of commits, commit_range, or pull_request")
    config = load_config(config_path)
    cache = _ensure_source_cache(config)
    title = ""
    source_url = ""
    values: list[str]
    if commits:
        values = list(commits)
    elif commit_range:
        parts = commit_range.split("..")
        safe_ref = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
        if len(parts) != 2 or not all(safe_ref.fullmatch(part) for part in parts):
            raise FleetError("commit range must use safe contiguous A..B syntax")
        values = _git_lines(cache, ["rev-list", "--reverse", "--topo-order", commit_range])
    else:
        pr_ref = str(pull_request).strip()
        if not (pr_ref.isdigit() or re.fullmatch(r"https://github\.com/[^/]+/[^/]+/pull/\d+/?", pr_ref)):
            raise FleetError("pull_request must be a PR number or GitHub PR URL")
        if pr_ref.startswith("https://"):
            expected = f"https://github.com/{config.source_repository}/pull/"
            if not pr_ref.casefold().startswith(expected.casefold()):
                raise FleetError("pull request URL must belong to fleet.source_repository")
        args = ["pr", "view", pr_ref]
        if pr_ref.isdigit():
            args += ["--repo", config.source_repository]
        payload = _gh_json([*args, "--json", "number,title,url,commits"])
        title = str(payload.get("title") or "")
        source_url = str(payload.get("url") or "")
        values = [str(row.get("oid") or "") for row in payload.get("commits", [])]
        number = str(payload.get("number") or "")
        if number:
            _run(["git", "fetch", "origin", f"pull/{number}/head"], cwd=cache, timeout=300)
    resolved: list[str] = []
    for value in values:
        sha = _commit_sha(cache, value)
        if sha not in resolved:
            resolved.append(sha)
    if not resolved:
        raise FleetError("feature input resolved to zero commits")
    subjects = [_git_lines(cache, ["show", "-s", "--format=%s", sha])[0] for sha in resolved]
    if not title:
        title = subjects[0]
    return {
        "repository": config.source_repository,
        "commits": resolved,
        "subjects": subjects,
        "title": title,
        "url": source_url,
        "input": {"commits": list(commits), "range": commit_range, "pull_request": pull_request},
    }


def _parse_name_status(lines: Iterable[str]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith(("R", "C")) and len(parts) >= 3:
            changes.append({"status": status, "path": parts[1], "new_path": parts[2]})
        else:
            changes.append({"status": status, "path": parts[-1]})
    return changes


def _feature_changes(cache: Path, commits: Sequence[str]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for commit in commits:
        changes.extend(_parse_name_status(_git_lines(
            cache, ["diff-tree", "--root", "--no-commit-id", "--name-status", "-r", "-M", commit],
        )))
    unique: dict[tuple[str, str, str], dict[str, str]] = {}
    for change in changes:
        key = (change["status"], change["path"], change.get("new_path", ""))
        unique[key] = change
    return list(unique.values())


def _commit_presence(cache: Path, target_ref: str, commit: str) -> str:
    ancestor = _run(["git", "merge-base", "--is-ancestor", commit, target_ref], cwd=cache)
    if ancestor.returncode == 0:
        return "present"
    cherry = _run(["git", "cherry", target_ref, commit], cwd=cache)
    for line in cherry.stdout.splitlines():
        if line.rstrip().endswith(commit):
            return "patch-equivalent" if line.startswith("-") else "missing"
    return "missing"


def _target_custom_changes(cache: Path, source_ref: str, target_ref: str, manifest: dict[str, Any]) -> list[dict[str, str]]:
    base = _run(["git", "merge-base", source_ref, target_ref], cwd=cache)
    if base.returncode == 0 and base.stdout.strip():
        start = base.stdout.strip()
    else:
        start = str((manifest.get("fork") or {}).get("source_sha") or "")
        if not start or _run(["git", "cat-file", "-e", f"{start}^{{commit}}"], cwd=cache).returncode:
            return []
    return _parse_name_status(_git_lines(cache, ["diff", "--name-status", "-M", start, target_ref]))


def _open_pr_path_collisions(repository: str, candidate_paths: set[str]) -> list[dict[str, Any]]:
    if "://" in repository or repository.startswith("git@"):
        return []
    try:
        rows = _gh_json(["pr", "list", "-R", repository, "--state", "open", "--limit", "30", "--json", "number,title,url"])
    except FleetError:
        return []
    collisions = []
    for row in rows or []:
        try:
            detail = _gh_json(["pr", "view", str(row["number"]), "-R", repository, "--json", "files"])
        except FleetError:
            continue
        paths = {str(item.get("path") or "") for item in detail.get("files", [])}
        overlap = sorted(candidate_paths & paths)
        if overlap:
            collisions.append({"number": row["number"], "title": row.get("title"), "url": row.get("url"), "paths": overlap})
    return collisions


def _trial_cherry_pick(
    cache: Path, target_ref: str, commits: Sequence[str], *, repo: RepositorySpec, config: FleetConfig,
) -> dict[str, Any]:
    if not commits:
        return {"success": True, "status": "already-applied", "conflicted_paths": []}
    for commit in commits:
        fetch = _run(["git", "fetch", "upstream", commit], cwd=cache, timeout=300)
        if fetch.returncode and _run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=cache).returncode:
            return {"success": False, "status": "commit-unavailable", "conflicted_paths": [], "error": fetch.stderr.strip()[:600]}
    token = uuid.uuid4().hex[:10]
    target = config.resolve(config.worktree_dir) / "preflight" / repo.slug / token
    target.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "worktree", "add", "--detach", str(target), target_ref], cwd=cache, check=True)
    for commit in commits:
        picked = _run(["git", "cherry-pick", "--no-commit", commit], cwd=target, timeout=300)
        if picked.returncode:
            conflicted = _run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=target).stdout.splitlines()
            return {
                "success": False, "status": "conflict", "conflicted_paths": conflicted,
                "diagnostic_worktree": str(target), "error": (picked.stderr or picked.stdout).strip()[:1200],
            }
    _run(["git", "worktree", "remove", "--force", str(target)], cwd=cache, timeout=120, check=True)
    return {"success": True, "status": "clean", "conflicted_paths": []}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")[:40] or "feature"


def _plan_path(config: FleetConfig, plan_id: str) -> Path:
    return config.resolve(config.plan_dir) / f"{plan_id}.json"


def _feature_plan_id(payload: dict[str, Any]) -> str:
    keys = (
        "schema_version", "generated_at", "source", "feature_slug", "squash",
        "candidate_changes", "candidate_capabilities", "filters", "discovery_errors", "targets",
    )
    core = {key: payload[key] for key in keys}
    return hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    ).hexdigest()[:16]


def plan_feature_shipping(
    *, commits: Sequence[str] = (), commit_range: str = "", pull_request: str = "",
    include: Sequence[str] = (), exclude: Sequence[str] = (), squash: bool = False,
    config_path: Path | str = DEFAULT_CONFIG, write_report: bool = True,
) -> dict[str, Any]:
    """Build a compatibility plan without changing any fork remote."""
    config = load_config(config_path)
    source = resolve_feature_commits(
        commits=commits, commit_range=commit_range, pull_request=pull_request,
        config_path=config_path,
    )
    source_cache = _ensure_source_cache(config)
    changes = _feature_changes(source_cache, source["commits"])
    candidate_paths = {change["path"] for change in changes} | {
        change["new_path"] for change in changes if change.get("new_path")
    }
    candidate_capabilities = _capability_summary(changes)
    wanted = {value.casefold() for value in include}
    omitted = {value.casefold() for value in exclude}
    repos, discovery_errors = discover_repositories(config)
    targets: list[dict[str, Any]] = []
    for repo in repos:
        if wanted and repo.repository.casefold() not in wanted:
            continue
        if repo.repository.casefold() in omitted:
            continue
        try:
            cache = _ensure_cache(repo, config)
            target_ref = f"origin/{repo.default_branch}"
            source_ref = f"upstream/{config.default_branch}"
            for commit in source["commits"]:
                _run(["git", "fetch", "upstream", commit], cwd=cache, timeout=300)
            target_sha = _git_lines(cache, ["rev-parse", target_ref])[0]
            source_sha = _git_lines(cache, ["rev-parse", source_ref])[0]
            manifest = _manifest(cache, target_ref)
            presence = {commit: _commit_presence(cache, target_ref, commit) for commit in source["commits"]}
            remaining = [commit for commit, state in presence.items() if state == "missing"]
            custom_changes = _target_custom_changes(cache, source_ref, target_ref, manifest)
            custom_paths = {item["path"] for item in custom_changes} | {
                item["new_path"] for item in custom_changes if item.get("new_path")
            }
            collisions: list[dict[str, Any]] = []
            overlap = sorted(candidate_paths & custom_paths)
            if overlap:
                collisions.append({"type": "fork-path-overlap", "severity": "warning", "paths": overlap})
            custom_capabilities = _capability_summary(custom_changes)
            capability_overlap = {
                key: sorted(set(candidate_capabilities.get(key, ())) & set(custom_capabilities.get(key, ())))
                for key in CAPABILITY_ROOTS
            }
            capability_overlap = {key: values for key, values in capability_overlap.items() if values}
            if capability_overlap:
                collisions.append({"type": "capability-overlap", "severity": "warning", "capabilities": capability_overlap})
            selection = manifest.get("selection", {}) if isinstance(manifest, dict) else {}
            excluded = {}
            for key in ("apps", "workflows", "skills"):
                selected = selection.get(key)
                if isinstance(selected, list):
                    missing_selected = sorted(set(candidate_capabilities.get(key, ())) - {str(value) for value in selected})
                    if missing_selected:
                        excluded[key] = missing_selected
            if excluded:
                collisions.append({"type": "manifest-exclusion", "severity": "blocking", "capabilities": excluded})
            pr_collisions = _open_pr_path_collisions(repo.repository, candidate_paths)
            if pr_collisions:
                collisions.append({"type": "open-pr-overlap", "severity": "warning", "pull_requests": pr_collisions})
            trial = _trial_cherry_pick(cache, target_ref, remaining, repo=repo, config=config)
            if not trial["success"]:
                collisions.append({
                    "type": "trial-cherry-pick", "severity": "blocking",
                    "paths": trial.get("conflicted_paths", []), "detail": trial.get("error", ""),
                    "diagnostic_worktree": trial.get("diagnostic_worktree", ""),
                })
            if not remaining:
                status = "already-applied"
            elif any(item["severity"] == "blocking" for item in collisions):
                status = "blocked"
            elif collisions:
                status = "compatible-with-warnings"
            else:
                status = "compatible"
            targets.append({
                "repository": repo.repository, "default_branch": repo.default_branch,
                "target_sha": target_sha, "source_sha": source_sha, "status": status,
                "mergeable": status in {"compatible", "compatible-with-warnings"},
                "commit_presence": presence, "commits_to_apply": remaining,
                "drift": {
                    "missing_upstream_commits": _git_count(cache, f"{target_ref}..{source_ref}"),
                    "fork_only_commits": _git_count(cache, f"{source_ref}..{target_ref}"),
                    "custom_paths": sorted(custom_paths),
                },
                "collisions": collisions, "trial": trial,
                "references": _repo_links(repo, {}),
            })
        except (FleetError, OSError, subprocess.SubprocessError) as exc:
            targets.append({
                "repository": repo.repository, "default_branch": repo.default_branch,
                "status": "unavailable", "mergeable": False, "error": str(exc)[:1000],
                "references": _repo_links(repo, {}),
            })
    generated_at = datetime.now().astimezone().isoformat()
    core = {
        "schema_version": 1, "generated_at": generated_at,
        "source": source, "feature_slug": _slug(source["title"]), "squash": squash,
        "candidate_changes": changes, "candidate_capabilities": candidate_capabilities,
        "filters": {"include": list(include), "exclude": list(exclude)},
        "discovery_errors": discovery_errors, "targets": targets,
    }
    plan_id = _feature_plan_id(core)
    report = {**core, "plan_id": plan_id}
    report["summary"] = {
        "total": len(targets),
        "compatible": sum(row.get("status") == "compatible" for row in targets),
        "warnings": sum(row.get("status") == "compatible-with-warnings" for row in targets),
        "blocked": sum(row.get("status") == "blocked" for row in targets),
        "already_applied": sum(row.get("status") == "already-applied" for row in targets),
        "unavailable": sum(row.get("status") == "unavailable" for row in targets),
    }
    if write_report:
        path = _plan_path(config, plan_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
        report["plan_path"] = str(path)
    return report


def load_feature_plan(plan: str, *, config_path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    config = load_config(config_path)
    candidate = Path(plan)
    path = candidate.resolve() if candidate.exists() else _plan_path(config, plan)
    if not path.exists():
        raise FleetError(f"feature plan not found: {plan}")
    plan_root = config.resolve(config.plan_dir)
    if path.parent != plan_root:
        raise FleetError(f"feature plan must be persisted under {plan_root}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FleetError(f"feature plan is unreadable: {path}") from exc
    if payload.get("plan_id") != path.stem:
        raise FleetError("feature plan id does not match its persisted filename")
    try:
        expected = _feature_plan_id(payload)
    except KeyError as exc:
        raise FleetError(f"feature plan is missing integrity field: {exc.args[0]}") from exc
    if payload.get("plan_id") != expected:
        raise FleetError("feature plan integrity check failed; generate a new plan")
    payload["plan_path"] = str(path.resolve())
    return payload


def _infer_test_paths(worktree: Path, changes: Sequence[dict[str, str]]) -> list[str]:
    targets: list[str] = []
    for change in changes:
        path = str(change.get("new_path") or change.get("path") or "")
        parts = path.split("/")
        if len(parts) < 2 or parts[0] not in {"apps", "workflows"}:
            continue
        candidate = Path(parts[0]) / parts[1] / "tests"
        if (worktree / candidate).is_dir() and candidate.as_posix() not in targets:
            targets.append(candidate.as_posix())
    return targets


def _test_stage(executable: str, path: Path, targets: Sequence[str], *, label: str) -> dict[str, Any]:
    if label == "targeted" and not targets:
        return {"stage": label, "success": True, "skipped": True, "reason": "no component test paths inferred"}
    args = list(targets) if targets else ["-q"]
    result = _run([executable, "-m", "pytest", *args], cwd=path, timeout=3600)
    return {
        "stage": label, "success": result.returncode == 0,
        "command": ["python", "-m", "pytest", *args],
        "output": (result.stdout + result.stderr)[-10000:],
    }


def _apply_feature_commits(path: Path, commits: Sequence[str], *, squash: bool, feature_title: str) -> dict[str, Any]:
    if not commits:
        return {"success": True, "commits": [], "status": "already-applied"}
    for commit in commits:
        args = ["git", "cherry-pick"]
        if squash:
            args.append("--no-commit")
        args.append(commit)
        result = _run(args, cwd=path, timeout=300)
        if result.returncode:
            conflicted = _run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=path).stdout.splitlines()
            return {
                "success": False, "status": "conflict", "commit": commit,
                "conflicted_paths": conflicted, "error": (result.stderr or result.stdout).strip()[:1200],
            }
    if squash:
        committed = _run(["git", "commit", "-m", f"feat: {feature_title}"], cwd=path, timeout=300)
        if committed.returncode:
            return {"success": False, "status": "commit-failed", "error": (committed.stderr or committed.stdout).strip()[:1200]}
    return {"success": True, "status": "applied", "commits": list(commits), "squash": squash}


def ship_feature_plan(
    plan: str, *, approval: str, repositories: Sequence[str] = (),
    test_paths: Sequence[str] = (), deploy_roles: dict[str, str] | None = None,
    direct_main: Sequence[str] = (), direct_main_confirmation: str = "",
    config_path: Path | str = DEFAULT_CONFIG, write_report: bool = True,
) -> dict[str, Any]:
    """Execute an approved plan, isolating failures and revalidating every target SHA."""
    payload = load_feature_plan(plan, config_path=config_path)
    plan_id = str(payload.get("plan_id") or "")
    if not plan_id or approval != plan_id:
        raise FleetError("approval must exactly match the persisted plan_id")
    selected = {value.casefold() for value in repositories}
    direct = {value.casefold() for value in direct_main}
    if direct and direct_main_confirmation != f"DIRECT-MAIN:{plan_id}":
        raise FleetError(f"direct-main delivery requires confirmation DIRECT-MAIN:{plan_id}")
    if direct and (not selected or not direct.issubset(selected)):
        raise FleetError("direct-main repositories must be explicitly included in the rollout repository list")
    config = load_config(config_path)
    deploy_roles = {key.casefold(): value for key, value in (deploy_roles or {}).items()}
    invalid_roles = {role for role in deploy_roles.values() if role not in {"host", "worker"}}
    if invalid_roles:
        raise FleetError("deploy roles must be host or worker")
    results: list[dict[str, Any]] = []
    for target in payload.get("targets", []):
        repository = str(target.get("repository") or "")
        key = repository.casefold()
        if selected and key not in selected:
            continue
        if target.get("status") not in {"compatible", "compatible-with-warnings"}:
            results.append({"repository": repository, "status": "skipped", "reason": target.get("status")})
            continue
        try:
            repo = _registered_repo(repository, config)
            cache = _ensure_cache(repo, config)
            target_ref = f"origin/{repo.default_branch}"
            current_sha = _git_lines(cache, ["rev-parse", target_ref])[0]
            if current_sha != target.get("target_sha"):
                results.append({
                    "repository": repository, "status": "stale-plan",
                    "planned_sha": target.get("target_sha"), "current_sha": current_sha,
                })
                continue
            for commit in target.get("commits_to_apply", []):
                fetched = _run(["git", "fetch", "upstream", commit], cwd=cache, timeout=300)
                if fetched.returncode and _run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=cache).returncode:
                    raise FleetError(f"planned commit is no longer fetchable: {commit}")
            branch = f"fleet/{payload['feature_slug']}-{payload['source']['commits'][-1][:8]}"
            worktree = create_worktree(repository, branch, config_path=config_path)
            path = Path(worktree["path"])
            outcome: dict[str, Any] = {
                **worktree, "plan_id": plan_id, "status": "created",
                "direct_main": key in direct,
            }
            applied = _apply_feature_commits(
                path, target.get("commits_to_apply", []), squash=bool(payload.get("squash")),
                feature_title=str(payload["source"].get("title") or payload["feature_slug"]),
            )
            outcome["apply"] = applied
            if not applied["success"]:
                outcome["status"] = applied["status"]
                results.append(outcome)
                continue
            executable = _python_for(repo, path)
            targeted = list(test_paths) or _infer_test_paths(path, payload.get("candidate_changes", []))
            targeted_result = _test_stage(executable, path, targeted, label="targeted")
            outcome["targeted_tests"] = targeted_result
            if not targeted_result["success"]:
                outcome["status"] = "targeted-tests-failed"
                results.append(outcome)
                continue
            full_result = _test_stage(executable, path, (), label="full")
            outcome["full_tests"] = full_result
            if not full_result["success"]:
                outcome["status"] = "full-tests-failed"
                results.append(outcome)
                continue
            if key in deploy_roles:
                deployed = _run([executable, "scripts/deploy.py", "--role", deploy_roles[key]], cwd=path, timeout=3600)
                outcome["deployment"] = {
                    "role": deploy_roles[key], "success": deployed.returncode == 0,
                    "output": (deployed.stdout + deployed.stderr)[-10000:],
                }
                if deployed.returncode:
                    outcome["status"] = "deploy-failed"
                    results.append(outcome)
                    continue
            _run(["git", "fetch", "origin", repo.default_branch], cwd=cache, timeout=300, check=True)
            latest_sha = _git_lines(cache, ["rev-parse", target_ref])[0]
            if latest_sha != current_sha:
                outcome.update(status="stale-before-publish", current_sha=latest_sha)
                results.append(outcome)
                continue
            if key in direct:
                pushed = _run(["git", "push", "origin", f"HEAD:refs/heads/{repo.default_branch}"], cwd=path, timeout=600)
                outcome["push"] = {"success": pushed.returncode == 0, "output": (pushed.stderr or pushed.stdout).strip()[-1200:]}
                outcome["status"] = "direct-main-pushed" if pushed.returncode == 0 else "push-failed"
            else:
                pushed = _run(["git", "push", "--set-upstream", "origin", branch], cwd=path, timeout=600)
                outcome["push"] = {"success": pushed.returncode == 0, "output": (pushed.stderr or pushed.stdout).strip()[-1200:]}
                if pushed.returncode:
                    outcome["status"] = "push-failed"
                    results.append(outcome)
                    continue
                body = (
                    f"Fleet rollout plan `{plan_id}`\n\n"
                    f"Source: {payload['source'].get('url') or payload['source']['repository']}\n\n"
                    "Targeted and full regression tests passed before publication. "
                    "This PR remains draft until GitHub CI is reviewed and explicitly promoted."
                )
                pr = _run([
                    "gh", "pr", "create", "--draft", "--repo", repository,
                    "--head", branch, "--base", repo.default_branch,
                    "--title", str(payload["source"]["title"]), "--body", body,
                ], cwd=path, timeout=180)
                outcome["pull_request"] = {
                    "success": pr.returncode == 0, "url": pr.stdout.strip(), "error": pr.stderr.strip(), "draft": True,
                }
                outcome["status"] = "draft-pr-created" if pr.returncode == 0 else "pr-failed"
            results.append(outcome)
        except (FleetError, OSError, subprocess.SubprocessError) as exc:
            results.append({"repository": repository, "status": "error", "error": str(exc)[:1200]})
    report = {
        "schema_version": 1, "generated_at": datetime.now().astimezone().isoformat(),
        "plan_id": plan_id, "source": payload.get("source", {}), "results": results,
        "summary": {
            "total": len(results),
            "draft_prs": sum(row.get("status") == "draft-pr-created" for row in results),
            "direct_main": sum(row.get("status") == "direct-main-pushed" for row in results),
            "failed": sum(row.get("status") in {
                "conflict", "targeted-tests-failed", "full-tests-failed", "deploy-failed",
                "push-failed", "pr-failed", "error", "stale-plan", "stale-before-publish",
            } for row in results),
            "skipped": sum(row.get("status") == "skipped" for row in results),
        },
    }
    if write_report:
        rollout_dir = config.resolve(config.plan_dir).parent / "rollouts"
        rollout_dir.mkdir(parents=True, exist_ok=True)
        path = rollout_dir / f"{plan_id}-{datetime.now():%Y%m%d-%H%M%S}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        report["report_path"] = str(path)
    return report


def promote_feature_pull_request(
    repository: str, pull_request: int, *, approval: str,
) -> dict[str, Any]:
    """Mark a fleet PR ready only after every reported GitHub check succeeds."""
    expected = f"READY:{repository}#{pull_request}"
    if approval != expected:
        raise FleetError(f"PR promotion requires confirmation {expected}")
    payload = _gh_json([
        "pr", "view", str(pull_request), "-R", repository,
        "--json", "url,isDraft,mergeStateStatus,statusCheckRollup",
    ])
    if not payload.get("isDraft"):
        return {"repository": repository, "pull_request": pull_request, "status": "already-ready", "url": payload.get("url")}
    if str(payload.get("mergeStateStatus") or "").upper() in {"DIRTY", "BLOCKED"}:
        raise FleetError("PR is conflicted or blocked")
    checks = payload.get("statusCheckRollup") or []
    if not checks:
        raise FleetError("PR has no GitHub checks to verify")
    incomplete = []
    for check in checks:
        status = str(check.get("status") or "").upper()
        conclusion = str(check.get("conclusion") or check.get("state") or "").upper()
        if status not in {"COMPLETED", ""} or conclusion not in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
            incomplete.append(str(check.get("name") or check.get("context") or "unnamed check"))
    if incomplete:
        raise FleetError("PR checks are not successful: " + ", ".join(incomplete))
    ready = _run(["gh", "pr", "ready", str(pull_request), "-R", repository], timeout=180)
    if ready.returncode:
        raise FleetError((ready.stderr or ready.stdout).strip()[:800])
    return {"repository": repository, "pull_request": pull_request, "status": "ready", "url": payload.get("url")}


def shell_preview(command: Sequence[str]) -> str:
    """Render a command for reports without executing it."""
    return " ".join(shlex.quote(value) for value in command)
