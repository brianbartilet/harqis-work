"""
BaseKanbanAgent — Claude tool-use loop.

Runs the agent until the model emits a final text response (stop_reason == "end_turn")
or until a timeout/error occurs. All tool calls are permission-checked before execution.

Security:
  - Accepts a *scoped* secrets dict (not the full env) from the orchestrator.
  - Passes scoped env vars to MCP tools so they can authenticate.
  - Sanitizes all output before posting to Kanban comments.
  - Records every tool call and permission event to the audit log.
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
from agents.kanban.security.audit import AuditLogger, NullAuditLogger
from agents.kanban.security.sanitizer import OutputSanitizer
from agents.prompts import load_prompt

logger = logging.getLogger(__name__)

# Default system prompt loaded from agents/prompts/kanban_agent_default.md
# Edit that file to change agent behaviour — do not hardcode prompts here.
def _load_default_system() -> str:
    try:
        return load_prompt("kanban_agent_default")
    except FileNotFoundError:
        # Fallback if prompt file is missing (e.g. during tests with isolated imports)
        return (
            "You are {name}, an AI agent operating in a Kanban-driven workflow.\n"
            "Complete the task using the tools available. "
            "Your final message should summarise what you did and the result."
        )


class BaseKanbanAgent:
    """
    Runs a Claude tool-use loop for one Kanban card.

    Usage:
        agent = BaseKanbanAgent(profile, card, provider, api_key, scoped_secrets)
        result = agent.run()   # returns the agent's final text output
    """

    def __init__(
        self,
        profile: AgentProfile,
        card: KanbanCard,
        provider: KanbanProvider,
        api_key: str,
        scoped_secrets: Optional[dict[str, str]] = None,
        audit: Optional[AuditLogger] = None,
    ):
        self.profile = profile
        self.card = card
        self.provider = provider
        self._scoped_secrets = scoped_secrets or {}
        self._audit = audit or NullAuditLogger()
        self._sanitizer = OutputSanitizer(self._scoped_secrets)
        self.client = anthropic.Anthropic(api_key=api_key)
        self.enforcer = PermissionEnforcer(profile)
        self.registry = ToolRegistry(
            profile=profile,
            card=card,
            provider=provider,
            enforcer=self.enforcer,
            scoped_secrets=self._scoped_secrets,
        )

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self) -> str:
        """Execute the agent loop. Returns the final text output."""
        ctx = build_card_context(
            self.card,
            working_directory=self.profile.context.working_directory or None,
        )
        messages: list[dict] = [{"role": "user", "content": ctx.to_prompt()}]
        tools = self.registry.definitions()
        system = self._system_prompt()

        logger.info("[%s] Starting for card %s: %s", self.profile.id, self.card.id, self.card.title)
        self._audit.agent_start(self.card.title)

        iteration = 0
        max_iterations = 50

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
            try:
                response = self.client.messages.create(**kwargs)
            except anthropic.BadRequestError as e:
                msg = str(e)
                logger.warning("[%s] BadRequestError: %s", self.profile.id, msg)
                self._audit.agent_finish(success=False, iterations=iteration, detail=msg)
                return f"ERROR: Request blocked by API — {msg}"
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                text = self._extract_text(response)
                safe_text = self._sanitizer.scrub(text)
                self._audit.agent_finish(success=True, iterations=iteration)
                return safe_text

            if response.stop_reason != "tool_use":
                logger.warning(
                    "[%s] Unexpected stop_reason: %s", self.profile.id, response.stop_reason
                )
                text = self._extract_text(response)
                safe_text = self._sanitizer.scrub(text)
                self._audit.agent_finish(success=True, iterations=iteration)
                return safe_text

            # Process tool calls
            tool_results = self._handle_tool_calls(response.content)
            messages.append({"role": "user", "content": tool_results})

        logger.error("[%s] Hit max iterations (%d)", self.profile.id, max_iterations)
        self._audit.agent_finish(success=False, iterations=max_iterations, detail="max iterations exceeded")
        return "ERROR: Agent exceeded maximum iteration limit."

    # ── Internal ──────────────────────────────────────────────────────────────

    def _system_prompt(self) -> str:
        prompt = self.profile.model.resolved_system_prompt()
        if not prompt:
            prompt = _load_default_system().format(name=self.profile.name)
        # Inject profile context
        if self.profile.context.working_directory:
            prompt += f"\n\nWorking directory: {self.profile.context.working_directory}"
        if self.profile.context.repos:
            repo_list = "\n".join(
                f"  - {r.url} → {r.local_path} ({r.branch_policy})"
                for r in self.profile.context.repos
            )
            prompt += f"\n\nRepositories:\n{repo_list}"
        # Inject the actual tool list so the agent knows exactly what it has
        prompt += self._tool_inventory_prompt()
        return prompt

    def _tool_inventory_prompt(self) -> str:
        """
        Build a section listing every tool available to this agent.

        This prevents the agent from falling back on training-time assumptions
        about what tools it does or doesn't have access to.
        """
        definitions = self.registry.definitions()
        if not definitions:
            return ""
        names = [d["name"] for d in definitions]
        lines = "\n".join(f"  - {n}" for n in sorted(names))
        return (
            f"\n\n## Your available tools\n"
            f"You have exactly these tools — use them; do not assume you lack access to any service listed here:\n"
            f"{lines}"
        )

    def _handle_tool_calls(self, content: list) -> list[dict]:
        results: list[dict] = []
        for block in content:
            if getattr(block, "type", None) != "tool_use":
                continue
            tool_name = block.name
            tool_input = block.input
            logger.debug("[%s] Tool: %s(%s)", self.profile.id, tool_name, tool_input)
            self._audit.tool_call(tool_name, tool_input)

            try:
                self.enforcer.check_tool(tool_name)
                self._audit.permission_check("tool", tool_name, allowed=True)
                output = self.registry.call(tool_name, tool_input)
                safe_output = self._sanitizer.scrub(str(output))
                safe_output = _truncate_tool_output(safe_output, tool_name)
                self._audit.tool_result(tool_name, success=True)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": safe_output,
                })
            except PermissionDenied as e:
                logger.warning("[%s] Permission denied: %s", self.profile.id, e)
                self._audit.permission_check("tool", tool_name, allowed=False, reason=str(e))
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"PERMISSION DENIED: {e}",
                    "is_error": True,
                })
            except Exception as e:
                logger.error("[%s] Tool error '%s': %s", self.profile.id, tool_name, e)
                self._audit.tool_result(tool_name, success=False, detail=str(e))
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


# ── Tool output truncation ────────────────────────────────────────────────────

# ~4 chars per token; keep well under the 1M token context limit.
# bash output is the main offender (pytest, git log, large file reads).
_MAX_TOOL_OUTPUT_CHARS = 40_000   # ~10K tokens per tool result
_TRUNCATION_MSG = "\n\n[... output truncated to {kept} chars — {dropped} chars dropped ...]"


def _truncate_tool_output(text: str, tool_name: str) -> str:
    """
    Cap individual tool output at _MAX_TOOL_OUTPUT_CHARS.

    For bash/grep/read_file results that can be enormous (full pytest
    output, large files), this prevents context window overflow across
    many iterations.  The tail of the output is kept because errors
    and summaries typically appear last.
    """
    if len(text) <= _MAX_TOOL_OUTPUT_CHARS:
        return text
    kept = _MAX_TOOL_OUTPUT_CHARS
    dropped = len(text) - kept
    # Keep the tail — errors/summaries are usually at the end
    truncated = text[-kept:]
    note = _TRUNCATION_MSG.format(kept=kept, dropped=dropped)
    logger.warning(
        "Tool '%s' output truncated: %d → %d chars (%d dropped)",
        tool_name, len(text), kept, dropped,
    )
    return note + truncated
