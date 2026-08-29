"""Validated, atomic updates for corpus Markdown documents."""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from filelock import BaseFileLock, FileLock
from pydantic import BaseModel, Field


class UpdateDocumentRequest(BaseModel):
    text: str = Field(max_length=5_000_000)
    expected_updated_at: str | None = None


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

    with _document_lock(path):
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
        finally:
            temporary.unlink(missing_ok=True)
    return path
