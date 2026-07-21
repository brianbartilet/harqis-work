from __future__ import annotations

from typing import Any, Dict, List, Optional

from apps.youtube.references.dto.channel import DtoYouTubeChannel
from apps.youtube.references.dto.playlist import DtoYouTubePlaylist
from apps.youtube.references.dto.video import DtoYouTubeVideo
from apps.youtube.references.web.base_api_service import BaseApiServiceYouTube


def _optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    return int(value)


def _thumbnail_url(snippet: Dict[str, Any]) -> Optional[str]:
    thumbnails = snippet.get("thumbnails", {})
    for size in ("maxres", "standard", "high", "medium", "default"):
        url = thumbnails.get(size, {}).get("url")
        if url:
            return url
    return None


class ApiServiceYouTubeData(BaseApiServiceYouTube):
    """Read-only YouTube Data API v3 operations."""

    SERVICE_NAME = "youtube"
    SERVICE_VERSION = "v3"

    def _channel(self, item: Dict[str, Any]) -> DtoYouTubeChannel:
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        related = item.get("contentDetails", {}).get("relatedPlaylists", {})
        return DtoYouTubeChannel(
            id=item.get("id"),
            title=snippet.get("title"),
            description=snippet.get("description"),
            custom_url=snippet.get("customUrl"),
            published_at=snippet.get("publishedAt"),
            country=snippet.get("country"),
            thumbnail_url=_thumbnail_url(snippet),
            subscriber_count=_optional_int(statistics.get("subscriberCount")),
            view_count=_optional_int(statistics.get("viewCount")),
            video_count=_optional_int(statistics.get("videoCount")),
            uploads_playlist_id=related.get("uploads"),
            raw=item,
        )

    def _video(self, item: Dict[str, Any]) -> DtoYouTubeVideo:
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        status = item.get("status", {})
        video_id = item.get("id")
        if isinstance(video_id, dict):
            video_id = video_id.get("videoId")
        return DtoYouTubeVideo(
            id=video_id,
            title=snippet.get("title"),
            description=snippet.get("description"),
            published_at=(
                item.get("contentDetails", {}).get("videoPublishedAt")
                or snippet.get("publishedAt")
            ),
            added_at=snippet.get("publishedAt"),
            channel_id=(
                snippet.get("videoOwnerChannelId") or snippet.get("channelId")
            ),
            channel_title=(
                snippet.get("videoOwnerChannelTitle")
                or snippet.get("channelTitle")
            ),
            thumbnail_url=_thumbnail_url(snippet),
            duration=item.get("contentDetails", {}).get("duration"),
            view_count=_optional_int(statistics.get("viewCount")),
            like_count=_optional_int(statistics.get("likeCount")),
            comment_count=_optional_int(statistics.get("commentCount")),
            privacy_status=status.get("privacyStatus"),
            raw=item,
        )

    def _playlist(self, item: Dict[str, Any]) -> DtoYouTubePlaylist:
        snippet = item.get("snippet", {})
        return DtoYouTubePlaylist(
            id=item.get("id"),
            title=snippet.get("title"),
            description=snippet.get("description"),
            published_at=snippet.get("publishedAt"),
            channel_id=snippet.get("channelId"),
            channel_title=snippet.get("channelTitle"),
            thumbnail_url=_thumbnail_url(snippet),
            item_count=_optional_int(item.get("contentDetails", {}).get("itemCount")),
            raw=item,
        )

    def get_my_channel(self) -> Optional[DtoYouTubeChannel]:
        """Return the authenticated user's YouTube channel."""
        response = self.service.channels().list(
            part="snippet,statistics,contentDetails",
            mine=True,
        ).execute()
        items = response.get("items", [])
        return self._channel(items[0]) if items else None

    def get_channel(self, channel_id: str) -> Optional[DtoYouTubeChannel]:
        """Return a channel by its YouTube channel ID."""
        response = self.service.channels().list(
            part="snippet,statistics,contentDetails",
            id=channel_id,
        ).execute()
        items = response.get("items", [])
        return self._channel(items[0]) if items else None

    def list_playlists(
        self,
        channel_id: Optional[str] = None,
        max_results: Optional[int] = 25,
    ) -> List[DtoYouTubePlaylist]:
        """List playlists for a channel, paginating until the requested limit."""
        limit = None if max_results is None else max(max_results, 1)
        playlists: List[DtoYouTubePlaylist] = []
        seen_playlist_ids = set()
        seen_page_tokens = set()
        page_token = None

        while limit is None or len(playlists) < limit:
            page_size = 50 if limit is None else min(limit - len(playlists), 50)
            request: Dict[str, Any] = {
                "part": "snippet,contentDetails",
                "maxResults": page_size,
            }
            if channel_id:
                request["channelId"] = channel_id
            else:
                request["mine"] = True
            if page_token:
                request["pageToken"] = page_token
            response = self.service.playlists().list(**request).execute()
            for item in response.get("items", []):
                playlist_id = item.get("id")
                if not playlist_id or playlist_id in seen_playlist_ids:
                    continue
                playlists.append(self._playlist(item))
                seen_playlist_ids.add(playlist_id)
                if limit is not None and len(playlists) >= limit:
                    break
            next_page_token = response.get("nextPageToken")
            if not next_page_token or next_page_token in seen_page_tokens:
                break
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token
        return playlists

    def list_playlist_items(
        self,
        playlist_id: str,
        max_results: Optional[int] = 25,
    ) -> List[DtoYouTubeVideo]:
        """List unique videos in a playlist, paginating until the requested limit."""
        limit = None if max_results is None else max(max_results, 1)
        videos: List[DtoYouTubeVideo] = []
        seen_video_ids = set()
        seen_page_tokens = set()
        page_token = None

        while limit is None or len(videos) < limit:
            page_size = 50 if limit is None else min(limit - len(videos), 50)
            request: Dict[str, Any] = {
                "part": "snippet,contentDetails,status",
                "playlistId": playlist_id,
                "maxResults": page_size,
            }
            if page_token:
                request["pageToken"] = page_token

            response = self.service.playlistItems().list(**request).execute()
            for item in response.get("items", []):
                video_id = item.get("contentDetails", {}).get("videoId")
                if not video_id or video_id in seen_video_ids:
                    continue
                normalized = dict(item)
                normalized["id"] = video_id
                videos.append(self._video(normalized))
                seen_video_ids.add(video_id)
                if limit is not None and len(videos) >= limit:
                    break

            next_page_token = response.get("nextPageToken")
            if not next_page_token or next_page_token in seen_page_tokens:
                break
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token

        return videos

    def list_channel_videos(
        self,
        channel_id: Optional[str] = None,
        max_results: Optional[int] = 25,
    ) -> List[DtoYouTubeVideo]:
        """List unique uploads for a channel, paginating until the requested limit."""
        channel = self.get_channel(channel_id) if channel_id else self.get_my_channel()
        if not channel or not channel.uploads_playlist_id:
            return []
        return self.list_playlist_items(channel.uploads_playlist_id, max_results)

    def get_video(self, video_id: str) -> Optional[DtoYouTubeVideo]:
        """Return detailed metadata and statistics for a video."""
        response = self.service.videos().list(
            part="snippet,statistics,contentDetails,status",
            id=video_id,
        ).execute()
        items = response.get("items", [])
        return self._video(items[0]) if items else None

    def search_videos(
        self,
        query: str,
        channel_id: Optional[str] = None,
        max_results: int = 10,
    ) -> List[DtoYouTubeVideo]:
        """Search public videos by query, optionally within one channel."""
        request: Dict[str, Any] = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(max(max_results, 1), 50),
        }
        if channel_id:
            request["channelId"] = channel_id
        response = self.service.search().list(**request).execute()
        return [self._video(item) for item in response.get("items", [])]
