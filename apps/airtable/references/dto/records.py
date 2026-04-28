from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class DtoAirtableRecord:
    id: Optional[str] = None
    createdTime: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None


@dataclass
class DtoAirtableRecordsPage:
    records: Optional[List[DtoAirtableRecord]] = None
    offset: Optional[str] = None
