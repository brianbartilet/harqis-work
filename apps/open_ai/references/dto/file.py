from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoOpenAiFile:
    id: Optional[str] = None
    object: Optional[str] = None
    bytes: Optional[int] = None
    created_at: Optional[int] = None
    filename: Optional[str] = None
    purpose: Optional[str] = None
    status: Optional[str] = None
    expires_at: Optional[int] = None


@dataclass
class DtoOpenAiFileDeleted:
    id: Optional[str] = None
    object: Optional[str] = None
    deleted: Optional[bool] = None
