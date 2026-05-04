#!/usr/bin/env python
"""Single launcher for harqis-work daemons (cross-platform).

Replaces the per-OS .bat / .sh / .ps1 wrappers under scripts/. Each subcommand
loads .env/apps.env, sets the standard env vars, then `os.execvp`s into the
real process so that the system service / Task Scheduler / launchd / systemd
manages the actual Python process directly (no extra wrapper PID).

Usage:
    python scripts/launch.py worker [--queues default,hud]
    python scripts/launch.py scheduler
    python scripts/launch.py flower
    python scripts/launch.py frontend
    python scripts/launch.py mcp
    python scripts/launch.py kanban [--profile agent:default] [--num-agents 1]

Helpers:
    python scripts/launch.py trigger-hud-tasks [--queue hud]
    python scripts/launch.py push-config  [--redis-url URL] [--key KEY]
    python scripts/launch.py serve-config [--port 8765]    [--token TOKEN]
    python scripts/launch.py print-env                      # for shell `source`

Background orchestration (start multiple, manage PIDs) is in scripts/deploy.py.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
ENV_FILE = REPO_ROOT / ".env" / "apps.env"
VENV_PY = (
    REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt"
    else REPO_ROOT / ".venv" / "bin" / "python"
)


# ── Environment loading ───────────────────────────────────────────────────────

def load_env_file(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse a KEY=VALUE .env file and return the dict (does not mutate os.environ)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[key] = value
    return out


def setup_env() -> None:
    """Idempotent env setup: load apps.env, set PYTHONPATH and standard vars."""
    for key, value in load_env_file().items():
        os.environ.setdefault(key, value)

    pythonpath_parts = [str(REPO_ROOT), str(SCRIPTS_DIR)]
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        pythonpath_parts.append(existing)
    sep = ";" if os.name == "nt" else ":"
    os.environ["PYTHONPATH"] = sep.join(pythonpath_parts)

    os.environ.setdefault("ROOT_DIRECTORY", str(REPO_ROOT))
    os.environ.setdefault("PATH_APP_CONFIG", str(REPO_ROOT))
    os.environ.setdefault("PATH_APP_CONFIG_SECRETS", str(REPO_ROOT / ".env"))
    os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
    os.environ.setdefault("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672/")
    os.environ.setdefault("CONFIG_SOURCE", "local")


def _python() -> str:
    """Path to the venv Python (falls back to current interpreter if no venv)."""
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def _exec(*argv: str) -> None:
    """Replace the current process with the given command. Never returns."""
    os.execvp(argv[0], list(argv))


# ── Subcommand implementations ────────────────────────────────────────────────

def cmd_worker(args: argparse.Namespace) -> None:
    setup_env()
    if args.queues:
        os.environ["WORKFLOW_QUEUE"] = args.queues.replace(" ", "")
    os.environ.setdefault("WORKFLOW_QUEUE", "default")
    print(f"[launch] worker queues={os.environ['WORKFLOW_QUEUE']}", flush=True)
    _exec(_python(), str(REPO_ROOT / "run_workflows.py"), "worker")


def cmd_scheduler(args: argparse.Namespace) -> None:
    setup_env()
    print("[launch] scheduler (celery beat)", flush=True)
    _exec(_python(), str(REPO_ROOT / "run_workflows.py"), "scheduler")


def cmd_flower(args: argparse.Namespace) -> None:
    setup_env()
    user = os.environ.get("FLOWER_USER")
    password = os.environ.get("FLOWER_PASSWORD") or os.environ.get("FLOWER_PASS")
    if not user or not password:
        sys.exit("FLOWER_USER and FLOWER_PASSWORD must be set in .env/apps.env")
    port = os.environ.get("FLOWER_PORT", "5555")
    address = os.environ.get("FLOWER_ADDRESS", "127.0.0.1")
    print(f"[launch] flower {address}:{port} (auth: {user})", flush=True)
    _exec(
        _python(), "-m", "celery",
        "-A", "core.apps.sprout.app.celery:SPROUT", "flower",
        f"--port={port}", f"--address={address}",
        f"--basic-auth={user}:{password}",
    )


def cmd_frontend(args: argparse.Namespace) -> None:
    setup_env()
    sep = ";" if os.name == "nt" else ":"
    os.environ["PYTHONPATH"] = sep.join(
        [os.environ.get("PYTHONPATH", ""), str(REPO_ROOT / "frontend")]
    ).strip(sep)
    print("[launch] frontend (FastAPI)", flush=True)
    _exec(_python(), str(REPO_ROOT / "frontend" / "main.py"))


def cmd_mcp(args: argparse.Namespace) -> None:
    setup_env()
    print("[launch] mcp server", flush=True)
    _exec(_python(), str(REPO_ROOT / "mcp" / "server.py"))


def cmd_kanban(args: argparse.Namespace) -> None:
    setup_env()
    cli = [_python(), "-m", "agents.projects.orchestrator.local"]
    num = args.num_agents or os.environ.get("KANBAN_NUM_AGENTS")
    if num:
        cli += ["--num-agents", str(num)]
    if (poll := os.environ.get("KANBAN_POLL_INTERVAL")):
        cli += ["--poll-interval", poll]
    if (pdir := os.environ.get("KANBAN_PROFILES_DIR")):
        cli += ["--profiles-dir", pdir]
    profile = args.profile or os.environ.get("KANBAN_PROFILE_FILTER")
    if profile:
        cli += ["--profile", profile]
    if (oslab := os.environ.get("KANBAN_OS_LABELS")):
        cli += ["--os", oslab]
    if os.environ.get("KANBAN_DRY_RUN") == "1":
        cli += ["--dry-run"]
    print(f"[launch] kanban profile={profile or '(none)'}", flush=True)
    _exec(*cli)


def cmd_trigger_hud_tasks(args: argparse.Namespace) -> None:
    """Replaces run_hud_tasks.bat — fires HUD tasks via Flower's REST API.
    Flower creds come from FLOWER_USER / FLOWER_PASSWORD in .env/apps.env.
    """
    setup_env()
    user = os.environ.get("FLOWER_USER")
    password = os.environ.get("FLOWER_PASSWORD") or os.environ.get("FLOWER_PASS")
    if not user or not password:
        sys.exit("FLOWER_USER and FLOWER_PASSWORD must be set in .env/apps.env")
    cli = [
        _python(),
        str(REPO_ROOT / "workflows" / "n8n" / "utilities" / "send_flower_task.py"),
        "--send-all", "--queue", args.queue,
        "--user", user, "--password", password,
    ]
    _exec(*cli)


def cmd_push_config(args: argparse.Namespace) -> None:
    setup_env()
    if args.remote_broker_url:
        os.environ["CELERY_BROKER_URL"] = args.remote_broker_url
    cli = [_python(), "-m", "apps.config_remote", "push-redis"]
    if args.redis_url:
        cli += ["--redis-url", args.redis_url]
    if args.key:
        cli += ["--key", args.key]
    _exec(*cli)


def cmd_serve_config(args: argparse.Namespace) -> None:
    setup_env()
    if args.remote_broker_url:
        os.environ["CELERY_BROKER_URL"] = args.remote_broker_url
    cli = [_python(), "-m", "apps.config_remote", "serve-http"]
    if args.port:
        cli += ["--port", str(args.port)]
    if args.token:
        cli += ["--token", args.token]
    if args.host:
        cli += ["--host", args.host]
    _exec(*cli)


def cmd_print_env(args: argparse.Namespace) -> None:
    """Print KEY=VALUE lines for shell sourcing.

    Bash:        eval "$(python scripts/launch.py print-env)"
    PowerShell:  python scripts/launch.py print-env | ForEach-Object {
                     $k,$v = $_ -split '=',2; Set-Item "Env:$k" $v }
    """
    setup_env()
    keys = (
        "PYTHONPATH ROOT_DIRECTORY PATH_APP_CONFIG PATH_APP_CONFIG_SECRETS "
        "WORKFLOW_CONFIG APP_CONFIG_FILE CELERY_BROKER_URL CONFIG_SOURCE"
    ).split()
    for key in keys:
        if key in os.environ:
            print(f'{key}={os.environ[key]}')


# ── CLI wiring ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Single launcher for harqis-work daemons.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("worker", help="Celery worker")
    w.add_argument("-q", "--queues", help="Comma-separated queue list (default: $WORKFLOW_QUEUE or 'default')")
    w.set_defaults(func=cmd_worker)

    s = sub.add_parser("scheduler", help="Celery Beat scheduler")
    s.set_defaults(func=cmd_scheduler)

    f = sub.add_parser("flower", help="Celery Flower monitor")
    f.set_defaults(func=cmd_flower)

    fe = sub.add_parser("frontend", help="FastAPI frontend dashboard")
    fe.set_defaults(func=cmd_frontend)

    m = sub.add_parser("mcp", help="MCP server (stdio)")
    m.set_defaults(func=cmd_mcp)

    k = sub.add_parser("kanban", help="Kanban orchestrator")
    k.add_argument("-p", "--profile", help="Profile filter (e.g. agent:default)")
    k.add_argument("--num-agents", type=int, help="Concurrent in-process agents")
    k.set_defaults(func=cmd_kanban)

    t = sub.add_parser("trigger-hud-tasks", help="Fire all HUD tasks via Flower REST")
    t.add_argument("--queue", default="hud", help="Queue to send to (default: hud)")
    t.set_defaults(func=cmd_trigger_hud_tasks)

    pc = sub.add_parser("push-config", help="Push resolved config to Redis (host)")
    pc.add_argument("--redis-url", help="Redis URL (default: env CONFIG_REDIS_URL)")
    pc.add_argument("--key", help="Redis key (default: env CONFIG_REDIS_KEY)")
    pc.add_argument("--remote-broker-url", help="Override CELERY_BROKER_URL for the pushed dict")
    pc.set_defaults(func=cmd_push_config)

    sc = sub.add_parser("serve-config", help="Serve resolved config over HTTP (host)")
    sc.add_argument("--port", type=int, help="Port (default: env CONFIG_SERVER_PORT or 8765)")
    sc.add_argument("--token", help="Bearer token (default: env CONFIG_SERVER_TOKEN)")
    sc.add_argument("--host", default="0.0.0.0", help="Bind address")
    sc.add_argument("--remote-broker-url", help="Override CELERY_BROKER_URL for the served dict")
    sc.set_defaults(func=cmd_serve_config)

    e = sub.add_parser("print-env", help="Print env vars for shell sourcing")
    e.set_defaults(func=cmd_print_env)

    return p


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
