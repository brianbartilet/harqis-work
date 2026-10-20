"""Shared read-only Granola CLI/MCP adapter."""
import logging
from dataclasses import asdict, is_dataclass

from apps.granola.config import CONFIG
from apps.granola.references.web.api.notes import ApiServiceGranolaNotes

logger = logging.getLogger("harqis-mcp.granola")


def _output(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return value
    data = getattr(value, "data", None)
    if isinstance(data, dict):
        return data
    raise ValueError("Unexpected Granola result")


def register_granola_tools(mcp):
    @mcp.tool()
    def list_granola_notes(created_after: str = "", created_before: str = "",
                           updated_after: str = "", folder_id: str = "",
                           cursor: str = "", page_size: int = 20) -> dict:
        """Read one page of accessible Granola note metadata; does not import HFL.

        Args:
            created_after: ISO timestamp lower creation bound.
            created_before: ISO timestamp upper creation bound.
            updated_after: ISO timestamp lower modification bound.
            folder_id: Optional fol_ ID (includes child folders).
            cursor: Opaque next-page cursor from this query.
            page_size: Number of results, 1–30.
        """
        logger.info("list_granola_notes called")
        result = _output(ApiServiceGranolaNotes(CONFIG).list_notes(
            created_after=created_after, created_before=created_before,
            updated_after=updated_after, folder_id=folder_id, cursor=cursor, page_size=page_size))
        logger.info("list_granola_notes done")
        return result

    @mcp.tool()
    def get_granola_note(note_id: str, include_transcript: bool = False) -> dict:
        """Read a Granola note, including private notes available to the key.

        Args:
            note_id: The not_ ID from list_granola_notes.
            include_transcript: Include transcript; oversized transcripts require get_granola_transcript.
        """
        logger.info("get_granola_note called")
        result = _output(ApiServiceGranolaNotes(CONFIG).get_note(
            note_id, include_transcript=include_transcript))
        logger.info("get_granola_note done")
        return result

    @mcp.tool()
    def get_granola_transcript(note_id: str, cursor: str = "", page_size: int = 50) -> dict:
        """Read one transcript page without storing or summarizing it.

        Args:
            note_id: Granola not_ ID.
            cursor: Opaque transcript cursor.
            page_size: Number of transcript items, 1–100.
        """
        logger.info("get_granola_transcript called")
        result = _output(ApiServiceGranolaNotes(CONFIG).get_transcript(
            note_id, cursor=cursor, page_size=page_size))
        logger.info("get_granola_transcript done")
        return result

    @mcp.tool()
    def list_granola_folders(cursor: str = "", page_size: int = 20) -> dict:
        """Read one folder page to select an HFL import folder.

        Args:
            cursor: Opaque folder cursor.
            page_size: Number of folders, 1–30.
        """
        logger.info("list_granola_folders called")
        result = _output(ApiServiceGranolaNotes(CONFIG).list_folders(
            cursor=cursor, page_size=page_size))
        logger.info("list_granola_folders done")
        return result
