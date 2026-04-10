"""
Abstract Kanban provider interface.

All orchestrator and agent code depends only on these types — never on
Trello or Jira directly. Swap providers by changing one config value.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KanbanChecklistItem:
    id: str
    name: str
    checked: bool = False


@dataclass
class KanbanChecklist:
    id: str
    name: str
    items: list[KanbanChecklistItem] = field(default_factory=list)


@dataclass
class KanbanAttachment:
    id: str
    name: str
    url: str
    mime_type: str = ""
    is_inline: bool = False
    bytes_size: int = 0


@dataclass
class KanbanColumn:
    id: str
    name: str


@dataclass
class KanbanCard:
    id: str
    title: str
    description: str
    labels: list[str]
    assignees: list[str]
    column: str
    url: str
    checklists: list[KanbanChecklist] = field(default_factory=list)
    attachments: list[KanbanAttachment] = field(default_factory=list)
    custom_fields: dict[str, str] = field(default_factory=dict)
    due_date: Optional[str] = None
    raw: dict = field(default_factory=dict)


class KanbanProvider(ABC):
    """Abstract interface for Kanban backends (Trello, Jira, ...)."""

    # ── Board / Columns ───────────────────────────────────────────────────────

    @abstractmethod
    def get_columns(self, board_id: str) -> list[KanbanColumn]:
        """Return all columns/lists on the board."""

    @abstractmethod
    def get_column_by_name(self, board_id: str, name: str) -> Optional[KanbanColumn]:
        """Return the column with the given name, or None."""

    # ── Cards ─────────────────────────────────────────────────────────────────

    @abstractmethod
    def get_cards(
        self,
        board_id: str,
        column: str,
        label: Optional[str] = None,
    ) -> list[KanbanCard]:
        """Return all cards in the named column, optionally filtered by label."""

    @abstractmethod
    def get_card(self, card_id: str) -> KanbanCard:
        """Return a single card by ID."""

    @abstractmethod
    def move_card(self, card_id: str, column: str) -> None:
        """Move a card to the named column."""

    @abstractmethod
    def assign_card(self, card_id: str, member_id: str) -> None:
        """Assign a card to a member/user."""

    # ── Comments ──────────────────────────────────────────────────────────────

    @abstractmethod
    def add_comment(self, card_id: str, text: str) -> None:
        """Post a comment on a card."""

    @abstractmethod
    def get_comments(self, card_id: str) -> list[str]:
        """Return comment texts on a card, oldest first."""

    # ── Checklists ────────────────────────────────────────────────────────────

    @abstractmethod
    def check_item(self, card_id: str, item_id: str, checked: bool = True) -> None:
        """Mark a checklist item complete or incomplete."""

    # ── Attachments ───────────────────────────────────────────────────────────

    @abstractmethod
    def get_attachments(self, card_id: str) -> list[KanbanAttachment]:
        """Return all attachments on a card."""

    @abstractmethod
    def add_attachment(
        self,
        card_id: str,
        name: str,
        content: bytes,
        mime_type: str = "text/plain",
    ) -> None:
        """Upload an attachment to a card."""

    # ── Labels ────────────────────────────────────────────────────────────────

    @abstractmethod
    def add_label(self, card_id: str, label: str) -> None:
        """Add a label to a card."""

    @abstractmethod
    def remove_label(self, card_id: str, label: str) -> None:
        """Remove a label from a card."""

    # ── Custom Fields ─────────────────────────────────────────────────────────

    @abstractmethod
    def get_custom_fields(self, card_id: str) -> dict[str, str]:
        """Return all custom fields as {name: value}."""

    @abstractmethod
    def set_custom_field(self, card_id: str, field_name: str, value: str) -> None:
        """Set a custom field value on a card."""

    # ── Webhooks (optional) ───────────────────────────────────────────────────

    def register_webhook(self, board_id: str, callback_url: str) -> str:
        """Register a board webhook. Returns the webhook ID."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support webhooks")

    def delete_webhook(self, webhook_id: str) -> None:
        """Delete a webhook by ID."""
        raise NotImplementedError(f"{self.__class__.__name__} does not support webhooks")
