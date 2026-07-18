"""Sanitized four-hour Hermes Telegram mirror for the HERMES RADAR HUD.

The Hermes host exports outbound Telegram-visible assistant replies and scheduled
job deliveries into a small JSON file in the configured shared desktop feed.
Windows reads only that artifact; it never opens Hermes state or polls Telegram.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from apps.desktop.helpers.feed import _atomic_write_text, _resolve_feed_path

SNAPSHOT_FILENAME = "hermes-radar.json"
DEFAULT_WINDOW_HOURS = 4
# Zero means "do not truncate the number of messages". The time window is the
# bound for this HUD; dropping messages inside that window would no longer be a
# faithful Telegram mirror.
DEFAULT_MAX_ITEMS = 0
DEFAULT_STALE_MINUTES = 35
RECENT_HEADING = "HERMES UPDATES - LAST 4 HOURS"
EMPTY_STATE = "(no Hermes updates in the last 4h)"
STALE_STATE = "(Hermes notification snapshot is stale)"
UNAVAILABLE_STATE = "(Hermes notification snapshot is unavailable)"

_SPACE_RE = re.compile(r"\s+")
_HORIZONTAL_SPACE_RE = re.compile(r"[ \t\f\v]+")
_EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")
_MARKDOWN_RE = re.compile(r"[`*_#>|]+")
_BOT_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
_SECRET_RE = re.compile(
    r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|secret|password|authorization)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_CHAT_ID_RE = re.compile(r"(?i)\b(chat(?:_id)?|thread(?:_id)?)\s*[:=]\s*-?\d+")
_TECHNICAL_ID_RE = re.compile(
    r"(?i)\b(session|message|job|user|account|request|trace|thread|chat)[_ -]?id"
    r"\s*[:=]\s*[^\s,;]+"
)
_UUID_RE = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
_LONG_NUMERIC_ID_RE = re.compile(r"(?<![\d.])-?\d{9,16}(?![\d.])")
_SAFE_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_UNIX_PATH_RE = re.compile(r"(?<!\w)(?:~|/(?:Users|Volumes|home|var|tmp|opt))/[^\s]+")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?<!\w)[A-Z]:\\[^\s]+")
_MEDIA_PATH_RE = re.compile(r"(?i)MEDIA:\S+")
_LOOP_MARKERS = (
    "RECENT HERMES PUSHES",
    "HERMES UPDATES LAST 4 HOURS",
    "HERMES RADAR",
    "DAILY RADAR DUMP",
)
_ASCII_PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2026": "...",
        "\u2022": "-",
        "\u00a0": " ",
    }
)


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=_now_local().tzinfo)
    return value


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _aware(value)
    try:
        epoch = float(value)
    except (TypeError, ValueError):
        epoch = None
    if epoch is not None:
        if epoch > 10_000_000_000:  # tolerate millisecond epochs
            epoch /= 1000
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _aware(parsed)


def resolve_snapshot_path(path: Optional[Path | str] = None) -> Path:
    """Resolve the same shared feed artifact on macOS and Windows."""
    if path:
        return Path(path).expanduser()
    override = (os.environ.get("HERMES_RADAR_SNAPSHOT_PATH") or "").strip()
    if override:
        return Path(override).expanduser()
    feed_path = _resolve_feed_path()
    if not feed_path or "${" in feed_path:
        raise RuntimeError(
            "No shared feed path configured; set HERMES_RADAR_SNAPSHOT_PATH or "
            "DESKTOP_PATH_FEED_<OS>."
        )
    return Path(feed_path).expanduser() / SNAPSHOT_FILENAME


def resolve_hermes_home(path: Optional[Path | str] = None) -> Path:
    if path:
        return Path(path).expanduser()
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")).expanduser()


def _redact_sensitive_text(value: Any) -> str:
    """Remove data that must never leave the Hermes host."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _BOT_TOKEN_RE.sub("[REDACTED]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _CHAT_ID_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _TECHNICAL_ID_RE.sub(
        lambda match: re.split(r"[:=]", match.group(0), maxsplit=1)[0]
        + "=[REDACTED]",
        text,
    )
    text = _UUID_RE.sub("[REDACTED ID]", text)
    text = _LONG_NUMERIC_ID_RE.sub("[REDACTED ID]", text)
    text = _MEDIA_PATH_RE.sub("[attachment]", text)
    text = _WINDOWS_PATH_RE.sub("[local path]", text)
    text = _UNIX_PATH_RE.sub("[local path]", text)
    return text


def _ascii_text(value: str) -> str:
    """Return Rainmeter-safe ASCII, dropping emoji and unsupported Unicode."""
    translated = value.translate(_ASCII_PUNCTUATION_TRANSLATION)
    return (
        unicodedata.normalize("NFKD", translated)
        .encode("ascii", errors="ignore")
        .decode("ascii")
    )


def sanitize_message(value: Any, *, max_chars: int = 4096) -> str:
    """Redact an outbound reply while preserving its readable line structure."""
    text = _redact_sensitive_text(value)
    text = _MARKDOWN_RE.sub(" ", text)
    text = _ascii_text(text)
    lines = [_HORIZONTAL_SPACE_RE.sub(" ", line).rstrip() for line in text.splitlines()]
    text = _EXCESS_BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip(" -\n\t")
    if max_chars > 0 and len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def sanitize_preview(value: Any, *, max_chars: int = 220) -> str:
    """Backward-compatible single-line sanitizer for labels and callers."""
    return _SPACE_RE.sub(" ", sanitize_message(value, max_chars=0)).strip()[:max_chars]


def _is_looped_radar_content(text: str, *, source: str = "") -> bool:
    combined = re.sub(r"[^A-Z0-9]+", " ", f"{source}\n{text}".upper()).strip()
    return any(marker in combined for marker in _LOOP_MARKERS)


def _item(
    *, timestamp: datetime, source: str, text: str, kind: str, status: str = "delivered"
) -> Optional[dict[str, str]]:
    message = sanitize_message(text)
    source_preview = sanitize_preview(source, max_chars=72) or kind
    if not message or _is_looped_radar_content(message, source=source_preview):
        return None
    return {
        "timestamp": _aware(timestamp).astimezone(timezone.utc).isoformat(),
        "source": source_preview,
        "kind": kind,
        "status": status,
        "text": message,
    }


def collect_interactive_pushes(
    db_path: Path | str, *, since: datetime, now: Optional[datetime] = None
) -> list[dict[str, str]]:
    """Read assistant replies from Telegram sessions without exposing the DB."""
    now = _aware(now or _now_local())
    since = _aware(since)
    uri = f"file:{Path(db_path).expanduser()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            """
            SELECT m.timestamp, m.content
              FROM messages AS m
              JOIN sessions AS s ON s.id = m.session_id
             WHERE s.source = 'telegram'
               AND m.role = 'assistant'
               AND m.content IS NOT NULL
               AND m.content != ''
             ORDER BY m.timestamp DESC
            """
        ).fetchall()
    finally:
        connection.close()

    pushes: list[dict[str, str]] = []
    for raw_timestamp, content in rows:
        timestamp = _parse_datetime(raw_timestamp)
        if timestamp is None or timestamp < since or timestamp > now + timedelta(minutes=5):
            continue
        candidate = _item(
            timestamp=timestamp,
            source="Hermes chat",
            text=content,
            kind="interactive",
        )
        if candidate:
            pushes.append(candidate)
    return pushes


def _targets_telegram(job: dict[str, Any]) -> bool:
    deliver = str(job.get("deliver") or "origin").lower()
    raw_origin = job.get("origin")
    origin: dict[str, Any] = raw_origin if isinstance(raw_origin, dict) else {}
    if deliver == "local":
        return False
    if "telegram" in deliver or deliver == "all":
        return True
    return "origin" in deliver and str(origin.get("platform") or "").lower() == "telegram"


def _output_timestamp(path: Path) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=_now_local().tzinfo)
    except OSError:
        return None


def _extract_delivered_cron_text(raw: str) -> Optional[str]:
    """Extract only Telegram-bound response text from a Hermes audit file."""
    response_marker = "\n## Response\n"
    if response_marker in raw:
        response = raw.rsplit(response_marker, 1)[1].strip()
        if not response or response in {"(No response generated)", "[SILENT]"}:
            return None
        return response

    if raw.lstrip().startswith("# Cron Job:"):
        if "**Status:** silent" in raw or "Script gate returned" in raw:
            return None
        if "## Error" in raw or "**Status:** script failed" in raw:
            return "Scheduled job failed"
        if "**Mode:** no_agent" in raw and "---" in raw:
            response = raw.split("---", 1)[1].strip()
            return response or None
        # Unknown audit shape: fail closed rather than exposing prompt/metadata.
        return None

    # Backward compatibility for old files containing only delivered output.
    return raw.strip() or None


def collect_cron_pushes(
    jobs_path: Path | str,
    output_dir: Path | str,
    *,
    since: datetime,
    now: Optional[datetime] = None,
) -> list[dict[str, str]]:
    """Read locally audited outputs for jobs configured to deliver to Telegram."""
    now = _aware(now or _now_local())
    since = _aware(since)
    payload = json.loads(Path(jobs_path).expanduser().read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        jobs = payload.get("jobs", [])
    elif isinstance(payload, list):
        jobs = payload
    else:
        jobs = []
    pushes: list[dict[str, str]] = []

    for job in jobs:
        if not isinstance(job, dict) or not _targets_telegram(job):
            continue
        job_id = str(job.get("id") or "")
        job_name = str(job.get("name") or "Scheduled Hermes update")
        if (
            not _SAFE_JOB_ID_RE.fullmatch(job_id)
            or _is_looped_radar_content("", source=job_name)
        ):
            continue
        last_run = _parse_datetime(job.get("last_run_at") or job.get("last_run"))
        files = sorted(
            (Path(output_dir).expanduser() / job_id).glob("*.md"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        delivery_error = str(job.get("last_delivery_error") or "").strip()
        job_failed = str(job.get("last_status") or "").lower() in {"error", "failed"}
        matched_latest = False

        for output_path in files:
            timestamp = _output_timestamp(output_path)
            if timestamp is None or timestamp < since or timestamp > now + timedelta(minutes=5):
                continue
            is_latest = bool(
                last_run
                and abs(
                    (
                        timestamp.astimezone(timezone.utc)
                        - last_run.astimezone(timezone.utc)
                    ).total_seconds()
                )
                < 300
            )
            if is_latest and (delivery_error or job_failed):
                matched_latest = True
                status = "delivery_failed" if delivery_error else "job_failed"
                text = (
                    f"Delivery failed: {delivery_error}"
                    if delivery_error
                    else str(job.get("last_error") or "Scheduled job failed")
                )
            else:
                raw_output = output_path.read_text(encoding="utf-8", errors="replace")
                text = _extract_delivered_cron_text(raw_output)
                if text is None:
                    continue
                status = "delivered"

            candidate = _item(
                timestamp=timestamp,
                source=job_name,
                text=text,
                kind="scheduled",
                status=status,
            )
            if candidate:
                pushes.append(candidate)

        if (
            (delivery_error or job_failed)
            and not matched_latest
            and last_run
            and since <= last_run <= now + timedelta(minutes=5)
        ):
            candidate = _item(
                timestamp=last_run,
                source=job_name,
                text=(
                    f"Delivery failed: {delivery_error}"
                    if delivery_error
                    else str(job.get("last_error") or "Scheduled job failed")
                ),
                kind="scheduled",
                status="delivery_failed" if delivery_error else "job_failed",
            )
            if candidate:
                pushes.append(candidate)
    return pushes


def _sort_and_limit(
    items: Iterable[dict[str, str]], *, max_items: int
) -> list[dict[str, str]]:
    ordered = sorted(items, key=lambda item: item["timestamp"], reverse=True)
    return ordered[:max_items] if max_items > 0 else ordered


def build_snapshot(
    *,
    hermes_home: Optional[Path | str] = None,
    now: Optional[datetime] = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict[str, Any]:
    """Build a complete snapshot; any source failure prevents replacement."""
    now = _aware(now or _now_local())
    since = now - timedelta(hours=window_hours)
    home = resolve_hermes_home(hermes_home)
    interactive = collect_interactive_pushes(home / "state.db", since=since, now=now)
    scheduled = collect_cron_pushes(
        home / "cron" / "jobs.json", home / "cron" / "output", since=since, now=now
    )
    return {
        "schema_version": 2,
        "generated_at": now.isoformat(),
        "window_hours": window_hours,
        "max_items": max_items,
        "items": _sort_and_limit([*interactive, *scheduled], max_items=max_items),
    }


def export_snapshot(
    *,
    snapshot_path: Optional[Path | str] = None,
    hermes_home: Optional[Path | str] = None,
    now: Optional[datetime] = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> dict[str, Any]:
    """Atomically replace the shared artifact only after a complete build."""
    snapshot = build_snapshot(
        hermes_home=hermes_home,
        now=now,
        window_hours=window_hours,
        max_items=max_items,
    )
    destination = resolve_snapshot_path(snapshot_path)
    _atomic_write_text(
        destination,
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return snapshot


def load_snapshot(
    snapshot_path: Optional[Path | str] = None,
    *,
    now: Optional[datetime] = None,
    stale_minutes: int = DEFAULT_STALE_MINUTES,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> dict[str, Any]:
    """Validate a shared artifact, enforce the live window, and label freshness."""
    try:
        payload = json.loads(resolve_snapshot_path(snapshot_path).read_text(encoding="utf-8"))
        generated_at = _parse_datetime(payload.get("generated_at"))
        items = payload.get("items")
        schema_version = payload.get("schema_version")
        if (
            schema_version not in {1, 2}
            or generated_at is None
            or not isinstance(items, list)
        ):
            raise ValueError("invalid Hermes radar snapshot schema")
        now_value = _aware(now or _now_local())
        cutoff = now_value - timedelta(hours=window_hours)
        validated_items: list[dict[str, str]] = []
        allowed_statuses = {"delivered", "delivery_failed", "job_failed"}
        for item in items:
            required = {"timestamp", "source", "kind", "status"}
            if not isinstance(item, dict) or not required.issubset(item):
                raise ValueError("invalid Hermes radar item")
            timestamp = _parse_datetime(item.get("timestamp"))
            kind = str(item.get("kind") or "")
            status = str(item.get("status") or "")
            if timestamp is None or kind not in {"interactive", "scheduled"}:
                raise ValueError("invalid Hermes radar item values")
            if timestamp < cutoff or timestamp > now_value + timedelta(minutes=5):
                continue
            raw_text = item.get("text") if schema_version == 2 else item.get("preview")
            if raw_text is None:
                raise ValueError("invalid Hermes radar item text")
            candidate = _item(
                timestamp=timestamp,
                source=str(item.get("source") or "Hermes"),
                text=str(raw_text),
                kind=kind,
                status=status if status in allowed_statuses else "delivered",
            )
            if candidate:
                validated_items.append(candidate)
        payload["schema_version"] = 2
        payload["window_hours"] = window_hours
        payload["max_items"] = DEFAULT_MAX_ITEMS
        payload["items"] = _sort_and_limit(
            validated_items, max_items=DEFAULT_MAX_ITEMS
        )
        age = (
            now_value.astimezone(timezone.utc)
            - generated_at.astimezone(timezone.utc)
        )
        payload["state"] = (
            "stale" if age > timedelta(minutes=stale_minutes) else "fresh"
        )
        return payload
    except (OSError, ValueError, TypeError, json.JSONDecodeError, RuntimeError):
        return {"schema_version": 2, "state": "unavailable", "items": []}


def _format_items(snapshot: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    for item in snapshot.get("items", []):
        # Failure records are useful in the snapshot audit but were not replies
        # received in Telegram, so they do not belong in the mirror.
        if item.get("status") != "delivered":
            continue
        timestamp = _parse_datetime(item.get("timestamp"))
        time_label = timestamp.astimezone().strftime("%H:%M") if timestamp else "--:--"
        source = item.get("source", "Hermes")
        blocks.append(
            f"[{time_label}] {source}\n{item.get('text', '')}".rstrip()
        )
    return blocks


def displayed_item_count(snapshot: dict[str, Any]) -> int:
    """Count successfully delivered replies represented in the HUD mirror."""
    return sum(1 for item in snapshot.get("items", []) if item.get("status") == "delivered")


def compose_hermes_radar(snapshot: dict[str, Any]) -> str:
    """Render delivered Hermes replies from the strict four-hour snapshot."""
    state = snapshot.get("state", "fresh")
    blocks = _format_items(snapshot)
    if state == "unavailable":
        blocks = [UNAVAILABLE_STATE]
    elif not blocks:
        blocks = [EMPTY_STATE]
    if state == "stale":
        blocks.append(STALE_STATE)
    return f"{RECENT_HEADING}\n\n" + "\n\n".join(blocks)
