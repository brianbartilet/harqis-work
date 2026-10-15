"""Validated, atomic updates for corpus Markdown documents."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal
from collections.abc import Callable

from filelock import BaseFileLock, FileLock
from pydantic import BaseModel, Field

class UpdateDocumentRequest(BaseModel):
    text: str = Field(max_length=5_000_000)
    expected_updated_at: str | None = None


class EntryActionRequest(BaseModel):
    anchor: str = Field(min_length=1, max_length=200)
    action: Literal['archive', 'secret']
    expected_updated_at: str = Field(min_length=1, max_length=100)


def apply_entry_action(document, anchor: str, action: str, secret_tags=()) -> str:
    """Modify only the selected Markdown block; never delete an indexed record."""
    from modules.hfl_corpus.corpus import _HEADER, parse_entries

    entries = parse_entries(document.text)
    index = next((i for i, entry in enumerate(entries) if entry.anchor == anchor), None)
    if index is None:
        raise ValueError('Entry not found. Reload the document and try again.')
    headings = list(_HEADER.finditer(document.text))
    start = headings[index].start()
    end = headings[index + 1].start() if index + 1 < len(headings) else len(document.text)
    block = document.text[start:end]
    if action == 'archive':
        block = ''
    elif action == 'secret':
        missing = [tag for tag in secret_tags if tag not in entries[index].tags]
        if missing:
            suffix = ' '.join('#' + tag for tag in missing)
            tags = re.search(r'^Tags:[^\r\n]*', block, re.MULTILINE | re.IGNORECASE)
            if tags:
                block = block[:tags.end()] + ' ' + suffix + block[tags.end():]
            else:
                # Insert metadata immediately after the heading, before narrative fields.
                offset = block.find('\n') + 1
                if not offset:
                    block += '\n'
                    offset = len(block)
                block = block[:offset] + 'Tags: ' + suffix + '\n' + block[offset:]
    else:
        raise ValueError('Unsupported entry action.')
    return document.text[:start] + block + document.text[end:]


class DocumentConflictError(ValueError):
    """Raised when a caller tries to replace a stale corpus document."""


def _document_lock(path: Path) -> BaseFileLock:
    lock_dir = Path(tempfile.gettempdir()) / "harqis-hfl-document-locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return FileLock(lock_dir / f"{digest}.lock")


def update_document_text(
    document,
    text: str,
    *,
    corpus_dir: Path,
    expected_updated_at: str | None = None,
    after_write: Callable[[], None] | None = None,
) -> Path:
    """Replace a known corpus document without allowing arbitrary path writes."""
    root = corpus_dir.expanduser().resolve()
    path = (document.path or (root / document.relative_path)).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Corpus document is outside the configured corpus root.") from exc
    if path.suffix.casefold() != ".md" or not path.is_file():
        raise ValueError("Corpus document is not an editable Markdown file.")

    from workflows.hfl.write_lock import corpus_write_lock

    with corpus_write_lock(root), _document_lock(path):
        if expected_updated_at:
            observed = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            if observed != expected_updated_at:
                raise DocumentConflictError(
                    "The HFL document changed after review; retrieve it again before updating."
                )
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            if after_write is not None:
                # Entry projections must be updated under the same corpus lock,
                # otherwise a slower earlier save can overwrite a newer index.
                after_write()
        finally:
            temporary.unlink(missing_ok=True)
    from workflows.hfl.entity_events import notify_change
    notify_change()
    return path
