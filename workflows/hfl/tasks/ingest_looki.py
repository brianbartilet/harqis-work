"""Metadata-first Looki wearable moments → HFL corpus and Elasticsearch.

This task intentionally does not download media. Looki-generated descriptions
are indexed as unverified hypotheses with stable provenance; consequential
memories should be checked against source media through the explicit Looki MCP
tools. Missing credentials or API failures are clean no-ops.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from apps.looki.config import CONFIG as LOOKI_CONFIG
from apps.looki.references.adapter import (
    _contains_precise_coordinates,
    _scrub_url_string,
    build_adapter,
)
from apps.looki.references.dto.moment import DtoLookiMoment, valid_moment_id
from workflows.hfl.dto import HflEntry
from workflows.hfl.es_store import index_hfl_entry
from workflows.hfl.tasks.analyze_media import _try_lock_fd, _unlock_fd
from workflows.hfl.tasks.capture import resolve_corpus_dir

_log = create_logger("hfl.ingest_looki")


def _window(window_days: int, *, today: date) -> tuple[date, date]:
    days = max(1, min(int(window_days or 1), 31))
    return today - timedelta(days=days - 1), today


def _moment_time(value: Optional[str], *, fallback: datetime) -> datetime:
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return fallback


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value)).strip("-._").lower()
    return cleaned[:96] or "unknown"


def _looki_doc_id(moment_id: str) -> str:
    """ES identity using the first 128 bits (32 hex chars) of source-ID SHA-256."""
    digest = hashlib.sha256(moment_id.encode("utf-8")).hexdigest()[:32]
    return f"looki-{digest}"


def _safe_text(value: Optional[str], limit: int) -> str:
    text = " ".join(str(value or "").split())
    # External URLs are operational handles, not durable Looki metadata. The
    # stable source reference is `looki:<id>`; omit every URL fail-closed.
    text = _scrub_url_string(text)
    if _contains_precise_coordinates(text):
        # Coordinates may be embedded in generated prose, not only the nominal
        # location field. Fail closed rather than making them durable.
        return "[precise-location-omitted]"
    return text[:limit].strip()


def _entry_for(moment: DtoLookiMoment, *, fallback: datetime) -> HflEntry:
    when = _moment_time(moment.started_at, fallback=fallback)
    title = _safe_text(moment.title, 180) or f"Looki moment at {when.strftime('%H:%M')}"
    generated = _safe_text(moment.generated_text, 1800)
    location = _safe_text(moment.location_label, 160)

    details = []
    if generated:
        details.append(f"Looki-generated description (unverified): {generated}")
    else:
        details.append("Looki recorded this moment; no generated description was available.")
    if location:
        details.append(f"Location label: {location}.")

    vendor_tags = []
    for tag in moment.tags:
        raw_tag = str(tag)
        if (
            _contains_precise_coordinates(raw_tag)
            or _scrub_url_string(raw_tag) != raw_tag
        ):
            continue
        cleaned = _slug(raw_tag)
        if cleaned and cleaned != "unknown" and cleaned not in vendor_tags:
            vendor_tags.append(cleaned)

    return HflEntry(
        when=when,
        moment=title,
        what_happened=" ".join(details),
        why_it_stayed=(
            "Captured by the Looki wearable as a recall index. Verify against "
            "the source media before consequential use; the generated narrative "
            "is not treated as ground truth."
        ),
        possible_use="lifelog-recall / selective source-media verification",
        tags=("looki", "wearable", "lifelog", "unverified-ai", *vendor_tags[:6]),
        references=(f"looki:{moment.id}",),
    )


def _completed_reference_file(corpus_dir: Path, reference: str) -> Path | None:
    """Find a reference inside a structurally complete, terminated HFL block."""
    required_labels = (
        "Moment:",
        "What happened:",
        "Why it stayed:",
        "Possible use:",
        "Tags:",
        "References:",
    )
    for path in corpus_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # A crash can leave a header or reference line behind. Only chunks that
        # end at an explicit separator are eligible for duplicate detection.
        chunks = re.split(r"(?m)^---\s*$", text)
        for chunk in chunks[:-1]:
            lines = chunk.strip().splitlines()
            headers = [i for i, line in enumerate(lines) if line.startswith("## ")]
            if not headers:
                continue
            block = lines[headers[-1]:]
            if not all(
                any(line.startswith(label) for line in block)
                for label in required_labels
            ):
                continue
            entry = HflEntry.from_markdown(block[0][3:], "\n".join(block[1:]))
            if (
                all((entry.moment, entry.what_happened, entry.why_it_stayed, entry.possible_use))
                and reference in entry.references
            ):
                return path
    return None


def _looki_state_paths(corpus_dir: Path, moment_id: str) -> tuple[Path, Path]:
    key = hashlib.sha256(moment_id.encode("utf-8")).hexdigest()
    state_dir = corpus_dir / ".looki-ingest-state"
    return state_dir / f"{key}.lock", state_dir / f"{key}.done"


def _acquire_looki_claim(
    corpus_dir: Path, moment_id: str,
) -> tuple[Path, Path, int] | None:
    """Acquire an FD-bound claim; crashes release the advisory lock."""
    lock_path, done_path = _looki_state_paths(corpus_dir, moment_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if done_path.exists():
        return None
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    if not _try_lock_fd(fd):
        os.close(fd)
        return None
    if done_path.exists():
        _unlock_fd(fd)
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, f"{moment_id}\n".encode("utf-8"))
    return lock_path, done_path, fd


def _finish_looki_claim(
    claim: tuple[Path, Path, int], *, completed: bool,
) -> None:
    """Mark completion while holding the claim, then release it."""
    _lock_path, done_path, fd = claim
    try:
        if completed:
            try:
                done_fd = os.open(done_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                try:
                    os.write(done_fd, b"done\n")
                finally:
                    os.close(done_fd)
    finally:
        try:
            _unlock_fd(fd)
        finally:
            os.close(fd)


def _index_moment(entry: HflEntry, moment_id: str) -> None:
    index_hfl_entry(
        entry,
        source="looki",
        synthesized=False,
        doc_id=_looki_doc_id(moment_id),
    )


@SPROUT.task()
@log_result()
def ingest_looki_activity(
    *,
    window_days: int = 2,
    max_moments: int = 200,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Poll a bounded Looki date window and persist one entry per new moment."""
    run_at = now or datetime.now()
    adapter = build_adapter(LOOKI_CONFIG)
    if not adapter.status.get("ready"):
        return {
            "entries_written": 0,
            "duplicates_skipped": 0,
            "invalid_skipped": 0,
            "skipped": "no api key",
        }

    since, until = _window(window_days, today=run_at.date())
    try:
        moments = adapter.list_moments(
            since=since.isoformat(),
            until=until.isoformat(),
            max_moments=max(1, min(int(max_moments), 1000)),
        )
    except Exception as exc:  # noqa: BLE001 - scheduled source must no-op cleanly
        _log.warning("ingest_looki: API unavailable (%s)", type(exc).__name__)
        return {
            "entries_written": 0,
            "duplicates_skipped": 0,
            "invalid_skipped": 0,
            "skipped": "api unavailable",
            "window": [since.isoformat(), until.isoformat()],
        }

    if not moments:
        return {
            "entries_written": 0,
            "duplicates_skipped": 0,
            "invalid_skipped": 0,
            "skipped": "no moments",
            "window": [since.isoformat(), until.isoformat()],
        }

    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    written = duplicates = invalid = 0
    for moment in moments:
        moment_id = valid_moment_id(moment.id)
        if moment_id is None:
            invalid += 1
            continue
        entry = _entry_for(moment, fallback=run_at)
        entry_when = entry.when or run_at
        day_file = corpus_dir / f"{entry_when.strftime('%Y-%m-%d')}.md"
        reference = f"looki:{moment_id}"
        _, done_path = _looki_state_paths(corpus_dir, moment_id)
        if done_path.exists():
            # The ES write is best-effort; overlap polls re-upsert completed
            # items so a transient projection failure self-repairs.
            _index_moment(entry, moment_id)
            duplicates += 1
            continue

        claim = _acquire_looki_claim(corpus_dir, moment_id)
        if claim is None:
            duplicates += 1
            continue
        completed = False
        try:
            if _completed_reference_file(corpus_dir, reference) is not None:
                _index_moment(entry, moment_id)
                duplicates += 1
            else:
                with day_file.open("a", encoding="utf-8") as handle:
                    handle.write(entry.to_markdown())
                    handle.write("---\n\n")
                _index_moment(entry, moment_id)
                written += 1
            completed = True
        finally:
            _finish_looki_claim(claim, completed=completed)

    _log.info(
        "ingest_looki: %d written, %d duplicate, %d invalid from %d moments",
        written,
        duplicates,
        invalid,
        len(moments),
    )
    return {
        "entries_written": written,
        "duplicates_skipped": duplicates,
        "invalid_skipped": invalid,
        "moments_seen": len(moments),
        "window": [since.isoformat(), until.isoformat()],
        "metadata_only": True,
    }
