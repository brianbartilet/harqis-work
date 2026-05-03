"""
Canonical Trello list (column) names + transition rules.

The full board template is:

    Templates  → card templates (orchestrator never reads or writes here)
    Draft      → being refined by a human (orchestrator ignores)
    Ready      → ready to be picked up (orchestrator polls THIS)
    Pending    → orchestrator claimed it; about to start
    In Progress → agent is working
    Blocked    → hard-stop dependency; auto re-queued when resolved
    In Review  → agent finished; awaiting human (or reviewer agent) approval
    Done       → finished + approved
    Failed     → unrecoverable error

Cards always flow forward: Ready → Pending → In Progress → In Review → Done,
with branches into Blocked (re-queued back to Ready) and Failed (terminal).

`success_destination(profile)` returns where the agent should put a card after
a successful run — `In Review` by default, but `Done` if the profile has
`lifecycle.auto_approve: true` (no human gate).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.projects.profiles.schema import AgentProfile


class Lists:
    """Canonical column names. Strings are exactly what Trello shows."""
    TEMPLATES = "Templates"
    DRAFT = "Draft"
    READY = "Ready"
    PENDING = "Pending"
    IN_PROGRESS = "In Progress"
    BLOCKED = "Blocked"
    IN_REVIEW = "In Review"
    DONE = "Done"
    FAILED = "Failed"


# The full ordered set, suitable for board-template creation.
ALL_LISTS: tuple[str, ...] = (
    Lists.TEMPLATES,
    Lists.DRAFT,
    Lists.READY,
    Lists.PENDING,
    Lists.IN_PROGRESS,
    Lists.BLOCKED,
    Lists.IN_REVIEW,
    Lists.DONE,
    Lists.FAILED,
)

# Lists the orchestrator polls for incoming work. (Templates / Draft are
# off-limits — Templates holds card templates, Draft holds work being refined.)
INTAKE_LIST: str = Lists.READY

# Where re-queued blocked cards go.
REQUEUE_LIST: str = Lists.READY


def success_destination(profile: "AgentProfile") -> str:
    """Where to move a card when the agent finishes successfully.

    `In Review` is the default — work waits for a human or reviewer-agent to
    approve before reaching `Done`. Profiles can opt out with
    `lifecycle.auto_approve: true` for fully-trusted automations.
    """
    if getattr(profile.lifecycle, "auto_approve", False):
        return Lists.DONE
    return Lists.IN_REVIEW
