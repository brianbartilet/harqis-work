from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoFilterResult:
    id: Optional[str] = None,
    name: Optional[str] = None,
    setname: Optional[str] = None,
    image: Optional[str] = None,
    type: Optional[int] = None,
    crd_foil_type: Optional[str] = None
