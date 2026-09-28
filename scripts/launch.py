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
    python scripts/launch.py hfl-api
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
import glob
import os
import shelve
import subprocess
import sys
import time
from collections.abc import Mapping
from contextlib import redirect_stdout
from pathlib import Path


# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
ENV_FILE = REPO_ROOT / ".env" / "apps.env"

if os.name == "nt":
    # Prefer pythonw.exe (windowless) over python.exe so daemons spawned via
    # `os.execvp` below don't pop up an empty console on Windows. The
    # console-mode override happens in `_python()` below — when deploy.py
    # launches us with --console (CREATE_NEW_CONSOLE), we exec to python.exe
    # instead so output flows to the visible window.
    _PYTHONW = REPO_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    _PYTHON_NT = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    VENV_PY = _PYTHONW if _PYTHONW.exists() else _PYTHON_NT
else:
    VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"


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


def _machine_env_vars() -> dict[str, str]:
    """Per-machine env_vars from machines.toml / machines.local.toml for this host.

    Resolved via deploy.py's machine-config loader (lazy import so this
    lightweight launcher stays independent of the orchestration layer at import
    time). Returns {} on any failure — a missing or malformed machines.toml, or
    a remote worker using CONFIG_SOURCE=redis/http, must never break startup.
    """
    try:
        if str(SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPTS_DIR))
        import deploy  # lazy, optional — the orchestration layer above us
        return deploy.machine_env_vars(deploy.load_machine_config(None))
    except Exception:
        return {}


def setup_env() -> None:
    """Idempotent env setup: load apps.env, set PYTHONPATH and standard vars.

    apps.env values override any inherited shell env — the repo's pinned
    config is the source of truth for daemons. Per-machine env_vars from
    machines.toml/.local.toml are then layered on top (they win over apps.env).
    Defaults below (PYTHONPATH, ROOT_DIRECTORY, etc.) stay `setdefault` since
    they're last-resort fallbacks, not overrides.
    """
    for key, value in load_env_file().items():
        os.environ[key] = value

    # Per-machine env_vars (machines.toml / machines.local.toml) win over the
    # shared apps.env. These are deploy-topology values — local paths, ports,
    # hostnames — that legitimately differ per machine. Applying them here, at
    # the one chokepoint every daemon passes through, means: (a) a manually
    # launched daemon gets them too, not only deploy.py-spawned ones; and (b) a
    # stale apps.env duplicate can never clobber the per-machine value (the bug
    # that fed the Mac worker a Windows Scryfall path). Precedence:
    # machine_env_vars > apps.env > inherited shell.
    # See docs/info/WORKER-CONFIG-DISTRIBUTION.md §3.
    for key, value in _machine_env_vars().items():
        os.environ[key] = value

    # Pin cwd to repo root: core's file loader (IFileLoader) walks up from
    # os.getcwd() looking for apps_config.yaml. When launchd / a service /
    # the user's shell starts us elsewhere (e.g. $HOME), the search misses
    # the repo and the celery `-A` import fails with FileNotFoundError.
    try:
        os.chdir(REPO_ROOT)
    except OSError:
        pass

    pythonpath_parts = [str(REPO_ROOT), str(SCRIPTS_DIR)]
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        pythonpath_parts.append(existing)
    sep = ";" if os.name == "nt" else ":"
    os.environ["PYTHONPATH"] = sep.join(pythonpath_parts)

    # PYTHONPATH only affects child interpreters. This launcher imports repo
    # modules before execing Celery, so update the live interpreter as well.
    for import_root in (str(SCRIPTS_DIR), str(REPO_ROOT)):
        if import_root not in sys.path:
            sys.path.insert(0, import_root)

    os.environ.setdefault("ROOT_DIRECTORY", str(REPO_ROOT))
    os.environ.setdefault("PATH_APP_CONFIG", str(REPO_ROOT))
    os.environ.setdefault("PATH_APP_CONFIG_SECRETS", str(REPO_ROOT / ".env"))
    os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
    os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
    os.environ.setdefault("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672/")
    os.environ.setdefault("CONFIG_SOURCE", "local")


def _has_attached_console() -> bool:
    """True iff a Windows console is attached to this process.

    Used to pick python.exe (visible-output mode) vs pythonw.exe
    (silent daemon mode) — the deploy.py --console flag launches us
    via CREATE_NEW_CONSOLE which attaches a window we should keep.
    """
    if os.name != "nt":
        return True
    try:
        import ctypes
        return ctypes.windll.kernel32.GetConsoleWindow() != 0
    except (OSError, AttributeError):
        return False


def _python() -> str:
    """Path to the venv Python (falls back to current interpreter if no venv).

    On Windows: python.exe when a console is attached (output flows to
    the visible window after os.execvp), else pythonw.exe so the daemon
    stays windowless.
    """
    if os.name != "nt":
        return str(VENV_PY) if VENV_PY.exists() else sys.executable
    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if _has_attached_console() and venv_python.exists():
        return str(venv_python)
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def _exec(*argv: str) -> None:
    """Replace the current process with the given command. Never returns."""
    os.execvp(argv[0], list(argv))


# ── Subcommand implementations ────────────────────────────────────────────────

def cmd_worker(args: argparse.Namespace) -> None:
    """Launch a celery worker.

    Bypasses sprout's `restart_celery_worker` (which hard-codes
    `pool=gevent`, `concurrency=10`) so we can pick the pool implementation
    per-host. The default `WORKFLOW_POOL=threads` is the safe choice on
    Windows: gevent greenlets block on win32 C calls (GetForegroundWindow,
    Rainmeter ini writes, etc.) and serialise the entire pool, while
    Python threads release the GIL across blocking syscalls and run truly
    in parallel for the I/O-bound HUD tasks.

    Override via env: `WORKFLOW_POOL=gevent|eventlet|prefork|solo` and
    `WORKFLOW_CONCURRENCY=<n>`. See celery's worker docs for caveats —
    `prefork` doesn't work well on Windows.
    """
    setup_env()
    if args.queues:
        os.environ["WORKFLOW_QUEUE"] = args.queues.replace(" ", "")
    os.environ.setdefault("WORKFLOW_QUEUE", "default")
    from workflows.queues import qualify_queues

    queues = qualify_queues(os.environ["WORKFLOW_QUEUE"])
    pool = args.pool or os.environ.get("WORKFLOW_POOL", "threads")
    concurrency = args.concurrency or os.environ.get("WORKFLOW_CONCURRENCY", "8")
    print(
        f"[launch] worker queues={queues} pool={pool} concurrency={concurrency}",
        flush=True,
    )
    _exec(
        _python(), "-m", "celery",
        "-A", "core.apps.sprout:SPROUT", "worker",
        "--loglevel=INFO",
        f"--queues={queues}",
        f"--pool={pool}",
        f"--concurrency={concurrency}",
        *([f"--hostname={args.hostname}"] if args.hostname else []),
    )


def cmd_worker_check(args: argparse.Namespace) -> None:
    """Read-only deployment postflight, in the same bootstrap as the worker."""
    setup_env()
    if args.queues:
        os.environ["WORKFLOW_QUEUE"] = args.queues.replace(" ", "")
    from celery.utils.nodenames import default_nodename, host_format
    from workflows.queues import qualify_queues
    from core.apps.sprout import SPROUT

    queues = qualify_queues(os.environ.get("WORKFLOW_QUEUE", "default")).split(",")
    node = host_format(default_nodename(args.hostname))
    wait_for_worker(SPROUT, node, queues)


def wait_for_worker(app, node: str, queues: list[str], *, timeout: float = 60) -> None:
    """Require this exact node's pong and every subscription, with bounded retry.

    Kombu Broadcast queues have ephemeral names; their stable identity is the
    configured fanout exchange, not the queue's alias or generated name.
    """
    expected = {}
    for name in queues:
        queue = app.amqp.queues[name]
        expected[name] = queue.exchange.name if queue.exchange.type == "fanout" else None
    if not expected:
        raise RuntimeError("Worker readiness requires at least one configured queue")
    deadline = time.monotonic() + timeout
    detail = "no local ping"
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            inspect = app.control.inspect(destination=[node], timeout=min(2, remaining / 2))
            pings = inspect.ping() or {}
            active = (inspect.active_queues() or {}).get(node, [])
            if pings.get(node, {}).get("ok") != "pong":
                detail = "no local ping"
            else:
                names = {item.get("name") for item in active}
                exchanges = {item["exchange"].get("name") for item in active
                             if isinstance(item.get("exchange"), dict)
                             and item["exchange"].get("type") == "fanout"}
                missing = [name for name, exchange in expected.items()
                           if (exchange not in exchanges if exchange else name not in names)]
                if not missing:
                    print(f"[health] worker={node} queues={','.join(queues)} verified", flush=True)
                    return
                detail = f"missing queues: {','.join(missing)}"
        except Exception as exc:
            # Broker URLs and credentials can occur in exception messages.
            detail = f"inspection failed ({type(exc).__name__})"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(2, remaining))
    raise RuntimeError(f"Worker readiness failed for {node}: {detail}")


def _beat_schedule_base() -> Path:
    """Return an instance-owned Beat state path when isolation is enabled."""
    if not os.environ.get("HARQIS_INSTANCE"):
        # Preserve the established upstream path until an instance opts in.
        return REPO_ROOT / "celerybeat-schedule"
    data_root = Path(os.environ.get("HARQIS_DATA_ROOT", REPO_ROOT / ".harqis-data"))
    schedule = data_root / "runtime" / "celerybeat-schedule"
    schedule.parent.mkdir(parents=True, exist_ok=True)
    return schedule


def _heal_beat_schedule() -> None:
    """Rotate a corrupt celerybeat-schedule aside so beat can self-recover.

    Why: the shelve is a pickle db of per-task last-run times. A SIGKILL
    landing mid-write (deploy stop → SIGTERM → SIGKILL escalation, which
    fires on every 4-hourly stack restart) truncates the pickle. On the
    NEXT start, Celery's PersistentScheduler does ``self._store['entries']``
    and dies with ``UnpicklingError: pickle data was truncated`` /
    ``KeyError: 'entries'`` — CRITICAL, process exits before it can log or
    write a pidfile. The scheduler then stays dead through every redeploy
    until a human clears the file. This probe breaks that permanent-death
    loop: read the shelve exactly the way Celery will; if it can't be
    unpickled or lacks a valid ``entries`` mapping, rename every matching file
    aside (kept, not deleted, for forensics) and let beat regenerate a fresh
    one. Healthy db: a few KB, probe is microseconds, no-op.
    """
    base = str(_beat_schedule_base())
    if not glob.glob(base + "*") and not os.path.exists(base):
        return  # fresh host — nothing to heal

    reason = ""
    try:
        db = shelve.open(base, flag="r")
        try:
            entries = db.get("entries", None)  # the exact key Celery unpickles
            if not isinstance(entries, Mapping):
                raise ValueError("missing or invalid 'entries' mapping")
            for key in db:                     # force-read every pickled value
                _ = db[key]
        finally:
            db.close()
    except Exception as exc:             # UnpicklingError, KeyError, dbm.error…
        reason = f"{type(exc).__name__}: {exc}"

    if not reason:
        return  # schedule db is readable — leave it alone

    stamp = time.strftime("%Y%m%d-%H%M%S")
    rotated = []
    for path in glob.glob(base + "*") or [base]:
        if not os.path.exists(path):
            continue
        dest = f"{path}.corrupt-{stamp}"
        try:
            os.rename(path, dest)
            rotated.append(os.path.basename(dest))
        except OSError as exc:
            print(f"[launch] scheduler: could not rotate {path}: {exc}",
                  flush=True)
    print(
        f"[launch] scheduler: corrupt celerybeat-schedule rotated aside "
        f"({reason}); beat will regenerate a fresh schedule. Kept: "
        f"{', '.join(rotated) or '(none)'}",
        flush=True,
    )


def cmd_scheduler(args: argparse.Namespace) -> None:
    setup_env()
    _heal_beat_schedule()
    print("[launch] scheduler (celery beat)", flush=True)
    _exec(
        _python(), "-m", "celery",
        "-A", "core.apps.sprout:SPROUT", "beat",
        "--loglevel=INFO",
        "--pidfile=",
        f"--schedule={_beat_schedule_base()}",
    )


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
        "-A", "core.apps.sprout:SPROUT", "flower",
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


def cmd_hfl_agent(args: argparse.Namespace) -> None:
    setup_env()
    if not os.environ.get("HFL_AGENT_BRIDGE_TOKEN", "").strip():
        sys.exit("HFL_AGENT_BRIDGE_TOKEN must be set before starting hfl-agent")
    runner = str(REPO_ROOT / "scripts" / "agents" / "hfl" / "agent_bridge_runner.py")
    subprocess.run([_python(), str(REPO_ROOT / 'scripts/agents/hfl/setup_agent_bridge.py'), '--apply'], check=True)
    print("[launch] HFL Hermes execution worker", flush=True)
    _exec(_python(), runner, "--watch")


def cmd_hfl_api(args: argparse.Namespace) -> None:
    setup_env()
    if not os.environ.get("HFL_CORPUS_API_TOKEN", "").strip():
        sys.exit("HFL_CORPUS_API_TOKEN must be set before starting hfl-api")
    sep = ";" if os.name == "nt" else ":"
    os.environ["PYTHONPATH"] = sep.join(
        [os.environ.get("PYTHONPATH", ""), str(REPO_ROOT / "frontend")]
    ).strip(sep)
    host = os.environ.get("HFL_API_HOST", "0.0.0.0")
    port = os.environ.get("HFL_API_PORT", "8082")
    print(f"[launch] hfl-api {host}:{port} (Swagger: /docs)", flush=True)
    _exec(_python(), str(REPO_ROOT / "frontend" / "hfl_api.py"))


def setup_mcp_env() -> None:
    """Load the machine API credentials/topology, retaining an explicit client filter."""
    enabled_apps = os.environ.get("MCP_ENABLED_APPS")
    setup_env()
    if enabled_apps is not None:
        os.environ["MCP_ENABLED_APPS"] = enabled_apps


def cmd_mcp(args: argparse.Namespace) -> None:
    # MCP owns stdout from the moment the client starts this command.
    with redirect_stdout(sys.stderr):
        setup_mcp_env()
    print("[launch] mcp server", file=sys.stderr, flush=True)
    # pythonw is appropriate for detached daemons, but MCP needs stdio pipes.
    interpreter = str(REPO_ROOT / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else _python()
    _exec(interpreter, str(REPO_ROOT / "mcp" / "server.py"))


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


def cmd_command_runner(args: argparse.Namespace) -> None:
    """Launch the n8n command-runner Flask server (workflows/n8n/utilities).

    n8n's `cmd` nodes POST shell commands to this server which executes them
    and returns stdout/stderr/exit-code. Binds RUNNER_HOST:RUNNER_PORT
    (default 0.0.0.0:5252) so the dockerised n8n can reach it at
    http://host.docker.internal:5252/run. Requires RUNNER_TOKEN in the
    environment (from .env/apps.env) — without it the server rejects every
    request.
    """
    setup_env()
    host = os.environ.get("RUNNER_HOST", "0.0.0.0")
    port = os.environ.get("RUNNER_PORT", "5252")
    print(
        f"[launch] n8n command-runner (Flask {host}:{port}; "
        f"n8n container -> http://host.docker.internal:{port}/run)",
        flush=True,
    )
    _exec(
        _python(),
        str(REPO_ROOT / "workflows" / "n8n" / "utilities" / "command_runner.py"),
    )


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
    w.add_argument("--pool", help="Celery pool override (default: $WORKFLOW_POOL or threads)")
    w.add_argument("--concurrency", help="Celery concurrency override")
    w.add_argument("--hostname", help="Explicit Celery worker hostname")
    w.set_defaults(func=cmd_worker)

    check = sub.add_parser("worker-check", help="Verify exact local worker ping and all queues (read-only)")
    check.add_argument("--queues", required=True)
    check.add_argument("--hostname", help="Same Celery hostname override as the worker")
    check.set_defaults(func=cmd_worker_check)

    s = sub.add_parser("scheduler", help="Celery Beat scheduler")
    s.set_defaults(func=cmd_scheduler)

    f = sub.add_parser("flower", help="Celery Flower monitor")
    f.set_defaults(func=cmd_flower)

    fe = sub.add_parser("frontend", help="FastAPI frontend dashboard")
    fe.set_defaults(func=cmd_frontend)

    agent = sub.add_parser("hfl-agent", help="HFL Hermes execution worker")
    agent.set_defaults(func=cmd_hfl_agent)
    ha = sub.add_parser("hfl-api", help="Standalone HFL Activity Corpus API")
    ha.set_defaults(func=cmd_hfl_api)

    m = sub.add_parser("mcp", help="MCP server (stdio)")
    m.set_defaults(func=cmd_mcp)

    cr = sub.add_parser("command-runner", help="n8n command-runner Flask server")
    cr.set_defaults(func=cmd_command_runner)

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
    sc.add_argument("--host", default="127.0.0.1",
                    help="Bind address (default 127.0.0.1; pass 0.0.0.0 only if remote workers need access)")
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
