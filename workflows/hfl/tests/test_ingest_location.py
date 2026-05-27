"""
Tests for workflows/hfl/tasks/ingest_location.py.

Integration tests call the real task exactly as Beat will. With no OwnTracks
user/device configured the task is a guaranteed no-op — no Recorder call, no
LLM, no side-effects. The live path (real Recorder + Anthropic synthesis +
corpus/ES write) is marked skip. Unit tests exercise the stay-point clustering,
place-label, and raw-fallback distiller with no network.
"""

from datetime import date, datetime, timedelta

import pytest

from workflows.hfl.tasks.ingest_location import (
    _activity_body,
    _cluster_stays,
    _haversine_m,
    _movement_only_entry,
    _osm_link,
    _place_tags,
    _short_place,
    collect_location_activity,
    distill_location_activity,
    ingest_location_activity,
    nearest_fix,
)


def _svc_returning(data):
    """A stand-in ApiServiceOwnTracksLocations whose get_history returns data."""
    return lambda *a, **k: type("S", (), {"get_history": lambda self, **kw: data})()


def _track(start: datetime, fixes):
    """fixes: list of (offset_min, lat, lon) -> point dicts the collector emits."""
    return [
        {"lat": lat, "lon": lon, "tst": int((start + timedelta(minutes=off)).timestamp())}
        for off, lat, lon in fixes
    ]


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__ingest_location_activity_no_device(monkeypatch):
    """No OwnTracks user/device → clean no-op, no Recorder call, no LLM."""
    monkeypatch.delenv("OWN_TRACKS_DEFAULT_USER", raising=False)
    monkeypatch.delenv("OWN_TRACKS_DEFAULT_DEVICE", raising=False)
    result = ingest_location_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no device configured"


def test__ingest_location_activity_no_stays(monkeypatch):
    """A configured device with an empty track → no entry, no LLM call."""
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_USER", "brian")
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_DEVICE", "android")
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.ApiServiceOwnTracksLocations",
        lambda *a, **k: type("S", (), {"get_history": lambda self, **kw: {"data": []}})(),
    )
    result = ingest_location_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no stays"


def test__ingest_location_activity_movement_only_fallback(monkeypatch, tmp_path):
    """GPS fixes with no qualifying stay still write a location breadcrumb."""
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_USER", "brian")
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_DEVICE", "android")

    now = datetime.now().replace(microsecond=0)
    # 10 min near one point: enough signal to prove GPS is alive, but below the
    # default 15-min dwell threshold.
    track = _track(now, [(0, 1.3000, 103.8000), (5, 1.3001, 103.8001),
                         (10, 1.3000, 103.8000)])
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.ApiServiceOwnTracksLocations",
        lambda *a, **k: type("S", (), {"get_history": lambda self, **kw: {"data": track}})(),
    )
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.resolve_corpus_dir", lambda: tmp_path
    )
    indexed = []
    monkeypatch.setattr(
        "workflows.hfl.tasks.capture.index_hfl_entry",
        lambda entry, *, source, synthesized=False: indexed.append((source, synthesized)) or "doc-1",
    )

    result = ingest_location_activity(cfg_id__anthropic="ANTHROPIC")

    assert result["entries_written"] == 1
    assert result["stays"] == 0
    assert result["points"] == 3
    assert result["synthesized"] is False
    assert result["indexed"] is True
    assert indexed == [("location", False)]
    written = (tmp_path / f"{datetime.now():%Y-%m-%d}.md").read_text(encoding="utf-8")
    assert "Recorded movement but no qualifying location stay" in written
    assert "movement-only" in written
    assert "openstreetmap.org" not in written


def test__ingest_location_activity_dual_write_contract(monkeypatch, tmp_path):
    """A real in-window stay must drive BOTH the corpus write and the ES index
    call (the mandatory dual-write contract)."""
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_USER", "brian")
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_DEVICE", "android")

    now = datetime.now().replace(microsecond=0)
    # ~40 min stationary at one point → one stay-point.
    track = _track(now, [(0, 1.3000, 103.8000), (20, 1.3001, 103.8001),
                         (40, 1.3000, 103.8000)])
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.ApiServiceOwnTracksLocations",
        lambda *a, **k: type("S", (), {"get_history": lambda self, **kw: {"data": track}})(),
    )
    # No network geocode, no Anthropic call, corpus into tmp, capture ES write.
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location._reverse_geocode",
        lambda lat, lon, **kw: "Test Plaza",
    )
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.distill_location_activity",
        lambda activity, **kw: {
            "skip": False, "moment": "spent the morning at Test Plaza",
            "what_happened": "a long stop at Test Plaza", "why_it_stayed": "",
            "possible_use": "timeline", "tags": ["test-plaza"],
            "synthesized": False,
        },
    )
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.resolve_corpus_dir", lambda: tmp_path
    )
    indexed = []
    monkeypatch.setattr(
        "workflows.hfl.tasks.capture.index_hfl_entry",
        lambda entry, *, source, synthesized=False: indexed.append(source) or "doc-1",
    )

    result = ingest_location_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 1
    assert result["indexed"] is True
    assert indexed == ["location"]  # ES dual-write happened
    written = (tmp_path / f"{datetime.now():%Y-%m-%d}.md").read_text(encoding="utf-8")
    assert "Test Plaza" in written  # corpus write happened
    assert "openstreetmap.org" in written  # provenance reference rendered


@pytest.mark.skip(reason="Manual only — reads the live OwnTracks Recorder + "
                         "real Anthropic synthesis; appends a real entry to "
                         "today's corpus and the ES index.")
def test__ingest_location_activity_full_pipeline():
    result = ingest_location_activity(cfg_id__anthropic="ANTHROPIC", window_days=1)
    assert result["entries_written"] in (0, 1)


# ── Unit / function ───────────────────────────────────────────────────────────

def test__haversine_known_distance():
    # ~111 m for 0.001 deg of latitude near the equator.
    d = _haversine_m(1.3000, 103.8000, 1.3010, 103.8000)
    assert 100 < d < 125


def test__cluster_stays_separates_stay_from_transit():
    now = datetime(2026, 5, 17, 8, 0, 0)
    # Stay A (40 min near point 1), a transit jump, then Stay B (30 min near point 2).
    track = _track(now, [
        (0, 1.3000, 103.8000), (20, 1.3001, 103.8000), (40, 1.3000, 103.8001),
        (50, 1.3200, 103.8200),  # transit — far, single fix
        (60, 1.3500, 103.8500), (75, 1.3501, 103.8500), (90, 1.3500, 103.8501),
    ])
    stays = _cluster_stays(track, radius_m=150, min_dwell_min=15, max_gap_min=90)
    assert len(stays) == 2
    assert stays[0]["dwell_min"] >= 15 and stays[1]["dwell_min"] >= 15
    assert stays[0]["arrive"] < stays[1]["arrive"]


def test__cluster_stays_drops_short_dwell():
    now = datetime(2026, 5, 17, 8, 0, 0)
    track = _track(now, [(0, 1.30, 103.80), (5, 1.30, 103.80)])  # only 5 min
    assert _cluster_stays(track, radius_m=150, min_dwell_min=15, max_gap_min=90) == []


def test__cluster_stays_gap_breaks_a_stay():
    now = datetime(2026, 5, 17, 8, 0, 0)
    # Same place, but a 120-min gap (> max_gap_min) splits it; neither half
    # alone clears the dwell threshold.
    track = _track(now, [(0, 1.30, 103.80), (10, 1.30, 103.80),
                         (130, 1.30, 103.80), (140, 1.30, 103.80)])
    stays = _cluster_stays(track, radius_m=150, min_dwell_min=15, max_gap_min=90)
    assert stays == []


def test__short_place_prefers_name_then_locality():
    assert _short_place({"name": "Marina Bay Sands",
                         "address": {"suburb": "Downtown Core"}}) == \
        "Marina Bay Sands, Downtown Core"
    assert _short_place({"address": {"road": "Orchard Rd", "city": "Singapore"}}) == \
        "Orchard Rd, Singapore"
    assert _short_place({"display_name": "Somewhere, A, B, C"}) == "Somewhere"
    assert _short_place({}) is None


def test__place_tags_and_osm_link():
    stays = [{"place": "Marina Bay Sands, Downtown"}, {"place": "VivoCity"}]
    tags = _place_tags(stays)
    assert tags[0] == "location"
    assert "marina-bay-sands" in tags and "vivocity" in tags
    assert _osm_link(1.2345, 103.8) .startswith("https://www.openstreetmap.org/?mlat=1.23450")


def test__movement_only_entry_is_deterministic_no_api():
    activity = {
        "point_count": 7,
        "stay_count": 0,
        "stays": [],
        "window": {"from": 1_700_000_000, "to": 1_700_003_600},
    }
    entry = _movement_only_entry(activity, min_dwell_min=15)
    assert entry["skip"] is False
    assert entry["synthesized"] is False
    assert "7 GPS fix" in entry["what_happened"]
    assert "15 minutes" in entry["what_happened"]
    assert "movement-only" in entry["tags"]


def test__distill_location_raw_fallback_no_api():
    """synthesize=False must not call any API and must return entry fields."""
    activity = {
        "stays": [{"lat": 1.3, "lon": 103.8, "arrive": 1_700_000_000,
                   "depart": 1_700_003_600, "dwell_min": 60, "fixes": 5,
                   "place": "Test Plaza"}],
        "stay_count": 1, "point_count": 5,
    }
    d = distill_location_activity(activity, synthesize=False)
    assert d["skip"] is False
    assert d["synthesized"] is False
    assert "1 place" in d["moment"]
    assert "Test Plaza" in _activity_body(activity)
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d


def test__nearest_fix_picks_closest_in_time(monkeypatch):
    """nearest_fix returns the fix nearest the target time (used to geo-tag
    photos by capture time)."""
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_USER", "u")
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_DEVICE", "d")
    target = datetime(2026, 5, 1, 12, 0, 0)
    t = int(target.timestamp())
    data = {"data": [
        {"lat": 1.0, "lon": 100.0, "tst": t - 3600},   # 60 min before
        {"lat": 2.0, "lon": 200.0, "tst": t + 120},     # 2 min after — closest
        {"lat": 3.0, "lon": 300.0, "tst": t + 4000},    # ~67 min after
    ]}
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.ApiServiceOwnTracksLocations",
        _svc_returning(data),
    )
    assert nearest_fix(target) == (2.0, 200.0)


def test__nearest_fix_none_when_no_device(monkeypatch):
    monkeypatch.delenv("OWN_TRACKS_DEFAULT_USER", raising=False)
    monkeypatch.delenv("OWN_TRACKS_DEFAULT_DEVICE", raising=False)
    assert nearest_fix(datetime(2026, 5, 1, 12, 0)) is None
