from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoRedditUser:
    id: str = ''
    name: str = ''
    total_karma: int = 0
    link_karma: int = 0
    comment_karma: int = 0
    created_utc: float = 0.0
    is_mod: bool = False
    is_gold: bool = False
    verified: bool = False
    icon_img: Optional[str] = None
    has_mail: Optional[bool] = None
    inbox_count: Optional[int] = None
