"""
Tests for the location-enrichment helpers in workflows/hfl/tasks/analyze_media.py.

The vision pass itself needs real media + a live Anthropic call, so it isn't
unit-tested; these cover the EXIF / OwnTracks geo-resolution layered on top
(EXIF GPS preferred, OwnTracks-by-time fallback, reverse-geocode), all hermetic.
"""

from datetime import datetime
from inspect import signature
from pathlib import Path
from types import SimpleNamespace

import pytest

from workflows.dumps.files import CollectedFile
from workflows.hfl.tasks_config import WORKFLOW_HFL
from workflows.hfl.tasks.analyze_media import (
    _acquire_media_claim,
    _dms_to_deg,
    _filter_processed_media,
    _finish_media_claim,
    _media_reference_exists,
    _resolve_media_location,
    _secure_media_snapshot,
    _select_media_candidates,
    _target_media_candidate,
    analyze_hfl_media,
    classify_android_media_candidate,
)

_MOD = "workflows.hfl.tasks.analyze_media"


def _symlink_or_skip(link: Path, target: Path) -> None:
    """Create a test symlink or skip on Windows without symlink privilege."""
    try:
        link.symlink_to(target)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows symlink privilege is unavailable")
        raise


def test__dms_to_deg_signs_and_values():
    # 1° 18' 7.2" -> 1.302; sign flips for S/W.
    assert round(_dms_to_deg((1, 18, 7.2), "N"), 4) == 1.302
    assert round(_dms_to_deg((1, 18, 7.2), "S"), 4) == -1.302
    assert round(_dms_to_deg((103, 51, 0), "E"), 4) == 103.85
    assert round(_dms_to_deg((103, 51, 0), "W"), 4) == -103.85
    assert _dms_to_deg(None, "N") is None
    assert _dms_to_deg(("x", "y", "z"), "N") is None


def test__resolve_media_location_prefers_exif(monkeypatch):
    """EXIF GPS wins over OwnTracks when present."""
    monkeypatch.setattr(f"{_MOD}._exif_location_and_time",
                        lambda p: ((1.5, 103.8), datetime(2026, 5, 1, 9, 0)))
    # If EXIF coords exist, OwnTracks must not override them.
    monkeypatch.setattr(f"{_MOD}.nearest_fix", lambda *a, **k: (9.9, 9.9))
    monkeypatch.setattr(f"{_MOD}._reverse_geocode",
                        lambda lat, lon, **k: f"P({lat},{lon})")
    place, coords, source = _resolve_media_location(
        Path("x.jpg"), datetime(2026, 5, 1, 8, 0), True, geocode_cache={},
    )
    assert coords == (1.5, 103.8)
    assert source == "exif"
    assert place == "P(1.5,103.8)"


def test__resolve_media_location_falls_back_to_owntracks(monkeypatch):
    """No EXIF GPS → match capture time to the nearest OwnTracks fix."""
    monkeypatch.setattr(f"{_MOD}._exif_location_and_time", lambda p: (None, None))
    monkeypatch.setattr(f"{_MOD}.nearest_fix", lambda when, **k: (2.0, 104.0))
    monkeypatch.setattr(f"{_MOD}._reverse_geocode", lambda lat, lon, **k: "Fallback Place")
    place, coords, source = _resolve_media_location(
        Path("shot.png"), datetime(2026, 5, 1, 8, 0), True, geocode_cache={},
    )
    assert (place, coords, source) == ("Fallback Place", (2.0, 104.0), "owntracks")


def test__resolve_media_location_none_when_no_geo(monkeypatch):
    """No EXIF and no OwnTracks fix → media is still analyzed, just place-less."""
    monkeypatch.setattr(f"{_MOD}._exif_location_and_time", lambda p: (None, None))
    monkeypatch.setattr(f"{_MOD}.nearest_fix", lambda when, **k: None)
    assert _resolve_media_location(
        Path("x.png"), datetime(2026, 5, 1, 8, 0), True, geocode_cache={},
    ) == (None, None, None)


# ---------------------------------------------------------------------------
# classify_android_media_candidate
# ---------------------------------------------------------------------------

def test__classify_android_screenshot():
    """Path containing 'Screenshots' folder → screenshot capture type."""
    result = classify_android_media_candidate(Path("nothing-phone-daily-dumps-2026-07-19/Screenshots/shot.png"))
    assert result == {"capture_type": "screenshot", "device_type": "android"}


def test__classify_android_screenshot_case_insensitive():
    """Classification is case-insensitive for the folder name."""
    result = classify_android_media_candidate(Path("NOTHING-PHONE-DAILY-DUMPS-2026-07-19/SCREENSHOTS/2026-01-01.jpg"))
    assert result == {"capture_type": "screenshot", "device_type": "android"}


def test__classify_android_camera_photo():
    """Path containing 'DCIM' or 'Camera' → photo capture type."""
    assert classify_android_media_candidate(
        Path("nothing-phone-daily-dumps-2026-07-19/DCIM/Camera/IMG_001.jpg")
    ) == {"capture_type": "photo", "device_type": "android"}
    assert classify_android_media_candidate(
        Path("nothing-phone-daily-dumps-2026-07-19/Camera/photo.jpg")
    ) == {"capture_type": "photo", "device_type": "android"}


def test__classify_android_screen_recording():
    """Path containing 'Screen recordings' or 'Screenrecord' → screen_recording."""
    assert classify_android_media_candidate(
        Path("nothing-phone-daily-dumps-2026-07-19/Screen recordings/clip.mp4")
    ) == {"capture_type": "screen_recording", "device_type": "android"}
    assert classify_android_media_candidate(
        Path("nothing-phone-daily-dumps-2026-07-19/Screenrecord/clip.mp4")
    ) == {"capture_type": "screen_recording", "device_type": "android"}


def test__classify_android_non_android_paths():
    """Desktop or unrecognised folders → None (not Android)."""
    assert classify_android_media_candidate(Path("desktop/Downloads/file.png")) is None
    assert classify_android_media_candidate(Path("macbook/Documents/scan.jpg")) is None
    assert classify_android_media_candidate(Path("shot.png")) is None
    assert classify_android_media_candidate(
        Path("windows-work-all-daily-dumps-2026-07-19/Screenshots/shot.png")
    ) is None


def test__classify_android_filename_not_matched():
    """The filename itself is excluded from classification — only parent dirs matter."""
    # A file named 'screenshot.png' at the root should NOT match.
    assert classify_android_media_candidate(Path("screenshot.png")) is None
    # A generic Screenshots folder is not enough without Android provenance.
    assert classify_android_media_candidate(
        Path("Screenshots/screenshot.png")
    ) is None


def test__classify_android_requires_exact_canonical_dump_source():
    """Prefix-like and generic source names cannot claim Android provenance."""
    rejected = (
        "pixelbook-daily-dumps-2026-07-19/Screenshots/shot.png",
        "android-studio-daily-dumps-2026-07-19/Screenshots/shot.png",
        "nothing-phonebook-daily-dumps-2026-07-19/Screenshots/shot.png",
        "nothing-phone/Screenshots/shot.png",
    )
    assert all(classify_android_media_candidate(Path(path)) is None for path in rejected)


# ---------------------------------------------------------------------------
# source-aware selection + targeted ingest
# ---------------------------------------------------------------------------

def _candidate(root: Path, relative: str, minute: int) -> CollectedFile:
    return CollectedFile(
        source_root=root,
        path=root / relative,
        relative=Path(relative),
        mtime=datetime(2026, 7, 19, 12, minute),
    )


def test__select_media_candidates_reserves_android_slots(tmp_path):
    """Newer desktop captures cannot consume Android's reserved capacity."""
    desktop = [
        _candidate(tmp_path, f"desktop/Downloads/shot-{i}.png", 59 - i)
        for i in range(12)
    ]
    android = [
        _candidate(tmp_path, f"nothing-phone-daily-dumps-2026-07-19/Screenshots/phone-{i}.png", i)
        for i in range(3)
    ]

    selected = _select_media_candidates(
        desktop + android, max_files=10, android_min_files=3,
    )

    assert len(selected) == 10
    assert sum(bool(classify_android_media_candidate(c.relative)) for c in selected) == 3
    assert {c.path for c in android}.issubset({c.path for c in selected})


def test__select_media_candidates_fills_unused_android_slots(tmp_path):
    """A quiet phone does not reduce the total batch capacity."""
    desktop = [
        _candidate(tmp_path, f"desktop/Downloads/file-{i}.jpg", i)
        for i in range(8)
    ]

    selected = _select_media_candidates(
        desktop, max_files=5, android_min_files=3,
    )

    assert [c.path.name for c in selected] == [
        "file-7.jpg", "file-6.jpg", "file-5.jpg", "file-4.jpg", "file-3.jpg",
    ]


def test__scheduled_media_kwargs_bind_to_task_signature():
    """Beat configuration cannot silently drift from the task's public kwargs."""
    kwargs = WORKFLOW_HFL["run-job--analyze_hfl_media"]["kwargs"]

    signature(analyze_hfl_media).bind_partial(**kwargs)
    assert kwargs["max_files"] == 40
    assert kwargs["android_min_files"] == 10


def test__processed_android_media_is_removed_before_quota_selection(tmp_path):
    """Referenced phone items cannot consume slots needed by pending phone media."""
    corpus = tmp_path / "hfl"
    corpus.mkdir()
    desktop = [
        _candidate(tmp_path, f"windows-work/Downloads/file-{i}.jpg", 50 + i)
        for i in range(8)
    ]
    android = [
        _candidate(tmp_path, f"nothing-phone-daily-dumps-2026-07-19/Screenshots/phone-{i}.png", 10 + i)
        for i in range(5)
    ]
    day_file = corpus / "2026-07-19.md"
    day_file.write_text(
        "## 2026-07-19 12:00\nMoment: processed media\nReferences:\n"
        + "".join(f"                 - {item.path.resolve()}\n" for item in android[:3])
        + "\n",
        encoding="utf-8",
    )

    pending, duplicates = _filter_processed_media(desktop + android, corpus)
    selected = _select_media_candidates(
        pending, max_files=5, android_min_files=3,
    )

    assert duplicates == 3
    assert {item.path for item in android[3:]}.issubset({item.path for item in selected})


def test__canonical_aliases_do_not_consume_multiple_quota_slots(tmp_path):
    corpus = tmp_path / "hfl"
    corpus.mkdir()
    source = tmp_path / "nothing-phone-daily-dumps-2026-07-19" / "Screenshots"
    source.mkdir(parents=True)
    media = source / "shot.png"
    media.write_bytes(b"png")
    alias = source / "alias.png"
    _symlink_or_skip(alias, media)
    when = datetime.now()
    candidates = [
        CollectedFile(tmp_path, media, media.relative_to(tmp_path), when),
        CollectedFile(tmp_path, alias, alias.relative_to(tmp_path), when),
    ]

    pending, duplicates = _filter_processed_media(candidates, corpus)

    assert len(pending) == 1
    assert pending[0].path == media.resolve()
    assert duplicates == 1


def test__media_claim_is_atomic_and_persists_completion(tmp_path):
    media = tmp_path / "dumps" / "nothing-phone" / "Screenshots" / "shot.png"
    first = _acquire_media_claim(tmp_path / "hfl", media)

    assert first is not None
    assert _acquire_media_claim(tmp_path / "hfl", media) is None

    _finish_media_claim(first, completed=True)
    assert _acquire_media_claim(tmp_path / "hfl", media) is None


def test__media_claim_release_is_retryable_with_persistent_lock_file(tmp_path):
    """FD lock release permits retry without deleting/replacing the lock path."""
    media = tmp_path / "dumps" / "shot.png"
    first = _acquire_media_claim(tmp_path / "hfl", media)
    assert first is not None
    lock_path, done_path, _fd = first

    _finish_media_claim(first, completed=False)
    second = _acquire_media_claim(tmp_path / "hfl", media)

    assert lock_path.exists()
    assert not done_path.exists()
    assert second is not None
    _finish_media_claim(second, completed=False)


def test__media_reference_exists_matches_exact_source_path(tmp_path):
    media = (tmp_path / "nothing-phone" / "Screenshots" / "shot.png").resolve()
    day_file = tmp_path / "2026-07-19.md"
    day_file.write_text(
        "## 2026-07-19 12:00\nMoment: kept\nReferences:\n"
        f"                 - {media}\n\n",
        encoding="utf-8",
    )

    assert _media_reference_exists(day_file, media) is True
    assert _media_reference_exists(day_file, media.with_name("other.png")) is False


def test__media_reference_ignores_incomplete_tail_entry(tmp_path):
    media = (tmp_path / "shot.png").resolve()
    day_file = tmp_path / "2026-07-19.md"
    day_file.write_text(
        "## 2026-07-19 12:00\nMoment: partial\nReferences:\n"
        f"                 - {media}\n",
        encoding="utf-8",
    )

    assert _media_reference_exists(day_file, media) is False


def test__partial_entry_stays_retryable_after_later_complete_entry(tmp_path):
    partial = (tmp_path / "partial.png").resolve()
    complete = (tmp_path / "complete.png").resolve()
    day_file = tmp_path / "2026-07-19.md"
    day_file.write_text(
        "## 2026-07-19 12:00\nMoment: partial\nReferences:\n"
        f"                 - {partial}\n"
        "## 2026-07-19 12:01\nMoment: complete\nReferences:\n"
        f"                 - {complete}\n\n",
        encoding="utf-8",
    )

    assert _media_reference_exists(day_file, partial) is False
    assert _media_reference_exists(day_file, complete) is True


def test__target_media_candidate_accepts_media_inside_inbox(tmp_path):
    media = tmp_path / "nothing-phone-daily-dumps-2026-07-19" / "Screenshots" / "shot.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"png")

    item = _target_media_candidate(tmp_path, media)

    assert item.source_root == tmp_path.resolve()
    assert item.path == media.resolve()
    assert item.relative == media.relative_to(tmp_path)


def test__target_media_candidate_rejects_path_outside_inbox(tmp_path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"png")

    try:
        _target_media_candidate(tmp_path, outside)
    except ValueError as exc:
        assert "outside dumps inbox" in str(exc)
    else:
        raise AssertionError("outside path must be rejected")


def test__target_media_candidate_rejects_symlink_escape(tmp_path):
    inbox = tmp_path / "dumps"
    inbox.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    link = inbox / "shot.png"
    _symlink_or_skip(link, outside)

    try:
        _target_media_candidate(inbox, link)
    except ValueError as exc:
        assert "outside dumps inbox" in str(exc)
    else:
        raise AssertionError("symlink escape must be rejected")


def test__secure_snapshot_blocks_swap_between_resolve_and_open(tmp_path, monkeypatch):
    inbox = tmp_path / "dumps"
    media = inbox / "desktop" / "shot.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"inside")
    outside = tmp_path / "private.png"
    outside.write_bytes(b"outside")
    probe = inbox / "symlink-probe.png"
    _symlink_or_skip(probe, outside)
    probe.unlink()
    item = CollectedFile(
        source_root=inbox,
        path=media,
        relative=media.relative_to(inbox),
        mtime=datetime.now(),
    )
    real_open = __import__("os").open
    swapped = False

    def swapping_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        is_source_open = (
            (dir_fd is not None and path == media.name)
            or (dir_fd is None and Path(path) == media)
        )
        if is_source_open and not swapped:
            swapped = True
            media.unlink()
            media.symlink_to(outside)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(f"{_MOD}.os.open", swapping_open)

    try:
        _secure_media_snapshot(inbox, item)
    except (OSError, ValueError):
        pass
    else:
        raise AssertionError("secure open must reject the swapped final component")
    assert swapped is True


def test__secure_snapshot_copies_confined_file(tmp_path):
    inbox = tmp_path / "dumps"
    media = inbox / "desktop" / "shot.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"inside")
    item = CollectedFile(
        source_root=inbox,
        path=media,
        relative=media.relative_to(inbox),
        mtime=datetime.now(),
    )

    snapshot, safe_item = _secure_media_snapshot(inbox, item)
    try:
        assert snapshot.read_bytes() == b"inside"
        assert safe_item.path == media.resolve()
        assert safe_item.relative == media.relative_to(inbox)
    finally:
        snapshot.unlink(missing_ok=True)


def test__batch_revalidates_symlink_before_media_read(tmp_path, monkeypatch):
    """A post-collection symlink swap cannot redirect a batch read outside inbox."""
    inbox = tmp_path / "dumps"
    inside = inbox / "desktop" / "shot.png"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"inside")
    link = inbox / "selected.png"
    _symlink_or_skip(link, inside)
    outside = tmp_path / "private.png"
    outside.write_bytes(b"outside")
    item = CollectedFile(
        source_root=inbox,
        path=link,
        relative=Path("selected.png"),
        mtime=datetime.now(),
    )
    corpus = tmp_path / "hfl"
    monkeypatch.setattr(
        f"{_MOD}.get_dumps_target", lambda: SimpleNamespace(inbox=inbox),
    )
    monkeypatch.setattr(f"{_MOD}.iter_recent_files", lambda *_args: iter([item]))
    monkeypatch.setattr(f"{_MOD}.resolve_corpus_dir", lambda: corpus)
    monkeypatch.setattr(f"{_MOD}.get_anthropic_config", lambda _cfg: object())

    class SwapClient:
        base_client = object()

        def __init__(self, _config):
            inside.unlink()
            _symlink_or_skip(inside, outside)

        def send_messages(self, **_kwargs):
            raise AssertionError("escaped media must never reach the model")

    monkeypatch.setattr(f"{_MOD}.BaseApiServiceAnthropic", SwapClient)

    result = analyze_hfl_media(window_days=1, max_files=1)

    assert result["entries_written"] == 0
    assert result["skipped"] == 1


def test__targeted_duplicate_skips_before_anthropic_init(tmp_path, monkeypatch):
    """An idempotent targeted retry must not spend a second vision call."""
    inbox = tmp_path / "dumps"
    media = inbox / "nothing-phone" / "Screenshots" / "shot.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"png")
    captured = datetime.fromtimestamp(media.stat().st_mtime)

    corpus = tmp_path / "hfl"
    corpus.mkdir()
    (corpus / f"{captured:%Y-%m-%d}.md").write_text(
        f"## {captured:%Y-%m-%d %H:%M}\nReferences:\n                 - {media.resolve()}\n\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        f"{_MOD}.get_dumps_target", lambda: SimpleNamespace(inbox=inbox),
    )
    monkeypatch.setattr(f"{_MOD}.resolve_corpus_dir", lambda: corpus)

    class UnexpectedClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Anthropic must not initialize for a duplicate")

    monkeypatch.setattr(f"{_MOD}.BaseApiServiceAnthropic", UnexpectedClient)

    result = analyze_hfl_media(media_path=str(media))

    assert result == {
        "skipped": "already ingested",
        "entries_written": 0,
        "scanned": 1,
        "duplicates": 1,
        "targeted": True,
    }


def _configure_targeted_model_test(tmp_path, monkeypatch, response_text):
    inbox = tmp_path / "dumps"
    media = inbox / "nothing-phone-daily-dumps-2026-07-19" / "Screenshots" / "shot.png"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"png")
    corpus = tmp_path / "hfl"
    monkeypatch.setattr(
        f"{_MOD}.get_dumps_target", lambda: SimpleNamespace(inbox=inbox),
    )
    monkeypatch.setattr(f"{_MOD}.resolve_corpus_dir", lambda: corpus)
    monkeypatch.setattr(f"{_MOD}.get_anthropic_config", lambda _cfg: object())
    monkeypatch.setattr(
        f"{_MOD}._encode_image", lambda _path: {"type": "image"},
    )
    monkeypatch.setattr(
        f"{_MOD}._resolve_media_location",
        lambda *_args, **_kwargs: (None, None, None),
    )

    class FakeClient:
        base_client = object()

        def __init__(self, _config):
            pass

        def send_messages(self, **_kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(text=response_text)],
            )

    monkeypatch.setattr(f"{_MOD}.BaseApiServiceAnthropic", FakeClient)
    return inbox, media, corpus


def test__malformed_model_response_releases_claim_for_retry(tmp_path, monkeypatch):
    """Transport/schema failures must not permanently consume the media item."""
    _inbox, media, corpus = _configure_targeted_model_test(
        tmp_path, monkeypatch, "not-json",
    )

    result = analyze_hfl_media(media_path=str(media))
    retry_claim = _acquire_media_claim(corpus, media)

    assert result["entries_written"] == 0
    assert result["skipped"] == 1
    assert retry_claim is not None
    _finish_media_claim(retry_claim, completed=False)


def test__wrong_model_schema_releases_claim_for_retry(tmp_path, monkeypatch):
    _inbox, media, corpus = _configure_targeted_model_test(
        tmp_path, monkeypatch,
        '{"skip": false, "moment": {"bad": true}, "what_happened": "x", '
        '"why_it_stayed": "x", "possible_use": "x", "tags": "abc"}',
    )

    result = analyze_hfl_media(media_path=str(media))
    retry_claim = _acquire_media_claim(corpus, media)

    assert result["entries_written"] == 0
    assert retry_claim is not None
    _finish_media_claim(retry_claim, completed=False)


def test__partial_append_failure_remains_retryable(tmp_path, monkeypatch):
    valid = (
        '{"skip": false, "moment": "kept", "what_happened": "x", '
        '"why_it_stayed": "x", "possible_use": "x", "tags": ["android"]}'
    )
    _inbox, media, corpus = _configure_targeted_model_test(
        tmp_path, monkeypatch, valid,
    )
    calls = 0

    def flaky_append(day_file, entry, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            day_file.write_text(
                f"## partial\nReferences:\n                 - {media.resolve()}\n",
                encoding="utf-8",
            )
            raise OSError("simulated partial append")
        return 1, None

    monkeypatch.setattr(f"{_MOD}.append_entry", flaky_append)

    first = analyze_hfl_media(media_path=str(media))
    second = analyze_hfl_media(media_path=str(media))

    assert first["entries_written"] == 0
    assert second["entries_written"] == 1
    assert calls == 2


def test__explicit_semantic_skip_is_terminal(tmp_path, monkeypatch):
    """A valid story-worthiness skip is a completed semantic decision."""
    _inbox, media, corpus = _configure_targeted_model_test(
        tmp_path, monkeypatch,
        '{"skip": true, "moment": "", "what_happened": "", '
        '"why_it_stayed": "", "possible_use": "", "tags": []}',
    )

    result = analyze_hfl_media(media_path=str(media))

    assert result["entries_written"] == 0
    assert result["skipped"] == 1
    assert _acquire_media_claim(corpus, media) is None
