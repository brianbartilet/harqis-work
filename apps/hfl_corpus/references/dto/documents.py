from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class DtoHflCorpusDocument:
    relative_path: Optional[str] = None
    name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    tags: Optional[list[str]] = None
    tag_counts: Optional[list[list[Any]]] = None
    entry_count: Optional[int] = None
    excerpt: Optional[str] = None
    entries: Optional[list[dict[str, Any]]] = None
    matching_entry_count: Optional[int] = None
    tag_entry_anchors: Optional[list[list[str]]] = None
    text: Optional[str] = None


@dataclass
class DtoHflCorpusUpdateResult:
    updated: Optional[bool] = None
    relative_path: Optional[str] = None
    size: Optional[int] = None
