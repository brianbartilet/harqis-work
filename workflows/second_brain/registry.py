"""Code-owned operation allowlist and complete HUD migration inventory."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    collector: str
    label: str = ""
    refresh_minutes: int = 15
    kwargs: dict[str, Any] = field(default_factory=dict)
    advisory_only: bool = True
    eligible: bool = True
    reason: str = ""


OPERATIONS = {
    "jira.changed": OperationSpec(
        operation_id="jira.changed",
        label="Recently changed Jira tickets",
        collector="workflows.second_brain.collectors.jira.collect_jira_changed",
        refresh_minutes=15,
    ),
}


def operation_catalog() -> list[dict[str, Any]]:
    catalog = [asdict(spec) for spec in OPERATIONS.values()]
    known_paths = {spec.collector for spec in OPERATIONS.values()}
    tasks_root = Path(__file__).resolve().parents[1] / "hud" / "tasks"
    try:
        for source in tasks_root.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            module = f"workflows.hud.tasks.{source.stem}"
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                has_meter = any(
                    isinstance(decorator, ast.Call)
                    and isinstance(decorator.func, ast.Name)
                    and decorator.func.id == "init_meter"
                    for decorator in node.decorator_list
                )
                task_path = f"{module}.{node.name}"
                if not has_meter or task_path in known_paths or node.name == "render_second_brain_rainmeter":
                    continue
                name = node.name
                known_paths.add(task_path)
                catalog.append(
                    asdict(
                        OperationSpec(
                            operation_id=f"hud.{source.stem}.{name}",
                            label=name.replace("_", " ").title(),
                            collector="",
                            eligible=False,
                            reason="Legacy HUD task inventoried; explicit read-only normalization adapter required.",
                        )
                    )
                )
    except Exception:
        pass
    return sorted(catalog, key=lambda value: (not value["eligible"], value["label"]))


def selected_operations(
    mode_ids: tuple[str, ...], mode_definitions: list[dict[str, Any]]
) -> tuple[tuple[OperationSpec, tuple[str, ...], int], ...]:
    attached: dict[str, list[str]] = {}
    refresh: dict[str, int] = {}
    selected = set(mode_ids)
    for mode in mode_definitions:
        if mode.get("mode_id") not in selected or mode.get("archived") or not mode.get("enabled", True):
            continue
        for operation_id in mode.get("operation_ids") or []:
            if operation_id in OPERATIONS:
                attached.setdefault(operation_id, []).append(mode["mode_id"])
                refresh[operation_id] = min(
                    refresh.get(operation_id, 1440),
                    int(mode.get("refresh_minutes") or OPERATIONS[operation_id].refresh_minutes),
                )
    return tuple(
        (OPERATIONS[operation_id], tuple(categories), refresh[operation_id])
        for operation_id, categories in attached.items()
    )
