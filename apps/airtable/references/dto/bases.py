from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoAirtableBase:
    id: Optional[str] = None
    name: Optional[str] = None
    permissionLevel: Optional[str] = None


@dataclass
class DtoAirtableUser:
    id: Optional[str] = None
    email: Optional[str] = None
    scopes: Optional[list] = None
