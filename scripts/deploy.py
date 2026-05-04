#!/usr/bin/env python
"""Deploy the harqis-work platform on this machine (cross-platform).

Replaces scripts/sh/deploy.sh and scripts/ps/deploy.ps1. Reads per-machine
topology from scripts/machines.toml so each host just runs:

    python scripts/deploy.py            # auto-detect from hostname
    python scripts/deploy.py --down

Override the auto-detection or add ad-hoc daemons via flags:

    python scripts/deploy.py --machine harqis-server
    python scripts/deploy.py --role host --queues tcg,peon,agent
    python scripts/deploy.py --role node --queues agent,worker
    python scripts/deploy.py --role host --no-mcp --no-kanban --no-flower

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
MACHINES_TOML = SCRIPTS_DIR / "machines.toml"
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
    "mcp":       {"cmd": ["mcp"],               "roles": {"host"}},
    "kanban":    {"cmd": ["kanban"],            "roles": {"host", "node"}},
    "flower":    {"cmd": ["flower"],            "roles": {"host"}},
}


# ── Machine config ────────────────────────────────────────────────────────────

def _merge_machines(base: dict, override: dict) -> dict:
    """Shallow merge: override's top-level keys win; for dict values
    (e.g. [hostnames] or a [<machine>] section), inner keys merge."""
    out = {**base}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


def load_machine_config(name: str | None) -> dict:
    """Resolve machine config from scripts/machines.toml + machines.local.toml.

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
        name = cfg.get("hostnames", {}).get(host, "default")
    machine = cfg.get(name)
    if machine is None:
        machine = cfg.get("default", {"role": "host", "queues": ["default"]})
    return {**machine, "_name": name}


# ── Env loading (for docker-compose) ──────────────────────────────────────────

def load_env_into_os() -> None:
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
        os.environ.setdefault(key, value)


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


def spawn_detached(cmd: list[str], log_file: Path, *, show_console: bool = False) -> int:
    """Spawn a long-running process detached from this terminal. Returns its PID.

    Two modes on Windows:
      - show_console=False (default) — windowless daemon. CREATE_NO_WINDOW
        suppresses console creation; stdout/stderr redirect to log_file.
      - show_console=True — visible window. CREATE_NEW_CONSOLE allocates a
        new console; stdio is NOT redirected so live output flows there.
        Closing the window terminates the daemon.

    CREATE_NEW_PROCESS_GROUP detaches the child from this terminal's signal
    group so Ctrl-C here doesn't kill the daemon. On Unix, the start_new_session
    equivalent is used; show_console=True there means inherit the current
    terminal's stdio (no separate window concept).
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        if show_console:
            flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(cmd, creationflags=flags, close_fds=True)
        else:
            fout = open(log_file, "ab")
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL, stdout=fout, stderr=subprocess.STDOUT,
                creationflags=flags, close_fds=True,
            )
    else:
        if show_console:
            proc = subprocess.Popen(cmd, start_new_session=True, close_fds=True)
        else:
            fout = open(log_file, "ab")
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL, stdout=fout, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True,
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
    existing = read_pid(service)
    if existing:
        print(f"  Already running: {service} (PID {existing})")
        return True
    cmd = build_service_cmd(service, machine, args)
    use_console = _service_uses_console(service, args)
    pid = spawn_detached(cmd, log_path(service), show_console=use_console)
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
        print(f"  Not running: {service}")
        return
    if stop_pid(pid, service):
        print(f"  Stopped: {service} (PID {pid})")


def _process_matching(needle: str) -> list[int]:
    """Return PIDs of running python processes whose command line contains needle.

    Used as a fuzzy supplement to PID-file tracking — Sprout's Django reloader
    forks the actual worker, so the launcher PID we tracked may have exited.
    """
    if IS_WIN:
        try:
            ps_cmd = (
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
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
        "run_workflows.py",       # launcher entrypoint (host & node)
        "core.apps.sprout.app",   # celery -A target — worker, beat, flower
    ]
    pids: set[int] = set()
    self_pid = os.getpid()
    for needle in needles:
        for pid in _all_processes_matching(needle):
            if pid != self_pid:
                pids.add(pid)
    if not pids:
        return
    pids_sorted = sorted(pids)
    print(f"  Killing {len(pids_sorted)} stray celery/launcher process(es): "
          f"{','.join(str(p) for p in pids_sorted)}")
    for pid in pids_sorted:
        if IS_WIN:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, check=False,
            )
        else:
            try:
                os.kill(pid, 15)
            except OSError:
                pass


_STATUS_NEEDLES = {
    "scheduler": "run_workflows.py scheduler",
    "worker":    "run_workflows.py worker",
    "flower":    "celery -A core.apps.sprout.app.celery:SPROUT flower",
    "frontend":  "frontend\\main.py",
    "mcp":       "mcp\\server.py",
    "kanban":    "agents.projects.orchestrator.local",
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


# ── OS-native service registration ────────────────────────────────────────────

def register_services(machine: dict, args: argparse.Namespace, services: list[str]) -> None:
    """Register every active service as an OS auto-start unit."""
    if IS_MAC:
        _register_launchd(machine, args, services)
    elif IS_LIN:
        _register_systemd(machine, args, services)
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


def _register_launchd(machine, args, services):
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
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
        subprocess.run(["launchctl", "load", str(path)], check=False)
        print(f"  Registered launchd: {label}")


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


def _register_systemd(machine, args, services):
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
        subprocess.run(["systemctl", "--user", "enable", "--now", path.name], check=False)
        print(f"  Registered systemd: harqis-{s}")


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
    """Filter SERVICES by role + machine.disable + --no-* flags."""
    role = machine["role"]
    disabled: set[str] = set(machine.get("disable", []))
    if args.no_frontend: disabled.add("frontend")
    if args.no_mcp:      disabled.add("mcp")
    if args.no_kanban:   disabled.add("kanban")
    if args.no_flower:   disabled.add("flower")
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
    p.add_argument("--machine", help="Machine name in scripts/machines.toml (default: auto-detect by hostname)")
    p.add_argument("--role", choices=["host", "node"], help="Override role from machines.toml")
    p.add_argument("-q", "--queues", help="Override worker queues (comma-separated)")
    p.add_argument("-p", "--profile", help="Override Kanban profile filter")
    p.add_argument("--num-agents", type=int, help="Override Kanban concurrent agents")
    p.add_argument("--docker-only", action="store_true", help="Manage Docker only — skip Python services")
    p.add_argument("--no-frontend", action="store_true")
    p.add_argument("--no-mcp",      action="store_true")
    p.add_argument("--no-kanban",   action="store_true")
    p.add_argument("--no-flower",   action="store_true")
    p.add_argument("--console",     action="store_true",
                   help="Launch scheduler+worker in visible console windows "
                        "(live celery output, no log file). Closing a window kills the daemon.")

    g = p.add_mutually_exclusive_group()
    g.add_argument("--down",       action="store_true", help="Stop services")
    g.add_argument("--status",     action="store_true", help="Show running services")
    g.add_argument("--stop",       metavar="SERVICE",   help="Stop one service by name")
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

    machine = load_machine_config(args.machine)
    if args.role:
        machine["role"] = args.role
    services = select_services(machine, args)
    name = machine.get("_name", "(adhoc)")
    role = machine["role"]
    queues = args.queues or ",".join(machine.get("queues", ["default"]))

    if args.unregister:
        unregister_services(services)
        return

    if args.down:
        print(f"==> Tearing down machine={name} role={role}")
        for s in services:
            stop_service(s)
        kill_stray_celery()
        if role == "host" and not args.docker_only:
            docker_down()
        print(f"All services stopped for machine={name}.")
        return

    print(f"==> Deploy machine={name}  role={role}  queues={queues}")
    print(f"    services: {', '.join(services) if services else '(none)'}")

    # Clean slate: kill any orphan celery/launcher processes from prior runs
    # before spawning new daemons (avoids piling up console windows on Windows).
    if not args.docker_only:
        kill_stray_celery()

    if role == "host" and not args.docker_only:
        docker_up()
    elif role == "node":
        print("[node] Skipping Docker — broker is on the host.")

    if args.register:
        register_services(machine, args, services)
        # fall through and start services NOW too — registration only fires
        # at logon (Windows) / login (macOS LaunchAgent) / login (systemd user),
        # so without this the user has to log out/in to see anything running.

    if args.docker_only:
        return

    print("")
    started = sum(1 for s in services if start_service(s, machine, args))

    print("")
    print(f"Started {started}/{len(services)} services. (PID-based --status may show 'stopped' "
          f"for daemons whose launcher forks; check logs/<service>.log to confirm.)")
    print(f"Stop with: python scripts/deploy.py --down")
    print(f"Status:    python scripts/deploy.py --status")


if __name__ == "__main__":
    main()
