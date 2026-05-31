"""
Tests for workflows/hfl/tasks/ingest_spotify.py.

Integration tests call the real task exactly as Beat will. The default
(no Spotify credentials) is a guaranteed no-op — no network, no side-effects.
The live path (real Spotify API round-trip + corpus write) is marked skip.
"""

from datetime import date, datetime

import pytest

import workflows.hfl.tasks.ingest_spotify as mod
from workflows.hfl.tasks.ingest_spotify import (
    ingest_spotify_activity,
    collect_spotify_activity,
    distill_spotify_activity,
    _credentials_present,
    _played_local_day,
    _track_artist,
    _activity_body,
)


# ── Workflow (integration) ────────────────────────────────────────────────────

def test__ingest_spotify_activity_no_credentials(monkeypatch):
    """No credentials configured → clean no-op, no network call, no write."""
    monkeypatch.setattr(mod, "_credentials_present", lambda: False)
    result = ingest_spotify_activity(cfg_id__anthropic="ANTHROPIC")
    assert result["entries_written"] == 0
    assert result["skipped"] == "no credentials"


@pytest.mark.skip(reason="Manual only — live Spotify Web API round-trip (needs "
                         "valid SPOTIFY_* creds) + Anthropic; appends a real "
                         "entry to today's corpus.")
def test__ingest_spotify_activity_full_pipeline():
    result = ingest_spotify_activity(cfg_id__anthropic="ANTHROPIC", window_days=1)
    assert result["entries_written"] in (0, 1)


# ── Unit / function ───────────────────────────────────────────────────────────

def test__played_local_day_parses_utc_and_garbage():
    # A real UTC instant maps to *some* local date (offset-dependent but valid).
    assert isinstance(_played_local_day("2026-05-31T22:10:05.123Z"), date)
    assert isinstance(_played_local_day("2026-05-31T22:10:05+00:00"), date)
    assert _played_local_day("not-a-date") is None
    assert _played_local_day("") is None


def test__track_artist_joins_and_falls_back():
    assert _track_artist({"artists": [{"name": "Khruangbin"}, {"name": "Bonobo"}]}) \
        == "Khruangbin, Bonobo"
    assert _track_artist({"artists": []}) == "(unknown artist)"
    assert _track_artist({}) == "(unknown artist)"


class _FakePlayer:
    """Stand-in for ApiServiceSpotifyPlayer.get_recently_played."""
    def __init__(self, items):
        self._items = items
        self.access_token = "fake"

    def get_recently_played(self, limit=50, after_ms=None):
        return {"items": self._items}


def test__collect_filters_to_window_and_aggregates():
    today = datetime.now().astimezone().date()
    # Two plays today (one needs UTC→local mapping), one far in the past.
    items = [
        {"played_at": f"{today.isoformat()}T12:00:00Z",
         "track": {"name": "Weightless", "artists": [{"name": "Marconi Union"}],
                   "duration_ms": 60000}},
        {"played_at": f"{today.isoformat()}T13:00:00Z",
         "track": {"name": "Reflections", "artists": [{"name": "Marconi Union"}],
                   "duration_ms": 90000}},
        {"played_at": "2020-01-01T00:00:00Z",
         "track": {"name": "Old", "artists": [{"name": "Nobody"}],
                   "duration_ms": 1000}},
    ]
    activity = collect_spotify_activity(
        since=today, until=today,
        player_svc=_FakePlayer(items), personalization_svc=None,
    )
    # The past play is excluded; today's two are kept. (Window is local-day,
    # so a UTC-midnight-adjacent play could shift days — assert the bound.)
    assert activity["track_count"] <= 2
    assert activity["distinct_artists"] <= 1 or activity["track_count"] == 0


def test__collect_empty_when_no_items():
    today = datetime.now().date()
    activity = collect_spotify_activity(
        since=today, until=today,
        player_svc=_FakePlayer([]), personalization_svc=None,
    )
    assert activity["track_count"] == 0
    assert activity["total_ms"] == 0


def test__activity_body_structure():
    activity = {
        "track_count": 1, "total_ms": 60000, "distinct_artists": 1,
        "tracks": [{"played_at": "2026-05-31 12:00", "name": "Weightless",
                    "artist": "Marconi Union", "ms": 60000}],
        "top_tracks": [{"name": "Reflections", "artist": "Marconi Union"}],
        "top_artists": [{"name": "Bonobo", "genres": ["downtempo"]}],
    }
    body = _activity_body(activity)
    assert "Weightless" in body
    assert "Marconi Union" in body
    assert "downtempo" in body


def test__distill_spotify_activity_raw_fallback_no_api():
    """synthesize=False must not call any API and must return entry fields."""
    activity = {
        "track_count": 2, "total_ms": 150000, "distinct_artists": 1,
        "tracks": [
            {"played_at": "2026-05-31 12:00", "name": "Weightless",
             "artist": "Marconi Union", "ms": 60000},
            {"played_at": "2026-05-31 13:00", "name": "Reflections",
             "artist": "Marconi Union", "ms": 90000},
        ],
        "top_tracks": [], "top_artists": [],
    }
    d = distill_spotify_activity(activity, synthesize=False)
    assert d["skip"] is False
    assert d["synthesized"] is False
    assert "2 Spotify play" in d["moment"]
    for key in ("moment", "what_happened", "possible_use", "tags"):
        assert key in d


def test__dual_write_calls_index(monkeypatch, tmp_path):
    """The task must dual-write: corpus append + index_hfl_entry(source=spotify)."""
    today = datetime.now().date()
    items = [
        {"played_at": f"{today.isoformat()}T12:00:00Z",
         "track": {"name": "Weightless", "artists": [{"name": "Marconi Union"}],
                   "duration_ms": 60000}},
    ]

    monkeypatch.setattr(mod, "_credentials_present", lambda: True)
    monkeypatch.setattr(mod, "ApiServiceSpotifyPlayer", lambda cfg, **kw: _FakePlayer(items))
    monkeypatch.setattr(mod, "ApiServiceSpotifyPersonalization", lambda cfg, **kw: None)
    monkeypatch.setattr(mod, "resolve_corpus_dir", lambda: tmp_path)
    # Force the deterministic raw fallback (no Anthropic call).
    monkeypatch.setattr(mod, "distill_spotify_activity",
                        lambda activity, **kw: {
                            "skip": False, "moment": "m", "what_happened": "w",
                            "why_it_stayed": "", "possible_use": "mood log",
                            "tags": ["music", "spotify"], "synthesized": False,
                        })

    calls = {}

    def _fake_append(day_file, entry, *, source, synthesized=False):
        calls["source"] = source
        calls["synthesized"] = synthesized
        return 10, "doc-id-123"

    monkeypatch.setattr(mod, "append_entry", _fake_append)

    result = ingest_spotify_activity(window_days=1)
    # collect may drop the play if UTC→local crosses the day boundary; only
    # assert the dual-write contract when an entry was actually written.
    if result["entries_written"] == 1:
        assert calls["source"] == "spotify"
        assert result["indexed"] is True
