"""Validated, atomic updates for corpus Markdown documents."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from pydantic import BaseModel, Field


class UpdateDocumentRequest(BaseModel):
    text: str = Field(max_length=5_000_000)


def update_document_text(document, text: str, *, corpus_dir: Path) -> Path:
    """Replace a known corpus document without allowing arbitrary path writes."""
    root = corpus_dir.expanduser().resolve()
    path = (document.path or (root / document.relative_path)).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Corpus document is outside the configured corpus root.") from exc
    if path.suffix.casefold() != ".md" or not path.is_file():
        raise ValueError("Corpus document is not an editable Markdown file.")

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
