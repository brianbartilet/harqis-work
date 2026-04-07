from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DtoDiscordEmbed:
    title: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    color: Optional[int] = None
    timestamp: Optional[str] = None
    footer: Optional[dict] = None
    image: Optional[dict] = None
    thumbnail: Optional[dict] = None
    author: Optional[dict] = None
    fields: List[dict] = field(default_factory=list)


@dataclass
class DtoDiscordMessage:
    id: str = ''
    channel_id: str = ''
    content: str = ''
    timestamp: str = ''
    edited_timestamp: Optional[str] = None
    tts: bool = False
    mention_everyone: bool = False
    pinned: bool = False
    type: int = 0
    author: dict = field(default_factory=dict)
    attachments: List[dict] = field(default_factory=list)
    embeds: List[dict] = field(default_factory=list)
    reactions: List[dict] = field(default_factory=list)
