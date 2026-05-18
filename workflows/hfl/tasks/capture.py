"""
workflows/hfl/tasks/capture.py

Capture one Homework-for-Life entry to the structured corpus.

Entry shape (Markdown, one file per day, multiple entries appended):

    ## YYYY-MM-DD HH:MM
    Moment:          <one-line headline>
    What happened:   <2-4 lines>
    Why it stayed:   <why this is story-worthy>
    Possible use:    <linkedin idea / retro / mentoring / lesson / etc.>
    Tags:            #tag1 #tag2 ...

Corpus path resolution (first hit wins):
    1. apps_config.yaml::HFL.corpus.path
    2. env var HFL_CORPUS_PATH
    3. <repo>/logs/hfl/

This task is NOT in the beat schedule by default — see
workflows/hfl/README.md §Activation.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.hfl.dto import HflEntry
from workflows.hfl.es_store import index_hfl_entry

_log = create_logger("hfl.capture")

REPO_ROOT = Path(__file__).resolve().parents[3]


def resolve_corpus_dir() -> Path:
    """Resolve the HFL corpus directory using the documented precedence."""
    try:
        from apps.apps_config import CONFIG_MANAGER
        hfl_cfg = CONFIG_MANAGER.get("HFL")
        if hfl_cfg and isinstance(hfl_cfg, dict):
            cfg_path = (hfl_cfg.get("corpus") or {}).get("path")
            if cfg_path and "${" not in cfg_path:
                return Path(cfg_path).resolve()
    except Exception:
        pass

    env_path = os.environ.get("HFL_CORPUS_PATH", "").strip()
    if env_path:
        return Path(env_path).resolve()

    return (REPO_ROOT / "logs" / "hfl").resolve()


def _format_tags(tags: Optional[Iterable[str]]) -> str:
    """Kept for backward compatibility; HflEntry now owns tag formatting."""
    if not tags:
        return ""
    cleaned = [t.strip().lstrip("#") for t in tags if t and t.strip()]
    return " ".join(f"#{t}" for t in cleaned)


def _build_entry(
    *,
    when: datetime,
    moment: str,
    what_happened: str,
    why_it_stayed: str,
    possible_use: str,
    tags: Optional[Iterable[str]] = None,
    references: Optional[Iterable[str]] = None,
) -> HflEntry:
    """Construct the formal HflEntry DTO — the single source of truth for
    both the on-disk Markdown shape and the ES projection."""
    return HflEntry(
        when=when,
        moment=moment,
        what_happened=what_happened,
        why_it_stayed=why_it_stayed,
        possible_use=possible_use,
        tags=tuple(tags) if tags else (),
        references=tuple(references) if references else (),
    )


def _render_entry(
    *,
    when: datetime,
    moment: str,
    what_happened: str,
    why_it_stayed: str,
    possible_use: str,
    tags: Optional[Iterable[str]],
    references: Optional[Iterable[str]] = None,
) -> str:
    """Render one corpus entry block.

    Thin delegator to the formal HflEntry DTO (the single source of truth
    for the on-disk format). With no `references` the output is
    byte-identical to the pre-DTO format — existing producers (the ingest
    tasks, analyze_media) are unaffected unless they pass references.
    """
    return _build_entry(
        when=when,
        moment=moment,
        what_happened=what_happened,
        why_it_stayed=why_it_stayed,
        possible_use=possible_use,
        tags=tags,
        references=references,
    ).to_markdown()


def append_entry(
    day_file: Path,
    entry: HflEntry,
    *,
    source: str,
    synthesized: bool = False,
) -> tuple[int, Optional[str]]:
    """Append `entry` to the day's corpus file and best-effort dual-write
    it to the ES entry index (workflows/hfl/es_store.py).

    The corpus write is the source of truth and happens first; ES indexing
    is additive and never raises (any failure is swallowed + logged by
    index_hfl_entry). Returns ``(bytes_written, doc_id)`` where ``doc_id``
    is the ES document id, or ``None`` if indexing was skipped/failed (the
    corpus write is unaffected either way).
    """
    with day_file.open("a", encoding="utf-8") as fh:
        bytes_written = fh.write(entry.to_markdown())
    doc_id = index_hfl_entry(entry, source=source, synthesized=synthesized)
    return bytes_written, doc_id


@SPROUT.task()
@log_result()
def capture_hfl_entry(
    *,
    moment: str = "",
    what_happened: str = "",
    why_it_stayed: str = "",
    possible_use: str = "",
    tags: Optional[list[str]] = None,
    references: Optional[list[str]] = None,
    when_iso: Optional[str] = None,
) -> dict[str, Any]:
    """Append a single HFL entry to the day's corpus file.

    Args:
        references: optional URLs / host file paths / links pointing at
            source material for this moment. Stored in the entry (and made
            searchable by retrieve); summarize_hfl_week resolves them to
            enrich the weekly rollup. The manifesto provenance convention:
            an hfl_signal entry should reference its source artifact.

    Returns a small dict for the Elasticsearch review trail:
        {"path": str, "bytes_written": int, "moment": str, "references": int}

    Empty `moment` is a no-op — the manifesto's rule is "the smallest useful
    entry is one line", and one line is the moment headline.
    """
    if not moment.strip():
        return {"path": "", "bytes_written": 0, "moment": "", "skipped": "empty"}

    when = datetime.fromisoformat(when_iso) if when_iso else datetime.now()

    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    target = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"

    entry = _build_entry(
        when=when,
        moment=moment,
        what_happened=what_happened,
        why_it_stayed=why_it_stayed,
        possible_use=possible_use,
        tags=tags,
        references=references,
    )

    bytes_written, _doc_id = append_entry(target, entry, source="capture")

    _log.info("Captured HFL entry to %s (%d bytes)", target, bytes_written)
    return {
        "path": str(target),
        "bytes_written": bytes_written,
        "moment": moment.strip()[:120],
        "references": len(references) if references else 0,
    }
