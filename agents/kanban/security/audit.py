"""
AuditLogger — structured JSONL event log for all security-relevant
actions taken by a Kanban agent during a single card run.

Each event is written as a single JSON line to:
  - A rotating file (logs/kanban_audit.jsonl by default)
  - Python's logging system at DEBUG level

Event categories
────────────────
  tool_call          — agent invoked a tool
  tool_result        — tool returned (success or error)
  permission_check   — enforcer allowed or denied an action
  secret_access      — SecretStore scoped secrets for a profile
  sanitizer_redact   — OutputSanitizer replaced a secret value
  agent_start        — agent loop began for a card
  agent_finish       — agent loop completed (final result or error)
  card_lifecycle     — card moved between Kanban columns
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = Path("logs")
_DEFAULT_LOG_FILE = "kanban_audit.jsonl"


class AuditLogger:
    """
    Writes structured JSONL audit events.

    Args:
        log_path: Path to the output JSONL file.
                  Parent directory is created if it does not exist.
        agent_id: Profile ID of the agent being audited.
        card_id:  Kanban card ID being processed.
    """

    def __init__(
        self,
        agent_id: str,
        card_id: str,
        log_path: Optional[Path] = None,
    ) -> None:
        self.agent_id = agent_id
        self.card_id = card_id

        if log_path is None:
            log_path = _DEFAULT_LOG_DIR / _DEFAULT_LOG_FILE
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path = log_path

    # ── Typed event helpers ────────────────────────────────────────────────────

    def tool_call(self, tool_name: str, inputs: dict) -> None:
        self._write("tool_call", tool=tool_name, inputs=_safe_inputs(inputs))

    def tool_result(self, tool_name: str, *, success: bool, detail: str = "") -> None:
        self._write("tool_result", tool=tool_name, success=success, detail=detail[:500])

    def permission_check(
        self, check_type: str, target: str, *, allowed: bool, reason: str = ""
    ) -> None:
        self._write(
            "permission_check",
            check_type=check_type,
            target=target,
            allowed=allowed,
            reason=reason,
        )

    def secret_access(self, profile_id: str, var_names: list[str]) -> None:
        self._write("secret_access", profile_id=profile_id, var_names=var_names)

    def sanitizer_redact(self, location: str) -> None:
        self._write("sanitizer_redact", location=location)

    def agent_start(self, card_title: str) -> None:
        self._write("agent_start", card_title=card_title)

    def agent_finish(self, *, success: bool, iterations: int, detail: str = "") -> None:
        self._write(
            "agent_finish", success=success, iterations=iterations, detail=detail[:500]
        )

    def card_lifecycle(self, from_col: str, to_col: str) -> None:
        self._write("card_lifecycle", from_col=from_col, to_col=to_col)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _write(self, event: str, **kwargs: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "agent_id": self.agent_id,
            "card_id": self.card_id,
            **kwargs,
        }
        line = json.dumps(record, default=str)
        logger.debug("AUDIT %s", line)
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.error("AuditLogger: could not write to %s: %s", self._log_path, e)


# ── Null implementation for tests / dry-run ───────────────────────────────────

class NullAuditLogger(AuditLogger):
    """Drop-all audit logger used in tests and dry-run mode."""

    def __init__(self) -> None:  # type: ignore[override]
        self.agent_id = "null"
        self.card_id = "null"
        self._log_path = Path(os.devnull)

    def _write(self, event: str, **kwargs: Any) -> None:  # type: ignore[override]
        pass


# ── Input scrubbing for audit records ─────────────────────────────────────────

def _safe_inputs(inputs: dict) -> dict:
    """
    Remove values that look like secrets from tool-call inputs before
    writing to the audit log.  Heuristic: values > 20 chars that are
    hex/base64-ish are replaced with '<omitted>'.
    """
    import re
    _SECRET_RE = re.compile(r'^[A-Za-z0-9+/=_\-]{20,}$')
    out = {}
    for k, v in inputs.items():
        if isinstance(v, str) and _SECRET_RE.match(v):
            out[k] = "<omitted>"
        else:
            out[k] = v
    return out
