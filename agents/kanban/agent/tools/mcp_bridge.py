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

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

# Maps profile mcp_apps key → register function import path
_APP_LOADERS: dict[str, str] = {
    "google_apps": "apps.google_apps.mcp.register_google_apps_tools",
    "trello":      "apps.trello.mcp.register_trello_tools",
    "airtable":    "apps.airtable.mcp.register_airtable_tools",
    "browser":     "apps.browser.mcp.register_browser_tools",
    "discord":     "apps.discord.mcp.register_discord_tools",
    "echo_mtg":    "apps.echo_mtg.mcp.register_echo_mtg_tools",
    "filesystem":  "apps.filesystem.mcp.register_filesystem_tools",
    "gemini":      "apps.gemini.mcp.register_gemini_tools",
    "git":         "apps.git.mcp.register_git_tools",
    "github":      "apps.github.mcp.register_github_tools",
    "google_apps": "apps.google_apps.mcp.register_google_apps_tools",
    "google_drive":"apps.google_drive.mcp.register_google_drive_tools",
    "grok":        "apps.grok.mcp.register_grok_tools",
    "jira":        "apps.jira.mcp.register_jira_tools",
    "linkedin":    "apps.linkedin.mcp.register_linkedin_tools",
    "notion":      "apps.notion.mcp.register_notion_tools",
    "oanda":       "apps.oanda.mcp.register_oanda_tools",
    "open_ai":     "apps.open_ai.mcp.register_open_ai_tools",
    "orgo":        "apps.orgo.mcp.register_orgo_tools",
    "own_tracks":  "apps.own_tracks.mcp.register_own_tracks_tools",
    "perplexity":  "apps.perplexity.mcp.register_perplexity_tools",
    "playwright":  "apps.playwright.mcp.register_playwright_tools",
    "reddit":      "apps.reddit.mcp.register_reddit_tools",
    "scryfall":    "apps.scryfall.mcp.register_scryfall_tools",
    "tcg_mp":      "apps.tcg_mp.mcp.register_tcg_mp_tools",
    "telegram":    "apps.telegram.mcp.register_telegram_tools",
    "trello":      "apps.trello.mcp.register_trello_tools",
    "ynab":        "apps.ynab.mcp.register_ynab_tools",
}


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

    def __init__(self, app_keys: list[str], scoped_secrets: Optional[dict[str, str]] = None):
        self._mcp = FastMCP("kanban-agent-bridge")
        self._loaded_apps: list[str] = []
        self._scoped_secrets: dict[str, str] = scoped_secrets or {}
        for key in app_keys:
            self._load_app(key)

    def _load_app(self, key: str) -> None:
        loader_path = _APP_LOADERS.get(key)
        if not loader_path:
            logger.warning("Unknown MCP app key: '%s' — skipping", key)
            return
        try:
            module_path, fn_name = loader_path.rsplit(".", 1)
            import importlib
            module = importlib.import_module(module_path)
            register_fn = getattr(module, fn_name)
            register_fn(self._mcp)
            self._loaded_apps.append(key)
            logger.debug("Loaded MCP tools from: %s", key)
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

    def call(self, name: str, inputs: dict[str, Any]) -> Any:
        """
        Call a tool by name with given inputs.

        Injects scoped secrets into os.environ for the duration of the
        call, then restores the original environment.
        """
        tool = self._mcp._tool_manager._tools.get(name)
        if not tool:
            return f"Unknown MCP tool: {name}"
        try:
            with _injected_env(self._scoped_secrets):
                result = tool.fn(**inputs)
            return result
        except Exception as e:
            logger.error("MCP tool '%s' error: %s", name, e)
            raise

    def tool_names(self) -> list[str]:
        return list(self._mcp._tool_manager._tools.keys())

    @property
    def loaded_apps(self) -> list[str]:
        return list(self._loaded_apps)


def build_bridge(
    mcp_apps: list[str],
    scoped_secrets: Optional[dict[str, str]] = None,
) -> McpBridge | None:
    """Build an McpBridge from a list of app keys. Returns None if list is empty."""
    if not mcp_apps:
        return None
    return McpBridge(mcp_apps, scoped_secrets=scoped_secrets)
