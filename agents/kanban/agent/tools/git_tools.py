"""
Git operation tools for agents.

Allows agents to create branches, commit changes, push, and open pull
requests — all attributed to claude[bot] as the git author.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional

from agents.kanban.permissions.enforcer import PermissionEnforcer
from agents.kanban.profiles.schema import GitPermission

logger = logging.getLogger(__name__)

_DEFAULT_AUTHOR_NAME = "claude[bot]"
_DEFAULT_AUTHOR_EMAIL = "claude[bot]@users.noreply.github.com"


def _run_git(
    args: list[str],
    cwd: str,
    author_name: str = _DEFAULT_AUTHOR_NAME,
    author_email: str = _DEFAULT_AUTHOR_EMAIL,
    timeout: int = 60,
) -> tuple[int, str]:
    """Run a git command with the given author attribution."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": author_name,
        "GIT_AUTHOR_EMAIL": author_email,
        "GIT_COMMITTER_NAME": author_name,
        "GIT_COMMITTER_EMAIL": author_email,
    }
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
        env=env,
    )
    output = result.stdout
    if result.stderr:
        output += f"\n[stderr]\n{result.stderr}"
    return result.returncode, output.strip()


class _BaseGitTool:
    name: str
    description: str
    input_schema: dict

    def run(self, **kwargs): ...


class GitStatusTool(_BaseGitTool):
    name = "git_status"
    description = "Show the working tree status of the git repository."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Repository root path. Defaults to working directory.",
            },
        },
        "required": [],
    }

    def __init__(self, enforcer: PermissionEnforcer, cwd: Optional[str] = None):
        self._enforcer = enforcer
        self._cwd = cwd

    def run(self, path: str = ".") -> str:
        self._enforcer.check_tool("git_status")
        rc, output = _run_git(["status", "--short", "--branch"], cwd=path or self._cwd or ".")
        return output or "(clean working tree)"


class GitCreateBranchTool(_BaseGitTool):
    name = "git_create_branch"
    description = (
        "Create a new git branch from current HEAD and switch to it. "
        "Use naming convention: agent/<card_id>/<short-slug>"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Branch name, e.g. 'agent/card123/add-hello-world'.",
            },
            "path": {
                "type": "string",
                "description": "Repository root path. Defaults to working directory.",
            },
        },
        "required": ["branch"],
    }

    def __init__(self, enforcer: PermissionEnforcer, cwd: Optional[str] = None):
        self._enforcer = enforcer
        self._cwd = cwd

    def run(self, branch: str, path: str = ".") -> str:
        self._enforcer.check_tool("git_create_branch")
        rc, output = _run_git(["checkout", "-b", branch], cwd=path or self._cwd or ".")
        if rc != 0:
            return f"ERROR creating branch '{branch}': {output}"
        return f"Created and switched to branch: {branch}"


class GitCommitTool(_BaseGitTool):
    name = "git_commit"
    description = (
        "Stage specified paths (or all changes) and create a git commit. "
        "The commit is attributed to claude[bot] as the author."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message. Be concise and descriptive.",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File paths to stage. Omit to stage all changes (git add .).",
            },
            "path": {
                "type": "string",
                "description": "Repository root path. Defaults to working directory.",
            },
        },
        "required": ["message"],
    }

    def __init__(
        self,
        enforcer: PermissionEnforcer,
        git_config: Optional[GitPermission] = None,
        cwd: Optional[str] = None,
    ):
        self._enforcer = enforcer
        self._git_config = git_config
        self._cwd = cwd

    def _author(self) -> tuple[str, str]:
        if self._git_config:
            return (
                self._git_config.author_name or _DEFAULT_AUTHOR_NAME,
                self._git_config.author_email or _DEFAULT_AUTHOR_EMAIL,
            )
        return _DEFAULT_AUTHOR_NAME, _DEFAULT_AUTHOR_EMAIL

    def run(
        self,
        message: str,
        paths: Optional[list[str]] = None,
        path: str = ".",
    ) -> str:
        self._enforcer.check_tool("git_commit")
        cwd = path or self._cwd or "."
        author_name, author_email = self._author()

        stage_args = ["add"] + (paths if paths else ["."])
        rc, out = _run_git(stage_args, cwd=cwd, author_name=author_name, author_email=author_email)
        if rc != 0:
            return f"ERROR staging files: {out}"

        rc, out = _run_git(
            ["commit", "-m", message],
            cwd=cwd,
            author_name=author_name,
            author_email=author_email,
        )
        if rc != 0:
            if "nothing to commit" in out:
                return "Nothing to commit — working tree clean."
            return f"ERROR committing: {out}"
        return f"Committed:\n{out}"


class GitPushTool(_BaseGitTool):
    name = "git_push"
    description = (
        "Push the current branch to the remote (origin). "
        "Requires git.can_push: true in the agent profile."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": "Branch to push. Defaults to current branch.",
            },
            "force": {
                "type": "boolean",
                "description": "Force push with --force-with-lease. Default false.",
            },
            "path": {
                "type": "string",
                "description": "Repository root path. Defaults to working directory.",
            },
        },
        "required": [],
    }

    def __init__(
        self,
        enforcer: PermissionEnforcer,
        git_config: Optional[GitPermission] = None,
        cwd: Optional[str] = None,
    ):
        self._enforcer = enforcer
        self._git_config = git_config
        self._cwd = cwd

    def run(
        self,
        branch: Optional[str] = None,
        force: bool = False,
        path: str = ".",
    ) -> str:
        self._enforcer.check_tool("git_push")
        cwd = path or self._cwd or "."

        if not branch:
            _, branch_out = _run_git(["branch", "--show-current"], cwd=cwd)
            branch = branch_out.strip()

        self._enforcer.check_git_push(branch)

        args = ["push", "--set-upstream", "origin", branch]
        if force:
            args.insert(1, "--force-with-lease")

        rc, out = _run_git(args, cwd=cwd)
        if rc != 0:
            return f"ERROR pushing branch '{branch}': {out}"
        return f"Pushed branch '{branch}':\n{out}"


class GitCreatePRTool(_BaseGitTool):
    name = "git_create_pr"
    description = (
        "Create a GitHub pull request for the current branch using `gh pr create`. "
        "Requires the `gh` CLI to be installed and authenticated."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "PR title (under 70 characters).",
            },
            "body": {
                "type": "string",
                "description": "PR description in Markdown. Include summary, test plan, and card reference.",
            },
            "base": {
                "type": "string",
                "description": "Base branch to merge into. Default: main.",
            },
            "draft": {
                "type": "boolean",
                "description": "Open as draft PR. Default false.",
            },
            "path": {
                "type": "string",
                "description": "Repository root path. Defaults to working directory.",
            },
        },
        "required": ["title", "body"],
    }

    def __init__(self, enforcer: PermissionEnforcer, cwd: Optional[str] = None):
        self._enforcer = enforcer
        self._cwd = cwd

    def run(
        self,
        title: str,
        body: str,
        base: str = "main",
        draft: bool = False,
        path: str = ".",
    ) -> str:
        self._enforcer.check_tool("git_create_pr")
        cwd = path or self._cwd or "."

        args = ["gh", "pr", "create", "--title", title, "--body", body, "--base", base]
        if draft:
            args.append("--draft")

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
            env=os.environ,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            return f"ERROR creating PR: {output.strip()}"
        return f"Pull request created:\n{output.strip()}"
