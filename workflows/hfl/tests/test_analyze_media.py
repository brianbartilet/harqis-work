"""
Tests for the location-enrichment helpers in workflows/hfl/tasks/analyze_media.py.

The vision pass itself needs real media + a live Anthropic call, so it isn't
unit-tested; these cover the EXIF / OwnTracks geo-resolution layered on top
(EXIF GPS preferred, OwnTracks-by-time fallback, reverse-geocode), all hermetic.
"""

from datetime import datetime
from pathlib import Path

from workflows.hfl.tasks.analyze_media import (
    _dms_to_deg,
    _resolve_media_location,
    classify_android_media_candidate,
)

_MOD = "workflows.hfl.tasks.analyze_media"


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
    result = classify_android_media_candidate(Path("android-phone/Screenshots/shot.png"))
    assert result == {"capture_type": "screenshot", "device_type": "android"}


def test__classify_android_screenshot_case_insensitive():
    """Classification is case-insensitive for the folder name."""
    result = classify_android_media_candidate(Path("Pixel6/SCREENSHOTS/2026-01-01.jpg"))
    assert result == {"capture_type": "screenshot", "device_type": "android"}


def test__classify_android_camera_photo():
    """Path containing 'DCIM' or 'Camera' → photo capture type."""
    assert classify_android_media_candidate(
        Path("android-phone/DCIM/Camera/IMG_001.jpg")
    ) == {"capture_type": "photo", "device_type": "android"}
    assert classify_android_media_candidate(
        Path("android-phone/Camera/photo.jpg")
    ) == {"capture_type": "photo", "device_type": "android"}


def test__classify_android_screen_recording():
    """Path containing 'Screen recordings' or 'Screenrecord' → screen_recording."""
    assert classify_android_media_candidate(
        Path("phone/Screen recordings/clip.mp4")
    ) == {"capture_type": "screen_recording", "device_type": "android"}
    assert classify_android_media_candidate(
        Path("phone/Screenrecord/clip.mp4")
    ) == {"capture_type": "screen_recording", "device_type": "android"}


def test__classify_android_non_android_paths():
    """Desktop or unrecognised folders → None (not Android)."""
    assert classify_android_media_candidate(Path("desktop/Downloads/file.png")) is None
    assert classify_android_media_candidate(Path("macbook/Documents/scan.jpg")) is None
    assert classify_android_media_candidate(Path("shot.png")) is None


def test__classify_android_filename_not_matched():
    """The filename itself is excluded from classification — only parent dirs matter."""
    # A file named 'screenshot.png' at the root should NOT match.
    assert classify_android_media_candidate(Path("screenshot.png")) is None
    # But the same name inside a Screenshots folder should.
    assert classify_android_media_candidate(
        Path("Screenshots/screenshot.png")
    ) == {"capture_type": "screenshot", "device_type": "android"}
