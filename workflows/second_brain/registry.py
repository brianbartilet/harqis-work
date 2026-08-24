"""Allowlisted operations that may be selected by modes or an agent."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    category: str
    collector: str
    advisory_only: bool = True
    refresh_minutes: int = 5


OPERATIONS = {
    "work.jira_changed": OperationSpec(
        operation_id="work.jira_changed",
        category="work",
        collector="workflows.second_brain.collectors.jira.collect_jira_changed",
        refresh_minutes=5,
    ),
}


def operations_for_modes(modes: tuple[str, ...]) -> tuple[OperationSpec, ...]:
    selected = set(modes)
    return tuple(spec for spec in OPERATIONS.values() if spec.category in selected)
