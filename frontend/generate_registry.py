#!/usr/bin/env python3
"""
Generate frontend/registry.py from workflows/*/tasks_config.py.

For each workflow, the generator:
  - Pulls task_path, queue, and kwargs from tasks_config.py   (always authoritative)
  - Preserves label, description, schedule, manual_only from  the existing registry.py
  - Keeps manual-only tasks that have no beat schedule entry
  - Auto-generates a label and schedule string for brand-new tasks

Usage (from repo root):
    python frontend/generate_registry.py

Requirements:
    - Run with the repo venv active (needs celery for crontab/timedelta imports)
    - Run from the repo root directory
"""
import importlib
import importlib.util
import sys
from datetime import timedelta
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).resolve().parent.parent
FRONTEND_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(FRONTEND_DIR))

from celery.schedules import crontab  # noqa: E402 — needs sys.path above

# ── Workflow source config ────────────────────────────────────────────────────
# Defines which tasks_config variable maps to which dashboard workflow tab.
# Update this dict when adding a new workflow to the dashboard.
WORKFLOW_SOURCES = {
    "hud": {
        "module":      "workflows/hud/tasks_config.py",
        "var":         "WORKFLOWS_HUD",
        "label":       "HUD",
        "color":       "blue",
        "description": "Desktop heads-up display — Rainmeter widgets for forex, calendar, budgets, and TCG orders.",
    },
    "purchases": {
        "module":      "workflows/purchases/tasks_config.py",
        "var":         "WORKFLOW_PURCHASES",
        "label":       "Purchases",
        "color":       "emerald",
        "description": "MTG card resale pipeline — Scryfall bulk data → listings → price updates → order audit.",
    },
    "desktop": {
        "module":      "workflows/desktop/tasks_config.py",
        "var":         "WORKFLOWS_DESKTOP",
        "label":       "Desktop",
        "color":       "violet",
        "description": "Windows desktop automation — git pulls, window management, file sync, and activity capture.",
    },
}


# ── Schedule → human-readable string ─────────────────────────────────────────

def schedule_to_str(schedule) -> str:
    """Convert a Celery timedelta or crontab to a short human-readable string."""
    if isinstance(schedule, timedelta):
        total = int(schedule.total_seconds())
        if total < 60:
            return f"Every {total} sec"
        if total < 3600:
            return f"Every {total // 60} min"
        if total < 86400:
            return f"Every {total // 3600} hours"
        return f"Every {total // 86400} days"

    if isinstance(schedule, crontab):
        return _crontab_to_str(schedule)

    return repr(schedule)


def _detect_interval(values: frozenset) -> int | None:
    """Return the uniform step between sorted values, or None if irregular."""
    sv = sorted(values)
    if len(sv) < 2:
        return None
    diffs = {sv[i + 1] - sv[i] for i in range(len(sv) - 1)}
    return diffs.pop() if len(diffs) == 1 else None


def _crontab_to_str(c: crontab) -> str:
    all_min = frozenset(range(60))
    all_hr  = frozenset(range(24))
    all_dow = frozenset(range(7))
    all_dom = frozenset(range(1, 32))

    mins  = c.minute
    hours = c.hour
    dow   = c.day_of_week
    dom   = c.day_of_month

    DOW_NAMES = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}
    WEEKDAYS  = frozenset({1, 2, 3, 4, 5})

    # ── Day-of-month (e.g. 1st of month at 2am) ──────────────────────────────
    if dom != all_dom:
        d      = sorted(dom)[0]
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(d if d <= 20 else d % 10, "th")
        h      = sorted(hours)[0] if len(hours) == 1 else 0
        m      = sorted(mins)[0]  if len(mins)  == 1 else 0
        t      = f"{h}am" if m == 0 and h < 12 else f"{h:02d}:{m:02d}"
        return f"{d}{suffix} of month at {t}"

    # ── Specific day(s) of week ───────────────────────────────────────────────
    if dow != all_dow:
        if dow == WEEKDAYS:
            day_str = "Mon–Fri"
        elif dow == frozenset({0, 6}):
            day_str = "Weekends"
        else:
            day_str = "/".join(DOW_NAMES[d] for d in sorted(dow))

        if hours == all_hr:
            interval = _detect_interval(mins)
            if interval:
                return f"Every {interval} min ({day_str})"

        if len(hours) == 1 and len(mins) == 1:
            h, m = sorted(hours)[0], sorted(mins)[0]
            return f"{day_str} at {h:02d}:{m:02d}"

        return f"Scheduled ({day_str})"

    # ── Every minute ─────────────────────────────────────────────────────────
    if mins == all_min and hours == all_hr:
        return "Every minute"

    # ── Interval minutes (e.g. */15 → {0,15,30,45}) ──────────────────────────
    if hours == all_hr:
        if len(mins) == 1:
            m = sorted(mins)[0]
            return "Every hour" if m == 0 else f"Hourly at :{m:02d}"
        interval = _detect_interval(mins)
        if interval:
            return f"Every {interval} min"

    # ── Multiple specific hours with single minute ────────────────────────────
    if len(mins) == 1 and len(hours) > 1:
        interval = _detect_interval(hours)
        if interval:
            return f"Every {interval} hours"

    # ── Single hour — daily ───────────────────────────────────────────────────
    if len(hours) == 1 and len(mins) == 1:
        h, m = sorted(hours)[0], sorted(mins)[0]
        if m == 0:
            if h == 0:
                return "Daily at midnight"
            return f"Daily at {h}am" if h < 12 else f"Daily at {h:02d}:00"
        return f"Daily at {h:02d}:{m:02d}"

    return repr(c)


# ── Metadata helpers ──────────────────────────────────────────────────────────

def _label_from_key(key: str) -> str:
    """snake_case → Title Case label for new tasks."""
    return key.replace("_", " ").title()


def _load_existing_registry() -> dict:
    """Import the current registry.py and return TASK_REGISTRY (or {} on failure)."""
    mod_name = "registry"
    sys.modules.pop(mod_name, None)
    try:
        mod = importlib.import_module(mod_name)
        return getattr(mod, "TASK_REGISTRY", {})
    except Exception as exc:
        print(f"  Warning: could not load existing registry.py ({exc}) — starting fresh.")
        return {}


# ── Registry builder ──────────────────────────────────────────────────────────

def build_registry() -> dict:
    existing = _load_existing_registry()
    registry = {}

    for wf_key, wf_cfg in WORKFLOW_SOURCES.items():
        mod_path = REPO_ROOT / wf_cfg["module"]
        spec     = importlib.util.spec_from_file_location(f"_tasks_cfg_{wf_key}", mod_path)
        mod      = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        beat_dict = getattr(mod, wf_cfg["var"])  # type: dict

        existing_wf    = existing.get(wf_key, {})
        existing_tasks = {t["key"]: t for t in existing_wf.get("tasks", [])}

        # Tasks sourced from tasks_config.py
        scheduled_keys: set[str] = set()
        tasks = []

        for beat_key, beat_val in beat_dict.items():
            if not beat_key.startswith("run-job--"):
                continue

            task_key  = beat_key.removeprefix("run-job--")
            task_path = beat_val["task"]
            queue     = beat_val.get("options", {}).get("queue", "default")
            kwargs    = beat_val.get("kwargs", {})
            schedule  = beat_val.get("schedule")

            prev = existing_tasks.get(task_key, {})
            scheduled_keys.add(task_key)

            tasks.append({
                "key":         task_key,
                "label":       prev.get("label",       _label_from_key(task_key)),
                "task_path":   task_path,                                           # always overwrite
                "queue":       queue,                                                # always overwrite
                "schedule":    prev.get("schedule",    schedule_to_str(schedule) if schedule else "Manual only"),
                "kwargs":      kwargs,                                               # always overwrite
                "description": prev.get("description", ""),
                "manual_only": prev.get("manual_only", False),
            })

        # Preserve manual-only tasks not in the beat schedule
        for task_key, task in existing_tasks.items():
            if task_key not in scheduled_keys:
                tasks.append(task)
                print(f"  [{wf_key}] Preserved manual task: {task_key}")

        # Report new tasks
        for t in tasks:
            if t["key"] not in existing_tasks:
                print(f"  [{wf_key}] New task detected:      {t['key']}")

        registry[wf_key] = {
            "label":       existing_wf.get("label",       wf_cfg["label"]),
            "color":       existing_wf.get("color",       wf_cfg["color"]),
            "description": existing_wf.get("description", wf_cfg["description"]),
            "tasks":       tasks,
        }

    return registry


# ── Code renderer ─────────────────────────────────────────────────────────────

def render_registry(registry: dict) -> str:
    """Render the registry dict as a valid Python source file."""
    lines = [
        '"""',
        'Static task registry built from workflows/*/tasks_config.py definitions.',
        'Each workflow maps to a dict of tasks with their Celery path, queue, schedule, and default kwargs.',
        '',
        'AUTO-GENERATED by frontend/generate_registry.py',
        'Run `python frontend/generate_registry.py` after adding or changing tasks in workflows/*/tasks_config.py.',
        '"""',
        'from typing import TypedDict',
        '',
        '',
        'class TaskDef(TypedDict):',
        '    key: str',
        '    label: str',
        '    task_path: str',
        '    queue: str',
        '    schedule: str',
        '    kwargs: dict',
        '    description: str',
        '    manual_only: bool',
        '',
        '',
        'class WorkflowDef(TypedDict):',
        '    label: str',
        '    color: str           # tailwind color name: blue | emerald | violet',
        '    description: str',
        '    tasks: list[TaskDef]',
        '',
        '',
        'TASK_REGISTRY: dict[str, WorkflowDef] = {',
    ]

    sep = "─" * 74
    for wf_key, wf in registry.items():
        lines += [
            '',
            f'    # {sep}',
            f'    # {wf["label"].upper():<12}  {wf["description"]}',
            f'    # {sep}',
            f'    {repr(wf_key)}: {{',
            f'        "label":       {repr(wf["label"])},',
            f'        "color":       {repr(wf["color"])},',
            f'        "description": {repr(wf["description"])},',
            f'        "tasks": [',
        ]
        for task in wf["tasks"]:
            lines += [
                f'            {{',
                f'                "key":         {repr(task["key"])},',
                f'                "label":       {repr(task["label"])},',
                f'                "task_path":   {repr(task["task_path"])},',
                f'                "queue":       {repr(task["queue"])},',
                f'                "schedule":    {repr(task["schedule"])},',
                f'                "kwargs":      {repr(task["kwargs"])},',
                f'                "description": {repr(task["description"])},',
                f'                "manual_only": {repr(task["manual_only"])},',
                f'            }},',
            ]
        lines += [
            '        ],',
            '    },',
        ]

    lines += ['}', '']
    return '\n'.join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    out_path = FRONTEND_DIR / "registry.py"

    print("Generating frontend/registry.py from tasks_config.py files...")
    registry = build_registry()

    total = sum(len(wf["tasks"]) for wf in registry.values())
    print(f"  Workflows: {len(registry)}  |  Tasks: {total}")

    source   = render_registry(registry)
    existing = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    if source == existing:
        print("  registry.py is up to date.")
        return
    out_path.write_text(source, encoding="utf-8")
    print(f"  Written -> {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
