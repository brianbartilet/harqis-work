"""Tests for the monthly YouTube -> HFL archive ingest."""

from datetime import date
from pathlib import Path

import pytest

from apps.youtube.references.dto.channel import DtoYouTubeChannel
from apps.youtube.references.dto.playlist import DtoYouTubePlaylist
from apps.youtube.references.dto.video import DtoYouTubeVideo
import workflows.hfl.tasks.ingest_youtube as iy


def _video(**overrides):
    values = {
        "id": "vid-123",
        "title": "A Video: With / Characters",
        "description": "Full description\n\nSecond paragraph.",
        "published_at": "2026-06-12T08:30:00Z",
        "channel_id": "my-channel",
        "channel_title": "My channel",
    }
    values.update(overrides)
    return DtoYouTubeVideo(**values)


class _FakeClient:
    def __init__(self, uploads, playlists=(), playlist_items=None):
        self.uploads = list(uploads)
        self.playlists = list(playlists)
        self.playlist_items = playlist_items or {}
        self.calls = []

    def get_my_channel(self):
        return DtoYouTubeChannel(
            id="my-channel",
            title="My channel",
            uploads_playlist_id="uploads",
        )

    def list_playlists(self, max_results=25):
        self.calls.append(("playlists", max_results))
        return list(self.playlists)

    def list_playlist_items(self, playlist_id, max_results=25):
        self.calls.append((playlist_id, max_results))
        if playlist_id == "uploads":
            return list(self.uploads)
        return list(self.playlist_items.get(playlist_id, []))


@pytest.mark.smoke
def test_last_month_is_calendar_bounded():
    assert iy._resolve_days("last_month", today=date(2026, 7, 1)) == (
        date(2026, 6, 1),
        date(2026, 6, 30),
    )
    assert iy._resolve_days(7, today=date(2026, 7, 22)) == (
        date(2026, 7, 16),
        date(2026, 7, 22),
    )
    assert iy._resolve_days("all", today=date(2026, 7, 22)) == (
        None,
        date(2026, 7, 22),
    )


@pytest.mark.smoke
def test_collector_classifies_uploads_and_playlist_additions():
    playlist = DtoYouTubePlaylist(id="PL1", title="Deep Learning")
    own = _video(id="mine", published_at="2026-06-15T00:00:00Z")
    external = _video(
        id="external",
        channel_id="another-channel",
        published_at="2024-01-10T00:00:00Z",
        added_at="2026-06-20T09:00:00Z",
    )
    client = _FakeClient(
        [own],
        playlists=[playlist],
        playlist_items={"PL1": [own, external]},
    )
    result = iy.collect_youtube_activity(
        since=date(2026, 6, 1), until=date(2026, 6, 30), client=client,
    )
    assert result["uploads"] == 1
    assert result["playlist_additions"] == 1
    upload, addition = result["items"]
    assert upload.event_type == "upload"
    assert upload.required_tags == (
        "youtube",
        "upload",
        "playlist-uploads",
        "playlist-deep-learning",
    )
    assert addition.event_type == "playlist_addition"
    assert addition.occurred_at.date() == date(2026, 6, 20)
    assert addition.required_tags == (
        "youtube",
        "watch-later",
        "playlist-deep-learning",
    )


@pytest.mark.smoke
def test_missing_archive_path_is_clean_noop(monkeypatch):
    monkeypatch.delenv("YOUTUBE_ARCHIVE_PATH", raising=False)
    monkeypatch.setattr(
        iy,
        "ApiServiceYouTubeData",
        lambda _config: pytest.fail("YouTube client must not initialize"),
    )
    result = iy.ingest_youtube_activity()
    assert result["entries_written"] == 0
    assert result["skipped"] == "YOUTUBE_ARCHIVE_PATH not set"


@pytest.mark.smoke
def test_archive_contains_full_description_and_video(monkeypatch, tmp_path):
    def fake_download(_video_id: str, directory: Path) -> Path:
        target = directory / "video.mp4"
        target.write_bytes(b"video")
        return target

    monkeypatch.setattr(iy, "_download_video", fake_download)
    artifacts = iy.archive_youtube_video(_video(), tmp_path)

    directory = Path(artifacts["directory"])
    assert directory.name == "2026-06-12-A-Video-With-Characters"
    description = Path(artifacts["description"])
    assert "Full description\n\nSecond paragraph." in description.read_text(
        encoding="utf-8"
    )
    assert Path(artifacts["video"]).read_bytes() == b"video"


@pytest.mark.smoke
def test_distiller_raw_fallback_preserves_required_fields():
    result = iy.distill_youtube_video(_video(), synthesize=False)
    assert result["what_happened"] == "A Video: With / Characters"
    assert result["tags"] == ["youtube", "upload"]
    assert result["synthesized"] is False


@pytest.mark.smoke
def test_one_retroactive_entry_per_video_maps_both_artifacts(monkeypatch, tmp_path):
    video = _video()
    monkeypatch.setenv("YOUTUBE_ARCHIVE_PATH", str(tmp_path))
    playlist = DtoYouTubePlaylist(id="PL1", title="Build Queue")
    monkeypatch.setattr(
        iy,
        "ApiServiceYouTubeData",
        lambda _config: _FakeClient(
            [video],
            playlists=[playlist],
            playlist_items={"PL1": [video]},
        ),
    )

    def fake_archive(_video, root, **_kwargs):
        return {
            "description": str(root / "2026-06-12-title" / "description.md"),
            "video": str(root / "2026-06-12-title" / "video.mp4"),
            "directory": str(root / "2026-06-12-title"),
        }

    monkeypatch.setattr(iy, "archive_youtube_video", fake_archive)
    submitted = []

    def fake_submit(entry, **kwargs):
        submitted.append((entry, kwargs))
        return {"delivery": "persisted", "path": str(tmp_path / "2026-06-12.md")}

    monkeypatch.setattr(iy, "submit_hfl_entry", fake_submit)
    result = iy.ingest_youtube_activity(days="all", synthesize=False)

    assert result["entries_written"] == 1
    entry, kwargs = submitted[0]
    assert entry.when.date() == date(2026, 6, 12)
    assert entry.what_happened == video.title
    assert entry.source == "youtube"
    assert entry.tags[:4] == (
        "youtube",
        "upload",
        "playlist-uploads",
        "playlist-build-queue",
    )
    assert entry.references[0].endswith("description.md")
    assert entry.references[1].endswith("video.mp4")
    assert entry.references[2] == "https://www.youtube.com/watch?v=vid-123"
    assert kwargs["source"] == "youtube"
    assert kwargs["dedup_key"] == "youtube:upload:vid-123"
    assert kwargs["es_doc_id"] == "20260612-youtube-upload-vid-123"


@pytest.mark.smoke
def test_external_playlist_entry_uses_added_timestamp_and_watch_later(monkeypatch, tmp_path):
    playlist = DtoYouTubePlaylist(id="PL2", title="Watch Soon")
    external = _video(
        id="external",
        channel_id="someone-else",
        published_at="2020-03-04T00:00:00Z",
        added_at="2026-06-22T17:45:00Z",
    )
    client = _FakeClient(
        [],
        playlists=[playlist],
        playlist_items={"PL2": [external]},
    )
    monkeypatch.setenv("YOUTUBE_ARCHIVE_PATH", str(tmp_path))
    monkeypatch.setattr(iy, "ApiServiceYouTubeData", lambda _config: client)
    monkeypatch.setattr(
        iy,
        "archive_youtube_video",
        lambda _video, root, **_kwargs: {
            "description": str(root / "description.md"),
            "video": str(root / "video.mp4"),
            "directory": str(root),
        },
    )
    submitted = []
    monkeypatch.setattr(
        iy,
        "submit_hfl_entry",
        lambda entry, **kwargs: submitted.append((entry, kwargs))
        or {"delivery": "persisted", "path": ""},
    )

    result = iy.ingest_youtube_activity(days="all", synthesize=False)

    assert result["playlist_additions"] == 1
    entry, kwargs = submitted[0]
    assert entry.when.date() == date(2026, 6, 22)
    assert entry.tags[:3] == (
        "youtube",
        "watch-later",
        "playlist-watch-soon",
    )
    assert entry.references[2] == (
        "https://www.youtube.com/watch?v=external"
    )
    assert kwargs["dedup_key"] == (
        "youtube:playlist:PL2:external:2026-06-22T17:45:00"
    )


@pytest.mark.smoke
def test_all_scan_removes_api_limit(monkeypatch, tmp_path):
    client = _FakeClient([])
    monkeypatch.setenv("YOUTUBE_ARCHIVE_PATH", str(tmp_path))
    monkeypatch.setattr(iy, "ApiServiceYouTubeData", lambda _config: client)
    result = iy.ingest_youtube_activity(days="all", synthesize=False)
    assert result["skipped"] == "no videos"
    assert ("uploads", None) in client.calls
    assert ("playlists", None) in client.calls


@pytest.mark.skip(reason="Manual only - live YouTube OAuth, yt-dlp, Anthropic, corpus, and ES")
def test_full_pipeline_live():
    iy.ingest_youtube_activity(days="last_month")
