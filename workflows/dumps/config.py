"""
workflows/dumps/config.py

Reads `machines.toml` + `machines.toml.local` (the same files deploy.py uses)
and resolves the current machine's daily-dumps configuration.

Schema (machines.toml — committed, schema docs only):

    [dumps]
    # SSH target the broadcast task uses to ship files to harqis-server's inbox.
    # Example values live in machines.local.toml (gitignored).

    # [<machine>.daily_dumps]
    # paths = [ "<path1>", "<path2>", ... ]

    # [dumps.pull_targets.<device-name>]
    # ssh   = "<user>@<host>"
    # port  = 22
    # paths = [ "<path1>", ... ]

Schema (machines.toml.local — gitignored, real values):

    [dumps]
    harqis_server_ssh   = "harqis-one@harqis-mac-mini.tailnet.ts.net"
    harqis_server_inbox = "/Users/harqis-one/dumps"
    summary_path        = "/Volumes/harqis-data/dumps-summary"   # optional

    [windows-work-all.daily_dumps]
    paths = [ "C:/path/to/screenshots", "C:/path/to/logs" ]

    [dumps.pull_targets.pixel-7]
    ssh   = "u0_a200@pixel-7.tailnet.ts.net"
    port  = 8022
    paths = [ "/storage/emulated/0/DCIM/Camera" ]
"""
from __future__ import annotations

import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MACHINES_TOML = REPO_ROOT / "machines.toml"
MACHINES_LOCAL_TOML = REPO_ROOT / "machines.local.toml"

# Canonical name for the central hub. Must match the [<name>] block in
# machines.toml AND the destination of broadcast pushes. Don't change this
# without also updating machines.toml.local [dumps] and the pull-task config.
HARQIS_SERVER_MACHINE_NAME = "harqis-server"


def _merge(base: dict, override: dict) -> dict:
    """One-level recursive merge — same semantics as scripts/deploy.py."""
    out = {**base}
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_merged_config() -> dict:
    """Load machines.toml + machines.local.toml as one merged dict."""
    if not MACHINES_TOML.exists():
        return {}
    cfg = tomllib.loads(MACHINES_TOML.read_text(encoding="utf-8"))
    if MACHINES_LOCAL_TOML.exists():
        cfg = _merge(cfg, tomllib.loads(MACHINES_LOCAL_TOML.read_text(encoding="utf-8")))
    return cfg


def resolve_local_machine_name(cfg: dict | None = None) -> str:
    """Map socket.gethostname() through [hostnames] to a machine name.

    Falls back to socket.gethostname() unchanged if no mapping exists, so the
    daily-dumps config can still be keyed by the raw hostname if preferred.
    """
    cfg = cfg if cfg is not None else load_merged_config()
    host = socket.gethostname()
    hostnames = cfg.get("hostnames", {}) or {}
    if host in hostnames:
        return hostnames[host]
    lower_host = host.lower()
    for key, machine_name in hostnames.items():
        if str(key).lower() == lower_host:
            return machine_name
    return host


@dataclass
class DumpsTarget:
    """Where the broadcast task ships files to."""
    ssh: str       # e.g. "harqis-one@harqis-mac-mini.tailnet.ts.net"
    inbox: str     # remote dir, e.g. "/Users/harqis-one/dumps"


@dataclass
class LocalDumpsConfig:
    """The dumps config relevant to the current machine."""
    machine_name: str
    paths: list[str] = field(default_factory=list)
    is_harqis_server: bool = False


@dataclass
class PullTarget:
    """A non-celery device that harqis-server pulls from."""
    name: str
    ssh: str
    paths: list[str]
    port: int = 22


@dataclass(frozen=True)
class ExpectedDumpSource:
    """A configured source that should produce a daily dump folder."""
    name: str
    source_type: str  # "worker" for celery broadcast, "pull" for host pulls
    paths: list[str]


def get_dumps_target(cfg: dict | None = None) -> DumpsTarget | None:
    """Return the harqis-server SSH target + inbox path, or None if unset."""
    cfg = cfg if cfg is not None else load_merged_config()
    section = cfg.get("dumps", {})
    ssh = section.get("harqis_server_ssh")
    inbox = section.get("harqis_server_inbox")
    if not ssh or not inbox:
        return None
    return DumpsTarget(ssh=ssh, inbox=inbox)


def get_dumps_summary_path(cfg: dict | None = None) -> str | None:
    """Return the host-local dir for the per-day summary Markdown, or None.

    Lives in `[dumps] summary_path` in machines.local.toml — right next to
    `harqis_server_inbox`, since the summary dir is just as host-local to
    harqis-server as the inbox is. None when unset (callers fall back to the
    apps_config / env / repo-logs chain in summary_store)."""
    cfg = cfg if cfg is not None else load_merged_config()
    path = (cfg.get("dumps", {}) or {}).get("summary_path")
    return path or None


def get_local_dumps_config(cfg: dict | None = None) -> LocalDumpsConfig:
    """Return the dumps config for the machine this code is running on."""
    cfg = cfg if cfg is not None else load_merged_config()
    name = resolve_local_machine_name(cfg)
    machine = cfg.get(name, {}) or {}
    dumps = machine.get("daily_dumps", {}) or {}
    return LocalDumpsConfig(
        machine_name=name,
        paths=list(dumps.get("paths", []) or []),
        is_harqis_server=(name == HARQIS_SERVER_MACHINE_NAME),
    )


def get_pull_targets(cfg: dict | None = None) -> list[PullTarget]:
    """Return the list of non-celery devices harqis-server should pull from."""
    cfg = cfg if cfg is not None else load_merged_config()
    targets = (cfg.get("dumps", {}) or {}).get("pull_targets", {}) or {}
    out: list[PullTarget] = []
    for name, entry in targets.items():
        if not isinstance(entry, dict):
            continue
        ssh = entry.get("ssh")
        paths = entry.get("paths") or []
        if not ssh or not paths:
            continue
        out.append(PullTarget(
            name=name,
            ssh=ssh,
            paths=list(paths),
            port=int(entry.get("port", 22)),
        ))
    return out


def get_expected_dump_sources(cfg: dict | None = None) -> list[ExpectedDumpSource]:
    """Return configured machines/devices expected to produce daily dumps.

    Celery-attached machines are expected when their machine section has a
    non-empty ``daily_dumps.paths`` list. Non-celery devices are the configured
    pull targets. Schema-only / disabled sections and empty path lists are not
    expected to produce output.
    """
    cfg = cfg if cfg is not None else load_merged_config()
    sources: list[ExpectedDumpSource] = []

    for name, entry in cfg.items():
        if name in {"default", "dumps", "hostnames", "shared", "sync", "ssh"}:
            continue
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        daily = entry.get("daily_dumps") or {}
        paths = list(daily.get("paths") or []) if isinstance(daily, dict) else []
        if paths:
            sources.append(ExpectedDumpSource(
                name=name,
                source_type="worker",
                paths=paths,
            ))

    for target in get_pull_targets(cfg):
        sources.append(ExpectedDumpSource(
            name=target.name,
            source_type="pull",
            paths=target.paths,
        ))

    return sorted(sources, key=lambda s: (s.source_type, s.name))
