import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from apps.plaud.config import CONFIG
from apps.plaud.references.adapter import build_adapter

logger = logging.getLogger("harqis-mcp.plaud")


def register_plaud_tools(mcp: FastMCP):

    @mcp.tool()
    def list_plaud_recordings(since: Optional[str] = None,
                              until: Optional[str] = None) -> list[dict]:
        """List Plaud voice recordings, optionally within a date window.

        Tries the Plaud cloud API first and transparently falls back to the
        local export folder if the cloud is unavailable.

        Args:
            since: Inclusive lower bound, ISO-8601 (e.g. '2026-06-08T00:00:00').
                   Omit for no lower bound.
            until: Inclusive upper bound, ISO-8601. Omit for no upper bound.

        Returns:
            A list of recordings, each with id, title, started_at, duration_seconds,
            audio_format, and whether a Plaud transcript/summary is already present.
        """
        logger.info("Tool called: list_plaud_recordings since=%s until=%s", since, until)
        adapter = build_adapter(CONFIG)
        recordings = adapter.list_recordings(since=since, until=until)
        recordings = recordings if isinstance(recordings, list) else []
        logger.info("list_plaud_recordings returned %d recording(s)", len(recordings))
        return [
            {
                "id": r.id,
                "title": r.title,
                "started_at": r.started_at,
                "duration_seconds": r.duration_seconds,
                "audio_format": r.audio_format,
                "has_transcript": r.has_transcript,
                "has_summary": bool(r.summary),
                "origin": r.origin,
            }
            for r in recordings
        ]

    @mcp.tool()
    def get_plaud_transcript(recording_id: str) -> dict:
        """Get the transcript and summary for a single Plaud recording, if present.

        Args:
            recording_id: The recording id returned by list_plaud_recordings.

        Returns:
            Dict with id, transcript, and summary. Empty strings if Plaud has not
            produced them (the ingest pipeline transcribes such recordings itself).
        """
        logger.info("Tool called: get_plaud_transcript id=%s", recording_id)
        adapter = build_adapter(CONFIG)
        for r in adapter.list_recordings():
            if r.id == recording_id:
                return {
                    "id": r.id,
                    "transcript": r.transcript or "",
                    "summary": r.summary or "",
                }
        return {"id": recording_id, "transcript": "", "summary": ""}

    @mcp.tool()
    def plaud_status() -> dict:
        """Report which Plaud acquisition backend is active (cloud vs export folder).

        Returns:
            Dict with cloud_ready, folder_ready, and the active backend name.
        """
        logger.info("Tool called: plaud_status")
        adapter = build_adapter(CONFIG)
        status = adapter.status
        return status if isinstance(status, dict) else {}
