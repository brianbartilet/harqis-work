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
from agents.kanban.agent.question import (
    AgentPausedForQuestion,
    REMEMBER_LABEL,
    serialize_state,
)
from agents.kanban.agent.tools.registry import ToolRegistry
from agents.kanban.interface import KanbanCard, KanbanProvider
from agents.kanban.permissions.enforcer import PermissionDenied, PermissionEnforcer
from agents.kanban.profiles.schema import AgentProfile
from agents.kanban.security.audit import AuditLogger, NullAuditLogger
from agents.kanban.security.sanitizer import OutputSanitizer
from agents.prompts import load_prompt

logger = logging.getLogger(__name__)


class AgentExecutionError(Exception):
    """Raised when the agent cannot complete a card and the orchestrator should
    move it to the Failed column.

    The orchestrator's `_handle_error` checks for this exception type and posts
    a clean failure comment (no traceback noise) before moving the card.

    Attributes:
        kind: A short stable identifier for the failure category. Used by the
              audit log and the comment header.
              Known values:
                - 'api_usage_limit'  — Anthropic returned a usage/credit/quota error
                                       (e.g. 400 with "You have reached your specified
                                       API usage limits"). Do NOT retry.
                - 'api_rate_limit'   — Anthropic returned 429. Transient; manual re-queue ok.
                - 'api_error'        — Other 4xx/5xx from Anthropic.
                - 'general'          — Catch-all.
    """

    def __init__(self, message: str, *, kind: str = "general"):
        self.kind = kind
        super().__init__(message)


# Substrings (lowercased) that indicate an Anthropic 400 is actually a hard usage
# limit and not a transient bad request. When matched, `kind` is set to
# 'api_usage_limit' so the orchestrator can surface the expected unblock time.
_USAGE_LIMIT_PATTERNS = (
    "usage limit",
    "credit balance",
    "monthly spend limit",
    "quota",
)


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
        prior_messages: Optional[list[dict]] = None,
        prior_iteration: int = 0,
        resume_user_message: Optional[str] = None,
    ):
        """
        Args:
            prior_messages:       Previously persisted message history (stateful
                                  resume — REMEMBER_LABEL). When provided, the
                                  run loop skips building fresh context and
                                  starts from this list.
            prior_iteration:      Iteration counter to resume from. Capped under
                                  the same max_iterations budget; a card that
                                  paused at iteration 30 can only run 20 more
                                  before hitting the cap.
            resume_user_message:  Text to append as a user-role message before
                                  the next Claude call. Used by both stateless
                                  resume (recap prompt) and stateful resume
                                  (the human's reply text).
        """
        self.profile = profile
        self.card = card
        self.provider = provider
        self._scoped_secrets = scoped_secrets or {}
        self._audit = audit or NullAuditLogger()
        self._sanitizer = OutputSanitizer(self._scoped_secrets)
        self.client = anthropic.Anthropic(api_key=api_key)
        self.enforcer = PermissionEnforcer(profile)
        self._prior_messages = prior_messages
        self._prior_iteration = prior_iteration
        self._resume_user_message = resume_user_message
        # Mutable state used by the AskHumanTool callback. Updated each loop
        # iteration so a pause captures the most recent message list.
        self._current_messages: list[dict] = []
        self._current_iteration: int = 0
        self.registry = ToolRegistry(
            profile=profile,
            card=card,
            provider=provider,
            enforcer=self.enforcer,
            scoped_secrets=self._scoped_secrets,
            save_state_fn=self._save_state_for_pause,
        )

    # ── Public ────────────────────────────────────────────────────────────────

    def run(self) -> str:
        """Execute the agent loop. Returns the final text output.

        Raises:
            AgentPausedForQuestion: when the agent calls `ask_human` to wait
                for a human reply. The orchestrator catches this and leaves
                the card in `In Progress` until a reply arrives. Comment +
                label have already been posted by the tool before this is
                raised; no further state changes happen here.
            AgentExecutionError: any unrecoverable Claude API failure.
        """
        tools = self.registry.definitions()
        system = self._system_prompt()

        # Stateful resume — caller passed previously persisted message history.
        # Otherwise build fresh context from the card.
        if self._prior_messages is not None:
            messages: list[dict] = list(self._prior_messages)
            logger.info(
                "[%s] Resuming card %s from prior history (%d messages, iteration %d)",
                self.profile.id, self.card.id, len(messages), self._prior_iteration,
            )
        else:
            ctx = build_card_context(
                self.card,
                working_directory=self.profile.context.working_directory or None,
            )
            messages = [{"role": "user", "content": ctx.to_prompt()}]
            logger.info(
                "[%s] Starting for card %s: %s",
                self.profile.id, self.card.id, self.card.title,
            )

        # Append the resume cue (recap prompt for stateless mode, human reply
        # text for stateful mode) so the model sees it on the next turn.
        if self._resume_user_message:
            messages.append({"role": "user", "content": self._resume_user_message})

        self._audit.agent_start(self.card.title)

        iteration = self._prior_iteration
        max_iterations = 50

        while iteration < max_iterations:
            iteration += 1
            # Track the live state so the AskHumanTool callback can serialise
            # exactly the messages-so-far if the model decides to pause.
            self._current_messages = messages
            self._current_iteration = iteration

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
            except anthropic.APIStatusError as e:
                # Any 4xx/5xx from Anthropic is unrecoverable for this card —
                # raise so the orchestrator routes it to the Failed column instead
                # of silently posting the error message as a "Done" comment.
                msg = str(e)
                low = msg.lower()
                if any(p in low for p in _USAGE_LIMIT_PATTERNS):
                    kind = "api_usage_limit"
                elif isinstance(e, anthropic.RateLimitError):
                    kind = "api_rate_limit"
                else:
                    kind = "api_error"
                logger.warning(
                    "[%s] %s (kind=%s): %s",
                    self.profile.id, type(e).__name__, kind, msg,
                )
                self._audit.agent_finish(success=False, iterations=iteration, detail=msg)
                raise AgentExecutionError(msg, kind=kind) from e
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
            try:
                tool_results = self._handle_tool_calls(response.content)
            except AgentPausedForQuestion as paused:
                logger.info(
                    "[%s] Card %s paused for human reply (stateful=%s) at iteration %d",
                    self.profile.id, self.card.id, paused.stateful, iteration,
                )
                self._audit.agent_finish(
                    success=True, iterations=iteration, detail="paused_for_question"
                )
                raise
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
            except AgentPausedForQuestion:
                # The ask_human tool already posted the question and added
                # the label. Bubble up to the run loop so it can exit cleanly
                # without recording a generic tool error.
                self._audit.tool_result(tool_name, success=True, detail="paused_for_question")
                raise
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

    # ── Stateful pause / resume ───────────────────────────────────────────────

    def _save_state_for_pause(self) -> None:
        """Serialise current message history and post it as a sidecar comment.

        Called by the AskHumanTool just before it raises AgentPausedForQuestion,
        and only when the card carries REMEMBER_LABEL. The serialised payload is
        embedded inside an HTML-comment marker so it stays out of human readers'
        way; the orchestrator finds it on resume via `extract_state`.

        Failures here are logged but not raised — see AskHumanTool.run.
        """
        jsonable = [_message_to_jsonable(m) for m in self._current_messages]
        body = serialize_state(
            messages=jsonable,
            iteration=self._current_iteration,
            profile_id=self.profile.id,
            model_id=self.profile.model.model_id,
        )
        self.provider.add_comment(self.card.id, body)
        logger.debug(
            "[%s] Persisted agent state for card %s (%d messages, iteration %d)",
            self.profile.id, self.card.id, len(jsonable), self._current_iteration,
        )


# ── JSON-serialisable conversion for state persistence ───────────────────────

def _message_to_jsonable(message: dict) -> dict:
    """Return a deep-JSON-serialisable copy of a single message dict.

    The Anthropic SDK populates assistant turns with rich `ContentBlock`
    objects (TextBlock, ToolUseBlock, etc.) that can't go through `json.dumps`
    directly. This helper converts each block to the same shape the API
    accepts on a follow-up call so the resumed agent can replay the
    conversation faithfully.
    """
    role = message.get("role", "user")
    content = message.get("content")

    # Plain string content (typical for user messages with text only)
    if isinstance(content, str):
        return {"role": role, "content": content}

    # List of blocks — coerce each to a dict the API will accept on resume.
    blocks: list[dict] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                blocks.append(block)
                continue
            block_type = getattr(block, "type", None)
            if block_type == "text":
                blocks.append({"type": "text", "text": getattr(block, "text", "")})
            elif block_type == "tool_use":
                blocks.append({
                    "type": "tool_use",
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}) or {},
                })
            elif block_type == "tool_result":
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": getattr(block, "tool_use_id", ""),
                    "content": getattr(block, "content", ""),
                    "is_error": getattr(block, "is_error", False),
                })
            else:
                # Unknown block type — fall back to repr so we don't lose it
                # entirely. Resume will likely ignore this turn but won't crash.
                blocks.append({"type": "text", "text": repr(block)})
    return {"role": role, "content": blocks}


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
