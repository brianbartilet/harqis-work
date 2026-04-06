import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from apps.own_tracks.config import CONFIG
from apps.own_tracks.references.web.api.locations import ApiServiceOwnTracksLocations

logger = logging.getLogger("harqis-mcp.own_tracks")


def register_own_tracks_tools(mcp: FastMCP):

    @mcp.tool()
    def get_last_location(user: str = None, device: str = None) -> list[dict]:
        """Get the last known GPS location for all tracked devices, or filter by user/device.

        Args:
            user:   Filter by username (e.g. 'brian'). Leave empty for all devices.
            device: Filter by device name (e.g. 'iphone'). Requires user.

        Returns:
            List of location records with lat, lon, tst (Unix timestamp), acc (accuracy metres),
            tid (tracker label), username, device, and topic.
        """
        logger.info("Tool called: get_last_location user=%s device=%s", user, device)
        result = ApiServiceOwnTracksLocations(CONFIG).get_last(user=user, device=device)
        result = result if isinstance(result, list) else []
        logger.info("get_last_location returned %d location(s)", len(result))
        return result

    @mcp.tool()
    def get_location_history(user: str, device: str,
                             from_ts: Optional[int] = None, to_ts: Optional[int] = None) -> dict:
        """Get GPS location history for a specific device within an optional time range.

        Args:
            user:     Username (e.g. 'brian').
            device:   Device name (e.g. 'iphone').
            from_ts:  Start time as Unix timestamp. Optional.
            to_ts:    End time as Unix timestamp. Optional.

        Returns:
            Dict with key 'data' containing a list of historical location records.
        """
        logger.info("Tool called: get_location_history user=%s device=%s", user, device)
        result = ApiServiceOwnTracksLocations(CONFIG).get_history(
            user=user, device=device, from_ts=from_ts, to_ts=to_ts
        )
        result = result if isinstance(result, dict) else {}
        data = result.get('data', [])
        logger.info("get_location_history returned %d point(s)", len(data))
        return result

    @mcp.tool()
    def list_tracked_devices() -> dict:
        """List all users and devices currently tracked by the OwnTracks Recorder.

        Returns:
            Dict with key 'results' listing all known {username, device, topic} pairs.
        """
        logger.info("Tool called: list_tracked_devices")
        result = ApiServiceOwnTracksLocations(CONFIG).list_devices()
        result = result if isinstance(result, dict) else {}
        return result
