"""
workflows/hfl/tasks/retrieve.py

Retrieve HFL entries by substring / tag, with optional date filter.

This is the v0 retrieval — a literal scan over the corpus directory. It is
intentionally not vector-based: the corpus is small (one or two entries per
day), so grep beats RAG until the corpus has critical mass. The follow-up
path is the existing `workflows/knowledge/` RAG pipeline; this task's API
will not change.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger

from workflows.hfl.tasks.capture import resolve_corpus_dir

_log = create_logger("hfl.retrieve")


def _parse_since(since: Optional[str]) -> Optional[date]:
    if not since:
        return None
    s = since.strip()
    # accept "YYYY-MM-DD" or a relative "-Nd"
    if s.startswith("-") and s.endswith("d"):
        try:
            n = int(s[1:-1])
            return (datetime.now() - timedelta(days=n)).date()
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _entries_for_file(path: Path) -> list[dict[str, str]]:
    """Split one day's corpus file into individual entries by `## ` headers."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    entries: list[dict[str, str]] = []
    current: list[str] = []
    header: str = ""
    for line in text.splitlines():
        if line.startswith("## "):
            if header:
                entries.append({"header": header, "body": "\n".join(current).rstrip()})
            header = line[3:].strip()
            current = []
        else:
            current.append(line)
    if header:
        entries.append({"header": header, "body": "\n".join(current).rstrip()})
    return entries


@SPROUT.task()
@log_result()
def retrieve_hfl_corpus(
    *,
    query: str = "",
    k: int = 8,
    since: Optional[str] = None,
) -> dict[str, Any]:
    """Return up to `k` matching HFL entries, most recent first.

    Args:
        query: substring matched (case-insensitive) against header + body.
               Empty query returns the most recent `k` entries unfiltered.
        k:     max results.
        since: ISO date "YYYY-MM-DD" or a relative "-Nd" (e.g. "-30d").

    Returns:
        {"hits": [{"date": ..., "header": ..., "body": ..., "path": ...}],
         "count": int, "corpus_dir": str}
    """
    corpus_dir = resolve_corpus_dir()
    if not corpus_dir.exists():
        return {"hits": [], "count": 0, "corpus_dir": str(corpus_dir)}

    files = sorted(corpus_dir.glob("*.md"), reverse=True)
    since_date = _parse_since(since)
    needle = query.strip().lower()

    hits: list[dict[str, str]] = []
    for f in files:
        try:
            file_date = datetime.strptime(f.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if since_date and file_date < since_date:
            continue
        for entry in _entries_for_file(f):
            hay = f"{entry['header']}\n{entry['body']}".lower()
            if not needle or needle in hay:
                hits.append({
                    "date": str(file_date),
                    "header": entry["header"],
                    "body": entry["body"],
                    "path": str(f),
                })
                if len(hits) >= k:
                    return {"hits": hits, "count": len(hits), "corpus_dir": str(corpus_dir)}

    return {"hits": hits, "count": len(hits), "corpus_dir": str(corpus_dir)}
