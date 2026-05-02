from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class DtoApifyTrendItem:
    """
    Normalised trend record across social platforms.

    Most Apify scrapers return platform-specific shapes. Use the conversion
    helpers in trends.py to project them onto this shape for cross-platform
    aggregation.
    """
    platform: Optional[str] = None         # 'google_trends' | 'instagram' | 'facebook' | 'tiktok' | 'reddit'
    keyword: Optional[str] = None          # search term or hashtag that produced this item
    title: Optional[str] = None
    url: Optional[str] = None
    author: Optional[str] = None
    posted_at: Optional[str] = None
    location: Optional[str] = None
    score: Optional[float] = None          # likes/upvotes/views — normalised per platform
    engagement: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None   # the original platform payload

    related_terms: Optional[List[str]] = field(default_factory=list)
