"""
Task registry — workflows + tasks consumed by the dashboard.

Backed by `frontend/registry.json` (gitignored — regenerated locally by
`frontend/generate_registry.py`). The JSON file is the source of truth at
runtime; this module loads it on import and exposes `TASK_REGISTRY` as a
mutable dict. Use `save_registry()` after mutating to persist changes.

Why JSON instead of a generated `.py`:
    The previous implementation wrote a frozen Python literal that needed
    a regenerate-and-restart cycle for every change. JSON lets the
    dashboard (or any caller) update labels/descriptions/manual_only
    flags at runtime and persist them with one call.

Consumers that did `from registry import TASK_REGISTRY` keep working —
the module attribute is the same dict object across the lifetime of the
process. `load_registry()` mutates the dict in place rather than
rebinding it, so existing references stay valid.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict


class TaskDef(TypedDict):
    key: str
    label: str
    task_path: str
    queue: str
    schedule: str
    kwargs: dict
    description: str
    manual_only: bool


class WorkflowDef(TypedDict):
    label: str
    color: str           # tailwind color name: blue | emerald | violet
    description: str
    tasks: list[TaskDef]


REGISTRY_JSON: Path = Path(__file__).with_name("registry.json")

TASK_REGISTRY: dict[str, WorkflowDef] = {}


def load_registry() -> dict[str, WorkflowDef]:
    """Read `registry.json` and replace `TASK_REGISTRY` contents in place.

    Mutating in place (clear + update) keeps `from registry import
    TASK_REGISTRY` references valid for callers who imported the symbol
    before the reload.
    """
    if not REGISTRY_JSON.exists():
        TASK_REGISTRY.clear()
        return TASK_REGISTRY
    with REGISTRY_JSON.open(encoding="utf-8") as f:
        data = json.load(f)
    TASK_REGISTRY.clear()
    TASK_REGISTRY.update(data)
    return TASK_REGISTRY


def save_registry(registry: dict[str, WorkflowDef] | None = None) -> Path:
    """Persist `registry` (default: the live TASK_REGISTRY) to `registry.json`.

    Returns the path written.
    """
    payload = TASK_REGISTRY if registry is None else registry
    REGISTRY_JSON.parent.mkdir(parents=True, exist_ok=True)
    with REGISTRY_JSON.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return REGISTRY_JSON


# Populate on import so `from registry import TASK_REGISTRY` works as before.
load_registry()
