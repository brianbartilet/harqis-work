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
