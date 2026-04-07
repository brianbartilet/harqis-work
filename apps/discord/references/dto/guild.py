from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class DtoDiscordGuild:
    id: str = ''
    name: str = ''
    icon: Optional[str] = None
    description: Optional[str] = None
    owner_id: str = ''
    verification_level: int = 0
    premium_tier: int = 0
    preferred_locale: str = 'en-US'
    approximate_member_count: Optional[int] = None
    approximate_presence_count: Optional[int] = None
    features: List[str] = field(default_factory=list)


@dataclass
class DtoDiscordChannel:
    id: str = ''
    type: int = 0
    guild_id: Optional[str] = None
    name: Optional[str] = None
    topic: Optional[str] = None
    position: Optional[int] = None
    nsfw: bool = False
    parent_id: Optional[str] = None


@dataclass
class DtoDiscordWebhook:
    id: str = ''
    type: int = 1
    guild_id: Optional[str] = None
    channel_id: Optional[str] = None
    name: Optional[str] = None
    token: Optional[str] = None
    url: Optional[str] = None
