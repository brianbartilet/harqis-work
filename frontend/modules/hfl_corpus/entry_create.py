"""Validation, preview, and persistence for manually created HFL entries."""

from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from modules.hfl_corpus.corpus import format_hfl_markdown
from services.markdown import render_markdown


_REFERENCE_BULLET = re.compile(r"^\s*[-*•]\s+")


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


def make_manual_envelope(payload: CreateEntryRequest):
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
    return make_envelope(entry, source="manual-entry")


def preview_manual_entry(payload: CreateEntryRequest) -> dict[str, str]:
    envelope = make_manual_envelope(payload)
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
