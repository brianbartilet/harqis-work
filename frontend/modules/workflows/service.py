"""Workflow registry access kept separate from HTTP routing."""

from __future__ import annotations

import logging

import generate_registry
from registry import TASK_REGISTRY, load_registry


logger = logging.getLogger(__name__)
_registry_fingerprint: tuple[tuple[str, int, int], ...] | None = None


def _source_fingerprint() -> tuple[tuple[str, int, int], ...]:
    rows = []
    paths = generate_registry.REPO_ROOT.glob(generate_registry.WORKFLOWS_GLOB)
    for path in sorted(paths):
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append((path.as_posix(), stat.st_mtime_ns, stat.st_size))
    return tuple(rows)


def refresh_registry(*, force: bool = False) -> dict:
    """Refresh only when a workflow task configuration changed on disk."""
    global _registry_fingerprint
    fingerprint = _source_fingerprint()
    if not force and _registry_fingerprint == fingerprint:
        return TASK_REGISTRY
    try:
        generate_registry.main()
        load_registry()
        _registry_fingerprint = _source_fingerprint()
    except Exception as exc:
        logger.warning("Registry regeneration failed: %s", exc)
    return TASK_REGISTRY


_registry_fingerprint = _source_fingerprint()


def find_task(workflow: str, task_key: str) -> dict | None:
    workflow_def = TASK_REGISTRY.get(workflow)
    if not workflow_def:
        return None
    return next(
        (task for task in workflow_def["tasks"] if task["key"] == task_key),
        None,
    )
