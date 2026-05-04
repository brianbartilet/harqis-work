# scripts/

Operational scripts for **harqis-work**. The legacy per-OS / per-queue
shell + batch wrappers have been collapsed into two cross-platform Python
entry points.

| Path | Purpose |
|---|---|
| [`launch.py`](#launchpy) | Single-process launcher — runs one daemon in the foreground (`worker`, `scheduler`, `flower`, `frontend`, `mcp`, `kanban`, `trigger-hud-tasks`, `push-config`, `serve-config`). |
| [`deploy.py`](#deploypy) | Multi-daemon orchestrator — reads `machines.toml`, brings the whole stack up/down, optionally registers OS auto-start units. |
| [`machines.toml`](#machinestoml) | Per-machine topology (role, queue list, disabled services). Auto-detected from hostname. |
| [`run_agent_prompt.py`](#run_agent_promptpy) | Claude-driven docs / code-smell regenerator. Unchanged. |
| [`tailscale/`](#tailscale) | Tailscale ACL policy. Unchanged. |

Both Python scripts use `pathlib`, work on Windows / macOS / Linux, and
require Python 3.11+ (uses `tomllib` from stdlib).

---

## `launch.py`

Loads `.env/apps.env`, sets `PYTHONPATH` + the standard `WORKFLOW_*` and
`PATH_APP_CONFIG_*` env vars, then `os.execvp`s into the actual command.
The result: the system service / Task Scheduler / launchd / systemd
manages the real Python process directly — no extra wrapper PID, no
PowerShell-vs-bash drift.

**Subcommands**

```bash
python scripts/launch.py worker [-q default,hud,tcg]
python scripts/launch.py scheduler
python scripts/launch.py flower
python scripts/launch.py frontend
python scripts/launch.py mcp
python scripts/launch.py kanban [-p agent:default] [--num-agents 1]

# Helpers
python scripts/launch.py trigger-hud-tasks [--queue hud]
python scripts/launch.py push-config  [--redis-url URL] [--key KEY]
python scripts/launch.py serve-config [--port 8765]    [--token TOKEN]
python scripts/launch.py print-env                                 # eval-able env
```

**Notes**

- `worker --queues` accepts a comma-separated list. Celery's `-Q` natively
  consumes multiple queues, so one process listens to all of them.
- `flower`, `trigger-hud-tasks` require `FLOWER_USER` and `FLOWER_PASSWORD`
  in `.env/apps.env`. The legacy hardcoded creds in `run_hud_tasks.bat`
  are gone — `launch.py trigger-hud-tasks` reads them from the env.
- `push-config` / `serve-config` run on the **host** machine. Remote workers
  set `CONFIG_SOURCE=redis|http` to consume the resolved config.

---

## `deploy.py`

Orchestrator. Reads `machines.toml`, decides which services to start
(based on `role` + `disable`), launches each as a detached background
process, tracks PIDs in `<repo>/.run/<service>.pid`, and logs to
`<repo>/logs/<service>.log`.

```bash
python scripts/deploy.py                            # auto-detect from hostname
python scripts/deploy.py --machine harqis-server    # explicit lookup
python scripts/deploy.py --role host -q tcg,peon,agent  # ad-hoc override

python scripts/deploy.py --status                   # list running services
python scripts/deploy.py --stop worker              # stop one
python scripts/deploy.py --down                     # stop everything

python scripts/deploy.py --register                 # OS auto-start (launchd /
                                                    # systemd / Scheduled Task)
python scripts/deploy.py --unregister               # remove auto-start
```

**Per-role behaviour**

| Role | Docker compose | scheduler | worker | frontend | mcp | kanban | flower |
|---|---|---|---|---|---|---|---|
| `host` | ✓ up/down | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `node` | — (broker is on host) | — | ✓ | — | — | ✓ | — |

Use `--no-frontend / --no-mcp / --no-kanban / --no-flower` to skip
individual host daemons, or list them under `disable` in `machines.toml`.

**OS-native registration (`--register`)**

| OS | Mechanism | Unit location |
|---|---|---|
| macOS | launchd LaunchAgent | `~/Library/LaunchAgents/work.harqis.<svc>.plist` |
| Linux | systemd user unit | `~/.config/systemd/user/harqis-<svc>.service` |
| Windows | Scheduled Task (at startup) | `work.harqis.<svc>` |

Each unit is `KeepAlive=true` / `Restart=always` / restarts on failure with
backoff. `--unregister` removes them cleanly.

---

## `machines.toml`

Declarative topology. Each section describes one machine; `[hostnames]`
maps `socket.gethostname()` → machine name. Example layout:

```toml
[default]                       # fallback when no [hostnames] entry matches
role = "host"
queues = ["default"]

[harqis-server]                 # always-on hub
role = "host"
queues = ["tcg", "peon", "agent"]

[windows-work]
role = "host"
queues = ["default", "hud"]
disable = ["mcp", "kanban"]

[vps-worker]
role = "node"
queues = ["agent", "worker"]
kanban_profile = "agent:code"

[hostnames]
"harqis-mac-mini.local" = "harqis-server"
"DESKTOP-N100"          = "windows-work"
```

Find a machine's hostname:
```bash
python -c "import socket; print(socket.gethostname())"
```

---

## Quick recipes

**Bring up your machine (anywhere):**
```bash
python scripts/deploy.py
# = auto-detect via machines.toml → start docker (if host) + all relevant daemons
```

**Stop everything:**
```bash
python scripts/deploy.py --down
```

**Run one worker by hand (no daemonization):**
```bash
python scripts/launch.py worker --queues hud,tcg
```

**See what's running:**
```bash
python scripts/deploy.py --status
```

**Auto-start at boot:**
```bash
python scripts/deploy.py --register     # one-time per machine
```

**Push resolved config to Redis (host) so remote workers pick it up:**
```bash
python scripts/launch.py push-config
```

---

## `run_agent_prompt.py`

Unchanged. Claude-powered regenerator for top-level docs.

```bash
python scripts/run_agent_prompt.py --agent docs          # regenerate README.md
python scripts/run_agent_prompt.py --agent code_smells   # regenerate CODE_SMELLS.md
python scripts/run_agent_prompt.py --agent both
```

---

## `tailscale/`

Unchanged. See `tailscale/acl-policy.hujson` (gitignored). Apply via:
```bash
tailscale acls set --file scripts/tailscale/acl-policy.hujson
```

Tag model and rules — see the file's header comment, or the previous
revision of this README in git history.
