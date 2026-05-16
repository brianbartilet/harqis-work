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
    if not tags:
        return ""
    cleaned = [t.strip().lstrip("#") for t in tags if t and t.strip()]
    return " ".join(f"#{t}" for t in cleaned)


def _render_entry(
    *,
    when: datetime,
    moment: str,
    what_happened: str,
    why_it_stayed: str,
    possible_use: str,
    tags: Optional[Iterable[str]],
) -> str:
    return (
        f"## {when.strftime('%Y-%m-%d %H:%M')}\n"
        f"Moment:          {moment.strip()}\n"
        f"What happened:   {what_happened.strip()}\n"
        f"Why it stayed:   {why_it_stayed.strip()}\n"
        f"Possible use:    {possible_use.strip()}\n"
        f"Tags:            {_format_tags(tags)}\n\n"
    )


@SPROUT.task()
@log_result()
def capture_hfl_entry(
    *,
    moment: str = "",
    what_happened: str = "",
    why_it_stayed: str = "",
    possible_use: str = "",
    tags: Optional[list[str]] = None,
    when_iso: Optional[str] = None,
) -> dict[str, Any]:
    """Append a single HFL entry to the day's corpus file.

    Returns a small dict for the Elasticsearch review trail:
        {"path": str, "bytes_written": int, "moment": str}

    Empty `moment` is a no-op — the manifesto's rule is "the smallest useful
    entry is one line", and one line is the moment headline.
    """
    if not moment.strip():
        return {"path": "", "bytes_written": 0, "moment": "", "skipped": "empty"}

    when = datetime.fromisoformat(when_iso) if when_iso else datetime.now()

    corpus_dir = resolve_corpus_dir()
    corpus_dir.mkdir(parents=True, exist_ok=True)
    target = corpus_dir / f"{when.strftime('%Y-%m-%d')}.md"

    block = _render_entry(
        when=when,
        moment=moment,
        what_happened=what_happened,
        why_it_stayed=why_it_stayed,
        possible_use=possible_use,
        tags=tags,
    )

    with target.open("a", encoding="utf-8") as fh:
        bytes_written = fh.write(block)

    _log.info("Captured HFL entry to %s (%d bytes)", target, bytes_written)
    return {
        "path": str(target),
        "bytes_written": bytes_written,
        "moment": moment.strip()[:120],
    }
