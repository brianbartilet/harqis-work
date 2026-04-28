from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoPerplexityModel:
    id: Optional[str] = None
    object: Optional[str] = None
    created: Optional[int] = None
    owned_by: Optional[str] = None
