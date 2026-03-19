from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoAnthropicSkill:
    id: Optional[str] = None
    created_at: Optional[str] = None
    display_title: Optional[str] = None
    latest_version: Optional[str] = None
    source: Optional[str] = None
    type: str = "skill"
    updated_at: Optional[str] = None
