from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoAnthropicFile:
    id: Optional[str] = None
    created_at: Optional[str] = None
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    type: str = "file"
    downloadable: Optional[bool] = None
