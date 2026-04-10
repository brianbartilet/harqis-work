"""
Kanban-specific tools — let the agent interact with its own card
(post comments, move columns, tick checklist items).
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.kanban.interface import KanbanChecklist, KanbanProvider

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

    def __init__(self, provider: KanbanProvider, card_id: str):
        self._provider = provider
        self._card_id = card_id

    def run(self, text: str) -> str:
        self._provider.add_comment(self._card_id, text)
        return f"Comment posted ({len(text)} chars)"


class TrelloMoveTool(_BaseTool):
    name = "move_card"
    description = (
        "Move the current Kanban card to a different column. "
        "Valid columns: Backlog, Claimed, In Progress, Blocked, Review, Done, Failed."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "column": {
                "type": "string",
                "description": "Target column name.",
                "enum": [
                    "Backlog",
                    "Claimed",
                    "In Progress",
                    "Blocked",
                    "Review",
                    "Done",
                    "Failed",
                ],
            }
        },
        "required": ["column"],
    }

    def __init__(self, provider: KanbanProvider, card_id: str):
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
        provider: KanbanProvider,
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
