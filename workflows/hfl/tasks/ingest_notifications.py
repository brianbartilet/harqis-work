"""
workflows/hfl/tasks/ingest_notifications.py

Daily Android notification metadata → HFL corpus. Reads privacy-first
notification records from a JSONL drop file (one JSON object per line),
aggregates the day's notification pattern into an attention-signal digest,
and distils it into ONE Homework-for-Life entry — an "attention / interruption
climate" beat — dual-written to the Markdown corpus + the harqis-hfl-entries
ES index.

Input contract — one JSON object per notification event:

    {"ts": "2026-06-01T09:15:22",   # ISO timestamp (required)
     "app": "com.whatsapp",          # package name (required)
     "app_label": "WhatsApp",        # human-readable label (required)
     "category": "msg"}              # msg | call | alarm | sys | media | other

Privacy boundary — strictly enforced server-side:
    - Notification titles, bodies, and raw message content are NEVER read,
      stored, or forwarded to any LLM. Only app name, category, and
      hour-of-day aggregates are used.
    - Any record that includes a "title", "text", or "body" key has those
      fields silently stripped before any processing occurs.
    - Raw package names that appear in the JSONL are kept only for
      app_label resolution; the label (not the package) goes to the LLM.

Android-side integration (Tasker / MacroDroid / Termux):
    Write one JSONL record per notification to a dated drop file:

        {HFL_NOTIFICATIONS_DIR}/android_notifications_{YYYYMMDD}.jsonl

    Drop-file location resolves (first hit wins):
        1. env var  HFL_ANDROID_NOTIFICATIONS_DIR
        2. {HFL_CORPUS_PATH}/android_notifications_inbox/

    See docs/android-notification-digest.md for Tasker / MacroDroid profiles
    and the JSONL schema reference.

No drop file or no records in the window → clean no-op (no LLM, no entry;
the beat never breaks). Multiple callers writing to the same file is safe —
the task is read-only on the JSONL files; corpus append is the only write.
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

_log = create_logger("hfl.ingest_notifications")

_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"

# Privacy: fields that must never be retained from a JSONL record.
_STRIP_FIELDS = frozenset({
    "title", "text", "body", "big_text", "summary_text",
    "info_text", "sub_text", "ticker", "content",
})

_VALID_CATEGORIES = frozenset({"msg", "call", "alarm", "sys", "media", "other"})


# ── path resolution ───────────────────────────────────────────────────────────

def resolve_notifications_dir() -> Path:
    """Resolve the Android notifications JSONL inbox directory.

    First hit wins:
        1. env var HFL_ANDROID_NOTIFICATIONS_DIR
        2. {HFL_CORPUS_PATH}/android_notifications_inbox/
    """
    env_path = os.environ.get("HFL_ANDROID_NOTIFICATIONS_DIR", "").strip()
    if env_path and "${" not in env_path:
        return Path(env_path).resolve()
    return (resolve_corpus_dir() / "android_notifications_inbox").resolve()


def _drop_file(notifications_dir: Path, day: date) -> Path:
    return notifications_dir / f"android_notifications_{day.strftime('%Y%m%d')}.jsonl"


# ── parsing ───────────────────────────────────────────────────────────────────

def _parse_record(raw: str) -> Optional[dict]:
    """Parse and validate one JSONL line.

    Privacy: strips any content fields before returning. Returns None for
    malformed or unusable records (missing required fields, bad timestamp).
    """
    s = raw.strip()
    if not s or s.startswith("#"):
        return None
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None

    # Privacy enforcement: strip free-text content fields unconditionally.
    for f in _STRIP_FIELDS:
        obj.pop(f, None)

    ts_raw = str(obj.get("ts") or "").strip()
    app = str(obj.get("app") or "").strip()
    app_label = str(obj.get("app_label") or obj.get("app") or "").strip()
    if not ts_raw or not app:
        return None

    try:
        ts = datetime.fromisoformat(ts_raw)
    except ValueError:
        return None

    category = str(obj.get("category") or "other").strip().lower()
    if category not in _VALID_CATEGORIES:
        category = "other"

    return {
        "ts": ts,
        "app": app,
        "app_label": app_label or app,
        "category": category,
    }


def _read_drop_files(notifications_dir: Path, *, since: date, until: date) -> list[dict]:
    """Read all JSONL drop files for ``[since, until]``. Malformed lines silently skipped."""
    records: list[dict] = []
    cur = since
    while cur <= until:
        drop = _drop_file(notifications_dir, cur)
        if drop.exists():
            try:
                with drop.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        rec = _parse_record(line)
                        if rec:
                            records.append(rec)
            except OSError as exc:
                _log.info("ingest_notifications: cannot read %s (%s)", drop, exc)
        cur += timedelta(days=1)
    return records


# ── collection ────────────────────────────────────────────────────────────────

def collect_notification_activity(
    *,
    since: date,
    until: date,
    notifications_dir: Optional[Path] = None,
    max_records: int = 2000,
) -> dict[str, Any]:
    """Read and aggregate Android notification records for ``[since, until]``.

    Returns aggregated counts only — no raw records cross the distillation
    boundary:

        {"records_read", "apps":{app_label: count}, "categories":{cat: count},
         "by_hour":{HH: count}, "total_count", "distinct_apps",
         "window":(since, until)}

    No drop file / empty file → total_count == 0 (caller no-ops).
    """
    d = notifications_dir or resolve_notifications_dir()
    records = _read_drop_files(d, since=since, until=until)

    if len(records) > max_records:
        _log.info("ingest_notifications: capping %d records to %d",
                  len(records), max_records)
        records = records[:max_records]

    apps: dict[str, int] = {}
    categories: dict[str, int] = {}
    by_hour: dict[int, int] = {}

    for rec in records:
        label = rec["app_label"]
        apps[label] = apps.get(label, 0) + 1

        cat = rec["category"]
        categories[cat] = categories.get(cat, 0) + 1

        hour = rec["ts"].hour
        by_hour[hour] = by_hour.get(hour, 0) + 1

    return {
        "records_read": len(records),
        "apps": apps,
        "categories": categories,
        "by_hour": {str(h): c for h, c in sorted(by_hour.items())},
        "total_count": len(records),
        "distinct_apps": len(apps),
        "window": (since, until),
    }


# ── distillation ──────────────────────────────────────────────────────────────

def _fmt_top_apps(apps: dict[str, int], *, limit: int = 8) -> str:
    top = sorted(apps.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return "; ".join(f"{label} \xd7{count}" for label, count in top)


def _fmt_categories(categories: dict[str, int]) -> str:
    order = ["msg", "call", "alarm", "media", "sys", "other"]
    parts = [f"{cat}: {categories[cat]}" for cat in order if cat in categories]
    parts += [f"{k}: {v}" for k, v in categories.items() if k not in order]
    return ", ".join(parts)


def _fmt_peak_hours(by_hour: dict[str, int]) -> str:
    if not by_hour:
        return "no hourly data"
    top = sorted(by_hour.items(), key=lambda kv: int(kv[1]), reverse=True)[:3]
    return ", ".join(f"{h}:00 (\xd7{c})" for h, c in top)


def _activity_body(activity: dict) -> str:
    return "\n".join([
        f"Total notifications: {activity['total_count']}  "
        f"({activity['distinct_apps']} distinct app(s))",
        f"Top apps: {_fmt_top_apps(activity['apps'])}",
        f"By category: {_fmt_categories(activity['categories'])}",
        f"Peak hours: {_fmt_peak_hours(activity['by_hour'])}",
    ])


def distill_notification_activity(
    activity: dict,
    *,
    synthesize: bool = True,
    model: str = _DEFAULT_HAIKU,
    cfg_id: str = "ANTHROPIC",
    max_tokens: int = 900,
) -> dict[str, Any]:
    """Turn collected notification aggregates into HFL entry fields (Haiku, raw fallback)."""
    total = activity["total_count"]
    apps_count = activity["distinct_apps"]

    def _fallback() -> dict:
        return {
            "skip": False,
            "moment": f"{total} Android notification(s) from {apps_count} app(s)",
            "what_happened": _activity_body(activity),
            "why_it_stayed": "",
            "possible_use": "attention log, distraction audit",
            "tags": ["android", "notifications", "attention"],
            "synthesized": False,
        }

    if not synthesize:
        return _fallback()

    user_msg = f"Today's Android notification digest:\n\n{_activity_body(activity)}"
    try:
        client = BaseApiServiceAnthropic(get_anthropic_config(cfg_id))
        if not getattr(client, "base_client", None):
            _log.warning("ingest_notifications: Anthropic not initialized — raw fallback")
            return _fallback()
        resp = client.send_message(
            prompt=user_msg,
            system=load_prompt("ingest_notifications").strip(),
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
        _log.warning("ingest_notifications: synthesis failed (%s) — raw fallback", exc)
        return _fallback()


# ── notification window ───────────────────────────────────────────────────────

def _notification_window(window_days: int, *, today: Optional[date] = None) -> tuple[date, date]:
    end = today or datetime.now().date()
    days = max(1, int(window_days or 1))
    start = end - timedelta(days=days - 1)
    return start, end


# ── Celery task ───────────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def ingest_notification_activity(
    *,
    cfg_id__anthropic: str = "ANTHROPIC",
    model: str = _DEFAULT_HAIKU,
    window_days: int = 1,
    max_records: int = 2000,
) -> dict[str, Any]:
    """Append one HFL corpus entry summarizing the day's Android notification signal.

    No JSONL drop file or empty inbox → no entry, no LLM call (clean no-op).
    """
    since, until = _notification_window(window_days)

    try:
        activity = collect_notification_activity(
            since=since, until=until, max_records=max_records,
        )
    except Exception as exc:  # noqa: BLE001 - inbox read failure must not break the beat
        _log.error("ingest_notifications: inbox read failed (%s)", exc)
        return {"skipped": "inbox read failed", "entries_written": 0,
                "error": str(exc)[:200]}

    if activity["total_count"] == 0:
        _log.info("ingest_notifications: no records in last %d day(s)", window_days)
        return {"skipped": "no records", "entries_written": 0}

    d = distill_notification_activity(
        activity, synthesize=True, model=model,
        cfg_id=cfg_id__anthropic, max_tokens=900,
    )
    if d.get("skip"):
        _log.info("ingest_notifications: distilled as skip — %d records not story-worthy",
                  activity["total_count"])
        return {"skipped": "distilled-skip", "entries_written": 0,
                "total_count": activity["total_count"]}

    tags = ["android", "notifications"] + [
        str(t) for t in (d.get("tags") or []) if str(t).strip()
        and str(t).strip().lower() not in ("android", "notifications")
    ][:6]

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
        day_file, entry, source="android-notifications",
        synthesized=d.get("synthesized", False),
    )

    _log.info("ingest_notifications: entry written (%d notifications, %d apps) → %s",
              activity["total_count"], activity["distinct_apps"], day_file)
    return {
        "entries_written": 1,
        "total_count": activity["total_count"],
        "distinct_apps": activity["distinct_apps"],
        "synthesized": d.get("synthesized", False),
        "model": model if d.get("synthesized") else None,
        "path": str(day_file),
        "indexed": doc_id is not None,
    }
