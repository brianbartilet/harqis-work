from __future__ import annotations

from datetime import date
from typing import Optional

from apps.youtube.references.dto.analytics import DtoYouTubeAnalyticsReport
from apps.youtube.references.web.base_api_service import BaseApiServiceYouTube


class ApiServiceYouTubeAnalytics(BaseApiServiceYouTube):
    """Targeted YouTube Analytics API v2 channel reports."""

    SERVICE_NAME = "youtubeAnalytics"
    SERVICE_VERSION = "v2"

    @staticmethod
    def _validate_dates(start_date: str, end_date: str) -> None:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if start > end:
            raise ValueError("start_date must be on or before end_date")

    @staticmethod
    def _report(response: dict) -> DtoYouTubeAnalyticsReport:
        return DtoYouTubeAnalyticsReport(
            kind=response.get("kind"),
            column_headers=response.get("columnHeaders", []),
            rows=response.get("rows", []),
            raw=response,
        )

    def query_channel_report(
        self,
        start_date: str,
        end_date: str,
        metrics: str,
        dimensions: Optional[str] = None,
        filters: Optional[str] = None,
        sort: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> DtoYouTubeAnalyticsReport:
        """Run a targeted Analytics query for the authenticated channel."""
        self._validate_dates(start_date, end_date)
        request = {
            "ids": "channel==MINE",
            "startDate": start_date,
            "endDate": end_date,
            "metrics": metrics,
        }
        if dimensions:
            request["dimensions"] = dimensions
        if filters:
            request["filters"] = filters
        if sort:
            request["sort"] = sort
        if max_results is not None:
            request["maxResults"] = min(max(max_results, 1), 200)
        response = self.service.reports().query(**request).execute()
        return self._report(response)

    def get_channel_summary(
        self,
        start_date: str,
        end_date: str,
    ) -> DtoYouTubeAnalyticsReport:
        """Return headline views, watch time, engagement, and subscriber metrics."""
        return self.query_channel_report(
            start_date=start_date,
            end_date=end_date,
            metrics=(
                "views,engagedViews,estimatedMinutesWatched,averageViewDuration,"
                "likes,comments,shares,subscribersGained,subscribersLost"
            ),
        )

    def get_top_videos(
        self,
        start_date: str,
        end_date: str,
        max_results: int = 10,
    ) -> DtoYouTubeAnalyticsReport:
        """Return the channel's top videos by views for a date range."""
        return self.query_channel_report(
            start_date=start_date,
            end_date=end_date,
            metrics="views,estimatedMinutesWatched,averageViewDuration,likes,comments",
            dimensions="video",
            sort="-views",
            max_results=max_results,
        )
