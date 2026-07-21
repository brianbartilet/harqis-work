import logging
from dataclasses import asdict, is_dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from apps.youtube.config import CONFIG
from apps.youtube.references.web.api.analytics import ApiServiceYouTubeAnalytics
from apps.youtube.references.web.api.data import ApiServiceYouTubeData

logger = logging.getLogger("harqis-mcp.youtube")


def _serialize(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def register_youtube_tools(mcp: FastMCP):

    @mcp.tool()
    def get_youtube_my_channel() -> dict:
        """Get the authenticated user's YouTube channel and headline statistics."""
        logger.info("Tool called: get_youtube_my_channel")
        result = ApiServiceYouTubeData(CONFIG).get_my_channel()
        output = _serialize(result) if result is not None else {}
        logger.info("get_youtube_my_channel done")
        return output

    @mcp.tool()
    def get_youtube_channel(channel_id: str) -> dict:
        """Get a YouTube channel and headline statistics.

        Args:
            channel_id: The canonical YouTube channel ID beginning with UC.
        """
        logger.info("Tool called: get_youtube_channel channel_id=%s", channel_id)
        result = ApiServiceYouTubeData(CONFIG).get_channel(channel_id)
        output = _serialize(result) if result is not None else {}
        logger.info("get_youtube_channel done")
        return output

    @mcp.tool()
    def list_youtube_playlists(
        channel_id: str | None = None,
        max_results: int = 25,
    ) -> list[dict]:
        """List playlists for a channel or the authenticated user.

        Args:
            channel_id: Optional YouTube channel ID; omit to use the authenticated channel.
            max_results: Number of playlists to return, from 1 to 50.
        """
        logger.info(
            "Tool called: list_youtube_playlists channel_id=%s max_results=%d",
            channel_id,
            max_results,
        )
        result = ApiServiceYouTubeData(CONFIG).list_playlists(channel_id, max_results)
        output = _serialize(result)
        logger.info("list_youtube_playlists returned %d playlist(s)", len(output))
        return output

    @mcp.tool()
    def list_youtube_playlist_videos(
        playlist_id: str,
        max_results: int | None = None,
    ) -> list[dict]:
        """List unique videos in a YouTube playlist, automatically paginating by default.

        Args:
            playlist_id: The YouTube playlist ID.
            max_results: Optional result limit; omit or pass null to return all videos.
        """
        logger.info(
            "Tool called: list_youtube_playlist_videos playlist_id=%s max_results=%s",
            playlist_id,
            max_results,
        )
        result = ApiServiceYouTubeData(CONFIG).list_playlist_items(playlist_id, max_results)
        output = _serialize(result)
        logger.info("list_youtube_playlist_videos returned %d video(s)", len(output))
        return output

    @mcp.tool()
    def list_youtube_channel_videos(
        channel_id: str | None = None,
        max_results: int | None = None,
    ) -> list[dict]:
        """List unique uploads for a channel, automatically paginating by default.

        Args:
            channel_id: Optional YouTube channel ID; omit to use the authenticated channel.
            max_results: Optional result limit; omit or pass null to return all uploads.
        """
        logger.info(
            "Tool called: list_youtube_channel_videos channel_id=%s max_results=%s",
            channel_id,
            max_results,
        )
        result = ApiServiceYouTubeData(CONFIG).list_channel_videos(channel_id, max_results)
        output = _serialize(result)
        logger.info("list_youtube_channel_videos returned %d video(s)", len(output))
        return output

    @mcp.tool()
    def get_youtube_video(video_id: str) -> dict:
        """Get detailed metadata and statistics for a YouTube video.

        Args:
            video_id: The YouTube video ID.
        """
        logger.info("Tool called: get_youtube_video video_id=%s", video_id)
        result = ApiServiceYouTubeData(CONFIG).get_video(video_id)
        output = _serialize(result) if result is not None else {}
        logger.info("get_youtube_video done")
        return output

    @mcp.tool()
    def search_youtube_videos(
        query: str,
        channel_id: str | None = None,
        max_results: int = 10,
    ) -> list[dict]:
        """Search public YouTube videos; this operation has a higher quota cost.

        Args:
            query: Free-text YouTube search query.
            channel_id: Optional channel ID used to restrict the search.
            max_results: Number of search results to return, from 1 to 50.
        """
        logger.info(
            "Tool called: search_youtube_videos channel_id=%s max_results=%d",
            channel_id,
            max_results,
        )
        result = ApiServiceYouTubeData(CONFIG).search_videos(
            query,
            channel_id,
            max_results,
        )
        output = _serialize(result)
        logger.info("search_youtube_videos returned %d video(s)", len(output))
        return output

    @mcp.tool()
    def analyze_youtube_channel(
        start_date: str,
        end_date: str,
        metrics: str,
        dimensions: str | None = None,
        filters: str | None = None,
        sort: str | None = None,
        max_results: int | None = None,
    ) -> dict:
        """Run a targeted YouTube Analytics query for the authenticated channel.

        Args:
            start_date: Inclusive report start date in YYYY-MM-DD format.
            end_date: Inclusive report end date in YYYY-MM-DD format.
            metrics: Comma-separated Analytics metric names such as views or likes.
            dimensions: Optional comma-separated dimensions such as day or video.
            filters: Optional YouTube Analytics filter expression.
            sort: Optional comma-separated sort fields; prefix descending fields with -.
            max_results: Optional maximum row count, from 1 to 200.
        """
        logger.info(
            "Tool called: analyze_youtube_channel start_date=%s end_date=%s",
            start_date,
            end_date,
        )
        result = ApiServiceYouTubeAnalytics(CONFIG).query_channel_report(
            start_date=start_date,
            end_date=end_date,
            metrics=metrics,
            dimensions=dimensions,
            filters=filters,
            sort=sort,
            max_results=max_results,
        )
        output = _serialize(result)
        logger.info("analyze_youtube_channel returned %d row(s)", len(output.get("rows") or []))
        return output

    @mcp.tool()
    def get_youtube_channel_summary(start_date: str, end_date: str) -> dict:
        """Get headline YouTube Studio metrics for the authenticated channel.

        Args:
            start_date: Inclusive report start date in YYYY-MM-DD format.
            end_date: Inclusive report end date in YYYY-MM-DD format.
        """
        logger.info(
            "Tool called: get_youtube_channel_summary start_date=%s end_date=%s",
            start_date,
            end_date,
        )
        result = ApiServiceYouTubeAnalytics(CONFIG).get_channel_summary(start_date, end_date)
        output = _serialize(result)
        logger.info(
            "get_youtube_channel_summary returned %d row(s)",
            len(output.get("rows") or []),
        )
        return output

    @mcp.tool()
    def get_youtube_top_videos(
        start_date: str,
        end_date: str,
        max_results: int = 10,
    ) -> dict:
        """Get the authenticated channel's top videos by views.

        Args:
            start_date: Inclusive report start date in YYYY-MM-DD format.
            end_date: Inclusive report end date in YYYY-MM-DD format.
            max_results: Number of videos to return, from 1 to 200.
        """
        logger.info(
            "Tool called: get_youtube_top_videos start_date=%s end_date=%s max_results=%d",
            start_date,
            end_date,
            max_results,
        )
        result = ApiServiceYouTubeAnalytics(CONFIG).get_top_videos(
            start_date,
            end_date,
            max_results,
        )
        output = _serialize(result)
        logger.info("get_youtube_top_videos returned %d row(s)", len(output.get("rows") or []))
        return output
