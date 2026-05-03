"""
Tool registry — maps tool names to callables and builds the definitions
list expected by the Anthropic Messages API.

Tools are registered with:
  - A JSON schema (for Claude's tool-use protocol)
  - A Python callable that executes the tool
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from agents.projects.trello.client import TrelloClient
from agents.projects.trello.models import KanbanCard
from agents.projects.permissions.enforcer import PermissionEnforcer
from agents.projects.profiles.schema import AgentProfile

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(
        self,
        profile: AgentProfile,
        card: KanbanCard,
        provider: TrelloClient,
        enforcer: PermissionEnforcer,
        scoped_secrets: Optional[dict[str, str]] = None,
        save_state_fn: Optional[Callable[[], None]] = None,
    ):
        self._tools: dict[str, dict] = {}       # name → {schema, fn}
        self._profile = profile
        self._card = card
        self._provider = provider
        self._enforcer = enforcer
        self._scoped_secrets = scoped_secrets or {}
        # Wired by BaseKanbanAgent so the AskHumanTool can persist message
        # history before pausing when REMEMBER_LABEL is on the card.
        self._save_state_fn = save_state_fn
        self._mcp_bridge = None
        self._register_defaults()
        self._register_integrations()
        self._register_mcp_tools()

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, name: str, description: str, schema: dict, fn: Callable) -> None:
        """Register a tool. Schema is the Anthropic input_schema object."""
        self._tools[name] = {
            "definition": {
                "name": name,
                "description": description,
                "input_schema": schema,
            },
            "fn": fn,
        }

    def _register_integrations(self) -> None:
        """Register opt-in integration tools that depend on profile config +
        env-var presence at the workspace level. Currently: Discord post tool.
        """
        discord_allowlist = self._profile.integrations.discord.allowed_channels
        if not discord_allowlist:
            return  # Profile didn't opt in.
        from agents.projects.integrations.discord import DiscordClient
        client = DiscordClient.from_env()
        if client is None:
            logger.info(
                "Profile %s declares Discord channels %s but DISCORD_BOT_TOKEN/"
                "DISCORD_GUILD_ID are not set — discord_post will not be registered.",
                self._profile.id, discord_allowlist,
            )
            return
        from agents.projects.agent.tools.discord_tool import DiscordPostTool
        tool = DiscordPostTool(client, self._profile)
        self.register(tool.name, tool.description, tool.input_schema, tool.run)
        logger.info(
            "Registered discord_post for profile %s (channels=%s)",
            self._profile.id, discord_allowlist,
        )

    def _register_mcp_tools(self) -> None:
        mcp_apps = self._profile.tools.mcp_apps
        if not mcp_apps:
            return
        from agents.projects.agent.tools.mcp_bridge import build_bridge
        self._mcp_bridge = build_bridge(mcp_apps, scoped_secrets=self._scoped_secrets)
        if self._mcp_bridge:
            logger.debug(
                "MCP bridge loaded apps: %s (%d tools)",
                self._mcp_bridge.loaded_apps,
                len(self._mcp_bridge.tool_names()),
            )

    def _register_defaults(self) -> None:
        from agents.projects.agent.tools.filesystem import (
            BashTool, GlobTool, GrepTool, ReadFileTool, WriteFileTool,
        )
        from agents.projects.agent.tools.git_tools import (
            GitCommitTool, GitCreateBranchTool, GitCreatePRTool,
            GitPushTool, GitStatusTool,
        )
        from agents.projects.agent.tools.kanban_tools import (
            AskHumanTool, ChecklistTool, TrelloCommentTool, TrelloMoveTool,
        )

        working_dir = self._profile.context.working_directory or None
        git_config = self._profile.permissions.git

        for tool_cls in (
            ReadFileTool(self._enforcer),
            WriteFileTool(self._enforcer),
            GlobTool(self._enforcer),
            GrepTool(self._enforcer),
            BashTool(self._enforcer, cwd=working_dir),
            GitStatusTool(self._enforcer, cwd=working_dir),
            GitCreateBranchTool(self._enforcer, cwd=working_dir),
            GitCommitTool(self._enforcer, git_config=git_config, cwd=working_dir),
            GitPushTool(self._enforcer, git_config=git_config, cwd=working_dir),
            GitCreatePRTool(self._enforcer, cwd=working_dir),
            TrelloCommentTool(self._provider, self._card.id),
            TrelloMoveTool(self._provider, self._card.id),
            ChecklistTool(self._provider, self._card.id, self._card.checklists),
            AskHumanTool(
                self._provider,
                self._card.id,
                self._card.labels,
                save_state_fn=self._save_state_fn,
            ),
        ):
            self.register(
                tool_cls.name,
                tool_cls.description,
                tool_cls.input_schema,
                tool_cls.run,
            )

    # ── Execution ─────────────────────────────────────────────────────────────

    def call(self, name: str, inputs: dict[str, Any]) -> Any:
        # Check native tools first, then MCP bridge
        tool = self._tools.get(name)
        if tool:
            try:
                return tool["fn"](**inputs)
            except Exception as e:
                logger.error("Tool '%s' raised: %s", name, e)
                raise
        if self._mcp_bridge and name in self._mcp_bridge.tool_names():
            return self._mcp_bridge.call(name, inputs)
        return f"Unknown tool: {name}"

    # ── Definitions for Claude API ────────────────────────────────────────────

    def definitions(self) -> list[dict]:
        """Return tool definitions filtered to the profile's allowed/denied lists."""
        allowed = self._profile.tools.allowed
        denied = self._profile.tools.denied

        result = []

        # Native tools
        for name, tool in self._tools.items():
            if name in denied:
                continue
            if allowed and name not in allowed:
                continue
            result.append(tool["definition"])

        # MCP tools — added on top; denied list still applies
        if self._mcp_bridge:
            for defn in self._mcp_bridge.definitions():
                name = defn["name"]
                if name in denied:
                    continue
                # MCP tools are included unless explicitly denied
                # (allowed list only restricts native tools when set)
                result.append(defn)

        return result
