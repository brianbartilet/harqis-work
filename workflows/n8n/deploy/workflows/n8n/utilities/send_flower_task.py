import argparse
import json
import importlib
from typing import Dict, List, Optional, Tuple

import requests


def _build_kwarg_dict(pairs: List[str]) -> Dict[str, str]:
    """
    Build kwargs dict from key="value" tokens.
    Matches your old behavior (string-only values; strips surrounding quotes).
    """
    kwarg_dict: Dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        value = value.strip().strip('"').strip("'")
        kwarg_dict[key] = value
    return kwarg_dict


def _load_celery_app(app_path: str):
    """
    app_path example: "core.apps.sprout.app.celery:SPROUT"
    """
    if ":" not in app_path:
        raise ValueError(
            'Celery app path must be "module:attr", e.g. core.apps.sprout.app.celery:SPROUT'
        )
    module_name, attr_name = app_path.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def _import_modules(modules: List[str]) -> None:
    """
    Import modules so tasks/register/routes are loaded (autodiscover may not run in CLI context).
    """
    for m in modules:
        importlib.import_module(m)


def _flower_async_apply(
    base_url: str,
    task_name: str,
    args: List[str],
    kwargs: Dict[str, str],
    auth: Optional[Tuple[str, str]] = None,
    timeout: int = 30,
) -> None:
    payload = {"args": args, "kwargs": kwargs}
    apply_url = f"{base_url}/task/async-apply/{task_name}"

    print(">> POST", apply_url)
    print(">> Payload:", json.dumps(payload))

    resp = requests.post(apply_url, json=payload, auth=auth, timeout=timeout)

    print("<< Status:", resp.status_code)
    try:
        print("<< JSON:", resp.json())
    except Exception:
        print("<< Text:", resp.text)
    print("-" * 60)


def _tasks_from_routes(app, queue_name: str) -> List[str]:
    """
    With your new config, the authoritative mapping is SPROUT.conf.task_routes.
    We use that to list tasks routed to queue_name.

    Supports:
      - dict routes: {"pattern.or.task": {"queue":"hud"}}
      - list/tuple of dicts (common in some setups)
    """
    routes = getattr(app.conf, "task_routes", None)
    patterns: List[str] = []

    if isinstance(routes, dict):
        for task_or_pattern, route in routes.items():
            if isinstance(route, dict) and route.get("queue") == queue_name:
                patterns.append(task_or_pattern)

    elif isinstance(routes, (list, tuple)):
        for r in routes:
            if isinstance(r, dict):
                for task_or_pattern, route in r.items():
                    if isinstance(route, dict) and route.get("queue") == queue_name:
                        patterns.append(task_or_pattern)

    if not patterns:
        return []

    # Ensure tasks are registered, then match registered task names against patterns.
    # Celery's task_routes supports glob patterns; we emulate with fnmatch.
    import fnmatch

    task_names = [name for name in app.tasks.keys() if not name.startswith("celery.")]
    matched: set[str] = set()

    for pat in patterns:
        # If it's an exact task name
        if pat in app.tasks:
            matched.add(pat)
            continue

        # If it's a glob-like pattern (e.g. workflows.hud.tasks.*)
        for t in task_names:
            if fnmatch.fnmatch(t, pat):
                matched.add(t)

    return sorted(matched)


def main():
    parser = argparse.ArgumentParser(description="Send task(s) to Flower API")

    # --- OLD BEHAVIOR (single task) ---
    parser.add_argument(
        "--task",
        help="Celery task full name, e.g. workflows.hud.tasks.hud_forex.show_forex_account",
    )
    parser.add_argument("--args", nargs="*", default=[], help="Positional arguments (space-separated).")
    parser.add_argument("--kwargs", nargs="*", default=[], help='Keyword args key="value" (space-separated).')

    parser.add_argument(
        "--url",
        default="http://localhost:5555/api",
        help="Flower API base URL, default http://localhost:5555/api",
    )
    parser.add_argument("--user", help="Flower basic auth user")
    parser.add_argument("--password", help="Flower basic auth password")

    # --- NEW: send all tasks routed to a queue (e.g. hud) using SPROUT.conf.task_routes ---
    parser.add_argument(
        "--send-all",
        action="store_true",
        help="Send all discovered tasks routed to a queue (see --queue).",
    )
    parser.add_argument(
        "--queue",
        default="hud",
        help="Queue name to filter on when using --send-all (default: hud).",
    )
    parser.add_argument(
        "--celery-app",
        default="core.apps.sprout.app.celery:SPROUT",
        help='Celery app import path in module:attr form. Default: core.apps.sprout.app.celery:SPROUT',
    )
    parser.add_argument(
        "--bootstrap-modules",
        nargs="*",
        default=[
            # This is the module that sets SPROUT.conf.task_routes and autodiscovers tasks
            # (based on your snippet). Update to your actual module path if different.
            "workflows.config",
        ],
        help=(
            "Modules to import so SPROUT.conf.task_routes and task discovery are loaded. "
            "Default includes workflows.config (change if your config module differs)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matched tasks but do not POST to Flower.",
    )

    parsed = parser.parse_args()

    auth = (parsed.user, parsed.password) if parsed.user and parsed.password else None
    kwarg_dict = _build_kwarg_dict(parsed.kwargs)

    # --- NEW MODE: send all ---
    if parsed.send_all:
        app = _load_celery_app(parsed.celery_app)

        # Import config/tasks modules so routes + registrations are present in this CLI process
        if parsed.bootstrap_modules:
            _import_modules(parsed.bootstrap_modules)

        tasks = _tasks_from_routes(app, parsed.queue)

        if not tasks:
            print(f"No tasks discovered routed to queue '{parsed.queue}'.")
            print("Tips:")
            print(" - Ensure your config module is imported via --bootstrap-modules")
            print(" - Confirm SPROUT.conf.task_routes includes the queue mapping")
            print(" - Ensure tasks are importable/registered (autodiscover_tasks may need the config module import)")
            return

        print(f"Discovered {len(tasks)} task(s) routed to queue '{parsed.queue}':")
        for t in tasks:
            print(" -", t)

        if parsed.dry_run:
            return

        for t in tasks:
            _flower_async_apply(parsed.url, t, parsed.args, kwarg_dict, auth=auth)

        return

    # --- OLD MODE: single task ---
    if not parsed.task:
        raise SystemExit("Missing --task (or use --send-all).")

    _flower_async_apply(parsed.url, parsed.task, parsed.args, kwarg_dict, auth=auth)


if __name__ == "__main__":
    main()
