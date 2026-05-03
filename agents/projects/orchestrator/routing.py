"""
Card routing helpers — who can pick up a card.

Three families of label decide routing:

  1. `human` / `manual` — explicit opt-out. No orchestrator touches the card.
  2. `input` — card needs human input; orchestrators leave it for a human.
  3. `agent:*` — which profile handles it (resolved by ProfileRegistry).
  4. `os:*` — which orchestrator host can claim it (auto-detected by OS).

This module owns the label-classification helpers; the BoardOrchestrator
decides what to do with the result.
"""

from __future__ import annotations

import platform

from agents.projects.trello.models import KanbanCard


# Cards bearing any of these labels are explicitly off-limits to every agent.
HUMAN_LABELS: frozenset[str] = frozenset({"human", "manual", "input"})


def is_human_card(card: KanbanCard) -> bool:
    """True if the card carries a `human`, `manual`, or `input` label.

    Case-insensitive. Orchestrators skip these cards entirely — no profile
    resolution, no claim, no comment, no column move.

    `input` was added alongside `human`/`manual` in the workspace refactor:
    same off-limits behaviour, but signals "we need a human to add info"
    rather than "this is a manual task."
    """
    if not card.labels:
        return False
    return any(lbl.strip().lower() in HUMAN_LABELS for lbl in card.labels)


def detect_local_os_labels() -> set[str]:
    """Return the `os:*` labels this host satisfies.

    Auto-detected from `platform.system()`. macOS gets both `os:darwin` and
    `os:macos` so card authors can use either spelling. `os:any` is always
    included as a wildcard so cards explicitly labelled `os:any` get picked up
    on every host.

    Was `detect_local_hw_labels()` returning `hw:*` labels — renamed in the
    workspace refactor (hard rename, no `hw:*` back-compat).
    """
    sysname = platform.system().lower()
    base: set[str]
    if sysname == "darwin":
        base = {"os:darwin", "os:macos", "os:mac"}
    elif sysname == "linux":
        base = {"os:linux"}
    elif sysname == "windows":
        base = {"os:windows", "os:win"}
    else:
        base = {f"os:{sysname}"}
    base.add("os:any")
    return base


def card_os_required(card: KanbanCard) -> set[str]:
    """Return the set of `os:*` labels declared on a card."""
    return {lbl for lbl in (card.labels or []) if lbl.startswith("os:")}
