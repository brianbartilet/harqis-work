from dataclasses import dataclass, field
from typing import List, Optional, Any


@dataclass
class DtoTelegramUser:
    id: Optional[int] = None
    is_bot: Optional[bool] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None


@dataclass
class DtoTelegramChat:
    id: Optional[int] = None
    type: Optional[str] = None      # private, group, supergroup, channel
    title: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    description: Optional[str] = None
    invite_link: Optional[str] = None
    member_count: Optional[int] = None


@dataclass
class DtoTelegramMessage:
    message_id: Optional[int] = None
    date: Optional[int] = None      # Unix timestamp
    chat: Optional[Any] = None      # DtoTelegramChat (kept as Any to avoid deep deserialisation)
    from_user: Optional[Any] = None # DtoTelegramUser
    text: Optional[str] = None
    caption: Optional[str] = None
    forward_from: Optional[Any] = None
    reply_to_message: Optional[Any] = None


@dataclass
class DtoTelegramUpdate:
    update_id: Optional[int] = None
    message: Optional[DtoTelegramMessage] = None
    edited_message: Optional[DtoTelegramMessage] = None
    channel_post: Optional[DtoTelegramMessage] = None


@dataclass
class DtoSendMessage:
    chat_id: Any                       # int or str (@username)
    text: str
    parse_mode: Optional[str] = None   # 'HTML' or 'MarkdownV2'
    disable_notification: Optional[bool] = None
    reply_to_message_id: Optional[int] = None
