"""
workflows/hfl/tasks/ingest_spotify.py

Daily Spotify listening → HFL corpus. Pulls the day's play history from the
Spotify Web API (apps/spotify), distils it into ONE Homework-for-Life entry
(Haiku) — an emotional-tone / soundtrack-of-the-day beat — and dual-writes it
to the Markdown corpus + the harqis-hfl-entries ES index.

Source: the Spotify Web API (apps/spotify ::
ApiServiceSpotifyPlayer.get_recently_played for the day's plays, and
ApiServiceSpotifyPersonalization.get_top_tracks / get_top_artists for the
operator's rolling taste as distillation context). Auth is OAuth2 with a
refresh token (SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET /
SPOTIFY_REFRESH_TOKEN in .env/apps.env); the base service exchanges the
refresh token for a short-lived access token on construction.

Centralized, single-account source: this runs on the Beat host (HFL queue),
NOT broadcast per-machine like ingest_browsing — one Spotify account, one
entry per day.

Caveats (read these):
  - recently-played caps at 50 items and is a time-cursor endpoint — there is
    no full-day history call. For a once-a-day digest this is acceptable; if
    the operator plays >50 tracks in a day the earliest are lost. The
    top-tracks / top-artists calls cover the "what defined the period" layer
    independent of the cap.
  - played_at is UTC; it is mapped to the LOCAL calendar day before bucketing.
  - No audio-features (valence/energy) — Spotify deprecated them for new apps
    (Nov 2024). Mood is inferred downstream by Haiku from track/artist/genre
    names, never computed.

No credentials configured → no entry, no network call (clean no-op, mirrors
ingest_chatgpt on a no-token day). No plays in the window → no entry, no LLM
call.

The collectors (collect_spotify_activity / distill_spotify_activity) are plain
functions so the MCP tool (workflows/hfl/mcp.py :: spotify_activity) can reuse
them for a live, no-write view.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic
from apps.spotify.config import CONFIG as SPOTIFY_CONFIG
from apps.spotify.references.web.api.player import ApiServiceSpotifyPlayer
from apps.spotify.references.web.api.personalization import ApiServiceSpotifyPersonalization

from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import _build_entry, append_entry, resolve_corpus_dir
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_spotify")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


def _spotify_window(window_days: int, *, today: Optional[date] = None) -> tuple[date, date]:
    """Return the inclusive local calendar-day window for a Spotify run."""
    end = today or datetime.now().date()
    days = max(1, int(window_days or 1))
    start = end - timedelta(days=days - 1)
    return start, end


def _credentials_present() -> bool:
    """True only when all three Spotify OAuth creds resolve to real values.

    Mirrors resolve_corpus_dir's unresolved-placeholder guard: an unset env
    var leaves a literal "${...}" in app_data. Checking here means a no-cred
    run makes NO network call (the token refresh happens at service init).
    """
    data = SPOTIFY_CONFIG.app_data or {}
    for key in ("client_id", "client_secret", "refresh_token"):
        val = str(data.get(key) or "").strip()
        if not val or "${" in val:
            return False
    return True


def _played_local_day(played_at: str) -> Optional[date]:
    """Map a Spotify UTC ``played_at`` ISO timestamp to the local calendar day."""
    s = (played_at or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date()


def _track_artist(track: dict) -> str:
    artists = track.get("artists") if isinstance(track, dict) else None
    if isinstance(artists, list) and artists:
        names = [str((a or {}).get("name", "")).strip() for a in artists if isinstance(a, dict)]
        names = [n for n in names if n]
        if names:
            return ", ".join(names[:3])
    return "(unknown artist)"


def collect_spotify_activity(
    *,
    since: date,
    until: date,
    player_svc: ApiServiceSpotifyPlayer,
    personalization_svc: Optional[ApiServiceSpotifyPersonalization] = None,
    max_tracks: int = 50,
    top_limit: int = 10,
) -> dict[str, Any]:
    """Pull the day's plays (+ rolling top tracks/artists) into a flat dict.

    The recently-played endpoint returns newest-first, capped at 50; we keep
    only plays whose LOCAL date falls in ``[since, until]``.

    Returns:
        {"tracks":[{"played_at","name","artist","ms"}], "track_count",
         "total_ms", "distinct_artists", "artists":[name],
         "top_tracks":[{"name","artist"}], "top_artists":[{"name","genres"}],
         "window":(since,until)}.
    """
    recent = player_svc.get_recently_played(limit=max_tracks)
    items = recent.get("items") if isinstance(recent, dict) else None
    items = items if isinstance(items, list) else []

    tracks: list[dict] = []
    artist_set: set[str] = set()
    total_ms = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        day = _played_local_day(it.get("played_at", ""))
        if not day or not (since <= day <= until):
            continue
        track = it.get("track") or {}
        if not isinstance(track, dict):
            continue
        name = str(track.get("name", "")).strip() or "(unknown track)"
        artist = _track_artist(track)
        ms = int(track.get("duration_ms") or 0)
        total_ms += ms
        artist_set.add(artist)
        tracks.append({
            "played_at": str(it.get("played_at", ""))[:19],
            "name": name[:160],
            "artist": artist[:160],
            "ms": ms,
        })

    top_tracks: list[dict] = []
    top_artists: list[dict] = []
    if personalization_svc is not None and tracks:
        try:
            tt = personalization_svc.get_top_tracks(limit=top_limit)
            for t in (tt.get("items") if isinstance(tt, dict) else []) or []:
                if isinstance(t, dict):
                    top_tracks.append({
                        "name": str(t.get("name", "")).strip()[:160],
                        "artist": _track_artist(t)[:160],
                    })
        except Exception as exc:  # noqa: BLE001 - top data is bonus context
            _log.info("ingest_spotify: top-tracks unavailable (%s)", exc)
        try:
            ta = personalization_svc.get_top_artists(limit=top_limit)
            for a in (ta.get("items") if isinstance(ta, dict) else []) or []:
                if isinstance(a, dict):
                    genres = [str(g).strip() for g in (a.get("genres") or []) if str(g).strip()]
                    top_artists.append({
                        "name": str(a.get("name", "")).strip()[:160],
                        "genres": genres[:5],
                    })
        except Exception as exc:  # noqa: BLE001 - top data is bonus context
            _log.info("ingest_spotify: top-artists unavailable (%s)", exc)

    return {
        "tracks": tracks,
        "track_count": len(tracks),
        "total_ms": total_ms,
        "distinct_artists": len(artist_set),
        "artists": sorted(artist_set),
        "top_tracks": top_tracks,
        "top_artists": top_artists,
        "window": (since, until),
    }


def _fmt_minutes(total_ms: int) -> str:
    mins = round(total_ms / 60000)
    return f"~{mins} min" if mins else "under a minute"


def _activity_body(activity: dict) -> str:
    lines: list[str] = [
        f"{activity['track_count']} play(s), {_fmt_minutes(activity['total_ms'])}, "
        f"{activity['distinct_artists']} distinct artist(s).",
        "",
        "Plays (newest first):",
    ]
    for t in activity["tracks"]:
        lines.append(f"- {t['played_at']}  {t['name']} — {t['artist']}")
    if activity["top_tracks"]:
        lines.append("")
        lines.append("Top tracks (rolling ~4 weeks):")
        for t in activity["top_tracks"]:
            lines.append(f"- {t['name']} — {t['artist']}")
    if activity["top_artists"]:
        lines.append("")
        lines.append("Top artists (rolling ~4 weeks):")
        for a in activity["top_artists"]:
            genres = f" [{', '.join(a['genres'])}]" if a["genres"] else ""
            lines.append(f"- {a['name']}{genres}")
    return "\n".join(lines)


def distill_spotify_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn collected plays into HFL entry fields (Haiku, raw fallback)."""
    count = activity["track_count"]
    minutes = _fmt_minutes(activity["total_ms"])

    def _fallback() -> dict:
        preview = "; ".join(
            f"{t['name']} — {t['artist']}" for t in activity["tracks"][:8]
        )
        return {
            "skip": False,
            "moment": f"{count} Spotify play(s) ({minutes}) across "
                      f"{activity['distinct_artists']} artist(s)",
            "what_happened": preview,
            "why_it_stayed": "",
            "possible_use": "mood log",
            "tags": ["music", "spotify"],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = f"Today's Spotify listening:\n\n{_activity_body(activity)}"
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_spotify: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_spotify").strip(),
            model=model,
            max_tokens=max_tokens,
        )
        text = resp.content[0].text if resp and resp.content else ""
        parsed = _parse_model_json(text)
        if not parsed:
            return _fallback()
        parsed.setdefault("skip", False)
        for key in ("moment", "what_happened", "why_it_stayed", "possible_use"):
            parsed[key] = str(parsed.get(key, "")).strip()
        parsed["tags"] = [str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_spotify: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


@SPROUT.task()
@log_result()
def ingest_spotify_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    max_tracks: int = 50,
    top_limit: int = 10,
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's Spotify listening.

    No Spotify credentials configured → no entry, no network call.
    No plays in the window → no entry, no LLM call.
    """
    if not _credentials_present():
        _log.info("ingest_spotify: Spotify credentials not set — no-op")
        return {"skipped": "no credentials", "entries_written": 0, "tracks": 0}

    since, until = _spotify_window(window_days)

    try:
        player = ApiServiceSpotifyPlayer(SPOTIFY_CONFIG)
        personalization = ApiServiceSpotifyPersonalization(
            SPOTIFY_CONFIG, access_token=player.access_token
        )
        activity = collect_spotify_activity(
            since=since, until=until,
            player_svc=player, personalization_svc=personalization,
            max_tracks=max_tracks, top_limit=top_limit,
        )
    except Exception as exc:  # noqa: BLE001 - API down/token expired must not break beat
        _log.error("ingest_spotify: Spotify API unavailable (%s)", exc)
        return {"skipped": "spotify unavailable", "entries_written": 0,
                "error": str(exc)[:200]}

    if activity["track_count"] == 0:
        _log.info("ingest_spotify: no plays in last %d day(s)", window_days)
        return {"skipped": "no plays", "entries_written": 0, "tracks": 0}

    d = distill_spotify_activity(
        activity, synthesize=True, model=model,
        cfg_id=cfg_id__anthropic, max_tokens=900,
    )
    if d.get("skip"):
        _log.info("ingest_spotify: distilled as skip — %d plays not story-worthy",
                  activity["track_count"])
        return {"skipped": "distilled-skip", "entries_written": 0,
                "tracks": activity["track_count"]}

    tags = ["music", "spotify"] + [
        str(t) for t in (d.get("tags") or []) if str(t).strip()
        and str(t).strip().lower() not in ("music", "spotify")
    ][:5]

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"
    entry = _build_entry(
        when=when,
        moment=d["moment"],
        what_happened=d["what_happened"],
        why_it_stayed=d["why_it_stayed"],
        possible_use=d["possible_use"] or "mood log",
        tags=tags,
        references=[],
    )
    bytes_written, doc_id = append_entry(
        day_file, entry, source="spotify", synthesized=d.get("synthesized", False),
    )

    _log.info("ingest_spotify: entry written (%d plays, %d artists) → %s",
              activity["track_count"], activity["distinct_artists"], day_file)
    return {
        "entries_written": 1,
        "tracks": activity["track_count"],
        "distinct_artists": activity["distinct_artists"],
        "total_ms": activity["total_ms"],
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": str(day_file),
        "indexed": doc_id is not None,
    }
