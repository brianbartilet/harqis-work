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
    source_task: str = ""


def _hud_operation(
    operation_id: str,
    label: str,
    source_task: str,
    *,
    refresh_minutes: int = 15,
    stale_after_minutes: int = 60,
    priority: int = 55,
    sensitivity: str = "internal",
) -> OperationSpec:
    return OperationSpec(
        operation_id=operation_id,
        label=label,
        collector="workflows.second_brain.hud_projection.collect_hud_projection",
        refresh_minutes=refresh_minutes,
        kwargs={
            "source_task": source_task,
            "operation_id": operation_id,
            "label": label,
            "stale_after_minutes": stale_after_minutes,
            "priority": priority,
            "sensitivity": sensitivity,
        },
        source_task=source_task,
    )


OPERATIONS = {
    "jira.changed": OperationSpec(
        operation_id="jira.changed",
        label="Recently changed Jira tickets",
        collector="workflows.second_brain.collectors.jira.collect_jira_changed",
        refresh_minutes=15,
    ),
    "hud.hud_api_costs.show_api_costs": _hud_operation(
        "hud.hud_api_costs.show_api_costs", "API costs",
        "workflows.hud.tasks.hud_api_costs.show_api_costs",
        refresh_minutes=60, stale_after_minutes=180, priority=58, sensitivity="restricted",
    ),
    "hud.hud_calendar.show_calendar_information": _hud_operation(
        "hud.hud_calendar.show_calendar_information", "Calendar information",
        "workflows.hud.tasks.hud_calendar.show_calendar_information",
        stale_after_minutes=60, priority=70, sensitivity="restricted",
    ),
    "hud.hud_finance.show_pc_daily_sales": _hud_operation(
        "hud.hud_finance.show_pc_daily_sales", "PC daily sales",
        "workflows.hud.tasks.hud_finance.show_pc_daily_sales",
        refresh_minutes=60, stale_after_minutes=180, priority=62, sensitivity="restricted",
    ),
    "hud.hud_finance.show_ynab_budgets_info": _hud_operation(
        "hud.hud_finance.show_ynab_budgets_info", "YNAB budgets",
        "workflows.hud.tasks.hud_finance.show_ynab_budgets_info",
        refresh_minutes=60, stale_after_minutes=180, priority=68, sensitivity="restricted",
    ),
    "hud.hud_forex.show_forex_account": _hud_operation(
        "hud.hud_forex.show_forex_account", "Forex account",
        "workflows.hud.tasks.hud_forex.show_forex_account",
        stale_after_minutes=60, priority=72, sensitivity="restricted",
    ),
    "hud.hud_gpt.get_desktop_logs": _hud_operation(
        "hud.hud_gpt.get_desktop_logs", "Desktop logs",
        "workflows.hud.tasks.hud_gpt.get_desktop_logs",
        stale_after_minutes=30, priority=60, sensitivity="restricted",
    ),
    "hud.hud_gpt.get_events_world_check": _hud_operation(
        "hud.hud_gpt.get_events_world_check", "Events world check",
        "workflows.hud.tasks.hud_gpt.get_events_world_check",
        refresh_minutes=60, stale_after_minutes=240, priority=48,
    ),
    "hud.hud_jira.show_jira_board": _hud_operation(
        "hud.hud_jira.show_jira_board", "Jira board",
        "workflows.hud.tasks.hud_jira.show_jira_board",
        stale_after_minutes=60, priority=72, sensitivity="restricted",
    ),
    "hud.hud_logs.get_failed_jobs": _hud_operation(
        "hud.hud_logs.get_failed_jobs", "Failed jobs",
        "workflows.hud.tasks.hud_logs.get_failed_jobs", stale_after_minutes=45, priority=82,
    ),
    "hud.hud_logs.get_schedules": _hud_operation(
        "hud.hud_logs.get_schedules", "Schedules",
        "workflows.hud.tasks.hud_logs.get_schedules",
        refresh_minutes=30, stale_after_minutes=90, priority=52,
    ),
    "hud.hud_radar.refresh_hermes_radar": _hud_operation(
        "hud.hud_radar.refresh_hermes_radar", "Hermes radar refresh",
        "workflows.hud.tasks.hud_radar.refresh_hermes_radar",
        stale_after_minutes=30, priority=55, sensitivity="restricted",
    ),
    "hud.hud_radar.show_daily_radar": _hud_operation(
        "hud.hud_radar.show_daily_radar", "Daily radar",
        "workflows.hud.tasks.hud_radar.show_daily_radar",
        refresh_minutes=60, stale_after_minutes=780, priority=76, sensitivity="restricted",
    ),
    "hud.hud_tcg.show_tcg_orders": _hud_operation(
        "hud.hud_tcg.show_tcg_orders", "TCG orders",
        "workflows.hud.tasks.hud_tcg.show_tcg_orders",
        refresh_minutes=30, stale_after_minutes=120, priority=65, sensitivity="restricted",
    ),
    "hud.hud_tcg.show_tcg_sell_cart": _hud_operation(
        "hud.hud_tcg.show_tcg_sell_cart", "TCG sell cart",
        "workflows.hud.tasks.hud_tcg.show_tcg_sell_cart",
        refresh_minutes=30, stale_after_minutes=120, priority=64, sensitivity="restricted",
    ),
    "hud.hud_utils.show_ahk_bindings": _hud_operation(
        "hud.hud_utils.show_ahk_bindings", "AHK bindings",
        "workflows.hud.tasks.hud_utils.show_ahk_bindings",
        refresh_minutes=60, stale_after_minutes=1440, priority=35,
    ),
    "hud.hud_utils.show_ai_helper": _hud_operation(
        "hud.hud_utils.show_ai_helper", "AI helper",
        "workflows.hud.tasks.hud_utils.show_ai_helper",
        stale_after_minutes=60, priority=52, sensitivity="restricted",
    ),
    "hud.hud_utils.show_hud_profiles": _hud_operation(
        "hud.hud_utils.show_hud_profiles", "HUD profiles",
        "workflows.hud.tasks.hud_utils.show_hud_profiles",
        refresh_minutes=60, stale_after_minutes=1440, priority=30,
    ),
    "hud.hud_utils.show_mouse_bindings": _hud_operation(
        "hud.hud_utils.show_mouse_bindings", "Mouse bindings",
        "workflows.hud.tasks.hud_utils.show_mouse_bindings",
        refresh_minutes=60, stale_after_minutes=1440, priority=35,
    ),
}


def operation_catalog() -> list[dict[str, Any]]:
    catalog = [asdict(spec) for spec in OPERATIONS.values()]
    known_paths = {spec.source_task for spec in OPERATIONS.values() if spec.source_task}
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
