"""
Kanban data models.

Plain dataclasses shared by orchestrator + agent + tools. The Trello client
in this same package returns these; agent code never sees raw Trello JSON.

Provider abstraction (`TrelloClient` ABC, factory) was removed when Jira
support was dropped — Trello is the only backend now.
"""

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
    board_id: str = ""
    checklists: list[KanbanChecklist] = field(default_factory=list)
    attachments: list[KanbanAttachment] = field(default_factory=list)
    custom_fields: dict[str, str] = field(default_factory=dict)
    due_date: Optional[str] = None
    raw: dict = field(default_factory=dict)
