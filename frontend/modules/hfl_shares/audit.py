"""Sanitized HFL audit events for guest share activity."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime


_log = logging.getLogger(__name__)
_TOKENISH = re.compile(
    r"(?i)\b(?:bearer\s+)?[A-Za-z0-9_-]{28,}\b|"
    r"\b(?:pin|token|secret|password)\s*[:=]\s*\S+"
)
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\[^\s<>\"']+")
_UNIX_PATH = re.compile(r"(?<!:)\/(?:Users|Volumes|home|srv|etc|var)\/[^\s<>\"']+")


def _sanitize(value: str, limit: int) -> str:
    text = _TOKENISH.sub("[redacted]", value or "")
    text = _WINDOWS_PATH.sub("[local path]", text)
    text = _UNIX_PATH.sub("[local path]", text)
    return text.strip()[:limit]


def record_share_audit(
    *,
    event: str,
    share_id: str,
    question: str = "",
    answer: str = "",
) -> None:
    """Best-effort durable audit without credentials or network identifiers."""
    try:
        from workflows.hfl.dto import HflEntry
        from workflows.hfl.persistence import submit_hfl_entry

        safe_event = re.sub(r"[^a-z0-9-]+", "-", event.casefold()).strip("-")
        safe_question = _sanitize(question, 2000)
        safe_answer = _sanitize(answer, 5000)
        details = "\n".join(
            part
            for part in (
                f"Event: {safe_event}",
                f"Share: {share_id}",
                f"Question: {safe_question}" if safe_question else "",
                f"Answer: {safe_answer}" if safe_answer else "",
            )
            if part
        )
        submit_hfl_entry(
            HflEntry(
                when=datetime.now(),
                moment=f"Corpus share {safe_event}",
                what_happened=details,
                why_it_stayed="Audit trail for temporary corpus sharing.",
                possible_use="sharing-audit",
                tags=("sharing", "audit", safe_event),
            ),
            source="sharing-audit",
            dedup_key=f"{share_id}:{safe_event}:{uuid.uuid4()}",
        )
    except Exception as exc:  # noqa: BLE001 - audit outbox is best effort here
        _log.warning("sharing audit persistence failed: %s", type(exc).__name__)
