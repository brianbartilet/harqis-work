"""
workflows/hfl/tasks/ingest_android_apps.py

Android app micro-ingest framework — HFL corpus entries from small JSONL
records exported from Android apps (Google Maps, Photos, payment apps,
delivery apps, listening apps, browser share links).

Input format
------------
JSONL files in the configured inbox directory (one JSON object per line):

    {"source": "maps", "app": "Google Maps", "timestamp": "2026-06-01T14:30:00",
     "title": "Visited Greenbelt Mall", "metadata": {"place_type": "mall"}}

Required fields: source, timestamp, title.
Optional: app (defaults to source name), metadata (source-specific extras).

Supported sources
-----------------
maps        Google Maps saves / check-ins / places
photos      Google Photos memories / highlights
payments    Google Pay / GCash / bank app activity (merchant+category only)
delivery    Foodpanda / Grab Food order records (merchant+category only)
listening   YouTube Music / podcast app history
browser     Chrome / Firefox share-to-notes links

Privacy
-------
- Raw GPS coordinates are never stored (metadata["lat"]/["lng"] are dropped).
- Payment amounts, card numbers, and recipient names are stripped — only the
  merchant name and category survive.
- Photo file paths and EXIF data are dropped; only the descriptive title passes.
- Delivery recipient addresses are dropped; merchant + category survive.
- Notification body text is never stored verbatim — title is the safe caption.

Inbox path (first hit wins)
---------------------------
1. apps_config.yaml :: HFL.android_inbox.path
2. env var  HFL_ANDROID_INBOX_PATH
3. <repo>/logs/hfl-android-inbox/

Records are read from *.jsonl files in the inbox directory. Processed files
are NOT deleted by default — the task is idempotent (same source + title +
date = same ES doc id). Pass clear_after=True to move processed files to an
<inbox>/done/ subdirectory after a successful run.

One HFL entry is produced per active source encountered in the inbox batch.
An empty inbox or a missing inbox directory is a clean no-op (no LLM, no write).

Extensibility: add a new source by extending AndroidAppSource and adding a
matching entry to _SOURCE_TAGS. No other code changes are required.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.hfl.tasks.capture import (
    _build_entry,
    append_entry,
    resolve_corpus_dir,
)

_log = create_logger("hfl.ingest_android_apps")

REPO_ROOT = Path(__file__).resolve().parents[3]


# ── Source taxonomy ────────────────────────────────────────────────────────────

class AndroidAppSource(str, Enum):
    """Supported Android app micro-ingest source categories."""
    MAPS      = "maps"
    PHOTOS    = "photos"
    PAYMENTS  = "payments"
    DELIVERY  = "delivery"
    LISTENING = "listening"
    BROWSER   = "browser"


# Source-specific base tags applied to every entry from that source.
_SOURCE_TAGS: dict[AndroidAppSource, list[str]] = {
    AndroidAppSource.MAPS:      ["location", "maps", "android"],
    AndroidAppSource.PHOTOS:    ["photo", "media", "android"],
    AndroidAppSource.PAYMENTS:  ["finance", "payment", "android"],
    AndroidAppSource.DELIVERY:  ["food", "delivery", "android"],
    AndroidAppSource.LISTENING: ["music", "listening", "android"],
    AndroidAppSource.BROWSER:   ["browsing", "browser", "android"],
}

# Metadata keys that are always stripped before any record enters the corpus.
_PRIVATE_KEYS = frozenset({
    "lat", "lng", "latitude", "longitude",      # raw GPS coordinates
    "address", "street", "recipient",            # physical addresses
    "amount", "card", "account", "phone",        # financial identifiers
    "path", "file_path", "exif",                 # local file metadata
    "notification_body", "body",                 # raw notification text
})


# ── Normalization ──────────────────────────────────────────────────────────────

def _resolve_source(raw: Any) -> Optional[AndroidAppSource]:
    """Map a raw source string to a known AndroidAppSource, or None."""
    try:
        return AndroidAppSource(str(raw or "").strip().lower())
    except ValueError:
        return None


def _sanitize_metadata(meta: Any) -> dict:
    """Return a copy of `meta` with all private keys removed."""
    if not isinstance(meta, dict):
        return {}
    return {k: v for k, v in meta.items() if k not in _PRIVATE_KEYS}


def normalize_record(raw: Any) -> Optional[dict]:
    """Normalize one raw JSONL record into a safe micro-ingest candidate.

    Returns None for records that are malformed, have no title, or carry an
    unrecognised source (callers must filter out None).

    Output shape::

        {
            "source":    AndroidAppSource,
            "app":       str,       # e.g. "Google Maps"
            "timestamp": datetime,
            "title":     str,       # safe caption (≤ 200 chars)
            "metadata":  dict,      # privacy-filtered extras
            "tags":      list[str], # source base tags (copy, not shared)
        }
    """
    if not isinstance(raw, dict):
        return None

    source = _resolve_source(raw.get("source", ""))
    if source is None:
        return None

    title = str(raw.get("title") or "").strip()[:200]
    if not title:
        return None

    ts_raw = str(raw.get("timestamp") or "").strip()
    try:
        ts: datetime = datetime.fromisoformat(ts_raw)
    except (ValueError, AttributeError):
        ts = datetime.now()

    app = str(raw.get("app") or source.value).strip()[:80]
    meta = _sanitize_metadata(raw.get("metadata"))

    return {
        "source":    source,
        "app":       app,
        "timestamp": ts,
        "title":     title,
        "metadata":  meta,
        "tags":      list(_SOURCE_TAGS[source]),
    }


# ── Inbox resolution ───────────────────────────────────────────────────────────

def resolve_android_inbox() -> Path:
    """Resolve the Android micro-ingest inbox directory.

    Precedence (first hit wins):
    1. apps_config.yaml :: HFL.android_inbox.path
    2. env var HFL_ANDROID_INBOX_PATH
    3. <repo>/logs/hfl-android-inbox/
    """
    try:
        from apps.apps_config import CONFIG_MANAGER  # type: ignore[import]
        hfl_cfg = CONFIG_MANAGER.get("HFL")
        if hfl_cfg and isinstance(hfl_cfg, dict):
            inbox_path = (hfl_cfg.get("android_inbox") or {}).get("path")
            if inbox_path and "${" not in str(inbox_path):
                return Path(inbox_path).resolve()
    except Exception:
        pass

    env_path = os.environ.get("HFL_ANDROID_INBOX_PATH", "").strip()
    if env_path:
        return Path(env_path).resolve()

    return (REPO_ROOT / "logs" / "hfl-android-inbox").resolve()


# ── Collection ─────────────────────────────────────────────────────────────────

def collect_android_app_records(
    inbox: Path,
    *,
    max_records: int = 500,
) -> dict[str, Any]:
    """Read and normalise all *.jsonl records from `inbox`.

    Returns::

        {
            "records":     list[dict],           # normalized candidates
            "by_source":   {source_value: [...]},
            "total_raw":   int,                  # lines attempted
            "skipped":     int,                  # malformed / unknown / no title
            "files_read":  list[str],            # filenames (not full paths)
            "inbox_found": bool,
        }

    Hard-caps at `max_records` across all files; reading stops early once the
    cap is reached to keep memory and Celery task time bounded.
    """
    if not inbox.is_dir():
        return {
            "records": [], "by_source": {}, "total_raw": 0,
            "skipped": 0, "files_read": [], "inbox_found": False,
        }

    files = sorted(inbox.glob("*.jsonl"))
    if not files:
        return {
            "records": [], "by_source": {}, "total_raw": 0,
            "skipped": 0, "files_read": [], "inbox_found": True,
        }

    records: list[dict] = []
    skipped = 0
    total_raw = 0
    files_read: list[str] = []

    for fpath in files:
        files_read.append(fpath.name)
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            _log.info("ingest_android_apps: cannot read %s (%s)", fpath.name, exc)
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            total_raw += 1
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            norm = normalize_record(obj)
            if norm is None:
                skipped += 1
                continue
            records.append(norm)
            if len(records) >= max_records:
                break
        if len(records) >= max_records:
            break

    by_source: dict[str, list[dict]] = {}
    for r in records:
        by_source.setdefault(r["source"].value, []).append(r)

    return {
        "records":     records,
        "by_source":   by_source,
        "total_raw":   total_raw,
        "skipped":     skipped,
        "files_read":  files_read,
        "inbox_found": True,
    }


# ── Distillation ───────────────────────────────────────────────────────────────

def _records_body(source: str, records: list[dict]) -> str:
    """Compact, model-safe view of one source's records (no private data)."""
    lines: list[str] = [f"Source: {source}  ({len(records)} record(s))"]
    for r in records[:40]:
        ts_obj = r["timestamp"]
        ts_str = (
            ts_obj.strftime("%Y-%m-%d %H:%M")
            if isinstance(ts_obj, datetime) else str(ts_obj)
        )
        meta_str = ""
        if r["metadata"]:
            parts = [f"{k}={v}" for k, v in list(r["metadata"].items())[:3]]
            meta_str = f" [{', '.join(parts)}]"
        lines.append(f"- [{ts_str}] {r['title']}{meta_str}")
    return "\n".join(lines)


def distill_android_source(
    source: str,
    records: list[dict],
) -> dict[str, Any]:
    """Produce HFL entry fields for one source's batch of records.

    Pure function — no LLM call, no IO. The compact, fact-grounded format is
    sufficient for the corpus; a future synthesis layer can extend this by
    calling the LLM with load_prompt("ingest_android_apps") if needed.
    """
    tags = list(_SOURCE_TAGS.get(AndroidAppSource(source), ["android"]))

    titles = [r["title"] for r in records]
    sample = "; ".join(titles[:6])
    if len(titles) > 6:
        sample += f" (+ {len(titles) - 6} more)"

    source_label = source.replace("_", " ")
    count = len(records)

    moment = f"{count} Android {source_label} signal(s): {sample}"[:200]
    what = _records_body(source, records)

    return {
        "source":       source,
        "moment":       moment,
        "what_happened": what,
        "why_it_stayed": f"Daily {source_label} micro-ingest from Android share stream.",
        "possible_use": f"daily-log {source_label}",
        "tags":         tags,
        "references":   [],
        "record_count": count,
    }


# ── Celery task ───────────────────────────────────────────────────────────────

@SPROUT.task()
@log_result()
def ingest_android_app_records(
    *,
    max_records: int = 500,
    clear_after: bool = False,
) -> dict[str, Any]:
    """Read JSONL micro-ingest records from the Android inbox and append one
    HFL corpus entry per active source encountered in the batch.

    No inbox directory or empty inbox → no entries, no write (clean no-op).
    Malformed lines and unknown sources are skipped and counted.

    Args:
        max_records: hard cap on total records read across all JSONL files.
        clear_after: if True, move processed JSONL files to <inbox>/done/
                     after a successful run (idempotency guard for re-runs).

    Returns::

        {
            "entries_written": int,
            "records":         int,   # total raw lines encountered
            "skipped_records": int,
            "by_source":       {source: record_count},
            "files_read":      list[str],
            "path":            str,   # day corpus file
        }
    """
    inbox = resolve_android_inbox()
    collected = collect_android_app_records(inbox, max_records=max_records)

    if not collected["inbox_found"]:
        _log.info("ingest_android_apps: inbox not found at %s — no-op", inbox)
        return {"skipped": "inbox not found", "entries_written": 0, "records": 0}

    if not collected["records"]:
        _log.info("ingest_android_apps: no records in inbox — no-op")
        return {
            "skipped": "no records", "entries_written": 0, "records": 0,
            "files_read": collected["files_read"],
        }

    when = datetime.now()
    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    day_file = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"

    entries_written = 0
    results_by_source: dict[str, int] = {}

    for source, source_records in collected["by_source"].items():
        d = distill_android_source(source, source_records)
        entry = _build_entry(
            when=when,
            moment=d["moment"],
            what_happened=d["what_happened"],
            why_it_stayed=d["why_it_stayed"],
            possible_use=d["possible_use"],
            tags=d["tags"],
            references=d["references"],
        )
        append_entry(day_file, entry, source=f"android:{source}", synthesized=False)
        entries_written += 1
        results_by_source[source] = d["record_count"]
        _log.info(
            "ingest_android_apps: wrote %s entry (%d record(s)) → %s",
            source, d["record_count"], day_file,
        )

    if clear_after and collected["files_read"]:
        done_dir = inbox / "done"
        done_dir.mkdir(exist_ok=True)
        for fname in collected["files_read"]:
            src = inbox / fname
            if src.exists():
                try:
                    shutil.move(str(src), str(done_dir / fname))
                except OSError as exc:
                    _log.info("ingest_android_apps: could not move %s (%s)", fname, exc)

    _log.info(
        "ingest_android_apps: %d entry/entries written across %d source(s)",
        entries_written, len(collected["by_source"]),
    )
    return {
        "entries_written":  entries_written,
        "records":          collected["total_raw"],
        "skipped_records":  collected["skipped"],
        "by_source":        results_by_source,
        "files_read":       collected["files_read"],
        "path":             str(day_file),
    }
