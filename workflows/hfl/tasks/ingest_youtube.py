"""Monthly YouTube uploads and playlist additions -> retrospective HFL entries.

The authenticated channel is read through ``apps.youtube``. Each selected
upload or playlist-addition event is archived under ``YOUTUBE_ARCHIVE_PATH`` as
``YYYY-MM-DD-<video-title>/description.md`` plus a local video downloaded by
yt-dlp. Only after both artifacts exist is an HFL entry submitted. Own uploads
use the video's publication time; external playlist additions use the playlist
item's added time as their HFL/archive date.

``days`` accepts a positive integer, ``"all"``, or ``"last_month"`` (the
scheduled default). Missing archive configuration, no videos, API failures,
and download failures are clean skips and never break Celery Beat.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from core.apps.es_logging.app.elasticsearch import log_result
from core.apps.sprout.app.celery import SPROUT
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.youtube.config import CONFIG as YOUTUBE_CONFIG
from apps.youtube.references.dto.video import DtoYouTubeVideo
from apps.youtube.references.web.api.data import ApiServiceYouTubeData
from workflows.hfl.dto import HflEntry
from workflows.hfl.persistence import submit_hfl_entry
from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_youtube")
_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


@dataclass(frozen=True)
class YouTubeActivityItem:
    """One upload or one external-video playlist-addition event."""

    video: DtoYouTubeVideo
    occurred_at: datetime
    event_type: str
    playlist_ids: tuple[str, ...] = ()
    playlist_names: tuple[str, ...] = ()

    @property
    def identity(self) -> str:
        if self.event_type == "upload":
            return f"upload:{self.video.id}"
        playlist_id = self.playlist_ids[0] if self.playlist_ids else "unknown"
        return (
            f"playlist:{playlist_id}:{self.video.id}:"
            f"{self.occurred_at.isoformat()}"
        )

    @property
    def required_tags(self) -> tuple[str, ...]:
        playlist_tags = tuple(
            f"playlist-{_tag_slug(name)}" for name in self.playlist_names
        )
        category = ("upload",) if self.event_type == "upload" else ("watch-later",)
        return tuple(dict.fromkeys(("youtube", *category, *playlist_tags)))


def _published_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def _resolve_days(
    days: int | str,
    *,
    today: Optional[date] = None,
) -> tuple[Optional[date], date]:
    """Resolve numeric/all/calendar-month lookbacks into inclusive bounds."""
    end = today or datetime.now().date()
    value = str(days).strip().lower()
    if value == "all":
        return None, end
    if value in {"last_month", "last-month", "month"}:
        first_this_month = end.replace(day=1)
        previous_end = first_this_month - timedelta(days=1)
        return previous_end.replace(day=1), previous_end
    try:
        count = int(value)
    except ValueError as exc:
        raise ValueError(
            "days must be a positive integer, 'last_month', or 'all'"
        ) from exc
    if count < 1:
        raise ValueError("days must be at least 1")
    return end - timedelta(days=count - 1), end


def _archive_slug(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", title or "video")
    cleaned = re.sub(r"[-\s]+", "-", cleaned).strip(" .-")
    return cleaned[:140].rstrip(" .-") or "video"


def _tag_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "playlist").lower())
    return slug.strip("-") or "playlist"


def _in_window(value: datetime, since: Optional[date], until: date) -> bool:
    return value.date() <= until and (since is None or value.date() >= since)


def collect_youtube_activity(
    *,
    since: Optional[date],
    until: date,
    client: ApiServiceYouTubeData,
    max_videos: Optional[int] = 500,
    max_playlists: Optional[int] = 50,
    max_playlist_items: Optional[int] = 500,
) -> dict[str, Any]:
    """Collect own uploads plus external videos added to owned playlists."""
    channel = client.get_my_channel()
    if not channel or not channel.id or not channel.uploads_playlist_id:
        return {"items": [], "count": 0, "uploads": 0, "playlist_additions": 0}

    uploads = client.list_playlist_items(
        channel.uploads_playlist_id,
        max_results=max_videos,
    )
    playlists = client.list_playlists(max_results=max_playlists)
    own_memberships: dict[str, list[tuple[str, str]]] = {}
    playlist_additions: list[YouTubeActivityItem] = []

    for playlist in playlists:
        if not playlist.id or playlist.id == channel.uploads_playlist_id:
            continue
        playlist_name = (playlist.title or "Untitled playlist").strip()
        playlist_videos = client.list_playlist_items(
            playlist.id,
            max_results=max_playlist_items,
        )
        for video in playlist_videos:
            if not video.id:
                continue
            if video.channel_id == channel.id:
                own_memberships.setdefault(video.id, []).append(
                    (playlist.id, playlist_name)
                )
                continue
            added_at = _published_datetime(video.added_at)
            if not added_at or not _in_window(added_at, since, until):
                continue
            playlist_additions.append(YouTubeActivityItem(
                video=video,
                occurred_at=added_at,
                event_type="playlist_addition",
                playlist_ids=(playlist.id,),
                playlist_names=(playlist_name,),
            ))

    upload_items: list[YouTubeActivityItem] = []
    for video in uploads:
        published = _published_datetime(video.published_at)
        if not published or not _in_window(published, since, until):
            continue
        memberships = own_memberships.get(video.id or "", [])
        upload_items.append(YouTubeActivityItem(
            video=video,
            occurred_at=published,
            event_type="upload",
            playlist_ids=(
                channel.uploads_playlist_id,
                *(item[0] for item in memberships),
            ),
            playlist_names=("Uploads", *(item[1] for item in memberships)),
        ))

    items = [*upload_items, *playlist_additions]
    items.sort(key=lambda item: item.occurred_at)
    return {
        "items": items,
        "count": len(items),
        "uploads": len(upload_items),
        "playlist_additions": len(playlist_additions),
    }


def distill_youtube_video(
    video: DtoYouTubeVideo,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 500,
    event_type: str = "upload",
    playlist_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Create bounded HFL fields while preserving the exact video title."""
    title = (video.title or "Untitled YouTube video").strip()

    def _fallback() -> dict[str, Any]:
        if event_type == "upload":
            moment = f"Uploaded to YouTube: {title}"
            possible_use = "youtube-archive"
            tags = ["youtube", "upload"]
        else:
            playlist = playlist_names[0] if playlist_names else "a playlist"
            moment = f"Added to {playlist}: {title}"
            possible_use = "watch-later"
            tags = ["youtube", "watch-later"]
        return {
            "skip": False,
            "moment": moment[:180],
            "what_happened": title,
            "why_it_stayed": "",
            "possible_use": possible_use,
            "tags": tags,
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()
    prompt = (
        f"Event: {event_type}\nPlaylists: {', '.join(playlist_names) or '(none)'}\n"
        f"Title: {title}\nPublished: {video.published_at or '(unknown)'}\n"
        f"Channel: {video.channel_title or '(unknown)'}\n\n"
        f"Description:\n{(video.description or '').strip()[:40000]}"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            return _fallback()
        response = client.send_message(
            prompt=prompt,
            system=load_prompt("ingest_youtube").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = response.content[0].text if response and response.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        # Collection already guarantees a real video id + event timestamp;
        # every archived event must produce its required one-video HFL entry.
        parsed["skip"] = False
        parsed["moment"] = str(parsed.get("moment") or _fallback()["moment"]).strip()
        parsed["what_happened"] = title
        parsed["why_it_stayed"] = str(parsed.get("why_it_stayed") or "").strip()
        parsed["possible_use"] = str(
            parsed.get("possible_use") or "youtube-archive"
        ).strip()
        parsed["tags"] = [
            str(tag).strip().lstrip("#") for tag in parsed.get("tags") or []
        ]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - synthesis is best-effort
        _log.warning("ingest_youtube: synthesis failed (%s) - raw fallback", exc)
        return _fallback()


def _description_markdown(
    video: DtoYouTubeVideo,
    occurred_at: datetime,
    *,
    event_type: str,
    playlist_names: tuple[str, ...],
) -> str:
    url = f"https://www.youtube.com/watch?v={video.id}"
    return (
        "---\n"
        f"source: youtube\nvideo_id: {video.id}\n"
        f"activity_type: {event_type}\nactivity_at: {occurred_at.isoformat()}\n"
        f"originally_published: {video.published_at or ''}\nurl: {url}\n---\n\n"
        f"# {video.title or 'Untitled YouTube video'}\n\n"
        + (
            f"Playlists: {', '.join(playlist_names)}\n\n"
            if playlist_names
            else ""
        )
        + f"{(video.description or '').rstrip()}\n"
    )


def _existing_video(directory: Path) -> Optional[Path]:
    return next(
        (
            path
            for path in sorted(directory.glob("video.*"))
            if path.suffix.lower() in _VIDEO_EXTENSIONS
        ),
        None,
    )


def _download_video(video_id: str, directory: Path) -> Path:
    """Download with yt-dlp, optionally using YOUTUBE_YT_DLP_COOKIES."""
    existing = _existing_video(directory)
    if existing:
        return existing
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed") from exc
    options: dict[str, Any] = {
        "outtmpl": str(directory / "video.%(ext)s"),
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    cookies = os.environ.get("YOUTUBE_YT_DLP_COOKIES", "").strip()
    if cookies:
        options["cookiefile"] = cookies
    with YoutubeDL(options) as downloader:
        downloader.download([f"https://www.youtube.com/watch?v={video_id}"])
    downloaded = _existing_video(directory)
    if not downloaded:
        raise RuntimeError("yt-dlp completed without producing a video file")
    return downloaded


def archive_youtube_video(
    video: DtoYouTubeVideo,
    archive_root: Path,
    *,
    occurred_at: Optional[datetime] = None,
    event_type: str = "upload",
    playlist_names: tuple[str, ...] = (),
) -> dict[str, str]:
    """Write the curated description and local video into the durable archive."""
    activity_at = occurred_at or _published_datetime(video.published_at)
    if not video.id or not activity_at:
        raise ValueError("video requires id and an activity timestamp")
    directory = archive_root / f"{activity_at:%Y-%m-%d}-{_archive_slug(video.title or '')}"
    directory.mkdir(parents=True, exist_ok=True)
    if event_type == "playlist_addition" and playlist_names:
        description = directory / f"description-{_tag_slug(playlist_names[0])}.md"
    else:
        description = directory / "description.md"
    description.write_text(
        _description_markdown(
            video,
            activity_at,
            event_type=event_type,
            playlist_names=playlist_names,
        ),
        encoding="utf-8",
    )
    downloaded = _download_video(video.id, directory)
    return {
        "directory": str(directory.resolve()),
        "description": str(description.resolve()),
        "video": str(downloaded.resolve()),
    }


@SPROUT.task()
@log_result()
def ingest_youtube_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    days: int | str = "last_month",
    max_videos: Optional[int] = 500,
    max_playlists: Optional[int] = 50,
    max_playlist_items: Optional[int] = 500,
    synthesize: bool = True,
) -> dict[str, Any]:
    """Ingest own uploads and external-video playlist additions."""
    archive_value = os.environ.get("YOUTUBE_ARCHIVE_PATH", "").strip()
    if not archive_value:
        return {
            "skipped": "YOUTUBE_ARCHIVE_PATH not set",
            "entries_written": 0,
            "videos": 0,
        }
    archive_root = Path(archive_value).expanduser().resolve()
    try:
        since, until = _resolve_days(days)
        client = ApiServiceYouTubeData(YOUTUBE_CONFIG)
        collected = collect_youtube_activity(
            since=since,
            until=until,
            client=client,
            max_videos=None if str(days).strip().lower() == "all" else max_videos,
            max_playlists=(
                None if str(days).strip().lower() == "all" else max_playlists
            ),
            max_playlist_items=(
                None
                if str(days).strip().lower() == "all"
                else max_playlist_items
            ),
        )
    except Exception as exc:  # noqa: BLE001 - API/auth errors never break beat
        _log.error("ingest_youtube: collection unavailable (%s)", exc)
        return {"skipped": "youtube unavailable", "entries_written": 0,
                "videos": 0, "error": str(exc)[:200]}
    if not collected["items"]:
        return {"skipped": "no videos", "entries_written": 0, "videos": 0}

    entries_written = 0
    failures: list[dict[str, str]] = []
    persistence_results: list[dict[str, Any]] = []
    for activity_item in collected["items"]:
        video = activity_item.video
        occurred_at = activity_item.occurred_at
        if not video.id:
            continue
        try:
            artifacts = archive_youtube_video(
                video,
                archive_root,
                occurred_at=occurred_at,
                event_type=activity_item.event_type,
                playlist_names=activity_item.playlist_names,
            )
        except Exception as exc:  # noqa: BLE001 - one bad download must not stop the batch
            _log.error("ingest_youtube: archive failed for %s (%s)", video.id, exc)
            failures.append({"video_id": video.id, "error": str(exc)[:200]})
            continue
        distilled = distill_youtube_video(
            video,
            synthesize=synthesize,
            model=model,
            cfg_id=cfg_id__anthropic,
            event_type=activity_item.event_type,
            playlist_names=activity_item.playlist_names,
        )
        if distilled.get("skip"):
            continue
        extra_tags = [
            str(tag).strip().lstrip("#")
            for tag in distilled.get("tags") or []
        ]
        tags = tuple(dict.fromkeys([*activity_item.required_tags, *extra_tags]))
        entry = HflEntry(
            when=occurred_at,
            moment=distilled["moment"],
            what_happened=(video.title or "Untitled YouTube video").strip(),
            why_it_stayed=distilled["why_it_stayed"],
            possible_use=distilled["possible_use"] or "youtube-archive",
            tags=tags,
            references=(
                artifacts["description"],
                artifacts["video"],
                f"https://www.youtube.com/watch?v={video.id}",
            ),
            source="youtube",
        )
        result = submit_hfl_entry(
            entry,
            source="youtube",
            synthesized=distilled.get("synthesized", False),
            dedup_key=f"youtube:{activity_item.identity}",
            es_doc_id=(
                f"{occurred_at:%Y%m%d}-youtube-"
                f"{_tag_slug(activity_item.identity)}"
            ),
        )
        persistence_results.append(result)
        entries_written += 1

    return {
        "entries_written": entries_written,
        "videos": collected["count"],
        "uploads": collected["uploads"],
        "playlist_additions": collected["playlist_additions"],
        "archive_root": str(archive_root),
        "failures": failures,
        "delivery": sorted({
            str(item.get("delivery") or "unknown") for item in persistence_results
        }),
        "paths": [str(item["path"]) for item in persistence_results if item.get("path")],
        "model": model if synthesize else None,
    }
