from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoApifyDataset:
    """Metadata for a stored dataset (one per finished actor run by default)."""
    id: Optional[str] = None
    name: Optional[str] = None
    userId: Optional[str] = None
    createdAt: Optional[str] = None
    modifiedAt: Optional[str] = None
    accessedAt: Optional[str] = None
    itemCount: Optional[int] = None
    cleanItemCount: Optional[int] = None
    actId: Optional[str] = None
    actRunId: Optional[str] = None
