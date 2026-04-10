"""
BaseKanbanAgent — Claude tool-use loop.

Runs the agent until the model emits a final text response (stop_reason == "end_turn")
or until a timeout/error occurs. All tool calls are permission-checked before execution.
"""

from __future__ import annotations

import logging
from typing import Optional

import anthropic

from agents.kanban.agent.context import build_card_context
from agents.kanban.agent.tools.registry import ToolRegistry
from agents.kanban.interface import KanbanCard, KanbanProvider
from agents.kanban.permissions.enforcer import PermissionDenied, PermissionEnforcer
from agents.kanban.profiles.schema import AgentProfile

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM = (
    "You are {name}, an AI agent operating in a Kanban-driven workflow.\n\n"
    "Complete the task described below using the tools available to you.\n"
    "Work methodically: read context, plan steps, execute, verify.\n\n"
    "Guidelines:\n"
    "- If you cannot complete a step, explain why clearly — do not guess.\n"
    "- Post a progress comment when starting a long sub-task.\n"
    "- Check off checklist items as you complete them.\n"
    "- Your final message should be a clear summary of what you did and the result.\n"
)


class BaseKanbanAgent:
    """
    Runs a Claude tool-use loop for one Kanban card.

    Usage:
        agent = BaseKanbanAgent(profile, card, provider, api_key)
        result = agent.run()   # returns the agent's final text output
    """

    def __init__(
        self,
        profile: AgentProfile,
        card: KanbanCard,
        provider: KanbanProvider,
        api_key: str,
    ):
        self.profile = profile
        self.card = card
        self.provider = provider
        self.client = anthropic.Anthropic(api_key=api_key)
        self.enforcer = PermissionEnforcer(profile)
        self.registry = ToolRegistry(
            profile=profile,
            card=card,
            provider=provider,
            enforcer=self.enforcer,
        )

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self) -> str:
        """Execute the agent loop. Returns the final text output."""
        ctx = build_card_context(self.card)
        messages: list[dict] = [{"role": "user", "content": ctx.to_prompt()}]
        tools = self.registry.definitions()
        system = self._system_prompt()

        logger.info("[%s] Starting for card %s: %s", self.profile.id, self.card.id, self.card.title)

        iteration = 0
        max_iterations = 30  # hard safety cap

        while iteration < max_iterations:
            iteration += 1

            kwargs: dict = {
                "model": self.profile.model.model_id,
                "max_tokens": self.profile.model.max_tokens,
                "system": system,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools

            logger.debug("[%s] Calling Claude (iteration %d)", self.profile.id, iteration)
            response = self.client.messages.create(**kwargs)
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                return self._extract_text(response)

            if response.stop_reason != "tool_use":
                logger.warning(
                    "[%s] Unexpected stop_reason: %s", self.profile.id, response.stop_reason
                )
                return self._extract_text(response)

            # Process tool calls
            tool_results = self._handle_tool_calls(response.content)
            messages.append({"role": "user", "content": tool_results})

        logger.error("[%s] Hit max iterations (%d)", self.profile.id, max_iterations)
        return "ERROR: Agent exceeded maximum iteration limit."

    # ── Internal ──────────────────────────────────────────────────────────────

    def _system_prompt(self) -> str:
        prompt = self.profile.model.resolved_system_prompt()
        if not prompt:
            prompt = _DEFAULT_SYSTEM.format(name=self.profile.name)
        # Inject profile context
        if self.profile.context.working_directory:
            prompt += f"\n\nWorking directory: {self.profile.context.working_directory}"
        if self.profile.context.repos:
            repo_list = "\n".join(
                f"  - {r.url} → {r.local_path} ({r.branch_policy})"
                for r in self.profile.context.repos
            )
            prompt += f"\n\nRepositories:\n{repo_list}"
        return prompt

    def _handle_tool_calls(self, content: list) -> list[dict]:
        results: list[dict] = []
        for block in content:
            if getattr(block, "type", None) != "tool_use":
                continue
            tool_name = block.name
            tool_input = block.input
            logger.debug("[%s] Tool: %s(%s)", self.profile.id, tool_name, tool_input)

            try:
                self.enforcer.check_tool(tool_name)
                output = self.registry.call(tool_name, tool_input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })
            except PermissionDenied as e:
                logger.warning("[%s] Permission denied: %s", self.profile.id, e)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"PERMISSION DENIED: {e}",
                    "is_error": True,
                })
            except Exception as e:
                logger.error("[%s] Tool error '%s': %s", self.profile.id, tool_name, e)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"ERROR: {e}",
                    "is_error": True,
                })
        return results

    @staticmethod
    def _extract_text(response) -> str:
        for block in response.content:
            if hasattr(block, "text"):
                return block.text
        return ""
