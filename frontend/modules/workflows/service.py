"""Workflow registry access kept separate from HTTP routing."""

from __future__ import annotations

import logging

import generate_registry
from registry import TASK_REGISTRY, load_registry


logger = logging.getLogger(__name__)


def refresh_registry() -> dict:
    try:
        generate_registry.main()
        load_registry()
    except Exception as exc:
        logger.warning("Registry regeneration failed: %s", exc)
    return TASK_REGISTRY


def find_task(workflow: str, task_key: str) -> dict | None:
    workflow_def = TASK_REGISTRY.get(workflow)
    if not workflow_def:
        return None
    return next(
        (task for task in workflow_def["tasks"] if task["key"] == task_key),
        None,
    )
