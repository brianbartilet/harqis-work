# scripts/

Operational scripts for **harqis-work**. The legacy per-OS / per-queue
shell + batch wrappers have been collapsed into two cross-platform Python
entry points.

| Path | Purpose |
|---|---|
| [`launch.py`](#launchpy) | Single-process launcher — runs one daemon in the foreground (`worker`, `scheduler`, `flower`, `frontend`, `mcp`, `kanban`, `trigger-hud-tasks`, `push-config`, `serve-config`). |
| [`deploy.py`](#deploypy) | Multi-daemon orchestrator — reads `machines.toml` from the repo root, brings the whole stack up/down, optionally registers OS auto-start units. |
| [`../machines.toml`](#machinestoml) | Per-machine topology (role, queue list, disabled services). Lives at the repo root so per-machine `machines.local.toml` overrides sit next to it. Auto-detected from hostname. |
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
`<repo>/logs/<service>.log`. On every deploy or `--down` it also sweeps
stray celery / launcher processes (matched by command-line needles
`run_workflows.py` and `core.apps.sprout.app`) so orphans from prior
runs — the kind that pile up extra console windows on Windows — are
killed before fresh daemons start.

**All commands**

```bash
# Lifecycle
python scripts/deploy.py                            # auto-detect from hostname → start everything
python scripts/deploy.py --down                     # stop services + sweep celery + docker compose down
python scripts/deploy.py --status                   # tabular status (PID + alive PIDs + log path)
python scripts/deploy.py --stop SERVICE             # stop one service by name (worker / scheduler / …)

# OS auto-start
python scripts/deploy.py --register                 # register at-logon auto-start, then start now
python scripts/deploy.py --unregister               # remove auto-start units

# Targeting / overrides
python scripts/deploy.py --machine NAME             # explicit profile lookup (skip hostname auto-detect)
python scripts/deploy.py --role host|node           # override role from machines.toml
python scripts/deploy.py -q QUEUES                  # comma-separated worker queues (override profile)
python scripts/deploy.py -p PROFILE                 # override Kanban profile filter (e.g. agent:code)
python scripts/deploy.py --num-agents N             # override Kanban concurrent agents

# Service filters (skip individual host daemons; can also live under `disable=` in machines.toml)
python scripts/deploy.py --no-frontend
python scripts/deploy.py --no-mcp
python scripts/deploy.py --no-kanban
python scripts/deploy.py --no-flower

# Visible scheduler/worker windows (live celery output)
python scripts/deploy.py --console                  # CREATE_NEW_CONSOLE for scheduler+worker only;
                                                    # closes-window-kills-daemon, no log file written

# Docker only (skip Python services)
python scripts/deploy.py --docker-only              # bring docker compose up/down without daemons
```

`--down`, `--status`, `--stop`, `--register`, `--unregister` are mutually
exclusive — pass at most one per invocation.

**Per-role behaviour**

| Role | Docker compose | scheduler | worker | frontend | mcp | kanban | flower |
|---|---|---|---|---|---|---|---|
| `host` | ✓ up/down | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `node` | — (broker is on host) | — | ✓ | — | — | ✓ | — |

Use `--no-frontend / --no-mcp / --no-kanban / --no-flower` to skip
individual host daemons, or list them under `disable` in `machines.toml`.

**Console mode (`--console`)**

`scheduler` and `worker` are flagged `console: True` in `SERVICES`. With
`--console`, those two daemons launch under `python.exe` (not
`pythonw.exe`) with `CREATE_NEW_CONSOLE` and **no stdout redirect** —
each gets its own visible window with live celery output. Other services
(`frontend`, `mcp`, `kanban`, `flower`) stay windowless even with the
flag set. Trade-offs:

- `logs/scheduler.log` / `logs/worker.log` are **not** written while in
  console mode (output goes only to the windows).
- Closing a console window terminates that daemon — no automatic respawn.
  Use `--down` for orderly shutdown.
- The harqis-core sprout patch (`d30527a` and later) auto-detects an
  attached console and inherits it for the forked celery child, so you
  see celery's actual log lines (not just the launcher's startup print).

**OS-native auto-start (`--register`)**

| OS | Mechanism | Unit / key location |
|---|---|---|
| macOS | launchd LaunchAgent | `~/Library/LaunchAgents/work.harqis.<svc>.plist` |
| Linux | systemd user unit | `~/.config/systemd/user/harqis-<svc>.service` |
| Windows | HKCU `…\CurrentVersion\Run` key | `HKCU:\Software\Microsoft\Windows\CurrentVersion\Run\work.harqis.<svc>` |

macOS launchd / Linux systemd units are `KeepAlive=true` /
`Restart=always` / restart on failure with backoff. Windows Run keys
fire **once at user logon** (no auto-restart on crash) — they were
chosen over Scheduled Tasks because Scheduled Tasks need admin even for
user-scope tasks on most installs. `--register` also starts the
services *now* (otherwise on Windows you'd have to log out/in to see
anything running). `--unregister` removes them cleanly.

---

## `machines.toml`

Lives at the **repo root** (alongside `requirements.txt`, `apps_config.yaml`,
etc.), not under `scripts/`. Declarative topology — each section describes
one machine; `[hostnames]` maps `socket.gethostname()` → machine name.
Example layout:

```toml
[default]                       # fallback when no [hostnames] entry matches
role = "host"
queues = ["default", "default_broadcast"]

[harqis-server]                 # always-on hub
role = "host"
queues = ["tcg", "agent", "host", "adhoc", "default_broadcast"]

[windows-work]
role = "host"
queues = ["default", "hud", "default_broadcast"]
disable = ["kanban"]

[vps-worker]
role = "node"
queues = ["agent", "worker", "default_broadcast"]
kanban_profile = "agent:code"

[hostnames]
"harqis-mac-mini.local" = "harqis-server"
"DESKTOP-N100"          = "windows-work"
```

> **Broadcast queues:** any name ending in `_broadcast` (e.g.
> `default_broadcast`, `hud_broadcast`) is a fanout exchange in
> `workflows/config.py`. Workers must include the broadcast queue in
> their `queues` list, otherwise the exchange is never declared on
> RabbitMQ and beat publishes fail with `404 NOT_FOUND - no exchange
> '<name>' in vhost '/'`. The broadcast subscriber on every machine
> above is what makes `git_pull_on_paths_broadcast` (and any future
> cluster-wide task) actually fan out.

Find a machine's hostname:
```bash
python -c "import socket; print(socket.gethostname())"
```

**Local override (`machines.local.toml`)** — gitignored. `deploy.py` merges
it on top of `machines.toml` at load time, so real hostname mappings or
per-machine tweaks stay off the repo. Copy `machines.local.toml.example`
to `machines.local.toml` and fill in:

```toml
[hostnames]
"harqis-mac-mini.local"   = "harqis-server"
"DESKTOP-N100"            = "windows-work"
"vps-1.tail-scale.ts.net" = "vps-worker"

# Override a field of an existing machine
[windows-work]
kanban_num_agents = 3
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
