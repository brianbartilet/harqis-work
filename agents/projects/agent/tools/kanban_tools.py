"""
Kanban-specific tools — let the agent interact with its own card
(post comments, move columns, tick checklist items, ask the human a question).
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from agents.projects.agent.question import (
    AgentPausedForQuestion,
    QUESTION_LABEL,
    QUESTION_MARKER,
)
from agents.projects.trello.client import TrelloClient
from agents.projects.trello.models import KanbanChecklist

logger = logging.getLogger(__name__)


class _BaseTool:
    name: str
    description: str
    input_schema: dict

    def run(self, **kwargs): ...


class TrelloCommentTool(_BaseTool):
    name = "post_comment"
    description = (
        "Post a comment on the current Kanban card. "
        "Use this to report progress, ask for clarification, or deliver results."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Markdown text of the comment.",
            }
        },
        "required": ["text"],
    }

    def __init__(self, provider: TrelloClient, card_id: str):
        self._provider = provider
        self._card_id = card_id

    def run(self, text: str) -> str:
        self._provider.add_comment(self._card_id, text)
        return f"Comment posted ({len(text)} chars)"


class TrelloMoveTool(_BaseTool):
    name = "move_card"
    description = (
        "Move the current Kanban card to a different column. "
        "The orchestrator owns most transitions automatically — only call this "
        "when you need to override (e.g. self-block by moving to 'Blocked' if "
        "you discover a missing dependency mid-run)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "column": {
                "type": "string",
                "description": "Target column name.",
                "enum": [
                    "Draft",
                    "Ready",
                    "Pending",
                    "In Progress",
                    "Blocked",
                    "In Review",
                    "Done",
                    "Failed",
                ],
            }
        },
        "required": ["column"],
    }

    def __init__(self, provider: TrelloClient, card_id: str):
        self._provider = provider
        self._card_id = card_id

    def run(self, column: str) -> str:
        self._provider.move_card(self._card_id, column)
        return f"Card moved to '{column}'"


class ChecklistTool(_BaseTool):
    name = "check_item"
    description = (
        "Mark a checklist item on the current card as complete or incomplete. "
        "Use item_name to identify the item (case-insensitive partial match)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "item_name": {
                "type": "string",
                "description": "Name (or partial name) of the checklist item.",
            },
            "checked": {
                "type": "boolean",
                "description": "True to check, False to uncheck. Default true.",
            },
        },
        "required": ["item_name"],
    }

    def __init__(
        self,
        provider: TrelloClient,
        card_id: str,
        checklists: list[KanbanChecklist],
    ):
        self._provider = provider
        self._card_id = card_id
        self._checklists = checklists

    def run(self, item_name: str, checked: bool = True) -> str:
        needle = item_name.lower()
        for cl in self._checklists:
            for item in cl.items:
                if needle in item.name.lower():
                    self._provider.check_item(self._card_id, item.id, checked)
                    state = "checked" if checked else "unchecked"
                    return f"Item '{item.name}' {state}"
        return f"No checklist item matching '{item_name}' found"


class AskHumanTool(_BaseTool):
    """Pause the agent and wait for a human reply on the current card.

    The tool posts the question as a card comment (prefixed with `[agent:question]`),
    adds the `agent:question` label, and raises `AgentPausedForQuestion` so the
    run loop exits cleanly. The orchestrator catches the exception, leaves the
    card in `In Progress`, and resumes the agent on a later poll once a human
    has replied in the comments.

    Stateful resume (carried-over message history): if the card also has the
    `agent:remember` label, the agent persists its full message history before
    pausing, so on resume it picks up exactly where it left off. Without
    `agent:remember`, the resumed agent gets a recap prompt and re-runs from
    scratch.
    """

    name = "ask_human"
    description = (
        "Pause execution and ask the human user a question on the current card. "
        "Use this when you need clarification, approval before an irreversible "
        "action, or a decision between options. Posts the question as a card "
        "comment, adds the 'agent:question' label, and waits — your run ends "
        "after this call. The orchestrator resumes you once the human replies "
        "with a comment on the card."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "The question to ask the human. Be specific — quote relevant "
                    "context from your work so far so the human doesn't have to "
                    "re-derive it. Markdown is rendered."
                ),
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of suggested answers to make the human's "
                    "reply easier. Rendered as a bullet list under the question."
                ),
            },
        },
        "required": ["question"],
    }

    def __init__(
        self,
        provider: TrelloClient,
        card_id: str,
        card_labels: list[str],
        save_state_fn: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            provider:       Kanban provider for the comment + label calls.
            card_id:        Current card ID.
            card_labels:    Snapshot of labels on the card at agent start —
                            used to detect REMEMBER_LABEL for stateful mode.
            save_state_fn:  Optional callback that serialises the agent's
                            current message history and posts it as a sidecar
                            comment. Invoked just before pausing when the
                            REMEMBER_LABEL is present. The agent's base class
                            wires this up via `BaseKanbanAgent._save_state_for_pause`.
        """
        from agents.projects.agent.question import REMEMBER_LABEL  # local import keeps the module graph flat
        self._provider = provider
        self._card_id = card_id
        self._stateful = REMEMBER_LABEL in (card_labels or [])
        self._save_state_fn = save_state_fn

    def run(self, question: str, options: Optional[list[str]] = None) -> str:
        # Build the comment body.
        body_lines = [f"{QUESTION_MARKER} {question.strip()}"]
        if options:
            body_lines.append("")
            body_lines.append("**Suggested answers:**")
            for opt in options:
                body_lines.append(f"- {opt}")
        body_lines.append("")
        body_lines.append(
            "_Reply with a comment to answer. The agent will resume "
            "automatically. Move the card to **Failed** or **Blocked** to "
            "cancel._"
        )
        body = "\n".join(body_lines)

        # Persist state BEFORE posting the question — if state-save fails we
        # don't want a question without a way to resume in stateful mode.
        if self._stateful and self._save_state_fn is not None:
            try:
                self._save_state_fn()
            except Exception as e:
                logger.error(
                    "ask_human: failed to save state for stateful resume — "
                    "will pause anyway in stateless mode: %s", e,
                )

        # Post the question and label the card.
        self._provider.add_comment(self._card_id, body)
        try:
            self._provider.add_label(self._card_id, QUESTION_LABEL)
        except Exception as e:
            # Label failure is non-fatal — the question still went out, the
            # human can still reply. The orchestrator's resume detector falls
            # back to the comment marker so we don't strictly need the label.
            logger.warning(
                "ask_human: failed to add %s label (continuing): %s",
                QUESTION_LABEL, e,
            )

        # Stop the run loop. The orchestrator catches this and leaves the
        # card in In Progress until a human replies.
        raise AgentPausedForQuestion(question, stateful=self._stateful)
