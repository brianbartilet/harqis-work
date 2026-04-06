from dataclasses import dataclass, field
from typing import List, Optional, Any


@dataclass
class DtoTrelloBoard:
    id: Optional[str] = None
    name: Optional[str] = None
    desc: Optional[str] = None
    closed: Optional[bool] = None
    url: Optional[str] = None
    short_url: Optional[str] = None
    id_organization: Optional[str] = None
    id_member_creator: Optional[str] = None


@dataclass
class DtoTrelloList:
    id: Optional[str] = None
    name: Optional[str] = None
    closed: Optional[bool] = None
    id_board: Optional[str] = None
    pos: Optional[float] = None


@dataclass
class DtoTrelloCard:
    id: Optional[str] = None
    name: Optional[str] = None
    desc: Optional[str] = None
    closed: Optional[bool] = None
    url: Optional[str] = None
    short_url: Optional[str] = None
    id_board: Optional[str] = None
    id_list: Optional[str] = None
    id_members: Optional[List[str]] = field(default_factory=list)
    id_labels: Optional[List[str]] = field(default_factory=list)
    due: Optional[str] = None
    due_complete: Optional[bool] = None
    pos: Optional[float] = None
    date_last_activity: Optional[str] = None


@dataclass
class DtoTrelloMember:
    id: Optional[str] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    initials: Optional[str] = None
    avatar_url: Optional[str] = None
    url: Optional[str] = None
