import logging

from mcp.server.fastmcp import FastMCP

from apps.spotify.config import CONFIG
from apps.spotify.references.web.api.player import ApiServiceSpotifyPlayer
from apps.spotify.references.web.api.personalization import ApiServiceSpotifyPersonalization

logger = logging.getLogger("harqis-mcp.spotify")


def register_spotify_tools(mcp: FastMCP):

    @mcp.tool()
    def spotify_recently_played(limit: int = 50) -> list[dict]:
        """List the most recently played Spotify tracks (newest first).

        Spotify caps this at the last 50 plays. Each item carries the
        ``played_at`` UTC timestamp and the full ``track`` object.

        Args:
            limit: Max plays to return (1-50).
        """
        logger.info("Tool called: spotify_recently_played limit=%s", limit)
        service = ApiServiceSpotifyPlayer(CONFIG)
        result = service.get_recently_played(limit=limit)
        items = result.get("items") if isinstance(result, dict) else None
        items = items if isinstance(items, list) else []
        logger.info("spotify_recently_played returned %d play(s)", len(items))
        return items

    @mcp.tool()
    def spotify_currently_playing() -> dict:
        """Get the track currently playing, or {} if nothing is playing."""
        logger.info("Tool called: spotify_currently_playing")
        service = ApiServiceSpotifyPlayer(CONFIG)
        result = service.get_currently_playing()
        return result if isinstance(result, dict) else {}

    @mcp.tool()
    def spotify_top_tracks(time_range: str = "short_term", limit: int = 20) -> list[dict]:
        """List the user's top tracks over a rolling window.

        Args:
            time_range: short_term (~4 weeks) / medium_term (~6 months) / long_term.
            limit: Max tracks to return (1-50).
        """
        logger.info("Tool called: spotify_top_tracks range=%s limit=%s", time_range, limit)
        service = ApiServiceSpotifyPersonalization(CONFIG)
        result = service.get_top_tracks(time_range=time_range, limit=limit)
        items = result.get("items") if isinstance(result, dict) else None
        items = items if isinstance(items, list) else []
        logger.info("spotify_top_tracks returned %d track(s)", len(items))
        return items

    @mcp.tool()
    def spotify_top_artists(time_range: str = "short_term", limit: int = 20) -> list[dict]:
        """List the user's top artists over a rolling window.

        Args:
            time_range: short_term (~4 weeks) / medium_term (~6 months) / long_term.
            limit: Max artists to return (1-50).
        """
        logger.info("Tool called: spotify_top_artists range=%s limit=%s", time_range, limit)
        service = ApiServiceSpotifyPersonalization(CONFIG)
        result = service.get_top_artists(time_range=time_range, limit=limit)
        items = result.get("items") if isinstance(result, dict) else None
        items = items if isinstance(items, list) else []
        logger.info("spotify_top_artists returned %d artist(s)", len(items))
        return items
