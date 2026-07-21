from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class DtoYouTubePlaylist:
    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    published_at: Optional[str] = None
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None
    thumbnail_url: Optional[str] = None
    item_count: Optional[int] = None
    raw: Optional[Dict[str, Any]] = None
