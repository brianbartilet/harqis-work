"""
Tests for PermissionEnforcer.
"""

import sys
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to, contains_string

from agents.kanban.permissions.enforcer import PermissionDenied, PermissionEnforcer


@pytest.mark.smoke
def test_open_profile_allows_all_tools(open_profile):
    enforcer = PermissionEnforcer(open_profile)
    # No exception = allowed
    enforcer.check_tool("bash")
    enforcer.check_tool("read_file")
    enforcer.check_tool("anything")


@pytest.mark.smoke
def test_restricted_profile_denies_bash(restricted_profile):
    enforcer = PermissionEnforcer(restricted_profile)
    with pytest.raises(PermissionDenied) as exc_info:
        enforcer.check_tool("bash")
    assert_that(str(exc_info.value), contains_string("denied"))


@pytest.mark.smoke
def test_restricted_profile_allows_read_file(restricted_profile):
    enforcer = PermissionEnforcer(restricted_profile)
    enforcer.check_tool("read_file")  # must not raise


@pytest.mark.smoke
def test_restricted_profile_denies_unknown_tool(restricted_profile):
    enforcer = PermissionEnforcer(restricted_profile)
    with pytest.raises(PermissionDenied):
        enforcer.check_tool("some_new_tool")


@pytest.mark.smoke
def test_filesystem_allow_list(restricted_profile, tmp_path):
    enforcer = PermissionEnforcer(restricted_profile)
    # tmp_path is in allow list — should pass
    enforcer.check_filesystem(str(tmp_path / "output.txt"))


@pytest.mark.smoke
def test_filesystem_deny_list(restricted_profile, tmp_path):
    enforcer = PermissionEnforcer(restricted_profile)
    with pytest.raises(PermissionDenied):
        enforcer.check_filesystem(str(tmp_path / "secrets" / "api_key.txt"))


@pytest.mark.smoke
def test_filesystem_not_in_allow_list(restricted_profile, tmp_path):
    enforcer = PermissionEnforcer(restricted_profile)
    outside = str(tmp_path.parent.parent / "other_dir" / "file.txt")
    with pytest.raises(PermissionDenied):
        enforcer.check_filesystem(outside)


@pytest.mark.smoke
def test_network_allowed_host(restricted_profile):
    enforcer = PermissionEnforcer(restricted_profile)
    enforcer.check_network("api.anthropic.com")  # must not raise


@pytest.mark.smoke
def test_network_denied_host(restricted_profile):
    enforcer = PermissionEnforcer(restricted_profile)
    with pytest.raises(PermissionDenied):
        enforcer.check_network("evil.example.com")


@pytest.mark.smoke
def test_git_push_denied_when_can_push_false(restricted_profile):
    enforcer = PermissionEnforcer(restricted_profile)
    with pytest.raises(PermissionDenied) as exc_info:
        enforcer.check_git_push("feature/my-feature")
    assert_that(str(exc_info.value), contains_string("disabled"))


@pytest.mark.smoke
def test_git_push_protected_branch(open_profile):
    open_profile.permissions.git.can_push = True
    open_profile.permissions.git.protected_branches = ["main", "prod"]
    enforcer = PermissionEnforcer(open_profile)

    with pytest.raises(PermissionDenied) as exc_info:
        enforcer.check_git_push("main")
    assert_that(str(exc_info.value), contains_string("protected"))


@pytest.mark.smoke
def test_git_push_allowed_branch(open_profile):
    open_profile.permissions.git.can_push = True
    open_profile.permissions.git.protected_branches = ["main"]
    enforcer = PermissionEnforcer(open_profile)
    enforcer.check_git_push("feature/new-thing")  # must not raise


@pytest.mark.smoke
def test_open_profile_no_filesystem_restrictions(open_profile):
    enforcer = PermissionEnforcer(open_profile)
    # No allow/deny configured — all paths allowed
    enforcer.check_filesystem("/any/path/at/all")


@pytest.mark.smoke
def test_open_profile_no_network_restrictions(open_profile):
    enforcer = PermissionEnforcer(open_profile)
    enforcer.check_network("example.com")
    enforcer.check_network("api.openai.com")
