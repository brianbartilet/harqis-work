"""Bounded page primitives; callers own pagination and retry budgets."""
import re
from types import SimpleNamespace

from core.web.services.core.decorators.deserializer import deserialized
from apps.granola.references.dto.note import DtoGranolaNote
from apps.granola.references.web.base_api_service import BaseApiServiceGranola


def resource_id(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(
        rf"(?i:{prefix})_[a-zA-Z0-9]{{14}}", value
    ):
        raise ValueError(f"Invalid Granola {prefix} ID")
    return prefix + value[len(prefix):]


def page(payload, field):
    if not isinstance(payload.get(field), list) or not isinstance(payload.get("hasMore"), bool):
        raise ValueError("Invalid Granola page")
    if payload["hasMore"] and (not isinstance(payload.get("cursor"), str) or not payload["cursor"]):
        raise ValueError("Missing Granola cursor")
    return payload


class ApiServiceGranolaNotes(BaseApiServiceGranola):
    def list_notes(self, *, created_after="", created_before="", updated_after="",
                   folder_id="", cursor="", page_size=20):
        """Return one page, including hasMore and cursor."""
        if not 1 <= page_size <= 30:
            raise ValueError("page_size must be 1–30")
        return page(self._get(
            "notes", created_after=created_after, created_before=created_before,
            updated_after=updated_after, folder_id=resource_id(folder_id, "fol") if folder_id else "",
            cursor=cursor, page_size=page_size,
        ), "notes")

    @deserialized(DtoGranolaNote)
    def get_note(self, note_id, *, include_transcript=False):
        """Return a typed note; request transcript only when explicitly selected."""
        payload = self._get(
            f"notes/{resource_id(note_id, 'not')}",
            include="transcript" if include_transcript else "",
        )
        if payload.get("id") != resource_id(note_id, "not"):
            raise ValueError("Granola note identity mismatch")
        # The shared deserializer consumes .data and the config's
        # return_data_only flag, just as it does for framework responses.
        return SimpleNamespace(data=payload)

    def get_transcript(self, note_id, *, cursor="", page_size=50):
        """Return one transcript page, including oversized-note transcripts."""
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be 1–100")
        return page(self._get(
            f"notes/{resource_id(note_id, 'not')}/transcript",
            cursor=cursor, page_size=page_size,
        ), "transcript")

    def list_folders(self, *, cursor="", page_size=20):
        """Return one folder page."""
        if not 1 <= page_size <= 30:
            raise ValueError("page_size must be 1–30")
        return page(self._get("folders", cursor=cursor, page_size=page_size), "folders")
