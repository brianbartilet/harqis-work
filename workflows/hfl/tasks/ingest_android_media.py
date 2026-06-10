"""
workflows/hfl/tasks/ingest_android_media.py

Daily Android screen activity → HFL corpus. Parses the hourly
android_actions-YYYYMMDD_HH.log files written by the Android capture agent
(mobile/android/tasks/capture.py), classifies foreground app sessions by
category, and distils the day's screen-attention arc into ONE
Homework-for-Life entry — dual-written to the Markdown corpus + the
harqis-hfl-entries ES index.

Source: the log directory pointed at by the env var
HFL_ANDROID_SCREEN_LOG_DIR — absolute path to where the Android log files
land after being synced from the device (rsync, scp, Tailscale share, or
direct mount). Unlike ingest_browsing (which has a %LOCALAPPDATA% default)
there is NO default path — if the env var is unset the task no-ops cleanly
with no I/O.

Log format (one entry per line):
  [YYYY-MM-DD HH:MM:SS] FOCUS: <dumpsys mCurrentFocus line>
  [YYYY-MM-DD HH:MM:SS] OCR: <screen text fragment>

Privacy rule: OCR text content is NEVER passed to the model or written to
HFL entries. Only inferred app categories and session counts are surfaced.

Centralized, single-device source: this runs on the Beat host (HFL queue),
NOT broadcast per-machine like ingest_browsing. Clean no-op until
HFL_ANDROID_SCREEN_LOG_DIR is set and populated.

The collectors (collect_android_media_activity / distill_android_media_activity)
are plain functions so the MCP tool (workflows/hfl/mcp.py :: android_activity)
can reuse them for a live, no-write view.
"""

from __future__ import annotations

import os
import re
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

_log = create_logger("hfl.ingest_android_media")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"
_SYSTEM_PROMPT = load_prompt("ingest_android_media").strip()

# ── Log line parsing ──────────────────────────────────────────────────────────

_LOG_LINE_RE = re.compile(
    r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (FOCUS|OCR): (.+)'
)
_PACKAGE_RE = re.compile(r'u\d+\s+([\w.]+)/')


def _parse_log_line(line: str) -> Optional[dict]:
    """Parse one android_actions log line into a structured dict.

    Returns {"ts": datetime, "kind": "focus"|"ocr", "content": str} or None
    for malformed / blank lines.
    """
    m = _LOG_LINE_RE.match(line.strip())
    if not m:
        return None
    try:
        ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return {
        "ts": ts,
        "kind": m.group(2).lower(),
        "content": m.group(3).strip(),
    }


def _extract_package(focus_line: str) -> Optional[str]:
    """Extract the Android package name from a mCurrentFocus dumpsys string.

    Pattern targets lines like:
      mCurrentFocus=Window{abc u0 com.google.android.docs/...}
    Returns None for system dialogs, null focus, and unparseable lines.
    """
    m = _PACKAGE_RE.search(focus_line or "")
    if not m:
        return None
    return m.group(1)


# ── Package → category classification ────────────────────────────────────────

_CATEGORY_PREFIXES: list[tuple[str, str]] = [
    # Productivity
    ("com.google.android.docs", "productivity"),
    ("com.google.android.sheets", "productivity"),
    ("com.google.android.slides", "productivity"),
    ("com.microsoft.office", "productivity"),
    ("com.microsoft.teams", "communication"),
    ("com.todoist", "productivity"),
    ("com.notion", "productivity"),
    ("com.obsidian", "productivity"),
    # Browsing
    ("com.android.chrome", "browsing"),
    ("org.mozilla", "browsing"),
    ("com.brave", "browsing"),
    # Social
    ("com.instagram", "social"),
    ("com.twitter", "social"),
    ("com.facebook", "social"),
    ("com.reddit", "social"),
    ("com.linkedin", "social"),
    # Entertainment
    ("com.spotify", "entertainment"),
    ("com.soundcloud", "entertainment"),
    ("com.netflix", "entertainment"),
    ("com.youtube", "entertainment"),
    ("com.google.android.youtube", "entertainment"),
    ("tv.twitch", "entertainment"),
    # Communication
    ("com.slack", "communication"),
    ("org.telegram", "communication"),
    ("com.whatsapp", "communication"),
    ("com.discord", "communication"),
    ("com.google.android.gm", "communication"),
    ("com.microsoft.outlook", "communication"),
    # Development
    ("com.jetbrains", "development"),
    ("com.github", "development"),
    ("com.termux", "development"),
    # System
    ("com.android.settings", "system"),
    ("com.android.launcher", "system"),
    ("com.google.android.launcher", "system"),
]


def _classify_package(package: str) -> str:
    """Infer the app category from the package name prefix."""
    if not package:
        return "system"
    p = package.lower()
    for prefix, category in _CATEGORY_PREFIXES:
        if p.startswith(prefix):
            return category
    # Heuristic fallback: known tld patterns
    if p.startswith("com.google.android"):
        return "system"
    if p.startswith("com.android"):
        return "system"
    return "other"


# ── Tag helpers ───────────────────────────────────────────────────────────────

def _package_tag(package: str) -> Optional[str]:
    """Derive a short tag from a package name (com.google → google, etc.)."""
    if not package:
        return None
    parts = package.split(".")
    # Skip generic prefixes and return the first meaningful segment
    skip = {"com", "org", "net", "io", "co", "android"}
    for part in parts:
        if part and part not in skip and not part.startswith("android"):
            return part.lower()[:20]
    return None


# ── Collection ────────────────────────────────────────────────────────────────

def collect_android_media_activity(
    *,
    since: date,
    until: date,
    logs_dir: str,
    max_log_files: int = 24,
) -> dict[str, Any]:
    """Parse android_actions log files in a date window into a structured dict.

    Globs logs_dir for android_actions-YYYYMMDD_HH.log files whose embedded
    date falls within [since, until]. Parses FOCUS and OCR lines; groups
    consecutive same-package FOCUS runs into sessions. Does NOT pass OCR
    content to callers — the count is included for context only.

    Returns:
        {log_files_found, session_count, app_switches, top_apps,
         window_start, window_end, logs_dir}
    """
    logs_path = Path(logs_dir).expanduser()
    all_files = sorted(logs_path.glob("android_actions-*.log"))

    # Filter by embedded date in the filename: android_actions-YYYYMMDD_HH.log
    _date_re = re.compile(r'android_actions-(\d{8})_\d{2}\.log$')
    in_window: list[Path] = []
    for f in all_files:
        m = _date_re.match(f.name)
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if since <= file_date <= until:
            in_window.append(f)

    in_window = in_window[:max_log_files]

    # Parse all lines
    all_parsed: list[dict] = []
    for f in in_window:
        try:
            for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
                parsed = _parse_log_line(raw)
                if parsed:
                    all_parsed.append(parsed)
        except OSError as exc:
            _log.warning("ingest_android_media: failed to read %s (%s)", f, exc)

    if not all_parsed:
        return {
            "log_files_found": len(in_window),
            "session_count": 0,
            "app_switches": 0,
            "top_apps": [],
            "window_start": since.isoformat(),
            "window_end": until.isoformat(),
            "logs_dir": str(logs_dir),
        }

    # Build sessions: consecutive FOCUS lines with the same package = 1 session.
    sessions: list[dict] = []
    current_package: Optional[str] = None
    current_start: Optional[datetime] = None
    current_end: Optional[datetime] = None
    current_ocr: int = 0
    app_switches = 0

    for entry in sorted(all_parsed, key=lambda e: e["ts"]):
        if entry["kind"] == "focus":
            pkg = _extract_package(entry["content"])
            if pkg is None:
                continue
            if pkg != current_package:
                if current_package is not None:
                    sessions.append({
                        "package": current_package,
                        "start_ts": current_start,
                        "end_ts": current_end,
                        "ocr_lines_count": current_ocr,
                    })
                    app_switches += 1
                current_package = pkg
                current_start = entry["ts"]
                current_end = entry["ts"]
                current_ocr = 0
            else:
                current_end = entry["ts"]
        elif entry["kind"] == "ocr":
            current_ocr += 1
            if current_end:
                current_end = entry["ts"]

    # Flush the last open session
    if current_package is not None:
        sessions.append({
            "package": current_package,
            "start_ts": current_start,
            "end_ts": current_end,
            "ocr_lines_count": current_ocr,
        })

    # Aggregate per-package totals
    pkg_map: dict[str, dict] = {}
    for s in sessions:
        pkg = s["package"]
        if pkg not in pkg_map:
            pkg_map[pkg] = {
                "package": pkg,
                "session_count": 0,
                "ocr_lines": 0,
                "category": _classify_package(pkg),
            }
        pkg_map[pkg]["session_count"] += 1
        pkg_map[pkg]["ocr_lines"] += s["ocr_lines_count"]

    top_apps = sorted(
        pkg_map.values(), key=lambda x: x["session_count"], reverse=True
    )

    window_start = all_parsed[0]["ts"].strftime("%Y-%m-%d %H:%M") if all_parsed else since.isoformat()
    window_end = all_parsed[-1]["ts"].strftime("%Y-%m-%d %H:%M") if all_parsed else until.isoformat()

    return {
        "log_files_found": len(in_window),
        "session_count": len(sessions),
        "app_switches": app_switches,
        "top_apps": top_apps,
        "window_start": window_start,
        "window_end": window_end,
        "logs_dir": str(logs_dir),
    }


# ── Distillation ──────────────────────────────────────────────────────────────

def _activity_body(activity: dict) -> str:
    """Compact, model-friendly view of the Android screen activity.

    Passes only app categories and session counts — never raw OCR content.
    """
    lines: list[str] = [
        f"{activity['session_count']} app sessions, "
        f"{activity['app_switches']} switches, "
        f"window {activity['window_start']}–{activity['window_end']}",
        "",
        "Top apps by session count:",
    ]
    for app in activity["top_apps"][:15]:
        pkg_label = app["package"]
        category = app.get("category", "other")
        ocr_note = f" [ocr: {app['ocr_lines']} lines]" if app["ocr_lines"] > 0 else ""
        lines.append(
            f"- {pkg_label} ({category}): {app['session_count']} session(s){ocr_note}"
        )
    lines.append("")
    lines.append("Note: OCR text content is summarized, not reproduced verbatim.")
    return "\n".join(lines)


def distill_android_media_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn collected Android screen activity into HFL entry fields.

    synthesize=True: calls Claude Haiku with the privacy-safe activity body.
    synthesize=False: returns a deterministic raw fallback (no API call).
    Either way, raw OCR content is never included in the returned entry.
    """
    session_count = activity["session_count"]
    top_apps = activity.get("top_apps") or []
    n_apps = len(top_apps)

    def _fallback() -> dict:
        top_cats = list(dict.fromkeys(
            app.get("category", "other") for app in top_apps[:6]
            if app.get("category") not in (None, "system", "other")
        ))[:4]
        return {
            "skip": False,
            "moment": f"{session_count} Android screen sessions across {n_apps} app(s)",
            "what_happened": "\n".join(
                f"- {a['package']} ({a.get('category','other')}): "
                f"{a['session_count']} session(s)"
                for a in top_apps[:10]
            ),
            "why_it_stayed": "",
            "possible_use": "focus log",
            "tags": ["android", "screen-activity"] + top_cats,
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = (
        f"Today's Android screen activity:\n\n{_activity_body(activity)}"
    )
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_android_media: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=_SYSTEM_PROMPT,
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
        _log.warning("ingest_android_media: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


# ── Celery task ───────────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def ingest_android_media_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    max_log_files: int = 24,
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's Android screen activity.

    HFL_ANDROID_SCREEN_LOG_DIR not set or dir missing → no entry, no I/O.
    No log files in the window → no entry, no LLM call.
    No sessions → no entry, no LLM call.

    Privacy: OCR text is never written to the corpus or sent to the model.
    Only app categories and session counts are used.
    """
    # Guard 1: env var must be set
    logs_dir = os.environ.get("HFL_ANDROID_SCREEN_LOG_DIR", "").strip()
    if not logs_dir:
        _log.info("ingest_android_media: HFL_ANDROID_SCREEN_LOG_DIR not set — no-op")
        return {"skipped": "no log dir", "entries_written": 0}

    # Guard 2: directory must exist
    logs_path = Path(logs_dir).expanduser()
    if not logs_path.exists():
        _log.info("ingest_android_media: log dir missing (%s) — no-op", logs_dir)
        return {"skipped": "log dir missing", "entries_written": 0}

    # Window
    until = datetime.now().date()
    since = until - timedelta(days=window_days)

    activity = collect_android_media_activity(
        since=since, until=until,
        logs_dir=logs_dir, max_log_files=max_log_files,
    )

    # Guard 3: log files must be present
    if activity["log_files_found"] == 0:
        _log.info("ingest_android_media: no log files in last %d day(s)", window_days)
        return {"skipped": "no log files", "entries_written": 0}

    # Guard 4: sessions must be present
    if activity["session_count"] == 0:
        _log.info("ingest_android_media: no sessions in last %d day(s)", window_days)
        return {"skipped": "no sessions", "entries_written": 0}

    d = distill_android_media_activity(
        activity, synthesize=True, model=model,
        cfg_id=cfg_id__anthropic, max_tokens=900,
    )
    if d.get("skip"):
        _log.info(
            "ingest_android_media: distilled as skip — %d sessions not story-worthy",
            activity["session_count"],
        )
        return {"skipped": "distilled-skip", "entries_written": 0,
                "session_count": activity["session_count"]}

    # Build tags: base tags + model-inferred tags; cap at 6 total
    base_tags = ["android", "screen-activity"]
    extra = [
        str(t) for t in (d.get("tags") or [])
        if str(t).strip().lower() not in ("android", "screen-activity")
    ][:4]
    tags = base_tags + extra

    # Optionally enrich with package-derived tags from top apps
    for app in (activity.get("top_apps") or [])[:3]:
        pkg_tag = _package_tag(app.get("package", ""))
        if pkg_tag and pkg_tag not in tags:
            tags.append(pkg_tag)
            if len(tags) >= 6:
                break
    tags = tags[:6]

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"

    # source_metadata: device_type + capture_type for HFL provenance
    entry = _build_entry(
        when=when,
        moment=d["moment"],
        what_happened=d["what_happened"],
        why_it_stayed=d["why_it_stayed"],
        possible_use=d["possible_use"] or "focus log",
        tags=tags,
        references=[],
    )
    bytes_written, doc_id = append_entry(
        day_file, entry,
        source="android_media",
        synthesized=d.get("synthesized", False),
    )

    _log.info(
        "ingest_android_media: entry written (%d sessions, %d apps, %d log files) → %s",
        activity["session_count"], len(activity["top_apps"]),
        activity["log_files_found"], day_file,
    )
    return {
        "entries_written": 1,
        "session_count": activity["session_count"],
        "log_files": activity["log_files_found"],
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": str(day_file),
        "indexed": doc_id is not None,
    }
