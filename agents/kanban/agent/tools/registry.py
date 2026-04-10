"""
Tool registry — maps tool names to callables and builds the definitions
list expected by the Anthropic Messages API.

Tools are registered with:
  - A JSON schema (for Claude's tool-use protocol)
  - A Python callable that executes the tool
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from agents.kanban.interface import KanbanCard, KanbanProvider
from agents.kanban.permissions.enforcer import PermissionEnforcer
from agents.kanban.profiles.schema import AgentProfile

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(
        self,
        profile: AgentProfile,
        card: KanbanCard,
        provider: KanbanProvider,
        enforcer: PermissionEnforcer,
    ):
        self._tools: dict[str, dict] = {}       # name → {schema, fn}
        self._profile = profile
        self._card = card
        self._provider = provider
        self._enforcer = enforcer
        self._register_defaults()

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

    def _register_defaults(self) -> None:
        from agents.kanban.agent.tools.filesystem import (
            BashTool, GlobTool, GrepTool, ReadFileTool, WriteFileTool,
        )
        from agents.kanban.agent.tools.kanban_tools import (
            ChecklistTool, TrelloCommentTool, TrelloMoveTool,
        )

        working_dir = self._profile.context.working_directory or None

        for tool_cls in (
            ReadFileTool(self._enforcer),
            WriteFileTool(self._enforcer),
            GlobTool(self._enforcer),
            GrepTool(self._enforcer),
            BashTool(self._enforcer, cwd=working_dir),
            TrelloCommentTool(self._provider, self._card.id),
            TrelloMoveTool(self._provider, self._card.id),
            ChecklistTool(self._provider, self._card.id, self._card.checklists),
        ):
            self.register(
                tool_cls.name,
                tool_cls.description,
                tool_cls.input_schema,
                tool_cls.run,
            )

    # ── Execution ─────────────────────────────────────────────────────────────

    def call(self, name: str, inputs: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return f"Unknown tool: {name}"
        try:
            result = tool["fn"](**inputs)
            return result
        except Exception as e:
            logger.error("Tool '%s' raised: %s", name, e)
            raise

    # ── Definitions for Claude API ────────────────────────────────────────────

    def definitions(self) -> list[dict]:
        """Return tool definitions filtered to the profile's allowed/denied lists."""
        allowed = self._profile.tools.allowed
        denied = self._profile.tools.denied
        result = []
        for name, tool in self._tools.items():
            if name in denied:
                continue
            if allowed and name not in allowed:
                continue
            result.append(tool["definition"])
        return result
