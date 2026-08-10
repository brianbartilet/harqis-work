"""
MCP bridge — exposes harqis-work app tools to kanban agents.

Imports the FastMCP tool registrations from each app's mcp.py directly
(no subprocess, no protocol overhead) and converts them into:
  - Anthropic tool definitions (JSON schema for Claude)
  - Python callables for the ToolRegistry

Security:
  The bridge accepts a *scoped_secrets* dict from the orchestrator.
  Before calling any MCP tool, it temporarily injects those secrets
  into os.environ so the underlying app configs can authenticate.
  The original environment is restored afterwards — secrets are never
  permanently added to the global env.

Usage in a profile:
    tools:
      mcp_apps:
        - google_apps
        - trello
        - discord
        - jira

Supported app keys map to the register_* functions in each apps/<app>/mcp.py.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any, Optional
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

from agents.projects.permissions.enforcer import PermissionDenied, PermissionEnforcer
from harqis_tools.catalog import APP_CATALOG, get_app_spec, register_app_tools

logger = logging.getLogger(__name__)


# Field names in MCP tool input schemas that we treat as network destinations.
# When present (and non-empty) in the runtime call inputs, the bridge extracts
# their hostname and invokes ``enforcer.check_network(host)`` before letting
# the tool run. This is how the H2 wiring mitigates the previously-decorative
# ``permissions.network.{allow,deny}`` settings.
_URL_INPUT_FIELDS: frozenset[str] = frozenset({
    "url",
    "uri",
    "endpoint",
})

# Backward-compatible lookup generated from the canonical shared catalog.
_APP_LOADERS: dict[str, str] = {spec.key: spec.registrar for spec in APP_CATALOG}


@contextlib.contextmanager
def _injected_env(secrets: dict[str, str]):
    """
    Context manager: temporarily set secrets in os.environ,
    restoring the original state on exit (even if an exception occurs).
    """
    prev = {}
    for k, v in secrets.items():
        prev[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        yield
    finally:
        for k, original in prev.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original


class McpBridge:
    """
    Loads MCP tool registrations from harqis-work apps and exposes them
    as Anthropic tool definitions + Python callables.
    """

    def __init__(
        self,
        app_keys: list[str],
        scoped_secrets: Optional[dict[str, str]] = None,
        enforcer: Optional[PermissionEnforcer] = None,
    ):
        self._mcp = FastMCP("kanban-agent-bridge")
        self._loaded_apps: list[str] = []
        self._tool_apps: dict[str, str] = {}
        self._scoped_secrets: dict[str, str] = scoped_secrets or {}
        self._enforcer = enforcer
        for key in app_keys:
            self._load_app(key)

    def _load_app(self, key: str) -> None:
        try:
            spec = get_app_spec(key)
        except KeyError:
            logger.warning("Unknown MCP app key: '%s' — skipping", key)
            return
        try:
            names = register_app_tools(self._mcp, spec)
            self._tool_apps.update({name: spec.key for name in names})
            self._loaded_apps.append(spec.key)
            logger.debug("Loaded MCP tools from: %s", spec.key)
        except Exception as e:
            logger.warning("Could not load MCP app '%s': %s", key, e)

    def definitions(self) -> list[dict]:
        """Return Anthropic-compatible tool definitions for all loaded tools."""
        defs = []
        for tool in self._mcp._tool_manager._tools.values():
            schema = dict(tool.parameters)
            schema.pop("title", None)   # Anthropic doesn't want the title field
            defs.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": schema,
            })
        return defs

    def definitions_with_apps(self) -> list[tuple[str, dict]]:
        """Return each definition paired with its authorizing app key."""
        return [
            (self._tool_apps[definition["name"]], definition)
            for definition in self.definitions()
        ]

    def _enforce_network(self, name: str, inputs: dict[str, Any]) -> None:
        """If the tool inputs include a URL-like field, run it through the
        profile's network ACL before allowing the call (H2). Tools without
        any URL/uri/endpoint argument are left untouched.
        """
        if self._enforcer is None:
            return
        for field in _URL_INPUT_FIELDS:
            value = inputs.get(field)
            if not isinstance(value, str) or not value:
                continue
            host = urlparse(value).hostname
            if not host:
                continue
            self._enforcer.check_network(host)
            logger.debug("MCP network check passed: tool=%s host=%s", name, host)

    def call(self, name: str, inputs: dict[str, Any]) -> Any:
        """
        Call a tool by name with given inputs.

        Injects scoped secrets into os.environ for the duration of the
        call, then restores the original environment. Before running the
        tool, applies the agent profile's network ACL (H2) for tools whose
        inputs include a URL-shaped field.
        """
        tool = self._mcp._tool_manager._tools.get(name)
        if not tool:
            return f"Unknown MCP tool: {name}"
        # Network ACL is enforced *before* secrets are injected, so a denied
        # destination can't capture credentials via a side-effect log.
        self._enforce_network(name, inputs)
        if self._enforcer is not None:
            self._enforcer.check_tool(name, app_key=self._tool_apps.get(name))
        try:
            with _injected_env(self._scoped_secrets):
                result = tool.fn(**inputs)
            return result
        except PermissionDenied:
            # Surface PermissionDenied unmodified so the agent loop can render
            # the standard PERMISSION DENIED tool_result.
            raise
        except Exception as e:
            logger.error("MCP tool '%s' error: %s", name, e)
            raise

    def tool_names(self) -> list[str]:
        return list(self._mcp._tool_manager._tools.keys())

    def app_for_tool(self, name: str) -> str | None:
        return self._tool_apps.get(name)

    @property
    def loaded_apps(self) -> list[str]:
        return list(self._loaded_apps)


def build_bridge(
    mcp_apps: list[str],
    scoped_secrets: Optional[dict[str, str]] = None,
    enforcer: Optional[PermissionEnforcer] = None,
) -> McpBridge | None:
    """Build an McpBridge from a list of app keys. Returns None if list is empty."""
    if not mcp_apps:
        return None
    return McpBridge(mcp_apps, scoped_secrets=scoped_secrets, enforcer=enforcer)
