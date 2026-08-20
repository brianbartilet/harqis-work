from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoHflCorpusEntryResult:
    entry_id: Optional[str] = None
    path: Optional[str] = None
    bytes_written: Optional[int] = None
    duplicate: Optional[bool] = None
    indexed: Optional[bool] = None
    doc_id: Optional[str] = None
    delivery: Optional[str] = None
    uploads: Optional[list[str]] = None


@dataclass
class DtoHflCorpusEntry:
    anchor: Optional[str] = None
    header: Optional[str] = None
    moment: Optional[str] = None
    what_happened: Optional[str] = None
    tags: Optional[list[str]] = None
    source: Optional[str] = None
    text: Optional[str] = None
    secret: Optional[bool] = None
