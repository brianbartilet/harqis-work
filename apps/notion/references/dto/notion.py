from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict


@dataclass
class DtoNotionUser:
    id: Optional[str] = None
    object: Optional[str] = None
    type: Optional[str] = None
    name: Optional[str] = None
    avatar_url: Optional[str] = None


@dataclass
class DtoNotionDatabase:
    id: Optional[str] = None
    object: Optional[str] = None
    created_time: Optional[str] = None
    last_edited_time: Optional[str] = None
    title: Optional[List[Dict]] = field(default_factory=list)
    description: Optional[List[Dict]] = field(default_factory=list)
    properties: Optional[Dict] = field(default_factory=dict)
    url: Optional[str] = None
    archived: Optional[bool] = None
    is_inline: Optional[bool] = None


@dataclass
class DtoNotionPage:
    id: Optional[str] = None
    object: Optional[str] = None
    created_time: Optional[str] = None
    last_edited_time: Optional[str] = None
    archived: Optional[bool] = None
    url: Optional[str] = None
    properties: Optional[Dict] = field(default_factory=dict)
    parent: Optional[Dict] = field(default_factory=dict)
    icon: Optional[Dict] = None
    cover: Optional[Dict] = None


@dataclass
class DtoNotionBlock:
    id: Optional[str] = None
    object: Optional[str] = None
    type: Optional[str] = None
    created_time: Optional[str] = None
    last_edited_time: Optional[str] = None
    has_children: Optional[bool] = None
    archived: Optional[bool] = None


@dataclass
class DtoNotionSearchResult:
    object: Optional[str] = None
    results: Optional[List[Dict]] = field(default_factory=list)
    next_cursor: Optional[str] = None
    has_more: Optional[bool] = None
