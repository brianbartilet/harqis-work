"""
OutputSanitizer — scrubs known secret values from agent output before
it is posted to Kanban comments or written to any external system.

Prevents accidental credential leakage via:
  - Final agent text responses
  - Tool result strings stored in the message history
  - Error messages / tracebacks

Usage:
    sanitizer = OutputSanitizer(scoped_secrets)
    safe_text = sanitizer.scrub(raw_text)
"""

from __future__ import annotations

import logging
import re
from typing import Sequence

logger = logging.getLogger(__name__)

# Replacement token used in place of detected secrets
_REDACTED = "[REDACTED]"

# Minimum length — don't redact short values (e.g. "1", "yes") that
# might appear legitimately in text.
_MIN_SECRET_LEN = 8


class OutputSanitizer:
    """
    Scrubs known secret values from strings.

    The sanitizer is initialised with the *scoped* secrets dict that
    was injected into a specific agent.  It replaces any occurrence of
    those values with [REDACTED].  Matching is:
      - Case-sensitive (API keys are case-sensitive)
      - Whole-value (not partial matches for values < 8 chars)
    """

    def __init__(self, secrets: dict[str, str]) -> None:
        # Build a sorted list of (value, pattern) pairs — longest first so
        # that a token that is a prefix of another is replaced correctly.
        patterns: list[tuple[str, re.Pattern]] = []
        for name, value in secrets.items():
            if len(value) < _MIN_SECRET_LEN:
                logger.debug("Sanitizer: skipping short secret %s (len=%d)", name, len(value))
                continue
            patterns.append((value, re.compile(re.escape(value))))

        # Sort longest-first for greedy replacement
        self._patterns = sorted(patterns, key=lambda t: -len(t[0]))
        logger.debug("Sanitizer: %d secret(s) registered", len(self._patterns))

    # ── Public API ─────────────────────────────────────────────────────────────

    def scrub(self, text: str) -> str:
        """Return *text* with all registered secret values replaced."""
        if not self._patterns:
            return text
        for value, pattern in self._patterns:
            if value in text:
                text = pattern.sub(_REDACTED, text)
                logger.warning("Sanitizer: redacted a secret value from output")
        return text

    def scrub_messages(self, messages: list[dict]) -> list[dict]:
        """
        Scrub a Claude message history in-place.

        Mutates string content fields so the full conversation log is
        clean before any part of it is persisted or posted externally.
        """
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                msg["content"] = self.scrub(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if "text" in block:
                            block["text"] = self.scrub(block["text"])
                        if "content" in block and isinstance(block["content"], str):
                            block["content"] = self.scrub(block["content"])
        return messages

    @staticmethod
    def from_secrets(secrets: dict[str, str]) -> "OutputSanitizer":
        return OutputSanitizer(secrets)
