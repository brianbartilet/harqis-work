"""
workflows/hfl/tasks/ingest_android_session.py

Android phone session rhythm -> HFL corpus. Reads a JSONL event log written
by Tasker or Termux on the phone (or synced to the host via Syncthing / sshfs)
and distils ONE Homework-for-Life entry that captures the day's attention
pattern: focus windows, fragmented check-in periods, idle blocks, and charging
rhythm.

JSONL event schema (one JSON object per line, produced by Tasker/Termux):

    {"ts": <unix_timestamp_int>, "type": "screen_on"}
    {"ts": <unix_timestamp_int>, "type": "screen_off"}
    {"ts": <unix_timestamp_int>, "type": "unlock"}
    {"ts": <unix_timestamp_int>, "type": "app_foreground", "app": "<pkg>"}
    {"ts": <unix_timestamp_int>, "type": "app_background", "app": "<pkg>"}
    {"ts": <unix_timestamp_int>, "type": "charging_on"}
    {"ts": <unix_timestamp_int>, "type": "charging_off"}

Privacy: raw package names are mapped to broad categories (web, productivity,
messaging, etc.) before distillation. No app names, notification bodies, or
raw coordinates ever enter HFL entries. The category breakdown is the coarsest
grain of app attribution retained.

Data path resolution (first hit wins):
    1. apps_config.yaml :: ANDROID_SESSION.data.path
    2. env var ANDROID_SESSION_JSONL_PATH
    -> clean no-op if neither resolves (no entry, no LLM call).

Cost: Haiku only — never raise the Anthropic DEFAULT_MODEL. No LLM call when
no data path is configured, the file is missing, or no events fall in the
window.

The collectors (collect_android_session_activity /
distill_android_session_activity) are plain functions so an MCP tool can reuse
them for a live, no-write view.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.antropic.config import get_config as get_anthropic_config
from apps.antropic.references.web.base_api_service import BaseApiServiceAnthropic

from workflows.hfl.prompts import load_prompt
from workflows.hfl.tasks.capture import _build_entry, append_entry, resolve_corpus_dir
from workflows.hfl.tasks.ingest_git import _parse_model_json

_log = create_logger("hfl.ingest_android_session")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"


# ── privacy: package-name -> category map ─────────────────────────────────────

_EXACT_CATEGORIES: dict[str, str] = {
    "com.android.chrome": "web",
    "org.mozilla.firefox": "web",
    "com.brave.browser": "web",
    "com.google.android.youtube": "video",
    "com.netflix.mediaclient": "video",
    "com.spotify.music": "music",
    "com.google.android.apps.youtube.music": "music",
    "com.whatsapp": "messaging",
    "org.telegram.messenger": "messaging",
    "com.discord": "messaging",
    "com.twitter.android": "social",
    "com.instagram.android": "social",
    "com.facebook.katana": "social",
    "com.linkedin.android": "professional",
    "com.google.android.gm": "email",
    "com.microsoft.teams": "productivity",
    "com.google.android.apps.meetings": "productivity",
    "com.google.android.apps.docs": "productivity",
    "com.microsoft.office.word": "productivity",
    "com.microsoft.office.excel": "productivity",
    "com.microsoft.office.powerpoint": "productivity",
    "com.google.android.keep": "notes",
    "com.evernote": "notes",
    "com.notion.id": "notes",
    "com.google.android.apps.maps": "navigation",
    "com.google.android.dialer": "calls",
    "com.android.phone": "calls",
    "com.android.settings": "settings",
    "com.android.launcher3": "launcher",
    "com.google.android.launcher": "launcher",
}

_PREFIX_CATEGORIES: list[tuple[str, str]] = [
    ("com.google.android.apps.camera", "camera"),
    ("com.android.camera", "camera"),
    ("com.google.android.apps.photos", "photos"),
    ("com.android.gallery", "photos"),
    ("com.google.android.calendar", "calendar"),
    ("com.android.calendar", "calendar"),
    ("com.google.android.contacts", "contacts"),
    ("com.android.contacts", "contacts"),
    ("com.android.", "system"),
    ("com.google.android.", "google"),
    ("com.microsoft.", "productivity"),
]


def _categorize_app(package: str) -> str:
    """Map an Android package name to a privacy-preserving category."""
    p = (package or "").strip().lower()
    if not p:
        return "other"
    exact = _EXACT_CATEGORIES.get(p)
    if exact:
        return exact
    for prefix, category in _PREFIX_CATEGORIES:
        if p.startswith(prefix):
            return category
    return "other"


# ── JSONL parsing ─────────────────────────────────────────────────────────────

_VALID_TYPES = frozenset({
    "screen_on", "screen_off", "unlock",
    "app_foreground", "app_background",
    "charging_on", "charging_off",
})


def parse_session_jsonl(jsonl_text: str) -> list[dict]:
    """Parse JSONL events from a Tasker/Termux session log.

    Tolerant: malformed lines are skipped. Returns events sorted by timestamp
    ascending. Only events with a valid ``ts`` (integer) and a recognised
    ``type`` are kept. ``app_foreground`` and ``app_background`` events carry
    an ``app`` field (package name, trimmed to 200 chars).
    """
    events: list[dict] = []
    for line in (jsonl_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        ev_type = str(obj.get("type", "")).strip()
        if ev_type not in _VALID_TYPES:
            continue
        try:
            ts = int(obj["ts"])
        except (KeyError, TypeError, ValueError):
            continue
        ev: dict[str, Any] = {"ts": ts, "type": ev_type}
        if ev_type in ("app_foreground", "app_background"):
            ev["app"] = str(obj.get("app", "")).strip()[:200]
        events.append(ev)
    events.sort(key=lambda e: e["ts"])
    return events


# ── aggregation helpers ───────────────────────────────────────────────────────

def _filter_window(events: list[dict], since: date, until: date) -> list[dict]:
    """Keep only events whose timestamp falls within [since, until] local day."""
    lo = int(datetime(since.year, since.month, since.day).timestamp())
    hi = int((datetime(until.year, until.month, until.day) + timedelta(days=1)).timestamp())
    return [e for e in events if lo <= e["ts"] < hi]


def _derive_screen_sessions(events: list[dict]) -> list[dict]:
    """Pair screen_on -> screen_off into sessions.

    An unclosed screen_on (screen still on at log end) is kept with
    end_ts == the last event's timestamp (best-effort bound).
    """
    sessions: list[dict] = []
    last_on: Optional[int] = None
    last_ts = events[-1]["ts"] if events else 0
    for e in events:
        if e["type"] == "screen_on":
            last_on = e["ts"]
        elif e["type"] == "screen_off" and last_on is not None:
            dur = max(0, e["ts"] - last_on)
            sessions.append({
                "start_ts": last_on,
                "end_ts": e["ts"],
                "duration_min": round(dur / 60.0, 1),
            })
            last_on = None
    if last_on is not None and last_ts > last_on:
        dur = last_ts - last_on
        sessions.append({
            "start_ts": last_on,
            "end_ts": last_ts,
            "duration_min": round(dur / 60.0, 1),
        })
    return sessions


def _derive_idle_blocks(
    sessions: list[dict],
    day_start_ts: int,
    day_end_ts: int,
    *,
    min_idle_min: int = 30,
) -> list[dict]:
    """Return gaps between screen sessions (and at day boundaries) >= min_idle_min.

    Includes a leading idle block if the first screen session starts late in the
    day, and a trailing idle block if the last session ends well before midnight.
    """
    gaps: list[dict] = []
    threshold = min_idle_min * 60

    boundaries: list[tuple[int, int]] = []
    if sessions:
        if sessions[0]["start_ts"] - day_start_ts >= threshold:
            boundaries.append((day_start_ts, sessions[0]["start_ts"]))
        for i in range(1, len(sessions)):
            gap_start = sessions[i - 1]["end_ts"]
            gap_end = sessions[i]["start_ts"]
            if gap_end - gap_start >= threshold:
                boundaries.append((gap_start, gap_end))
        if day_end_ts - sessions[-1]["end_ts"] >= threshold:
            boundaries.append((sessions[-1]["end_ts"], day_end_ts))
    else:
        boundaries.append((day_start_ts, day_end_ts))

    for start, end in boundaries:
        gaps.append({
            "start_ts": start,
            "end_ts": end,
            "duration_min": round((end - start) / 60.0, 1),
        })
    return gaps


def _derive_charging_periods(events: list[dict]) -> list[dict]:
    """Pair charging_on -> charging_off into periods."""
    periods: list[dict] = []
    last_on: Optional[int] = None
    for e in events:
        if e["type"] == "charging_on":
            last_on = e["ts"]
        elif e["type"] == "charging_off" and last_on is not None:
            dur = max(0, e["ts"] - last_on)
            periods.append({
                "start_ts": last_on,
                "end_ts": e["ts"],
                "duration_min": round(dur / 60.0, 1),
            })
            last_on = None
    return periods


def _derive_app_sessions(events: list[dict]) -> list[dict]:
    """Pair app_foreground -> app_background into app sessions.

    An unclosed foreground (app still in front at log end) is kept with
    end_ts == the last event's timestamp. Sessions carry the privacy-safe
    ``category`` from ``_categorize_app``; the raw ``app`` package name is
    retained only in this internal dict (never written to the HFL corpus).
    """
    sessions: list[dict] = []
    in_fg: dict[str, int] = {}
    last_ts = events[-1]["ts"] if events else 0
    for e in events:
        if e["type"] == "app_foreground":
            pkg = e.get("app", "")
            if pkg:
                in_fg[pkg] = e["ts"]
        elif e["type"] == "app_background":
            pkg = e.get("app", "")
            if pkg and pkg in in_fg:
                dur = max(0, e["ts"] - in_fg[pkg])
                sessions.append({
                    "app": pkg,
                    "category": _categorize_app(pkg),
                    "start_ts": in_fg.pop(pkg),
                    "end_ts": e["ts"],
                    "duration_sec": dur,
                })
    for pkg, start in in_fg.items():
        if last_ts > start:
            sessions.append({
                "app": pkg,
                "category": _categorize_app(pkg),
                "start_ts": start,
                "end_ts": last_ts,
                "duration_sec": last_ts - start,
            })
    return sorted(sessions, key=lambda s: s["start_ts"])


def _category_breakdown(app_sessions: list[dict]) -> dict[str, int]:
    """Aggregate total seconds per category from app sessions."""
    totals: dict[str, int] = {}
    for s in app_sessions:
        cat = s["category"]
        totals[cat] = totals.get(cat, 0) + s["duration_sec"]
    return totals


def _classify_focus_windows(
    screen_sessions: list[dict],
    app_sessions: list[dict],
    *,
    focus_min_duration_min: int = 20,
    focus_dominance_pct: float = 0.55,
) -> list[dict]:
    """Find screen sessions >= focus_min_duration_min where one app category dominates.

    A focus window requires both a long session AND one category consuming at
    least ``focus_dominance_pct`` of the app time within that session.
    Returns list of {start_ts, end_ts, duration_min, category, dominance_pct}.
    """
    focus: list[dict] = []
    for ss in screen_sessions:
        if ss["duration_min"] < focus_min_duration_min:
            continue
        overlapping = [
            a for a in app_sessions
            if a["start_ts"] < ss["end_ts"] and a["end_ts"] > ss["start_ts"]
        ]
        if not overlapping:
            continue
        totals: dict[str, int] = {}
        for a in overlapping:
            cat = a["category"]
            totals[cat] = totals.get(cat, 0) + a["duration_sec"]
        grand = sum(totals.values())
        if grand == 0:
            continue
        top_cat, top_sec = max(totals.items(), key=lambda x: x[1])
        if top_sec / grand >= focus_dominance_pct:
            focus.append({
                "start_ts": ss["start_ts"],
                "end_ts": ss["end_ts"],
                "duration_min": ss["duration_min"],
                "category": top_cat,
                "dominance_pct": round(100 * top_sec / grand),
            })
    return focus


def _classify_fragmented_periods(
    screen_sessions: list[dict],
    *,
    fragment_max_duration_min: float = 5.0,
    fragment_window_min: int = 30,
    fragment_min_count: int = 4,
) -> list[dict]:
    """Find bursts of short screen sessions within a rolling time window.

    A fragmented period is ``fragment_min_count`` or more screen sessions each
    lasting <= ``fragment_max_duration_min`` minutes, all falling within a
    ``fragment_window_min``-minute window. Returns {start_ts, end_ts,
    session_count, window_min}.
    """
    short = [s for s in screen_sessions if s["duration_min"] <= fragment_max_duration_min]
    periods: list[dict] = []
    i = 0
    while i < len(short):
        j = i + 1
        while j < len(short):
            span_min = (short[j]["end_ts"] - short[i]["start_ts"]) / 60.0
            if span_min > fragment_window_min:
                break
            j += 1
        cluster = short[i:j]
        if len(cluster) >= fragment_min_count:
            periods.append({
                "start_ts": cluster[0]["start_ts"],
                "end_ts": cluster[-1]["end_ts"],
                "session_count": len(cluster),
                "window_min": round(
                    (cluster[-1]["end_ts"] - cluster[0]["start_ts"]) / 60.0, 1
                ),
            })
            i = j
        else:
            i += 1
    return periods


def aggregate_sessions(
    events: list[dict],
    since: date,
    until: date,
    *,
    min_idle_min: int = 30,
    focus_min_duration_min: int = 20,
    focus_dominance_pct: float = 0.55,
    fragment_max_duration_min: float = 5.0,
    fragment_window_min: int = 30,
    fragment_min_count: int = 4,
) -> dict[str, Any]:
    """Turn raw events into aggregated session metrics.

    Returns a dict with: date, unlock_count, screen_session_count,
    total_screen_time_min, focus_window_count, fragmented_period_count,
    idle_block_count, longest_idle_min, charging_count, category_breakdown,
    focus_windows, fragmented_periods, idle_blocks, charging_periods,
    screen_sessions, and ``_events`` (the raw filtered events — internal only,
    must NOT flow into HFL prose).
    """
    filtered = _filter_window(events, since, until)

    day_start = int(datetime(since.year, since.month, since.day).timestamp())
    day_end = int(
        (datetime(until.year, until.month, until.day) + timedelta(days=1)).timestamp()
    )

    screen_sessions = _derive_screen_sessions(filtered)
    unlock_count = sum(1 for e in filtered if e["type"] == "unlock")
    app_sessions = _derive_app_sessions(filtered)
    charging_periods = _derive_charging_periods(filtered)
    idle_blocks = _derive_idle_blocks(
        screen_sessions, day_start, day_end, min_idle_min=min_idle_min
    )
    focus_windows = _classify_focus_windows(
        screen_sessions, app_sessions,
        focus_min_duration_min=focus_min_duration_min,
        focus_dominance_pct=focus_dominance_pct,
    )
    fragmented_periods = _classify_fragmented_periods(
        screen_sessions,
        fragment_max_duration_min=fragment_max_duration_min,
        fragment_window_min=fragment_window_min,
        fragment_min_count=fragment_min_count,
    )
    category_breakdown = _category_breakdown(app_sessions)
    total_screen_min = round(sum(s["duration_min"] for s in screen_sessions), 1)
    longest_idle_min = round(
        max((b["duration_min"] for b in idle_blocks), default=0.0), 1
    )

    return {
        "date": since.isoformat(),
        "unlock_count": unlock_count,
        "screen_session_count": len(screen_sessions),
        "total_screen_time_min": total_screen_min,
        "focus_window_count": len(focus_windows),
        "fragmented_period_count": len(fragmented_periods),
        "idle_block_count": len(idle_blocks),
        "longest_idle_min": longest_idle_min,
        "charging_count": len(charging_periods),
        "category_breakdown": category_breakdown,
        "focus_windows": focus_windows,
        "fragmented_periods": fragmented_periods,
        "idle_blocks": idle_blocks,
        "charging_periods": charging_periods,
        "screen_sessions": screen_sessions,
        # Internal-only raw events. HFL prose and normal responses must not
        # expose individual timestamps or package names from this list.
        "_events": filtered,
    }


# ── LLM prompt body ───────────────────────────────────────────────────────────

def _fmt_hhmm(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def _activity_body(activity: dict) -> str:
    """Build the LLM prompt body. No raw package names, no exact coordinates."""
    lines: list[str] = [
        f"Date: {activity['date']}",
        f"Unlocks: {activity['unlock_count']}",
        f"Total screen time: {activity['total_screen_time_min']} min",
        f"Screen sessions: {activity['screen_session_count']}",
        f"Focus windows (>= 20 min, one dominant category): {activity['focus_window_count']}",
        f"Fragmented periods (burst of short check-ins): {activity['fragmented_period_count']}",
        f"Longest idle block: {activity['longest_idle_min']} min",
        f"Charging sessions: {activity['charging_count']}",
        "",
    ]

    if activity.get("focus_windows"):
        lines.append("Focus windows:")
        for fw in activity["focus_windows"]:
            lines.append(
                f"  {_fmt_hhmm(fw['start_ts'])}-{_fmt_hhmm(fw['end_ts'])}"
                f"  ({fw['duration_min']} min, category: {fw['category']},"
                f" {fw['dominance_pct']}% dominant)"
            )
        lines.append("")

    if activity.get("fragmented_periods"):
        lines.append("Fragmented periods:")
        for fp in activity["fragmented_periods"]:
            lines.append(
                f"  {_fmt_hhmm(fp['start_ts'])}-{_fmt_hhmm(fp['end_ts'])}"
                f"  ({fp['session_count']} sessions in {fp['window_min']} min)"
            )
        lines.append("")

    if activity.get("idle_blocks"):
        lines.append("Idle blocks (screen off >= 30 min):")
        for ib in activity["idle_blocks"]:
            lines.append(
                f"  {_fmt_hhmm(ib['start_ts'])}-{_fmt_hhmm(ib['end_ts'])}"
                f"  ({ib['duration_min']} min)"
            )
        lines.append("")

    if activity.get("category_breakdown"):
        lines.append("App category breakdown (minutes on-screen, top 8):")
        sorted_cats = sorted(
            activity["category_breakdown"].items(), key=lambda x: -x[1]
        )
        for cat, secs in sorted_cats[:8]:
            lines.append(f"  {cat}: {round(secs / 60)} min")

    return "\n".join(lines)


# ── distillation ──────────────────────────────────────────────────────────────

def distill_android_session_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn session metrics into HFL entry fields (Haiku, raw fallback)."""
    unlocks = activity.get("unlock_count", 0)
    screen_min = activity.get("total_screen_time_min", 0)
    focus_count = activity.get("focus_window_count", 0)
    frag_count = activity.get("fragmented_period_count", 0)

    def _fallback() -> dict:
        parts: list[str] = [f"{unlocks} unlock(s)", f"{screen_min} min screen time"]
        if focus_count:
            parts.append(f"{focus_count} focus window(s)")
        if frag_count:
            parts.append(f"{frag_count} fragmented period(s)")
        return {
            "skip": False,
            "moment": "Android session rhythm: " + ", ".join(parts),
            "what_happened": _activity_body(activity),
            "why_it_stayed": "",
            "possible_use": "attention log, focus tracking",
            "tags": ["android", "session-rhythm"],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = f"Android session rhythm for the day:\n\n{_activity_body(activity)}"
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_android_session: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_android_session").strip(),
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
        parsed["tags"] = [
            str(t).strip().lstrip("#") for t in (parsed.get("tags") or [])
        ]
        parsed["synthesized"] = True
        return parsed
    except Exception as exc:  # noqa: BLE001 - never break the beat on API error
        _log.warning("ingest_android_session: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


# ── data path + collection ────────────────────────────────────────────────────

def _resolve_data_path() -> Optional[Path]:
    """Resolve the Android session JSONL data path. Returns None if not set.

    Guards against unset env vars leaving a literal "${...}" placeholder in
    app_data — mirrors the same check in ingest_spotify._credentials_present.
    """
    try:
        from apps.apps_config import CONFIG_MANAGER  # type: ignore[import]
        cfg = CONFIG_MANAGER.get("ANDROID_SESSION")
        if cfg and isinstance(cfg, dict):
            p = (cfg.get("data") or {}).get("path")
            if p and "${" not in str(p):
                return Path(p).resolve()
    except Exception:
        pass
    env_path = os.environ.get("ANDROID_SESSION_JSONL_PATH", "").strip()
    if env_path:
        return Path(env_path).resolve()
    return None


def _session_window(window_days: int, *, today: Optional[date] = None) -> tuple[date, date]:
    end = today or datetime.now().date()
    days = max(1, int(window_days or 1))
    start = end - timedelta(days=days - 1)
    return start, end


def collect_android_session_activity(
    data_path: Path,
    *,
    since: date,
    until: date,
    min_idle_min: int = 30,
    focus_min_duration_min: int = 20,
    focus_dominance_pct: float = 0.55,
    fragment_max_duration_min: float = 5.0,
    fragment_window_min: int = 30,
    fragment_min_count: int = 4,
) -> dict[str, Any]:
    """Read session events from ``data_path`` and aggregate into session metrics.

    On OSError (file unreadable, permission denied) returns a safe dict with
    an ``error`` key and zero counts so the task can no-op cleanly.
    """
    try:
        text = data_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "error": str(exc)[:200],
            "date": since.isoformat(),
            "unlock_count": 0,
            "screen_session_count": 0,
            "total_screen_time_min": 0,
            "focus_window_count": 0,
            "fragmented_period_count": 0,
            "idle_block_count": 0,
            "longest_idle_min": 0,
            "charging_count": 0,
            "category_breakdown": {},
            "focus_windows": [],
            "fragmented_periods": [],
            "idle_blocks": [],
            "charging_periods": [],
            "screen_sessions": [],
            "_events": [],
        }
    events = parse_session_jsonl(text)
    return aggregate_sessions(
        events, since, until,
        min_idle_min=min_idle_min,
        focus_min_duration_min=focus_min_duration_min,
        focus_dominance_pct=focus_dominance_pct,
        fragment_max_duration_min=fragment_max_duration_min,
        fragment_window_min=fragment_window_min,
        fragment_min_count=fragment_min_count,
    )


# ── task ──────────────────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def ingest_android_session_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    min_idle_min: int = 30,
    focus_min_duration_min: int = 20,
    fragment_min_count: int = 4,
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's Android session rhythm.

    No data path configured -> no entry, no LLM call (clean no-op).
    No events in the window -> no entry, no LLM call.
    """
    data_path = _resolve_data_path()
    if data_path is None:
        _log.info("ingest_android_session: ANDROID_SESSION_JSONL_PATH not set — skip")
        return {"skipped": "no data path", "entries_written": 0}

    if not data_path.exists():
        _log.info("ingest_android_session: data file not found at %s — skip", data_path)
        return {"skipped": "file not found", "entries_written": 0, "path": str(data_path)}

    since, until = _session_window(window_days)

    try:
        activity = collect_android_session_activity(
            data_path, since=since, until=until,
            min_idle_min=min_idle_min,
            focus_min_duration_min=focus_min_duration_min,
            fragment_min_count=fragment_min_count,
        )
    except Exception as exc:  # noqa: BLE001 - file parse errors must not break the beat
        _log.error("ingest_android_session: collect failed (%s)", exc)
        return {"skipped": "collect error", "entries_written": 0, "error": str(exc)[:200]}

    if activity.get("error"):
        _log.warning("ingest_android_session: data read error — %s", activity["error"])
        return {"skipped": "read error", "entries_written": 0, "error": activity["error"]}

    if activity["screen_session_count"] == 0 and activity["unlock_count"] == 0:
        _log.info(
            "ingest_android_session: no session events in last %d day(s)", window_days
        )
        return {"skipped": "no events", "entries_written": 0}

    d = distill_android_session_activity(
        activity, synthesize=True, model=model, cfg_id=cfg_id__anthropic,
    )
    if d.get("skip"):
        _log.info("ingest_android_session: distilled as skip")
        return {"skipped": "distilled-skip", "entries_written": 0}

    base_tags = {"android", "session-rhythm"}
    extra = [
        str(t) for t in (d.get("tags") or [])
        if str(t).strip().lower() not in base_tags
    ][:5]
    tags = ["android", "session-rhythm"] + extra

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"
    entry = _build_entry(
        when=when,
        moment=d["moment"],
        what_happened=d["what_happened"],
        why_it_stayed=d["why_it_stayed"],
        possible_use=d["possible_use"] or "attention log",
        tags=tags,
        references=[],
    )
    bytes_written, doc_id = append_entry(
        day_file, entry, source="android-session", synthesized=d.get("synthesized", False),
    )

    _log.info(
        "ingest_android_session: entry written (%d unlocks, %.0f min screen) -> %s",
        activity["unlock_count"], activity["total_screen_time_min"], day_file,
    )
    return {
        "entries_written": 1,
        "unlock_count": activity["unlock_count"],
        "total_screen_time_min": activity["total_screen_time_min"],
        "focus_windows": activity["focus_window_count"],
        "fragmented_periods": activity["fragmented_period_count"],
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": str(day_file),
        "indexed": doc_id is not None,
    }
