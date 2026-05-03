"""
Permission enforcer — checks all tool calls against the agent profile's
permission declarations before execution.

Raises PermissionDenied (which the agent loop catches and reports on the card)
rather than silently skipping — this makes denials visible and debuggable.
"""

import fnmatch
import logging
from pathlib import Path

from agents.projects.profiles.schema import AgentProfile

logger = logging.getLogger(__name__)


class PermissionDenied(Exception):
    """Raised when an agent attempts an action outside its declared permissions."""


class PermissionEnforcer:
    def __init__(self, profile: AgentProfile):
        self.profile = profile

    # ── Tool access ───────────────────────────────────────────────────────────

    def check_tool(self, tool_name: str) -> None:
        t = self.profile.tools
        if tool_name in t.denied:
            raise PermissionDenied(
                f"Tool '{tool_name}' is explicitly denied by profile '{self.profile.id}'"
            )
        if t.allowed and tool_name not in t.allowed:
            raise PermissionDenied(
                f"Tool '{tool_name}' is not in the allowed list for profile '{self.profile.id}'"
            )
        logger.debug("[%s] tool allowed: %s", self.profile.id, tool_name)

    # ── Filesystem access ─────────────────────────────────────────────────────

    def check_filesystem(self, path: str) -> None:
        fs = self.profile.permissions.filesystem
        if not fs.allow and not fs.deny:
            return  # no filesystem restrictions declared

        # Normalize to forward slashes for cross-platform fnmatch compatibility
        normalized = _norm_path(str(Path(path).resolve()))

        # Deny list checked first
        for pattern in fs.deny:
            norm_pat = _norm_pattern(pattern)
            if fnmatch.fnmatch(normalized, norm_pat):
                raise PermissionDenied(
                    f"Filesystem path '{normalized}' matches deny pattern '{pattern}'"
                )

        # Allow list — must match at least one
        if fs.allow:
            for pattern in fs.allow:
                norm_pat = _norm_pattern(pattern)
                if fnmatch.fnmatch(normalized, norm_pat):
                    logger.debug("[%s] fs allowed: %s", self.profile.id, normalized)
                    return
            raise PermissionDenied(
                f"Filesystem path '{normalized}' is not in the allow list for profile '{self.profile.id}'"
            )

    # ── Network access ────────────────────────────────────────────────────────

    def check_network(self, host: str) -> None:
        net = self.profile.permissions.network
        if not net.allow and not net.deny:
            return  # no network restrictions declared

        # If deny contains "*", check allow list first (allow overrides deny-all)
        for deny_pattern in net.deny:
            if deny_pattern == "*" or fnmatch.fnmatch(host, deny_pattern):
                # See if it's explicitly allowed
                for allow_pattern in net.allow:
                    if fnmatch.fnmatch(host, allow_pattern):
                        logger.debug("[%s] network allowed: %s", self.profile.id, host)
                        return
                raise PermissionDenied(
                    f"Network host '{host}' matches deny pattern '{deny_pattern}'"
                )

        if net.allow:
            for pattern in net.allow:
                if fnmatch.fnmatch(host, pattern):
                    logger.debug("[%s] network allowed: %s", self.profile.id, host)
                    return
            raise PermissionDenied(
                f"Network host '{host}' is not in the allow list for profile '{self.profile.id}'"
            )

    # ── Git operations ────────────────────────────────────────────────────────

    def check_git_push(self, branch: str) -> None:
        git = self.profile.permissions.git
        if not git.can_push:
            raise PermissionDenied(
                f"Git push is disabled for profile '{self.profile.id}'"
            )
        if branch in git.protected_branches:
            raise PermissionDenied(
                f"Push to protected branch '{branch}' denied for profile '{self.profile.id}'"
            )
        logger.debug("[%s] git push allowed: %s", self.profile.id, branch)

    def check_git_read(self, path: str) -> None:
        # Git read (clone, fetch) is always allowed if network is allowed
        self.check_filesystem(path)


def _is_glob(pattern: str) -> bool:
    return any(c in pattern for c in ("*", "?", "["))


def _norm_path(path: str) -> str:
    """Normalize a resolved path to forward slashes for cross-platform fnmatch."""
    return path.replace("\\", "/")


def _norm_pattern(pattern: str) -> str:
    """Normalize a pattern for cross-platform fnmatch.

    - Glob patterns: just normalize slashes (don't resolve — ** would be treated as a dir).
    - Non-glob patterns: resolve, then normalize slashes.
    """
    if _is_glob(pattern):
        return pattern.replace("\\", "/")
    return _norm_path(str(Path(pattern).resolve()))
