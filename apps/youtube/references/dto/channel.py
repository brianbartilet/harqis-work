from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class DtoYouTubeChannel:
    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    custom_url: Optional[str] = None
    published_at: Optional[str] = None
    country: Optional[str] = None
    thumbnail_url: Optional[str] = None
    subscriber_count: Optional[int] = None
    view_count: Optional[int] = None
    video_count: Optional[int] = None
    uploads_playlist_id: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None
