#!/usr/bin/env python
"""Deploy the harqis-work platform on this machine (cross-platform).

Replaces scripts/sh/deploy.sh and scripts/ps/deploy.ps1. Reads per-machine
topology from machines.toml (at the repo root) so each host just runs:

    python scripts/deploy.py            # auto-detect from hostname
    python scripts/deploy.py --down

Override the auto-detection or add ad-hoc daemons via flags:

    python scripts/deploy.py --machine harqis-server
    python scripts/deploy.py --role host --queues tcg,peon,agent
    python scripts/deploy.py --role node --queues agent,worker
    python scripts/deploy.py --role host --no-mcp --no-kanban --no-flower

Single-instance mode (skip the full stack — run just one celery process):

    python scripts/deploy.py --scheduler                    # only Beat
    python scripts/deploy.py -c 4                           # only worker, concurrency=4
    python scripts/deploy.py -c 4 -q hud,peon               # only worker on hud+peon, c=4

In single-instance mode Docker is NOT touched (assumes the broker is already
reachable). --scheduler and -c/--concurrency are mutually exclusive.

Lifecycle:
    --down           Stop all services this machine launched
    --status         Show running services with PIDs
    --stop SERVICE   Stop one service (worker / scheduler / flower / ...)
    --register       Register every service as an OS auto-start unit
                     (launchd plist on macOS, systemd unit on Linux,
                      Scheduled Task on Windows). Idempotent.
    --unregister     Remove the OS auto-start units.

Notes:
- Docker compose is invoked only when --role host (workers don't run brokers).
- Each launched daemon is tracked in <repo>/.run/<service>.pid and logs to
  <repo>/logs/<service>.log. Stale PID files (process gone) are auto-cleaned.
- The actual per-service launch logic lives in scripts/launch.py.
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import socket
import subprocess
import sys
import time
import tomllib
from pathlib import Path


# ── Paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LAUNCH_PY = SCRIPTS_DIR / "launch.py"
MACHINES_TOML = REPO_ROOT / "machines.toml"
RUN_DIR = REPO_ROOT / ".run"
LOG_DIR = REPO_ROOT / "logs"
ENV_FILE = REPO_ROOT / ".env" / "apps.env"

if os.name == "nt":
    # Prefer pythonw.exe (windowless) over python.exe so spawned daemons
    # don't pop up empty console windows. Fall back to python.exe if pythonw
    # was stripped (some minimal venv setups).
    _PYTHONW = REPO_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    _PYTHON_NT = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    VENV_PY = _PYTHONW if _PYTHONW.exists() else _PYTHON_NT
else:
    VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LIN = sys.platform.startswith("linux")


# ── Service registry ──────────────────────────────────────────────────────────
# Maps service short-name → launch.py subcommand + which roles can run it.

SERVICES: dict[str, dict] = {
    # `console: True` means --console flips this service to a visible
    # window (CREATE_NEW_CONSOLE + python.exe + no log redirect). Use
    # for celery-backed daemons where you want to monitor live output;
    # closing the window terminates the daemon.
    "scheduler": {"cmd": ["scheduler"],         "roles": {"host"},         "console": True},
    "worker":    {"cmd": ["worker"],            "roles": {"host", "node"}, "console": True},
    "frontend":  {"cmd": ["frontend"],          "roles": {"host"}},
    # HARQIS MCP is a stdio server: clients (Hermes, Claude Desktop, etc.)
    # spawn it on demand and keep stdin/stdout attached. Running it as a
    # detached deploy daemon closes stdin immediately, so it exits cleanly
    # after registering tools and looks falsely "stopped" in status output.
    "mcp":       {"cmd": ["mcp"],               "roles": {"host"}, "mode": "stdio"},
    "kanban":    {"cmd": ["kanban"],            "roles": {"host", "node"}},
    "flower":    {"cmd": ["flower"],            "roles": {"host"}},
    # n8n `cmd` nodes POST shell commands here. Binds 0.0.0.0:5252 so the
    # dockerised n8n reaches it via host.docker.internal. Host-only: it sits
    # next to the n8n container / scheduler, not on worker nodes.
    "command-runner": {"cmd": ["command-runner"], "roles": {"host"}},
}


# ── Machine config ────────────────────────────────────────────────────────────

def _merge_machines(base: dict, override: dict) -> dict:
    """Recursively merge two machine-config dicts; override wins on key conflict.

    For non-dict values: override replaces base.
    For dict values: recurse — inner keys merge, all the way down.

    This is necessary so that e.g. a `[windows-work-all.env_vars]` table
    declared in machines.local.toml MERGES with (rather than REPLACES) a
    `[windows-work-all.env_vars]` table declared in machines.toml. Same
    machine block split across both files: each contributes its keys, the
    other inherits them.

    Tuples/lists are not deep-merged — they're values, override replaces them
    (so `queues = […]` in machines.local.toml fully overrides the upstream
    list, which is the documented behaviour for that field).
    """
    out = {**base}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_machines(out[key], value)
        else:
            out[key] = value
    return out


def load_machine_config(name: str | None) -> dict:
    """Resolve machine config from machines.toml + machines.local.toml at repo root.

    machines.local.toml is gitignored — host it yourself per machine to add
    real hostnames or override settings without leaking topology to the repo.

    Lookup order: explicit --machine name → hostname mapping → 'default' section.
    """
    if not MACHINES_TOML.exists():
        return {"role": "host", "queues": ["default"]}
    cfg = tomllib.loads(MACHINES_TOML.read_text(encoding="utf-8"))

    local_path = MACHINES_TOML.with_suffix(".local.toml")
    if local_path.exists():
        cfg = _merge_machines(cfg, tomllib.loads(local_path.read_text(encoding="utf-8")))

    if name is None:
        host = socket.gethostname()
        # macOS reports the hostname with original case (e.g.
        # "harqis-ones-Mac-mini.local") while [hostnames] keys are lowercase.
        # Exact match wins for back-compat; fall back to a case-insensitive hit.
        hostnames = cfg.get("hostnames", {})
        name = hostnames.get(host) or hostnames.get(host.lower(), "default")
    machine = cfg.get(name)
    if machine is None:
        machine = cfg.get("default", {"role": "host", "queues": ["default"]})
    # Attach the top-level [shared] block under `_shared` so callers can
    # resolve cluster-wide defaults (e.g. [shared.env_vars]) without
    # re-loading the file. Per-machine values still override shared ones —
    # the merge happens in the consumer (see machine_env_vars below).
    return {**machine, "_name": name, "_shared": cfg.get("shared", {})}


def machine_env_vars(machine: dict) -> dict[str, str]:
    """Resolve env vars to inject into daemons spawned for this machine.

    Source files: machines.toml + machines.local.toml (merged earlier in
    load_machine_config). Two tables contribute:

      [shared.env_vars]           cluster-wide defaults from machines.toml
      [<machine>.env_vars]        per-machine overrides from either file

    Per-machine values win on key conflict. TOML values are stringified
    because OS environment variables must be strings.

    Phase 0 of the apps.env → machines.toml migration: deploy.py injects the
    returned dict into the environment of every daemon it spawns via
    spawn_detached(extra_env=...). Daemons keep calling os.environ.get(...)
    and apps_config.yaml's ${PLACEHOLDER} resolver keeps working — they just
    see the TOML-sourced values in addition to (or in place of) what
    .env/apps.env provides. See docs/info/WORKER-CONFIG-DISTRIBUTION.md §3
    for the migration design and the env-injection mechanism.
    """
    shared = (machine.get("_shared") or {}).get("env_vars") or {}
    own = machine.get("env_vars") or {}
    merged = {**shared, **own}
    return {k: str(v) for k, v in merged.items()}


# ── Env loading (for docker-compose) ──────────────────────────────────────────

def load_env_into_os() -> None:
    """Load .env/apps.env into os.environ, overriding any inherited shell values.

    apps.env is the source of truth — a stale value exported in the invoking
    shell must not silently override the repo's pinned config (otherwise
    workers/scheduler can pick up wrong paths, creds, etc.).
    """
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[key] = value


# ── Process tracking ──────────────────────────────────────────────────────────

def pid_path(service: str) -> Path:
    return RUN_DIR / f"{service}.pid"


def log_path(service: str) -> Path:
    return LOG_DIR / f"{service}.log"


def is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WIN:
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, check=False,
            )
            return str(pid) in out.stdout
        except FileNotFoundError:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False


def read_pid(service: str) -> int | None:
    pf = pid_path(service)
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
    except (ValueError, OSError):
        return None
    if not is_alive(pid):
        pf.unlink(missing_ok=True)
        return None
    return pid


def _spawn_macos_console(
    cmd: list[str],
    pidfile: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> int:
    """macOS console mode: open a new Terminal.app window running cmd.

    AppleScript's `do script` runs in a fresh shell inside a new Terminal
    window. To recover the daemon's PID for --status/--down, we wrap the
    command in `echo $$ > <pidfile>; exec <cmd>`:
      - `$$` is the shell's PID (captured BEFORE exec)
      - `exec` replaces the shell process with the celery binary
      - so the PID written to pidfile === the running celery PID

    When `extra_env` is provided, each KEY=VALUE pair is prefixed as an
    `export` statement before `exec`. Necessary because the new Terminal
    shell starts fresh and does NOT inherit our process's environment —
    re-export is the only way to make machines.toml env_vars visible to
    the celery process.

    We poll pidfile for up to 5s while Terminal launches and the helper runs.
    """
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.unlink(missing_ok=True)

    quoted = " ".join(shlex.quote(c) for c in cmd)
    exports = ""
    if extra_env:
        exports = "".join(
            f"export {k}={shlex.quote(v)}; " for k, v in extra_env.items()
        )
    inner = f"echo $$ > {shlex.quote(str(pidfile))}; {exports}exec {quoted}"
    # AppleScript double-quoted string: escape \ and " inside the do-script body.
    escaped = inner.replace("\\", "\\\\").replace('"', '\\"')
    # Tag the tab via custom title so _close_macos_terminal_windows() can find
    # and close it later on redeploy / --down.
    title = f"harqis-work:{pidfile.stem}"
    osa = (
        'tell application "Terminal"\n'
        '    activate\n'
        f'    set newTab to do script "{escaped}"\n'
        f'    set custom title of newTab to "{title}"\n'
        'end tell'
    )

    subprocess.Popen(["osascript", "-e", osa], close_fds=True)

    deadline = time.time() + 5
    while time.time() < deadline:
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text().strip())
                if pid > 0:
                    return pid
            except (ValueError, OSError):
                pass
        time.sleep(0.1)
    raise RuntimeError(
        f"Timed out (5s) waiting for {pidfile} to be written by Terminal helper. "
        "Check that AppleScript is allowed to control Terminal "
        "(System Settings → Privacy & Security → Automation)."
    )


def _close_macos_terminal_windows(services: list[str] | None = None) -> None:
    """Close Terminal.app tabs tagged 'harqis-work:<service>' from prior deploys.

    Tabs are tagged at spawn time via `set custom title of newTab to ...`
    in `_spawn_macos_console`. Closing the tab terminates the running celery
    process inside it (Terminal sends the shell SIGHUP).

    `services=None` closes every harqis-work:* tab (broad pre-deploy sweep).
    `services=['scheduler']` closes only the scheduler's tab (per-service stop).
    """
    if not IS_MAC:
        return
    if services is None:
        cond = '(tabTitle starts with "harqis-work:")'
    else:
        wanted = ' or '.join(f'(tabTitle is "harqis-work:{s}")' for s in services)
        cond = f'({wanted})'
    osa = (
        'tell application "Terminal"\n'
        '    set targets to {}\n'
        '    repeat with w in windows\n'
        '        repeat with t in tabs of w\n'
        '            try\n'
        '                set tabTitle to custom title of t\n'
        f'                if {cond} then\n'
        '                    set end of targets to t\n'
        '                end if\n'
        '            end try\n'
        '        end repeat\n'
        '    end repeat\n'
        '    repeat with t in targets\n'
        '        try\n'
        '            close t saving no\n'
        '        end try\n'
        '    end repeat\n'
        'end tell\n'
    )
    subprocess.run(
        ["osascript", "-e", osa],
        capture_output=True, text=True, check=False,
    )


def spawn_detached(
    cmd: list[str],
    log_file: Path,
    *,
    show_console: bool = False,
    pidfile: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> int:
    """Spawn a long-running process detached from this terminal. Returns its PID.

    `show_console=False` (default) — windowless daemon, stdio → log_file.
    `show_console=True` — visible window, stdio inherits the new window.

    `extra_env` — optional dict of KEY=VALUE pairs to inject into the child
    process's environment. These values win over anything subsequently
    loaded by dotenv inside the child (apps.env is loaded with
    override=False). Source: machine_env_vars(machine) — see Phase 0 of the
    apps.env → machines.toml migration in
    docs/info/WORKER-CONFIG-DISTRIBUTION.md §3.

    Per-platform behaviour for `show_console=True`:
      - **Windows:** CREATE_NEW_CONSOLE allocates a new console window.
        Closing the window terminates the daemon.
      - **macOS:** new Terminal.app window via `osascript`. Requires `pidfile`
        so the helper can write the celery PID (Terminal-spawned processes
        aren't direct children of this script). First run will prompt for
        Automation permission to control Terminal.app.
      - **Linux:** no portable new-window mechanism (gnome-terminal vs
        konsole vs xterm vs ...). Falls back to inheriting the current
        terminal's stdio. Run via `tmux new-session 'python scripts/deploy.py
        --console …'` if you want isolation.

    CREATE_NEW_PROCESS_GROUP / start_new_session detach the child from this
    terminal's signal group so Ctrl-C here doesn't kill the daemon.
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Compose the child's environment. When extra_env is empty we pass
    # env=None so subprocess inherits our env unchanged (the cheap path).
    env = {**os.environ, **extra_env} if extra_env else None

    if show_console and IS_MAC:
        if pidfile is None:
            raise ValueError("Mac console mode requires pidfile= for PID capture")
        # AppleScript Terminal can't inherit our env; _spawn_macos_console
        # injects extra_env via `export KEY=VAL` prefixes instead.
        return _spawn_macos_console(cmd, pidfile, extra_env=extra_env)

    if IS_WIN:
        if show_console:
            flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(cmd, creationflags=flags, close_fds=True, env=env)
        else:
            fout = open(log_file, "ab")
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL, stdout=fout, stderr=subprocess.STDOUT,
                creationflags=flags, close_fds=True, env=env,
            )
    else:
        if show_console:
            proc = subprocess.Popen(cmd, start_new_session=True, close_fds=True, env=env)
        else:
            fout = open(log_file, "ab")
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL, stdout=fout, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, env=env,
            )
    return proc.pid


def stop_pid(pid: int, service: str) -> bool:
    if not is_alive(pid):
        return False
    try:
        if IS_WIN:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, check=False,
            )
        else:
            os.kill(pid, 15)  # SIGTERM
            for _ in range(20):
                if not is_alive(pid):
                    break
                time.sleep(0.25)
            if is_alive(pid):
                os.kill(pid, 9)  # SIGKILL
        return True
    except OSError:
        return False
    finally:
        pid_path(service).unlink(missing_ok=True)


def python_exe(*, console: bool = False) -> str:
    """Resolve the venv python interpreter.

    On Windows: pythonw.exe by default (windowless daemon), python.exe when
    console=True so the spawned process can write to its CREATE_NEW_CONSOLE
    window. On Unix the choice is irrelevant — single python binary.
    """
    if not IS_WIN or not console:
        return str(VENV_PY) if VENV_PY.exists() else sys.executable
    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


# ── Service start / stop ──────────────────────────────────────────────────────

def _service_uses_console(service: str, args: argparse.Namespace) -> bool:
    """True iff this service should launch in a visible console window."""
    return bool(getattr(args, "console", False)) and SERVICES[service].get("console", False)


def _service_is_stdio(service: str) -> bool:
    """True iff the service is an on-demand stdio endpoint, not a daemon."""
    return SERVICES.get(service, {}).get("mode") == "stdio"


def build_service_cmd(service: str, machine: dict, args: argparse.Namespace) -> list[str]:
    use_console = _service_uses_console(service, args)
    base = [python_exe(console=use_console), str(LAUNCH_PY), *SERVICES[service]["cmd"]]
    if service == "worker":
        queues = args.queues or ",".join(machine.get("queues", ["default"]))
        base += ["--queues", queues]
    elif service == "kanban":
        profile = args.profile or machine.get("kanban_profile")
        if profile:
            base += ["--profile", profile]
        num = args.num_agents or machine.get("kanban_num_agents")
        if num:
            base += ["--num-agents", str(num)]
    return base


def start_service(service: str, machine: dict, args: argparse.Namespace) -> bool:
    """Spawn the daemon. Returns True on launch (or if already running)."""
    if _service_is_stdio(service):
        pid_path(service).unlink(missing_ok=True)
        print(
            f"  Skipped daemon start: {service} uses stdio/on-demand transport; "
            "MCP clients launch it when needed."
        )
        return True
    existing = read_pid(service)
    if existing:
        print(f"  Already running: {service} (PID {existing})")
        return True
    cmd = build_service_cmd(service, machine, args)
    use_console = _service_uses_console(service, args)
    pid = spawn_detached(
        cmd, log_path(service),
        show_console=use_console,
        pidfile=pid_path(service),
        extra_env=machine_env_vars(machine),
    )
    pid_path(service).write_text(str(pid))
    detail = ""
    if service == "worker":
        detail = f"  queues={cmd[cmd.index('--queues') + 1]}"
    elif service == "kanban" and "--profile" in cmd:
        detail = f"  profile={cmd[cmd.index('--profile') + 1]}"
    if use_console:
        detail += "  [console]"
    target = "console window" if use_console else log_path(service)
    print(f"  Started: {service} (PID {pid}){detail}  ->  {target}")
    # NOTE: PID tracked here is the launcher; Sprout's Django autoreloader
    # forks a child for the real celery process and the launcher PID may
    # exit shortly after. Use the per-service log to confirm the daemon
    # is actually serving requests.
    return True


def stop_service(service: str) -> None:
    pid = read_pid(service)
    if not pid:
        if _service_is_stdio(service):
            print(f"  No daemon to stop: {service} uses stdio/on-demand transport")
        else:
            print(f"  Not running: {service}")
        # Even if no PID file, a tagged Terminal tab may still be open
        # (e.g. PID file got deleted manually). Sweep that one tab anyway.
        _close_macos_terminal_windows([service])
        return
    if stop_pid(pid, service):
        print(f"  Stopped: {service} (PID {pid})")
    _close_macos_terminal_windows([service])


def _process_matching(needle: str) -> list[int]:
    """Return PIDs of running python processes whose command line contains needle.

    Used as a fuzzy supplement to PID-file tracking — Sprout's Django reloader
    forks the actual worker, so the launcher PID we tracked may have exited.
    """
    if IS_WIN:
        try:
            ps_cmd = (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -in @('python.exe','pythonw.exe') } | "
                f"Where-Object {{ $_.CommandLine -like '*{needle}*' }} | "
                "Select-Object -ExpandProperty ProcessId"
            )
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, check=False,
            )
            return [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        except (FileNotFoundError, OSError):
            return []
    try:
        out = subprocess.run(
            ["pgrep", "-f", needle],
            capture_output=True, text=True, check=False,
        )
        return [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except FileNotFoundError:
        return []


def _all_processes_matching(needle: str) -> list[int]:
    """Like _process_matching, but not restricted to python.exe.

    Sprout's autoreloader forks the actual celery worker as a separate
    celery.exe child of the python launcher. To clean those up we have to
    match every process by command line, not just python.exe.
    """
    if IS_WIN:
        try:
            ps_cmd = (
                "Get-CimInstance Win32_Process | "
                f"Where-Object {{ $_.CommandLine -like '*{needle}*' }} | "
                "Select-Object -ExpandProperty ProcessId"
            )
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, check=False,
            )
            return [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        except (FileNotFoundError, OSError):
            return []
    try:
        out = subprocess.run(
            ["pgrep", "-f", needle],
            capture_output=True, text=True, check=False,
        )
        return [int(x) for x in out.stdout.split() if x.strip().isdigit()]
    except FileNotFoundError:
        return []


def kill_stray_celery() -> None:
    """Kill any leftover launcher / celery processes from prior runs.

    Sprout's Django autoreloader forks celery as a child of the launcher.
    The launcher may exit while the forked celery keeps running, leaving
    our PID-file tracking stale. Repeated deploys without this sweep pile
    up orphan workers — visible as multiple console windows on Windows.
    """
    needles = [
        "run_workflows.py",       # launcher entrypoint (host & node) — legacy
        "core.apps.sprout",       # celery -A target — worker, beat, flower
    ]
    pids: set[int] = set()
    self_pid = os.getpid()
    for needle in needles:
        for pid in _all_processes_matching(needle):
            if pid != self_pid:
                pids.add(pid)
    # macOS: also close any tagged Terminal.app tabs from prior --console runs.
    # The pgrep sweep above kills the celery PIDs; this closes the leftover
    # windows so they don't pile up after every redeploy.
    _close_macos_terminal_windows()
    if not pids:
        return
    pids_sorted = sorted(pids)
    print(f"  Killing {len(pids_sorted)} stray celery/launcher process(es): "
          f"{','.join(str(p) for p in pids_sorted)}")
    if IS_WIN:
        for pid in pids_sorted:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, check=False,
            )
        return
    # SIGTERM all, wait up to 5s, then SIGKILL survivors. A beat spinning on
    # a corrupt celerybeat-schedule.db shelve lock ignores SIGTERM — without
    # escalation the next deploy spawns a second beat on top of the stuck
    # one, both fight for the lock at 99% CPU, and no tasks fire.
    for pid in pids_sorted:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    for _ in range(20):
        if not any(is_alive(p) for p in pids_sorted):
            return
        time.sleep(0.25)
    survivors = [p for p in pids_sorted if is_alive(p)]
    if survivors:
        print(f"  SIGTERM ignored — escalating SIGKILL: "
              f"{','.join(str(p) for p in survivors)}")
        for pid in survivors:
            try:
                os.kill(pid, 9)
            except OSError:
                pass


def kill_stray_processes(needle: str, *, label: str) -> int:
    """Force-kill every process whose command line contains ``needle``.

    Best-effort SIGTERM → 5s grace → SIGKILL escalation, same shape as
    kill_stray_celery() but parameterised so a single service (frontend,
    mcp, kanban) can be cleaned without touching the celery sweep.

    Returns the count killed.
    """
    self_pid = os.getpid()
    pids = sorted({p for p in _all_processes_matching(needle) if p != self_pid})
    if not pids:
        return 0
    print(f"  Killing {len(pids)} stray {label} process(es): "
          f"{','.join(str(p) for p in pids)}")
    if IS_WIN:
        for pid in pids:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, check=False,
            )
        return len(pids)
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    for _ in range(20):
        if not any(is_alive(p) for p in pids):
            return len(pids)
        time.sleep(0.25)
    survivors = [p for p in pids if is_alive(p)]
    if survivors:
        print(f"  SIGTERM ignored — escalating SIGKILL: "
              f"{','.join(str(p) for p in survivors)}")
        for pid in survivors:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
    return len(pids)


def restart_service(service: str, machine: dict, args: argparse.Namespace) -> bool:
    """Forcefully restart one service.

    Order matters:
      1. ``stop_service`` — SIGTERM the tracked PID (if any) and drop its
         pidfile / Terminal tab.
      2. ``kill_stray_processes`` — sweep anything matching this service's
         command-line needle. Catches orphans launched outside deploy.py
         (e.g. a manual ``python -m …`` run) and stale forks whose tracked
         PID has already exited.
      3. Clear any leftover pidfile so ``start_service`` doesn't short-
         circuit with "Already running".
      4. ``start_service`` — spawn a fresh daemon.
    """
    if service not in SERVICES:
        print(f"  Unknown service: {service}. Known: {', '.join(SERVICES)}")
        return False
    print(f"==> Restart: {service}")
    if _service_is_stdio(service):
        stop_service(service)
        kill_stray_processes(_STATUS_NEEDLES.get(service, service), label=service)
        pid_path(service).unlink(missing_ok=True)
        print(
            f"  {service} uses stdio/on-demand transport; no deploy daemon was started. "
            "MCP clients launch it when needed."
        )
        return True
    stop_service(service)
    needle = _STATUS_NEEDLES.get(service, service)
    kill_stray_processes(needle, label=service)
    pf = pid_path(service)
    if pf.exists():
        try:
            pf.unlink()
        except OSError:
            pass
    return start_service(service, machine, args)


_STATUS_NEEDLES = {
    "scheduler": "core.apps.sprout:SPROUT beat",
    "worker":    "core.apps.sprout:SPROUT worker",
    "flower":    "core.apps.sprout:SPROUT flower",
    # Use os.sep so the substring matches the real command line on each OS —
    # the previous hard-coded "\\" only matched on Windows, so on macOS/Linux
    # `--status` and the stray-sweep silently missed running frontend/mcp.
    "frontend":  f"frontend{os.sep}main.py",
    "mcp":       f"mcp{os.sep}server.py",
    "kanban":    "agents.projects.orchestrator.local",
    "command-runner": f"n8n{os.sep}utilities{os.sep}command_runner.py",
}


def show_status() -> None:
    print(f"{'SERVICE':<12} {'PID':>8}  {'ALIVE PIDs':<24}  STATUS")
    print(f"{'-' * 12} {'-' * 8}  {'-' * 24}  {'-' * 30}")
    for service in SERVICES:
        pid = read_pid(service)
        alive = _process_matching(_STATUS_NEEDLES.get(service, service))
        alive_str = ",".join(str(p) for p in alive) if alive else "-"
        if pid and pid in alive:
            status = f"running (tracked) -> {log_path(service)}"
        elif alive:
            status = f"running (forked) -> {log_path(service)}"
        elif pid:
            status = "stale PID file (process gone)"
        elif _service_is_stdio(service):
            status = "stdio/on-demand (not a deploy daemon; launched by MCP clients)"
        else:
            status = "stopped"
        print(f"{service:<12} {str(pid or '-'):>8}  {alive_str:<24}  {status}")


# ── Docker compose ────────────────────────────────────────────────────────────

def _docker_compose(*action: str) -> None:
    if not shutil.which("docker"):
        print("  WARNING: docker not on PATH — skipping compose step.")
        return
    subprocess.run(["docker", "compose", *action], cwd=REPO_ROOT, check=False)


def docker_up() -> None:
    print("[host] Starting Docker services...")
    _docker_compose("up", "-d")
    _docker_compose("ps", "--format", "table {{.Name}}\t{{.Status}}\t{{.Ports}}")


def docker_down() -> None:
    print("Stopping Docker services...")
    _docker_compose("down")


def _bootstrap_elasticsearch() -> None:
    """Run the ES single-node bootstrap after docker compose up. Non-fatal."""
    bootstrap_py = SCRIPTS_DIR / "bootstrap_elasticsearch.py"
    if not bootstrap_py.exists():
        print("  WARNING: scripts/bootstrap_elasticsearch.py not found — skipping ES bootstrap.")
        return
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    result = subprocess.run(
        [py, str(bootstrap_py)],
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print(
            "  WARNING: ES bootstrap returned non-zero — cluster may have yellow "
            "shards. Re-run: python scripts/bootstrap_elasticsearch.py"
        )


# ── OS-native service registration ────────────────────────────────────────────

def register_services(machine: dict, args: argparse.Namespace, services: list[str]) -> None:
    """Register every active service as an OS auto-start unit.

    With `--console`, register the unit for next-login persistence but do NOT
    activate it now — start_service will spawn visible Terminal tabs and we
    don't want a background duplicate alongside them.
    """
    activate = not getattr(args, "console", False)
    if IS_MAC:
        _register_launchd(machine, args, services, load=activate)
    elif IS_LIN:
        _register_systemd(machine, args, services, activate=activate)
    elif IS_WIN:
        _register_scheduled_tasks(machine, args, services)
    else:
        print(f"  WARNING: --register not supported on {sys.platform}")


def unregister_services(services: list[str]) -> None:
    if IS_MAC:
        _unregister_launchd(services)
    elif IS_LIN:
        _unregister_systemd(services)
    elif IS_WIN:
        _unregister_scheduled_tasks(services)


# macOS launchd

def _plist_path(service: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"work.harqis.{service}.plist"


def _register_launchd(machine, args, services, *, load: bool = True):
    """Write launchd plists. If `load`, also `launchctl load` (which starts the
    daemon via RunAtLoad=true). Pass `load=False` when the caller plans to
    start the same services in visible console tabs — loading the plist would
    spawn a background duplicate alongside the console process.
    """
    for s in services:
        cmd = build_service_cmd(s, machine, args)
        label = f"work.harqis.{s}"
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array>
    {''.join(f'<string>{c}</string>' for c in cmd)}
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{log_path(s)}</string>
  <key>StandardErrorPath</key><string>{log_path(s)}</string>
  <key>WorkingDirectory</key><string>{REPO_ROOT}</string>
</dict></plist>
"""
        path = _plist_path(s)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plist)
        # Always unload first so a prior plist doesn't keep a stale daemon
        # alive in the background.
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        if load:
            subprocess.run(["launchctl", "load", str(path)], check=False)
            print(f"  Registered + loaded launchd: {label}")
        else:
            print(f"  Registered launchd plist (not loaded — console mode): {label}")


def _unregister_launchd(services):
    for s in services:
        path = _plist_path(s)
        if path.exists():
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
            path.unlink()
            print(f"  Unregistered launchd: work.harqis.{s}")


# Linux systemd (user)

def _systemd_unit_path(service: str) -> Path:
    return Path.home() / ".config" / "systemd" / "user" / f"harqis-{service}.service"


def _register_systemd(machine, args, services, *, activate: bool = True):
    """Write systemd user units. If `activate`, also `enable --now`. Pass
    `activate=False` when start_service will spawn visible console tabs.
    """
    for s in services:
        cmd = build_service_cmd(s, machine, args)
        unit = f"""[Unit]
Description=harqis-work {s}
After=network-online.target

[Service]
ExecStart={' '.join(cmd)}
WorkingDirectory={REPO_ROOT}
Restart=always
RestartSec=5
StandardOutput=append:{log_path(s)}
StandardError=append:{log_path(s)}

[Install]
WantedBy=default.target
"""
        path = _systemd_unit_path(s)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(unit)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        if activate:
            subprocess.run(["systemctl", "--user", "enable", "--now", path.name], check=False)
            print(f"  Registered + started systemd: harqis-{s}")
        else:
            subprocess.run(["systemctl", "--user", "enable", path.name], check=False)
            print(f"  Registered systemd (not started — console mode): harqis-{s}")


def _unregister_systemd(services):
    for s in services:
        unit = f"harqis-{s}.service"
        subprocess.run(["systemctl", "--user", "disable", "--now", unit], capture_output=True)
        path = _systemd_unit_path(s)
        if path.exists():
            path.unlink()
            print(f"  Unregistered systemd: harqis-{s}")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


# Windows: HKCU\...\Run registry keys (auto-launch at user logon, no admin)
#
# Scheduled Tasks were attempted first but Register-ScheduledTask requires
# admin even for user-scope tasks on most installs. HKCU Run keys are the
# standard non-elevated equivalent: they fire at user logon, run as the
# current user with the user's env, and need no special privileges.

_RUN_KEY = r"HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"


def _register_scheduled_tasks(machine, args, services):
    for s in services:
        cmd = build_service_cmd(s, machine, args)
        # Quote the executable + each arg containing spaces.
        parts = [f'"{cmd[0]}"'] + [f'"{a}"' if " " in a else a for a in cmd[1:]]
        value = " ".join(parts).replace("'", "''")
        name = f"work.harqis.{s}"
        ps = (
            f"Set-ItemProperty -Path '{_RUN_KEY}' "
            f"-Name '{name}' -Value '{value}' -Type String"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  Registered Run key: {name} (auto-launch at logon)")
        else:
            err = (result.stderr or result.stdout or "(no error output)").strip()
            print(f"  WARN: Run-key registration FAILED for {name}: {err.splitlines()[0]}")


def _unregister_scheduled_tasks(services):
    for s in services:
        name = f"work.harqis.{s}"
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Remove-ItemProperty -Path '{_RUN_KEY}' -Name '{name}' "
             "-ErrorAction SilentlyContinue"],
            capture_output=True,
        )
        print(f"  Unregistered Run key: {name}")


# ── Service selection ─────────────────────────────────────────────────────────

def select_services(machine: dict, args: argparse.Namespace) -> list[str]:
    """Filter SERVICES by role + machine.disable + --no-* flags.

    Single-instance mode short-circuits the role-based selection: passing
    --scheduler runs only the scheduler; passing -c/--concurrency runs only
    the worker (with the given concurrency exported as WORKFLOW_CONCURRENCY).
    The two flags are mutually exclusive (enforced in argparse).
    """
    if args.scheduler:
        return ["scheduler"]
    if args.concurrency is not None:
        return ["worker"]

    role = machine["role"]
    disabled: set[str] = set(machine.get("disable", []))
    if args.no_scheduler: disabled.add("scheduler")
    if args.no_frontend:  disabled.add("frontend")
    if args.no_mcp:       disabled.add("mcp")
    if args.no_kanban:    disabled.add("kanban")
    if args.no_flower:    disabled.add("flower")
    return [
        s for s, info in SERVICES.items()
        if role in info["roles"] and s not in disabled
    ]


# ── Argparse ──────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Deploy the harqis-work platform on this machine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--machine", help="Machine name in machines.toml (default: auto-detect by hostname)")
    p.add_argument("--role", choices=["host", "node"], help="Override role from machines.toml")
    p.add_argument("-q", "--queues", help="Override worker queues (comma-separated)")
    p.add_argument("-p", "--profile", help="Override Kanban profile filter")
    p.add_argument("--num-agents", type=int, help="Override Kanban concurrent agents")
    p.add_argument("--docker-only", action="store_true", help="Manage Docker only — skip Python services")
    p.add_argument("--no-scheduler", action="store_true",
                   help="Skip the Celery Beat scheduler. Use on every host EXCEPT the "
                        "one canonical Beat runner — duplicate Beat instances fire every "
                        "scheduled task N times.")
    p.add_argument("--no-frontend", action="store_true")
    p.add_argument("--no-mcp",      action="store_true")
    p.add_argument("--no-kanban",   action="store_true")
    p.add_argument("--no-flower",   action="store_true")
    p.add_argument("--console",     action="store_true",
                   help="Launch scheduler+worker in visible console windows "
                        "(live celery output, no log file). Closing a window kills the daemon.")

    si = p.add_mutually_exclusive_group()
    si.add_argument("--scheduler", action="store_true",
                    help="Single-instance mode: run ONLY the Celery Beat scheduler (skip worker, "
                         "frontend, mcp, kanban, flower, Docker). Mutually exclusive with -c.")
    si.add_argument("-c", "--concurrency", type=int, metavar="N",
                    help="Single-instance mode: run ONLY a worker with concurrency N. "
                         "Sets WORKFLOW_CONCURRENCY=N before spawning. Mutually exclusive with --scheduler.")

    g = p.add_mutually_exclusive_group()
    g.add_argument("--down",       action="store_true", help="Stop services")
    g.add_argument("--status",     action="store_true", help="Show running services")
    g.add_argument("--stop",       metavar="SERVICE",   help="Stop one service by name")
    g.add_argument("--restart",    metavar="SERVICE",
                   help="Forcefully restart one service: stop tracked PID, sweep "
                        "strays by command-line match, clear stale pidfile, spawn "
                        "fresh. Use this when a daemon was launched outside deploy.py "
                        "or held stale env (e.g. `--restart frontend`).")
    g.add_argument("--register",   action="store_true", help="Register OS auto-start units")
    g.add_argument("--unregister", action="store_true", help="Remove OS auto-start units")
    return p


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = build_parser().parse_args()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    load_env_into_os()

    if args.status:
        show_status()
        return

    if args.stop:
        stop_service(args.stop)
        return

    if args.restart:
        machine = load_machine_config(args.machine)
        if args.role:
            machine["role"] = args.role
        restart_service(args.restart, machine, args)
        return

    machine = load_machine_config(args.machine)
    if args.role:
        machine["role"] = args.role

    # Per-machine env_vars must reach `docker compose` too — not just the
    # celery daemons (which get them via spawn_detached extra_env). docker_up()
    # inherits os.environ, so export the resolved table now; this is what makes
    # docker-compose.yml's ${HARQIS_DATA_ROOT} (ES bind path) resolve from
    # machines[.local].toml. Per the Phase-0 migration, per-machine values
    # win over .env/apps.env (loaded earlier in load_env_into_os).
    os.environ.update(machine_env_vars(machine))

    services = select_services(machine, args)
    name = machine.get("_name", "(adhoc)")
    role = machine["role"]
    queues = args.queues or ",".join(machine.get("queues", ["default"]))
    single_instance = args.scheduler or args.concurrency is not None
    if args.concurrency is not None:
        # Picked up by scripts/launch.py worker (which falls back to 8 if unset).
        os.environ["WORKFLOW_CONCURRENCY"] = str(args.concurrency)

    if args.unregister:
        unregister_services(services)
        return

    if args.down:
        print(f"==> Tearing down machine={name} role={role}")
        for s in services:
            stop_service(s)
        kill_stray_celery()
        if role == "host" and not args.docker_only and not single_instance:
            docker_down()
        print(f"All services stopped for machine={name}.")
        return

    if single_instance:
        mode = "scheduler" if args.scheduler else f"worker (concurrency={args.concurrency})"
        print(f"==> Single-instance: {mode}  queues={queues}")
        print(f"    services: {', '.join(services)}")
        print(f"    (skipping Docker — single-instance mode assumes broker is reachable)")
    else:
        print(f"==> Deploy machine={name}  role={role}  queues={queues}")
        print(f"    services: {', '.join(services) if services else '(none)'}")

    # Clean slate: kill any orphan celery/launcher processes from prior runs
    # before spawning new daemons (avoids piling up console windows on Windows).
    if not args.docker_only:
        kill_stray_celery()
        # The celery sweep only matches celery/launcher needles. The long-
        # running app daemons (frontend FastAPI, MCP server, Kanban
        # orchestrator) have separate command-line patterns — sweep them too
        # and clear their pidfiles so the upcoming start_service loop spawns
        # fresh code rather than short-circuiting with "Already running" on
        # a tracked PID that is still serving the previous boot's bytecode.
        for _svc in ("frontend", "mcp", "kanban", "command-runner"):
            if _svc in services:
                kill_stray_processes(_STATUS_NEEDLES[_svc], label=_svc)
                _pf = pid_path(_svc)
                if _pf.exists():
                    try:
                        _pf.unlink()
                    except OSError:
                        pass

    if role == "host" and not single_instance:
        docker_up()
        _bootstrap_elasticsearch()
    elif role == "node" and not single_instance:
        print("[node] Skipping Docker — broker is on the host.")

    # Did register_services already start the daemons? Yes when:
    #   - macOS launchd loaded the plist with RunAtLoad=true
    #   - Linux systemd ran `enable --now`
    # Both are skipped in console mode (see `register_services`) precisely so
    # the fall-through `start_service` loop can open Terminal tabs without
    # spawning a background duplicate alongside them. Windows HKCU\Run never
    # starts the daemon at register-time, so the fall-through is required.
    register_started_immediately = (
        args.register
        and (IS_MAC or IS_LIN)
        and not getattr(args, "console", False)
    )
    if args.register:
        register_services(machine, args, services)

    if args.docker_only:
        # docker_up + bootstrap already ran above for host role; just skip
        # spawning Python services.
        return

    if register_started_immediately:
        print("")
        print(f"Started {len(services)} service(s) via "
              f"{'launchd' if IS_MAC else 'systemd'} (background).")
        print(f"Stop with: python scripts/deploy.py --down")
        print(f"Status:    python scripts/deploy.py --status")
        return

    print("")
    started = sum(1 for s in services if start_service(s, machine, args))

    print("")
    print(f"Started {started}/{len(services)} services. (PID-based --status may show 'stopped' "
          f"for daemons whose launcher forks; check logs/<service>.log to confirm.)")
    print(f"Stop with: python scripts/deploy.py --down")
    print(f"Status:    python scripts/deploy.py --status")

    # Post-deploy hook: close console windows with "Process completed"
    if started > 0:
        print("\nRunning post-deploy cleanup (closing stray console windows)...")
        if IS_WIN:
            cleanup_script = SCRIPTS_DIR / "agents" / "fleet" / "close-completed-windows.ps1"
            if cleanup_script.exists():
                try:
                    subprocess.run(
                        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(cleanup_script)],
                        check=False,
                    )
                except Exception as e:
                    print(f"Warning: post-deploy cleanup failed: {e}")
            else:
                print(f"Warning: cleanup script not found at {cleanup_script}")
        elif IS_MAC:
            cleanup_script = SCRIPTS_DIR / "agents" / "fleet" / "close-completed-windows.sh"
            if cleanup_script.exists():
                try:
                    subprocess.run(["bash", str(cleanup_script)], check=False)
                except Exception as e:
                    print(f"Warning: post-deploy cleanup failed: {e}")
            else:
                print(f"Warning: cleanup script not found at {cleanup_script}")


if __name__ == "__main__":
    main()
