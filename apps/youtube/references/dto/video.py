from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class DtoYouTubeVideo:
    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    published_at: Optional[str] = None
    added_at: Optional[str] = None
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration: Optional[str] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    privacy_status: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None
