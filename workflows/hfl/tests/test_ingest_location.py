"""
Tests for workflows/hfl/tasks/ingest_location.py.

Integration tests call the real task exactly as Beat will. With no OwnTracks
user/device configured the task is a guaranteed no-op — no Recorder call, no
LLM, no side-effects. The live path (real Recorder + Anthropic synthesis +
corpus/ES write) is marked skip. Unit tests exercise the stay-point clustering,
place-label, and raw-fallback distiller with no network.
"""

from datetime import date, datetime, timedelta
import re

import pytest

from workflows.hfl.tasks.ingest_location import (
    _activity_body,
    _analyze_route_activity,
    _cluster_stays,
    _dedupe_points,
    _dedupe_route_anchors,
    _enrich_route_anchors,
    _fmt_distance_km,
    _haversine_m,
    _location_window,
    _movement_only_entry,
    _osm_link,
    _place_tags,
    _reverse_geocode,
    _route_summary_entry,
    _select_route_anchors,
    _short_place,
    _track_health,
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
    track.insert(1, dict(track[0]))  # exact Recorder duplicate must not inflate the count
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.ApiServiceOwnTracksLocations",
        lambda *a, **k: type("S", (), {"get_history": lambda self, **kw: {"data": track}})(),
    )
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location._reverse_geocode",
        lambda lat, lon, **kw: "Test Neighbourhood, Singapore",
    )
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.resolve_corpus_dir", lambda: tmp_path
    )
    submitted = []
    monkeypatch.setattr(
        "workflows.hfl.tasks.capture.submit_hfl_entry",
        lambda entry, *, source, synthesized=False: submitted.append(
            (entry, source, synthesized)
        ) or {"doc_id": "doc-1", "bytes_written": 0, "delivery": "forwarded"},
    )

    result = ingest_location_activity(cfg_id__anthropic="ANTHROPIC")

    assert result["entries_written"] == 1
    assert result["stays"] == 0
    assert result["points"] == 3
    assert result["synthesized"] is False
    assert result["indexed"] is True
    assert [(item[1], item[2]) for item in submitted] == [("location", False)]
    written = submitted[0][0].to_markdown()
    assert "Recorded movement but no qualifying location stay" in written
    assert "movement-only" in written
    assert "Route anchors:" in written
    assert "Test Neighbourhood, Singapore" in written
    assert now.strftime("%Y-%m-%d") in written
    assert "openstreetmap.org" not in written


def test__ingest_location_activity_travel_route_fallback(monkeypatch, tmp_path):
    """Travel-heavy GPS days without stays write a route summary, not generic movement-only."""
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_USER", "brian")
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_DEVICE", "android")

    now = datetime.now().replace(hour=0, minute=30, second=0, microsecond=0)
    # Sparse, moving points with a large Singapore -> Metro Manila jump. No run
    # stays within 150m for 15 minutes, but the route itself is meaningful.
    track = _track(now, [
        (0, 1.389, 103.987), (10, 1.390, 103.988),
        (360, 14.520, 121.000), (370, 14.530, 121.010),
        (480, 14.620, 121.100), (540, 14.650, 121.120),
        (600, 14.660, 121.130), (660, 14.670, 121.140),
        (720, 14.570, 121.080), (780, 14.560, 121.070),
    ])
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.ApiServiceOwnTracksLocations",
        lambda *a, **k: type("S", (), {"get_history": lambda self, **kw: {"data": track}})(),
    )
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location._reverse_geocode",
        lambda lat, lon, **kw: "Changi Village, Singapore" if lat < 5 else "Metro Manila, Philippines",
    )
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.resolve_corpus_dir", lambda: tmp_path
    )
    submitted = []
    monkeypatch.setattr(
        "workflows.hfl.tasks.capture.submit_hfl_entry",
        lambda entry, *, source, synthesized=False: submitted.append(
            (entry, source, synthesized)
        ) or {"doc_id": "doc-1", "bytes_written": 0, "delivery": "forwarded"},
    )

    result = ingest_location_activity(cfg_id__anthropic="ANTHROPIC")

    assert result["entries_written"] == 1
    assert result["stays"] == 0
    assert result["synthesized"] is False
    assert [(item[1], item[2]) for item in submitted] == [("location", False)]
    written = submitted[0][0].to_markdown()
    assert "Travelled from Changi Village, Singapore to Metro Manila, Philippines" in written
    assert "travel-heavy day" in written
    assert "movement-only" not in written
    assert "#location #travel" in written
    assert not re.search(r"\d+\.\d{3,}\s*,\s*\d+\.\d{3,}", written)
    assert "openstreetmap.org" not in written


def test__location_window_one_day_is_exact_current_day():
    today = date(2026, 5, 29)
    assert _location_window(1, today=today) == (today, today)
    assert _location_window(2, today=today) == (date(2026, 5, 28), today)


def test__route_analysis_below_threshold_is_not_travel():
    now = datetime(2026, 5, 29, 8, 0, 0)
    points = _track(now, [(i, 1.3000 + i * 0.00001, 103.8000) for i in range(10)])
    analysis = _analyze_route_activity(
        {"_points": points},
        do_geocode=False,
        min_direct_distance_m=20_000,
        min_path_distance_m=30_000,
        min_jump_m=50_000,
    )
    assert analysis["travel"] is False


def test__route_summary_entry_uses_places_not_coordinates():
    now = datetime(2026, 5, 29, 8, 0, 0)
    analysis = {
        "travel": True,
        "point_count": 12,
        "direct_distance_m": 2_300_000,
        "max_jump_m": 2_300_000,
        "anchors": [
            {"tst": int(now.timestamp()), "lat": 1.3, "lon": 103.8, "place": "Singapore"},
            {"tst": int((now + timedelta(hours=4)).timestamp()), "lat": 14.5, "lon": 121.0, "place": "Metro Manila"},
        ],
    }
    entry = _route_summary_entry(analysis)
    body = "\n".join(str(entry[k]) for k in ("moment", "what_happened", "why_it_stayed"))
    assert "Travelled from Singapore to Metro Manila" in entry["moment"]
    assert "2300 km" in body
    assert not re.search(r"\d+\.\d{3,}\s*,\s*\d+\.\d{3,}", body)


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
    # No network geocode, no Anthropic call; capture canonical persistence.
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
    submitted = []
    monkeypatch.setattr(
        "workflows.hfl.tasks.capture.submit_hfl_entry",
        lambda entry, *, source, synthesized=False: submitted.append(
            (entry, source, synthesized)
        ) or {"doc_id": "doc-1", "bytes_written": 0, "delivery": "forwarded"},
    )

    result = ingest_location_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 1
    assert result["indexed"] is True
    assert [item[1] for item in submitted] == ["location"]
    written = submitted[0][0].to_markdown()
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


def test__movement_only_entry_uses_actual_fix_times_and_route_anchors():
    now = datetime(2026, 7, 20, 8, 55, 0)
    points = _track(now, [
        (0, 1.3000, 103.8000),
        (180, 1.3500, 103.8500),
        (675, 1.4000, 103.9000),
    ])
    activity = {
        "point_count": 3,
        "stay_count": 0,
        "stays": [],
        # These midnight query bounds previously rendered as 00:00 to 00:00.
        "window": {
            "from": int(datetime(2026, 7, 20).timestamp()),
            "to": int(datetime(2026, 7, 21).timestamp()),
        },
        "_points": points,
        "_route_anchors": [
            dict(points[0], label="Home District, Singapore"),
            dict(points[1], label="1.35000, 103.85000"),
            dict(points[2], label="Town Centre, Singapore"),
        ],
    }

    entry = _movement_only_entry(activity, min_dwell_min=15)

    assert "from 08:55 to 20:10 on 2026-07-20" in entry["what_happened"]
    assert "08:55 — Home District, Singapore" in entry["what_happened"]
    assert "11:55 — 1.35000, 103.85000" in entry["what_happened"]
    assert "00:00 and 00:00" not in entry["what_happened"]


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


# ── Privacy ───────────────────────────────────────────────────────────────────

def test__activity_body_redacts_coordinates_when_no_place():
    """When geocoding fails (no 'place' key on a stay), _activity_body must
    NOT fall back to raw lat/lon — it must emit a redacted placeholder."""
    activity = {
        "stays": [
            {"lat": 1.3456, "lon": 103.8765, "arrive": 1_700_000_000,
             "depart": 1_700_003_600, "dwell_min": 60, "fixes": 10}
            # no "place" key → geocode unavailable
        ]
    }
    body = _activity_body(activity)
    assert "[location unavailable]" in body
    assert not re.search(r"\d+\.\d{3,}", body), "raw coordinates must not appear"


# ── _track_health ─────────────────────────────────────────────────────────────

def test__track_health_empty_and_single_point():
    assert _track_health([]) == {"path_km": 0.0, "duration_min": 0.0,
                                  "gap_count": 0, "max_gap_min": 0.0}
    single = [{"lat": 1.3, "lon": 103.8, "tst": 1_700_000_000}]
    assert _track_health(single)["path_km"] == 0.0


def test__track_health_basic_path_distance():
    """A ~550 m one-way trip should report roughly 0.55 km of path distance."""
    now = datetime(2026, 5, 29, 8, 0, 0)
    points = _track(now, [
        (0, 1.3000, 103.8000),
        (5, 1.3050, 103.8000),   # ~550 m north
    ])
    health = _track_health(points)
    assert 0.4 < health["path_km"] < 0.7
    assert health["gap_count"] == 0
    assert health["duration_min"] == pytest.approx(5.0, abs=0.1)


def test__track_health_detects_gaps():
    """Gaps > 30 min between consecutive fixes are counted."""
    now = datetime(2026, 5, 29, 8, 0, 0)
    points = _track(now, [
        (0, 1.30, 103.80),
        (10, 1.30, 103.80),   # 10-min gap — not counted
        (50, 1.30, 103.80),   # 40-min gap — counted
        (90, 1.30, 103.80),   # 40-min gap — counted
    ])
    health = _track_health(points)
    assert health["gap_count"] == 2
    assert health["max_gap_min"] == pytest.approx(40.0, abs=1.0)


def test__dedupe_points_removes_only_exact_recorder_duplicates():
    now = datetime(2026, 7, 20, 9, 0, 0)
    first, second = _track(now, [
        (0, 1.3000, 103.8000),
        (5, 1.3010, 103.8010),
    ])
    points = [first, dict(first), second, dict(second), dict(second, lon=103.8020)]

    deduped = _dedupe_points(points)

    assert deduped == [first, second, dict(second, lon=103.8020)]


# ── _movement_only_entry enrichment ──────────────────────────────────────────

def test__movement_only_entry_includes_distance_when_significant():
    """When _points covers > 0.1 km, what_happened mentions the approximate
    distance — without exposing raw coordinates."""
    now = datetime(2026, 5, 29, 8, 0, 0)
    # ~5.5 km roundtrip (2.75 km each way)
    points = _track(now, [
        (0, 1.3000, 103.8000),
        (5, 1.3250, 103.8000),
        (10, 1.3000, 103.8000),
    ])
    activity = {
        "point_count": 3,
        "stay_count": 0,
        "stays": [],
        "window": {"from": int(now.timestamp()), "to": int(now.timestamp()) + 600},
        "_points": points,
    }
    entry = _movement_only_entry(activity, min_dwell_min=15)
    assert entry["synthesized"] is False
    assert "km" in entry["what_happened"]
    assert not re.search(r"\d+\.\d{3,}", entry["what_happened"]), "no raw coords"


def test__movement_only_entry_flags_coverage_gaps():
    """_movement_only_entry warns about signal gaps when >30 min gaps exist."""
    now = datetime(2026, 5, 29, 8, 0, 0)
    points = _track(now, [
        (0, 1.30, 103.80),
        (60, 1.31, 103.80),  # 60-min gap → counted
    ])
    activity = {
        "point_count": 2,
        "stay_count": 0,
        "stays": [],
        "window": {"from": int(now.timestamp()), "to": int(now.timestamp()) + 3600},
        "_points": points,
    }
    entry = _movement_only_entry(activity, min_dwell_min=15)
    assert "coverage gap" in entry["what_happened"]


def test__movement_only_entry_no_coverage_note_for_tiny_track():
    """Very short tracks (< 0.1 km, no gaps) produce no coverage note —
    the text stays clean and the existing assertions remain valid."""
    now = datetime(2026, 5, 29, 8, 0, 0)
    # ~30 m roundtrip — below the 0.1 km threshold
    points = _track(now, [
        (0, 1.3000, 103.8000),
        (5, 1.3001, 103.8001),
        (10, 1.3000, 103.8000),
    ])
    activity = {
        "point_count": 3,
        "stay_count": 0,
        "stays": [],
        "window": {"from": int(now.timestamp()), "to": int(now.timestamp()) + 600},
        "_points": points,
    }
    entry = _movement_only_entry(activity, min_dwell_min=15)
    assert "3 GPS fix" in entry["what_happened"]
    assert "15 minutes" in entry["what_happened"]
    assert "km" not in entry["what_happened"]


# ── _reverse_geocode cache ────────────────────────────────────────────────────

def test__reverse_geocode_uses_cache(monkeypatch):
    """Two calls whose coordinates round to the same ~100 m grid cell must
    share one HTTP request — the second is served from cache."""
    import httpx as _httpx
    import workflows.hfl.tasks.ingest_location as _m

    monkeypatch.setattr(_m, "_LAST_GEOCODE_TS", 0.0)

    call_count = []

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"name": "Test Market", "address": {"suburb": "Downtown"}}

    monkeypatch.setattr(
        _httpx, "get",
        lambda *a, **k: (call_count.append(1) or FakeResp()),
    )

    cache: dict = {}
    # Both round to (1.3, 103.8) at 3 decimal places (~100 m grid)
    r1 = _reverse_geocode(1.30001, 103.80001, cache=cache, min_interval=0.0)
    r2 = _reverse_geocode(1.30002, 103.80002, cache=cache, min_interval=0.0)

    assert r1 == r2 == "Test Market, Downtown"
    assert len(call_count) == 1, "second call must hit cache, not the network"


# ── nearest_fix error path ────────────────────────────────────────────────────

def test__nearest_fix_returns_none_on_recorder_exception(monkeypatch):
    """nearest_fix must return None (not raise) when the Recorder is
    unreachable — it is best-effort geo-tagging."""
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_USER", "brian")
    monkeypatch.setenv("OWN_TRACKS_DEFAULT_DEVICE", "android")

    def _raise_conn(*a, **k):
        raise ConnectionError("refused")

    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location.ApiServiceOwnTracksLocations",
        lambda *a, **k: type("S", (), {"get_history": _raise_conn})(),
    )
    assert nearest_fix(datetime(2026, 5, 1, 12, 0, 0)) is None


# ── route anchor helpers ──────────────────────────────────────────────────────

def test__select_route_anchors_includes_first_and_last():
    """_select_route_anchors always includes the first and last fix."""
    now = datetime(2026, 5, 29, 8, 0, 0)
    points = _track(now, [(i * 5, 1.30 + i * 0.001, 103.80) for i in range(20)])
    anchors = _select_route_anchors(points)
    kinds = {a["kind"] for a in anchors}
    assert "first" in kinds
    assert "last" in kinds
    assert len(anchors) <= 6


def test__dedupe_route_anchors_removes_nearby_moved_samples():
    """Moved-sample anchors within 800 m of an earlier kept anchor are
    removed; first/last anchors are always kept."""
    base_ts = int(datetime(2026, 5, 29, 8, 0, 0).timestamp())
    anchors = [
        {"lat": 1.300, "lon": 103.800, "tst": base_ts, "kind": "first"},
        # ~111 m from first — within 800 m, should be dropped
        {"lat": 1.301, "lon": 103.800, "tst": base_ts + 300, "kind": "moved-sample"},
        # far away
        {"lat": 1.500, "lon": 103.900, "tst": base_ts + 1200, "kind": "last"},
    ]
    deduped = _dedupe_route_anchors(anchors, radius_m=800)
    assert len(deduped) < len(anchors)
    assert deduped[0]["kind"] == "first"
    assert deduped[-1]["kind"] == "last"


def test__enrich_route_anchors_prefers_place_and_falls_back_to_coordinates(monkeypatch):
    now = datetime(2026, 7, 20, 8, 0, 0)
    points = _track(now, [
        (0, 1.3000, 103.8000),
        (60, 1.3600, 103.8600),
        (120, 1.4200, 103.9200),
    ])
    monkeypatch.setattr(
        "workflows.hfl.tasks.ingest_location._reverse_geocode",
        lambda lat, lon, **kw: "Named Start, Singapore" if lat == 1.3000 else None,
    )

    anchors = _enrich_route_anchors(points)

    assert anchors[0]["label"] == "Named Start, Singapore"
    assert anchors[-1]["label"] == "1.42000, 103.92000"
    assert len(anchors) <= 6


# ── _fmt_distance_km ──────────────────────────────────────────────────────────

def test__fmt_distance_km_formatting():
    assert _fmt_distance_km(500) == "0.5 km"
    assert _fmt_distance_km(1_500) == "1.5 km"
    assert _fmt_distance_km(100_000) == "100 km"
    assert _fmt_distance_km(2_300_000) == "2300 km"
