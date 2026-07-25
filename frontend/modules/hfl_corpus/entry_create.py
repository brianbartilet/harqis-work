"""Validation, preview, and persistence for manually created HFL entries."""

from __future__ import annotations

import os
import re
import shutil
import uuid
from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile

from modules.hfl_corpus.corpus import format_hfl_markdown
from services.markdown import render_markdown


_REFERENCE_BULLET = re.compile(r"^\s*[-*•]\s+")
_UNSAFE_FILENAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')
MAX_UPLOAD_FILES = 10
MAX_UPLOAD_FILE_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_TOTAL_BYTES = 200 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024


class CreateEntryRequest(BaseModel):
    """Browser/API payload for one manual HFL entry."""

    date: str = Field(max_length=10)
    time: str = Field(max_length=8)
    moment: str = Field(max_length=500)
    what_happened: str = Field(max_length=20_000)
    why_it_stayed: str = Field(default="", max_length=10_000)
    possible_use: str = Field(default="", max_length=5_000)
    tags: str = Field(default="", max_length=2_000)
    references: str = Field(default="", max_length=20_000)
    attachment_names: list[str] = Field(default_factory=list, max_length=MAX_UPLOAD_FILES)


def _timestamp(payload: CreateEntryRequest) -> datetime:
    try:
        selected_date = date.fromisoformat(payload.date)
        selected_time = time.fromisoformat(payload.time)
    except ValueError as exc:
        raise ValueError("Enter a valid date and time.") from exc
    return datetime.combine(selected_date, selected_time).replace(second=0, microsecond=0)


def _tags(value: str) -> tuple[str, ...]:
    normalized = (
        token.strip().strip(",").lstrip("#")
        for token in re.split(r"\s+", value or "")
    )
    return tuple(dict.fromkeys(token for token in normalized if token))


def _references(value: str) -> tuple[str, ...]:
    normalized = (
        _REFERENCE_BULLET.sub("", line).strip()
        for line in (value or "").splitlines()
    )
    return tuple(line for line in normalized if line)


def make_manual_envelope(
    payload: CreateEntryRequest,
    *,
    generated_references: tuple[str, ...] = (),
):
    """Build a canonical manual-entry envelope using the shared HFL DTO."""
    moment = payload.moment.strip()
    what_happened = payload.what_happened.strip()
    if not moment:
        raise ValueError("Moment is required.")
    if not what_happened:
        raise ValueError("What happened is required.")

    # Lazy imports keep read-only corpus browsing from registering HFL tasks.
    from workflows.hfl.dto import HflEntry
    from workflows.hfl.persistence import make_envelope

    entry = HflEntry(
        when=_timestamp(payload),
        moment=moment,
        what_happened=what_happened,
        why_it_stayed=payload.why_it_stayed,
        possible_use=payload.possible_use,
        tags=_tags(payload.tags),
        references=_references(payload.references),
    )
    envelope = make_envelope(entry, source="manual-entry")
    if not generated_references:
        return envelope
    references = tuple(
        dict.fromkeys((*envelope.entry.references, *generated_references))
    )
    return replace(envelope, entry=replace(envelope.entry, references=references))


def resolve_upload_inbox() -> Path:
    """Resolve the canonical dumps inbox from the shared machine config."""
    from workflows.dumps.config import get_dumps_target

    target = get_dumps_target()
    if target is None or not str(target.inbox).strip():
        raise ValueError(
            "File uploads require [dumps].harqis_server_inbox on the canonical host."
        )
    return Path(target.inbox).expanduser().resolve()


def sanitize_upload_filename(filename: str) -> str:
    """Return a safe leaf filename while retaining the recognizable original."""
    leaf = re.split(r"[/\\]", filename or "")[-1].strip()
    safe = _UNSAFE_FILENAME.sub("_", leaf).strip(" .")
    if not safe:
        safe = "upload"
    if len(safe) > 240:
        suffix = Path(safe).suffix[:20]
        stem_limit = max(1, 240 - len(suffix))
        safe = safe[:stem_limit].rstrip(" .") + suffix
    return safe


def _available_upload_names(
    filenames: list[str],
    *,
    target_dir: Path,
) -> list[str]:
    selected: set[str] = set()
    available: list[str] = []
    for raw_name in filenames:
        safe = sanitize_upload_filename(raw_name)
        candidate = safe
        suffix = Path(safe).suffix
        stem = safe[:-len(suffix)] if suffix else safe
        counter = 2
        while candidate.casefold() in selected or (target_dir / candidate).exists():
            candidate = f"{stem} ({counter}){suffix}"
            counter += 1
        selected.add(candidate.casefold())
        available.append(candidate)
    return available


def attachment_reference_paths(
    payload: CreateEntryRequest,
    *,
    inbox_dir: Path | None = None,
) -> tuple[str, ...]:
    """Return the canonical future paths for the payload's attachment names."""
    if not payload.attachment_names:
        return ()
    if len(payload.attachment_names) > MAX_UPLOAD_FILES:
        raise ValueError(f"Select no more than {MAX_UPLOAD_FILES} files.")
    envelope = make_manual_envelope(payload)
    inbox = (inbox_dir or resolve_upload_inbox()).expanduser().resolve()
    target_dir = (
        inbox
        / "uploads"
        / f"{envelope.entry.when:%Y-%m-%d}"
        / envelope.entry.entry_id
    )
    names = _available_upload_names(payload.attachment_names, target_dir=target_dir)
    return tuple(str(target_dir / name) for name in names)


def preview_manual_entry(payload: CreateEntryRequest) -> dict[str, str]:
    generated = attachment_reference_paths(payload)
    envelope = make_manual_envelope(payload, generated_references=generated)
    markdown = envelope.entry.to_markdown()
    return {
        "filename": f"{envelope.entry.when:%Y-%m-%d}.md",
        "markdown": markdown,
        "html": str(render_markdown(format_hfl_markdown(markdown))),
    }


def persist_manual_entry(
    payload: CreateEntryRequest,
    *,
    corpus_dir: Path,
) -> dict[str, Any]:
    from workflows.hfl.persistence import persist_envelope

    return persist_envelope(
        make_manual_envelope(payload),
        corpus_dir=corpus_dir,
    )


async def persist_manual_entry_with_uploads(
    payload: CreateEntryRequest,
    uploads: list[UploadFile],
    *,
    corpus_dir: Path,
    inbox_dir: Path | None = None,
) -> dict[str, Any]:
    """Stage attachments, commit them, and persist their canonical references."""
    if not uploads:
        if payload.attachment_names:
            raise ValueError("The selected files were not included. Review the entry again.")
        return persist_manual_entry(payload, corpus_dir=corpus_dir)
    if len(uploads) > MAX_UPLOAD_FILES:
        raise ValueError(f"Select no more than {MAX_UPLOAD_FILES} files.")

    filenames = [upload.filename or "" for upload in uploads]
    if payload.attachment_names and payload.attachment_names != filenames:
        raise ValueError("The selected files changed after preview. Review the entry again.")
    payload = payload.model_copy(update={"attachment_names": filenames})
    base_envelope = make_manual_envelope(payload)
    inbox = (inbox_dir or resolve_upload_inbox()).expanduser().resolve()
    uploads_root = inbox / "uploads"
    target_dir = (
        uploads_root
        / f"{base_envelope.entry.when:%Y-%m-%d}"
        / base_envelope.entry.entry_id
    )
    names = _available_upload_names(filenames, target_dir=target_dir)
    references = tuple(str(target_dir / name) for name in names)
    envelope = make_manual_envelope(payload, generated_references=references)
    staging_dir = uploads_root / ".staging" / uuid.uuid4().hex
    committed: list[Path] = []
    total_bytes = 0

    try:
        staging_dir.mkdir(parents=True, exist_ok=False)
        for upload, name in zip(uploads, names, strict=True):
            staged_path = staging_dir / name
            file_bytes = 0
            with staged_path.open("xb") as handle:
                while chunk := await upload.read(_UPLOAD_CHUNK_BYTES):
                    file_bytes += len(chunk)
                    total_bytes += len(chunk)
                    if file_bytes > MAX_UPLOAD_FILE_BYTES:
                        raise ValueError(
                            f"{name} exceeds the 50 MB per-file upload limit."
                        )
                    if total_bytes > MAX_UPLOAD_TOTAL_BYTES:
                        raise ValueError(
                            "The selected files exceed the 200 MB combined upload limit."
                        )
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())

        target_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = staging_dir / name
            destination = target_dir / name
            os.link(source, destination)
            source.unlink()
            committed.append(destination)

        from workflows.hfl.persistence import persist_envelope

        result = persist_envelope(
            envelope,
            corpus_dir=corpus_dir,
            merge_duplicate_references=True,
        )
        result["uploads"] = list(references)
        return result
    except Exception:
        for path in committed:
            path.unlink(missing_ok=True)
        if target_dir.exists() and not any(target_dir.iterdir()):
            try:
                target_dir.rmdir()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_root = staging_dir.parent
        if staging_root.exists() and not any(staging_root.iterdir()):
            try:
                staging_root.rmdir()
            except OSError:
                pass
        for upload in uploads:
            try:
                await upload.close()
            except Exception:
                pass
