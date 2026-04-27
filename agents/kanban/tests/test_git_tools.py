"""
Tests for agents/kanban/agent/tools/git_tools.py

All tests run offline — git commands are mocked via subprocess.run.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, contains_string, equal_to, starts_with

from agents.kanban.agent.tools.git_tools import (
    GitCommitTool,
    GitCreateBranchTool,
    GitCreatePRTool,
    GitPushTool,
    GitStatusTool,
)
from agents.kanban.permissions.enforcer import PermissionDenied, PermissionEnforcer
from agents.kanban.profiles.schema import (
    AgentProfile,
    GitPermission,
    PermissionsConfig,
    ToolsConfig,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def full_git_profile():
    return AgentProfile(
        id="agent:test:git",
        name="Git Test Agent",
        tools=ToolsConfig(
            allowed=[
                "git_status", "git_create_branch", "git_commit",
                "git_push", "git_create_pr",
            ],
            denied=[],
        ),
        permissions=PermissionsConfig(
            git=GitPermission(
                can_push=True,
                protected_branches=["main", "master"],
                require_pr=True,
                author_name="claude[bot]",
                author_email="claude[bot]@users.noreply.github.com",
            ),
        ),
    )


@pytest.fixture()
def no_push_profile():
    return AgentProfile(
        id="agent:test:nopush",
        name="No Push Agent",
        tools=ToolsConfig(allowed=[], denied=["git_push"]),
        permissions=PermissionsConfig(
            git=GitPermission(can_push=False, protected_branches=["main"]),
        ),
    )


@pytest.fixture()
def enforcer(full_git_profile):
    return PermissionEnforcer(full_git_profile)


@pytest.fixture()
def restricted_enforcer(no_push_profile):
    return PermissionEnforcer(no_push_profile)


def _make_completed(returncode: int, stdout: str = "", stderr: str = ""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ── GitStatusTool ─────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_git_status_returns_output(enforcer):
    tool = GitStatusTool(enforcer, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed(0, stdout="## main\nM  foo.py\n")
        result = tool.run()
    assert_that(result, contains_string("main"))
    assert_that(result, contains_string("foo.py"))


@pytest.mark.smoke
def test_git_status_clean_tree(enforcer):
    tool = GitStatusTool(enforcer, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed(0, stdout="")
        result = tool.run()
    assert_that(result, equal_to("(clean working tree)"))


@pytest.mark.smoke
def test_git_status_tool_denied(no_push_profile):
    enforcer = PermissionEnforcer(no_push_profile)
    # git_status not in allowed list for no_push_profile (allowed=[])
    # so it should be allowed since allowed=[] means no restriction
    tool = GitStatusTool(enforcer, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed(0, stdout="## main")
        result = tool.run()
    assert_that(result, contains_string("main"))


# ── GitCreateBranchTool ───────────────────────────────────────────────────────

@pytest.mark.smoke
def test_git_create_branch_success(enforcer):
    tool = GitCreateBranchTool(enforcer, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed(0, stdout="Switched to a new branch 'agent/c1/fix'")
        result = tool.run(branch="agent/c1/fix")
    assert_that(result, contains_string("agent/c1/fix"))


@pytest.mark.smoke
def test_git_create_branch_failure(enforcer):
    tool = GitCreateBranchTool(enforcer, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed(128, stderr="branch already exists")
        result = tool.run(branch="existing-branch")
    assert_that(result, starts_with("ERROR"))
    assert_that(result, contains_string("existing-branch"))


# ── GitCommitTool ─────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_git_commit_success(enforcer, full_git_profile):
    tool = GitCommitTool(enforcer, git_config=full_git_profile.permissions.git, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed(0, stdout="[agent/c1/fix abc1234] add feature")
        result = tool.run(message="add feature")
    assert_that(result, contains_string("Committed"))


@pytest.mark.smoke
def test_git_commit_uses_claude_author(enforcer, full_git_profile):
    tool = GitCommitTool(enforcer, git_config=full_git_profile.permissions.git, cwd="/repo")
    calls = []
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed(0, stdout="[branch abc] msg")
        mock_run.side_effect = lambda *a, **kw: (calls.append(kw.get("env", {})), _make_completed(0, stdout="[branch abc] msg"))[1]
        tool.run(message="test commit")

    assert len(calls) > 0
    last_env = calls[-1]
    assert_that(last_env.get("GIT_AUTHOR_NAME"), equal_to("claude[bot]"))
    assert_that(last_env.get("GIT_AUTHOR_EMAIL"), equal_to("claude[bot]@users.noreply.github.com"))


@pytest.mark.smoke
def test_git_commit_nothing_to_commit(enforcer, full_git_profile):
    tool = GitCommitTool(enforcer, git_config=full_git_profile.permissions.git, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        # First call (add) succeeds, second call (commit) returns "nothing to commit"
        mock_run.side_effect = [
            _make_completed(0, stdout=""),
            _make_completed(1, stdout="nothing to commit, working tree clean"),
        ]
        result = tool.run(message="empty commit")
    assert_that(result, contains_string("Nothing to commit"))


@pytest.mark.smoke
def test_git_commit_specific_paths(enforcer, full_git_profile):
    tool = GitCommitTool(enforcer, git_config=full_git_profile.permissions.git, cwd="/repo")
    staged_args = []
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        def capture(*a, **kw):
            staged_args.append(a[0])
            return _make_completed(0, stdout="ok")
        mock_run.side_effect = capture
        tool.run(message="partial commit", paths=["src/foo.py", "src/bar.py"])

    assert_that(staged_args[0], equal_to(["git", "add", "src/foo.py", "src/bar.py"]))


# ── GitPushTool ───────────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_git_push_success(enforcer, full_git_profile):
    tool = GitPushTool(enforcer, git_config=full_git_profile.permissions.git, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.side_effect = [
            _make_completed(0, stdout="agent/c1/fix"),  # branch --show-current
            _make_completed(0, stdout="Branch set up to track origin/agent/c1/fix"),
        ]
        result = tool.run()
    assert_that(result, contains_string("Pushed"))


@pytest.mark.smoke
def test_git_push_protected_branch_denied(enforcer):
    tool = GitPushTool(enforcer, cwd="/repo")
    with pytest.raises(PermissionDenied, match="protected branch"):
        tool.run(branch="main")


@pytest.mark.smoke
def test_git_push_denied_by_profile(restricted_enforcer):
    tool = GitPushTool(restricted_enforcer, cwd="/repo")
    with pytest.raises(PermissionDenied):
        tool.run(branch="agent/c1/fix")


# ── GitCreatePRTool ───────────────────────────────────────────────────────────

@pytest.mark.smoke
def test_git_create_pr_success(enforcer):
    tool = GitCreatePRTool(enforcer, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed(
            0, stdout="https://github.com/owner/repo/pull/42\n"
        )
        result = tool.run(
            title="Add hello-world feature",
            body="## Summary\n- Added hello.py\n\n🤖 claude[bot]",
        )
    assert_that(result, contains_string("Pull request created"))
    assert_that(result, contains_string("github.com"))


@pytest.mark.smoke
def test_git_create_pr_failure(enforcer):
    tool = GitCreatePRTool(enforcer, cwd="/repo")
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        mock_run.return_value = _make_completed(
            1, stderr="no commits on branch"
        )
        result = tool.run(title="Bad PR", body="nothing")
    assert_that(result, starts_with("ERROR"))


@pytest.mark.smoke
def test_git_create_pr_uses_base_branch(enforcer):
    tool = GitCreatePRTool(enforcer, cwd="/repo")
    captured = []
    with patch("agents.kanban.agent.tools.git_tools.subprocess.run") as mock_run:
        def capture(*a, **kw):
            captured.append(a[0])
            return _make_completed(0, stdout="https://github.com/owner/repo/pull/99")
        mock_run.side_effect = capture
        tool.run(title="PR", body="body", base="develop")

    assert "--base" in captured[0]
    assert "develop" in captured[0]
