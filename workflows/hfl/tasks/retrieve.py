"""
workflows/hfl/tasks/retrieve.py

Retrieve HFL entries by substring / tag, with optional date filter.

This is the v0 retrieval — a literal scan over the corpus directory. It is
intentionally not vector-based: the corpus is small (one or two entries per
day), so grep beats RAG until the corpus has critical mass. The follow-up
path is the existing `workflows/knowledge/` RAG pipeline; this task's API
will not change.

Optional Gmail digest
---------------------
Pass ``email_to=<addr>`` (and optionally ``cfg_id__gmail``) to also mail the
rendered hits to that address — closes the capture → ingest → retrieve loop
for the weekly Sunday-evening digest scheduled in ``tasks_config.py``. MCP
callers leave ``email_to=None`` so live recall queries don't trigger mail.
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


def _render_digest(hits: list[dict[str, str]], query: str, since: Optional[str]) -> str:
    """Render hits as the plain-text body of the digest email."""
    header = f"HFL digest — {len(hits)} entr{'y' if len(hits) == 1 else 'ies'}"
    if query.strip():
        header += f" matching {query.strip()!r}"
    if since:
        header += f" since {since}"
    lines = [header, "=" * len(header), ""]
    for h in hits:
        lines.append(f"## {h['date']} — {h['header']}")
        body = (h.get("body") or "").rstrip()
        if body:
            lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _send_digest_email(
    *,
    hits: list[dict[str, str]],
    query: str,
    since: Optional[str],
    email_to: str,
    cfg_id__gmail: str,
) -> bool:
    """Send the digest via Gmail. Best-effort — returns True on success, False on
    any failure (logged), never raises so the task contract holds."""
    try:
        from apps.apps_config import CONFIG_MANAGER
        from apps.google_apps.references.web.api.gmail import ApiServiceGoogleGmail

        body = _render_digest(hits, query, since)
        suffix = f" matching {query.strip()!r}" if query.strip() else ""
        subject = f"HFL digest — {len(hits)} entr{'y' if len(hits) == 1 else 'ies'}{suffix}"

        cfg = CONFIG_MANAGER.get(cfg_id__gmail)
        gmail = ApiServiceGoogleGmail(cfg)
        gmail.send_email(to=email_to, subject=subject, body=body)
        _log.info("hfl.retrieve: digest emailed to %s (%d entries)", email_to, len(hits))
        return True
    except Exception as exc:  # noqa: BLE001 — email is bonus; retrieval already succeeded
        _log.warning("hfl.retrieve: digest email failed (%s) — retrieval unaffected", exc)
        return False


@SPROUT.task()
@log_result()
def retrieve_hfl_corpus(
    *,
    query: str = "",
    k: int = 8,
    since: Optional[str] = None,
    email_to: Optional[str] = None,
    cfg_id__gmail: str = "GOOGLE_GMAIL_SEND",
) -> dict[str, Any]:
    """Return up to `k` matching HFL entries, most recent first.

    Args:
        query: substring matched (case-insensitive) against header + body.
               Empty query returns the most recent `k` entries unfiltered.
        k:     max results.
        since: ISO date "YYYY-MM-DD" or a relative "-Nd" (e.g. "-30d").
        email_to: if set, mail the rendered hits to this address as a plain-text
                  digest. Skipped (no LLM, no send) when hits is empty. Failures
                  are logged-and-swallowed — retrieval is the source of truth.
        cfg_id__gmail: apps_config.yaml key for the Gmail-send account
                       (default ``GOOGLE_GMAIL_SEND``).

    Returns:
        {"hits": [{"date": ..., "header": ..., "body": ..., "path": ...}],
         "count": int, "corpus_dir": str, "emailed": bool}
    """
    corpus_dir = resolve_corpus_dir()
    if not corpus_dir.exists():
        return {"hits": [], "count": 0, "corpus_dir": str(corpus_dir), "emailed": False}

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
                    break
        if len(hits) >= k:
            break

    emailed = False
    if email_to and hits:
        emailed = _send_digest_email(
            hits=hits, query=query, since=since,
            email_to=email_to, cfg_id__gmail=cfg_id__gmail,
        )

    return {
        "hits": hits,
        "count": len(hits),
        "corpus_dir": str(corpus_dir),
        "emailed": emailed,
    }
