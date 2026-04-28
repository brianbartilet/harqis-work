from dataclasses import dataclass
from typing import Optional, List, Dict, Any


@dataclass
class DtoAirtableField:
    id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    options: Optional[Dict[str, Any]] = None


@dataclass
class DtoAirtableView:
    id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None


@dataclass
class DtoAirtableTable:
    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    primaryFieldId: Optional[str] = None
    fields: Optional[List[DtoAirtableField]] = None
    views: Optional[List[DtoAirtableView]] = None
