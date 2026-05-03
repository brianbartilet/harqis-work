"""
Agent ↔ human question-and-answer protocol.

Implements the "agent asks a question and waits for a human reply" interaction
pattern on top of the existing Kanban card surface.

How it works:
  1. The agent calls the `ask_human` tool. The tool:
       a. Posts a comment containing the QUESTION_MARKER prefix and the question.
       b. Adds the QUESTION_LABEL to the card.
       c. (If REMEMBER_LABEL is on the card) appends a hidden sidecar comment
          serialising the agent's full message history.
       d. Raises `AgentPausedForQuestion` to stop the run loop cleanly.
  2. The orchestrator catches the pause, leaves the card in `In Progress`, and
     does not post a result.
  3. On a later poll, the orchestrator scans `In Progress` cards. A card is
     "ready to resume" when it has the QUESTION_LABEL and a non-agent comment
     posted *after* the most recent QUESTION_MARKER comment.
  4. When a card is ready, the orchestrator removes QUESTION_LABEL and re-runs
     the agent. Two modes:
       - Stateful (REMEMBER_LABEL present): full message history is loaded
         from the sidecar; the human reply is appended as a new user message.
       - Stateless: the agent gets a recap prompt referencing the prior
         question and the human's answer, and runs from scratch.
  5. If the agent asks again, the cycle repeats. If it finishes normally, the
     card moves to Done as usual. If the human moves the card to Failed/Blocked
     while waiting, the orchestrator stops touching it.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Public constants ──────────────────────────────────────────────────────────

QUESTION_LABEL = "agent:question"
"""Card-level label added when the agent is waiting for a human reply."""

REMEMBER_LABEL = "agent:remember"
"""Card-level label that opts the card into stateful resume.

When present, the agent persists its full message history to a sidecar comment
each time it pauses, so on resume it picks up exactly where it left off
instead of getting a text recap.
"""

QUESTION_MARKER = "[agent:question]"
"""Prefix that marks a comment as the agent's question to a human.

The orchestrator uses this to find the resume anchor — comments posted *after*
the most recent occurrence are treated as the human's reply (assuming they
don't carry an agent-authored prefix).
"""

# Hidden marker block used to embed serialised agent state in a card comment.
# The block is intentionally an HTML comment so that any markdown renderer hides
# it. The base64 payload sits between START and END markers on its own line.
_STATE_START = "<!-- AGENT_STATE_V1:"
_STATE_END = "-->"

# Comment-prefix heuristics for "this comment was posted by the agent, not a
# human." Used by the resume detector when deciding whether a post-question
# comment is a human reply.
_AGENT_PREFIX_PATTERNS = (
    QUESTION_MARKER,
    "## Result",
    "## Agent",          # matches "## Agent Error", "## Agent: Blocked", etc.
    "claimed-by:",
    _STATE_START,
)


# ── Exceptions ────────────────────────────────────────────────────────────────

class AgentPausedForQuestion(Exception):
    """Raised by the `ask_human` tool to stop the run loop while waiting for a reply.

    The orchestrator catches this in `process_card` and leaves the card in
    `In Progress` without posting a result. The agent already posted the
    question comment and added `agent:question` before raising.
    """

    def __init__(self, question: str, *, stateful: bool = False):
        self.question = question
        self.stateful = stateful
        super().__init__(question)


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_agent_authored(comment: str) -> bool:
    """Heuristic: True if the comment was posted by an agent rather than a human.

    Matches the prefix patterns that the orchestrator and built-in tools use
    when posting agent comments. Persona signatures (Mode B) appear at the
    *end* of comments and aren't in the prefix list — for those, the agent's
    `## ...` heading earlier in the body still triggers the match.

    Not foolproof for free-form `post_comment` calls — agents can technically
    bypass the heuristic — but `ask_human` always uses QUESTION_MARKER so the
    primary signal (question/answer pairing) is reliable.
    """
    if not comment:
        return False
    stripped = comment.lstrip()
    return any(stripped.startswith(p) for p in _AGENT_PREFIX_PATTERNS)


def find_resume_signal(comments: list[str]) -> Optional[tuple[int, list[str]]]:
    """Return (question_index, human_replies) if the card is ready to resume.

    Args:
        comments: Card comments oldest-first, as returned by
                  `TrelloClient.get_comments(card_id)`.

    Returns:
        None when the agent isn't waiting (no question marker, or no human
        reply after the most recent question). When ready, returns a tuple of
        (index of the most recent QUESTION_MARKER comment, list of human
        comments posted after it in chronological order).
    """
    last_q = -1
    for i, c in enumerate(comments):
        if c.lstrip().startswith(QUESTION_MARKER):
            last_q = i
    if last_q == -1:
        return None
    human_replies = [c for c in comments[last_q + 1:] if not is_agent_authored(c)]
    if not human_replies:
        return None
    return last_q, human_replies


# ── State serialisation (stateful resume — REMEMBER_LABEL) ────────────────────

def serialize_state(
    messages: list[dict],
    iteration: int,
    profile_id: str,
    model_id: str,
) -> str:
    """Return the body of the hidden sidecar comment that captures agent state.

    The body is a single HTML-comment block enclosing a base64-encoded JSON
    payload. Format:

        <!-- AGENT_STATE_V1:<base64-json> -->

    The payload schema:
        {
          "v": 1,
          "profile_id": "<profile.id>",
          "model_id":   "<model.model_id>",
          "iteration":  <int>,
          "messages":   [...]
        }

    `messages` should already be JSON-serialisable — Anthropic's content blocks
    are dicts, but `assistant` turns produced by the SDK contain ContentBlock
    objects that need to be converted via `_message_to_jsonable` before calling
    this function. See `BaseKanbanAgent._save_state_for_pause`.
    """
    payload = {
        "v": 1,
        "profile_id": profile_id,
        "model_id": model_id,
        "iteration": iteration,
        "messages": messages,
    }
    encoded = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f"{_STATE_START}{encoded}{_STATE_END}"


_STATE_RE = re.compile(
    re.escape(_STATE_START) + r"\s*([A-Za-z0-9+/=]+)\s*" + re.escape(_STATE_END),
    re.DOTALL,
)


def extract_state(comments: list[str]) -> Optional[dict[str, Any]]:
    """Find and decode the most recent state sidecar in the comment list.

    Args:
        comments: Card comments oldest-first.

    Returns:
        The decoded JSON payload as a dict, or None if no valid state block is
        present. Older state blocks are ignored — only the latest is returned,
        because the agent re-serialises everything on each pause.
    """
    for comment in reversed(comments):
        match = _STATE_RE.search(comment)
        if not match:
            continue
        encoded = match.group(1)
        try:
            decoded = base64.b64decode(encoded).decode("utf-8")
            payload = json.loads(decoded)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Failed to decode AGENT_STATE block: %s", e)
            continue
        if not isinstance(payload, dict) or payload.get("v") != 1:
            logger.warning("Skipping unknown agent-state payload version: %s", payload.get("v"))
            continue
        return payload
    return None


# ── Recap prompt builder (stateless resume) ───────────────────────────────────

def build_recap_prompt(question_comment: str, human_replies: list[str]) -> str:
    """Compose the recap text that gets prepended to the resumed agent's user prompt.

    Used when REMEMBER_LABEL is NOT set — the agent gets a fresh instance and
    sees a recap of the prior question and the human's response, but does not
    have the original message history.
    """
    question = question_comment.split(QUESTION_MARKER, 1)[-1].strip()
    if len(human_replies) == 1:
        reply_block = human_replies[0].strip()
    else:
        reply_block = "\n\n---\n\n".join(r.strip() for r in human_replies)
    return (
        "## Resuming after a human reply\n\n"
        "On a previous run you asked the human a question via `ask_human`. "
        "That run paused; this run is the continuation. Pick up from where "
        "you left off — do NOT repeat actions already visible in the card's "
        "comment history.\n\n"
        "**You previously asked:**\n\n"
        f"> {question}\n\n"
        "**Human reply:**\n\n"
        f"{reply_block}\n\n"
        "Continue the task using this answer. If you need another piece of "
        "information, call `ask_human` again."
    )
