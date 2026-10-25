"""Wire fields from Granola Get Note; nested metadata stays lossless."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class DtoGranolaNote:
    id: Optional[str] = None
    object: Optional[str] = None
    title: Optional[str] = None
    owner: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None
    web_url: Optional[str] = None
    calendar_event: Optional[dict] = None
    attendees: Optional[list] = None
    folder_membership: Optional[list] = None
    space_membership: Optional[list] = None
    summary_text: Optional[str] = None
    summary_markdown: Optional[str] = None
    private_notes_text: Optional[str] = None
    private_notes_markdown: Optional[str] = None
    transcript: Optional[list] = None
