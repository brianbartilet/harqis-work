Deploy the harqis-work platform on this machine — full stack ("host") or worker-only ("node"). Walks through Docker services, env loading, scheduler, workers, frontend, MCP server, and the Kanban agent orchestrator. Uses the cross-platform Python entry point `python scripts/deploy.py`, which auto-detects OS and reads `machines.toml` for hostname → role/queues mapping (override via `--machine NAME` or `--role`/`--queues` flags). Auto-start: `python scripts/deploy.py --register` writes a launchd plist (macOS) / systemd user unit (Linux) / Scheduled Task (Windows); `--unregister` removes them. If `host` is selected, the Kanban orchestrator also acts as 1 in-process agent worker.

## Arguments

`$ARGUMENTS` format:

```
<role> [-q <queues>] [-p <profile>] [--os <labels>] [--down] [--no-frontend] [--no-mcp] [--no-kanban] [--no-flower] [--num-agents N] [--dry-run]
```

| Token | Required | Description |
|---|---|---|
| `role` | Yes | `host` or `node`. `host` is the always-on hub (Docker stack + Beat scheduler + worker + frontend + MCP + Kanban + Flower). `node` is a remote worker that connects to the host's broker — and **also** runs a profile-scoped Kanban orchestrator unless `--no-kanban` is set. |
| `-q`, `--queues <LIST>` | No | Comma-separated Celery queue list for the worker, e.g. `hud,tcg,default` or `code,write`. **Default:** `default` (both roles). |
| `-p`, `--profile <ID>` | Yes for `node`, optional for `host` | Kanban profile id this orchestrator owns (e.g. `agent:default`, `agent:code`, `agent:write`). The orchestrator only claims cards whose resolved profile matches. **Defaults:** host → `agent:default` (so the host also acts as 1 default-queue node); node → **no default — must be passed**. If the user invokes `/deploy-harqis node` without `-p`, **ask which profile** before continuing (list available profiles from `agents/projects/profiles/examples/`). |
| `--os <LABELS>` | No | Comma-separated `os:*` labels this orchestrator satisfies, e.g. `os:linux,os:gpu`. Unset = auto-detect from `platform.system()` (darwin → `os:darwin,os:macos,os:mac`; linux → `os:linux`; windows → `os:windows,os:win`; all hosts also satisfy `os:any`). Cards with no `os:*` label run on any node; cards with `os:windows` only run on Windows nodes. |
| `--down` | No | Tear down services for this role instead of starting them. |
| `--no-frontend` | No | Skip the FastAPI dashboard (host only). |
| `--no-mcp` | No | Skip the MCP server daemon (host only). |
| `--no-kanban` | No | Skip the Kanban orchestrator. On node this also relaxes the `--profile` requirement. |
| `--no-flower` | No | Skip the Flower Celery monitor (host only). |
| `--num-agents N` | No | Number of concurrent in-process Kanban agent workers (default 1). Applies to whichever profile this orchestrator is filtered to. |
| `--dry-run` | No | Run Kanban orchestrator in dry-run mode (logs actions, doesn't invoke Claude). |

`role` is mandatory. If the user invokes `/deploy-harqis` without args, ask which role and which queues (the latter only matters for `node`).

### Scheduler vs queues — the rule that must never break

- **Scheduler (Celery Beat)** runs on `host` only — there must be exactly **one** Beat instance across the whole cluster. Running it on a node would cause every scheduled task to fire multiple times.
- **Queues** are role-agnostic. Workers (host or node) consume from the queue list passed via `-q`. Beat dispatches tasks; whichever worker subscribes to the right queue picks them up. That's why `-q` only affects the worker, never the scheduler.

### Project routing — profile + os filters

The projects orchestrator runs on **both** host and node. Each instance polls every Trello board in the configured workspace (or static `TRELLO_BOARD_IDS`), and only claims cards that match its filters:

1. **Profile filter (`-p`)** — Card's resolved profile id must equal `--profile`. Cards with `agent:code` label go to the orchestrator filtered to `agent:code`; cards with no `agent:*` label fall back to `agent:default`.
2. **OS filter (`--os`)** — Card's `os:*` labels must intersect the orchestrator's `os_labels`. Cards with no `os:*` label match any orchestrator.

Both filters AND together. A card matching neither filter is skipped silently — another orchestrator is the intended owner.

If the user invokes `/deploy-harqis node` without `-p`, **stop and ask which profile** (e.g. `agent:code`, `agent:write`). List available profiles by reading filenames from `agents/projects/profiles/examples/`. Don't guess.

---

## Step 1 — Validate role and detect environment

Resolve the absolute repo root using `git rev-parse --show-toplevel`. From here on, refer to it as `$REPO_ROOT`.

Detect the OS first — every subsequent step branches on this:

| Detection | macOS / Linux | Windows |
|---|---|---|
| Test | `uname -s` returns `Darwin`/`Linux` | `$env:OS` is `Windows_NT` (or `uname -s` not available) |
| Deploy entrypoint | `python scripts/deploy.py` | `python scripts/deploy.py` |
| Python venv | `.venv/bin/python` | `.venv\Scripts\python.exe` |
| Daemon mechanism | LaunchAgent (macOS) / systemd user unit (Linux) via `--register` | Scheduled Task via `--register` (must run elevated) |
| PID tracking (Windows) | n/a | `$REPO_ROOT/.run/<label>.pid` |
| Logs | `~/Library/Logs/harqis-*.log` (macOS), `/var/log/harqis-*.log` (Linux) | `$REPO_ROOT/logs/work.harqis.*.log` |
| Secrets source | macOS Keychain, then `.env/apps.env` | `.env\apps.env` only (Keychain is macOS-specific) |

Detect Docker (`docker ps` succeeds) — required for `host`, optional for `node`.

Print a one-line summary: OS, deploy entrypoint, Python venv path, secrets source, Docker status, resolved role + queues.

If `--down` was passed, jump to Step 8 (teardown).

---

## Step 2 — Validate prerequisites for the chosen role

**`host`:**
- Docker daemon must be running (`docker info` exits 0).
- `$REPO_ROOT/docker-compose.yml` must exist.
- For Kanban: `$REPO_ROOT/agents/projects/profiles/examples/` should contain at least one `.yaml` profile.

**`node`:**
- `CELERY_BROKER_URL` must be set in `.env/apps.env` (CONFIG_SOURCE merged into launch.py — set in apps.env) and point to the host's broker (e.g. `amqp://guest:guest@<host-tailscale-ip>:5672/`).
- Tailscale connectivity to the host (`tailscale ping <host>`) is recommended.

If any check fails, print the missing item and the exact command to fix it (e.g. "Run `open -a Docker` then re-run `/deploy-harqis host`"). Stop without making changes.

---

## Step 3 — Bring up Docker services (host only)

Run `python scripts/deploy.py --role host --docker-only` (or, on `node`, skip this step).

After it returns, verify each container is healthy:
```bash
docker compose -f "$REPO_ROOT/docker-compose.yml" ps --format json
```

Wait up to 60s for `rabbitmq`, `redis`, and `elasticsearch` to report healthy. If any container is unhealthy after 60s, surface its last 20 log lines via `docker compose logs --tail=20 <name>` and stop — do not proceed to start workers against an unhealthy broker.

---

## Step 4 — Load environment

Env loading is handled automatically by `scripts/launch.py` when each daemon starts. It populates:
- `PYTHONPATH`, `ROOT_DIRECTORY`, `PATH_APP_CONFIG`, `PATH_APP_CONFIG_SECRETS`
- `WORKFLOW_CONFIG=workflows.config`, `APP_CONFIG_FILE=apps_config.yaml`
- `CELERY_BROKER_URL` (defaults to `amqp://guest:guest@localhost:5672/` on the host; node should override before invocation).

For `node`, set `CONFIG_SOURCE=redis|http` and queue overrides directly in `.env/apps.env` (merged into launch.py).

---

## Step 5 — Start Celery Beat scheduler (host only)

Celery Beat is the dispatcher: it reads `workflows.config.beat_schedule` and emits scheduled tasks to the broker. **It must run on exactly one machine across the entire cluster.** Running it on a node would create a second scheduler and every periodic task would fire twice (or N times, for N nodes).

- **macOS host:** `python scripts/launch.py scheduler` (or use `python scripts/deploy.py --register` to install as a LaunchAgent).
- **Linux host:** `python scripts/launch.py scheduler` (or use `python scripts/deploy.py --register` to install as a systemd user unit).
- **Windows host:** `python scripts/launch.py scheduler` (or `python scripts/deploy.py --register`, must run elevated, to install as a Scheduled Task that runs `AtStartup`).
- **Node (any OS):** **skip entirely.** No matter how many queues a node owns, it never runs Beat. Beat dispatches to queues; nodes only consume from queues.

After loading, confirm Beat is running:
```bash
# macOS / Linux
launchctl list | grep work.harqis.scheduler          # macOS
systemctl status harqis-scheduler                    # Linux
tail -n 5 ~/Library/Logs/harqis-scheduler.log
```

```powershell
# Windows
Get-Process -Id (Get-Content .\.run\work.harqis.scheduler.pid)
Get-Content .\logs\work.harqis.scheduler.log -Tail 5
# If using Scheduled Task:
Get-ScheduledTask -TaskName work.harqis.scheduler | Get-ScheduledTaskInfo
```

Beat startup logs `beat: Starting...` and lists every scheduled task it will emit. If absent after 10s, surface the log file and stop.

---

## Step 6 — Start Celery worker

A single worker process listens to **all** queues from `-q` simultaneously (Celery's `-Q` flag accepts a comma-separated list natively — `core.apps.sprout` already wires this through). One process, multiple queues — no need to spawn separate workers per queue.

Resolve the queue list:
- If `-q` was provided, use it verbatim.
- Otherwise, default to `default` for both roles. (Node operators should explicitly pass `-q` so it's clear which queues this node owns.)
- Strip whitespace; the value must look like `q1,q2,q3` with no spaces.

Then export and launch (cross-platform):

```bash
export WORKFLOW_QUEUE="<comma,separated,queue,list>"
python scripts/launch.py worker
# Or pass --queues directly:
python scripts/launch.py worker --queues <comma,separated,queue,list>
```

`scripts/launch.py worker` honours `WORKFLOW_QUEUE` if pre-set in the environment, falling back to `default` only if unset.

Verify the worker registered with the broker (cross-platform):
```bash
celery -A core.apps.sprout.app.celery:SPROUT inspect ping --timeout=10
celery -A core.apps.sprout.app.celery:SPROUT inspect active_queues --timeout=10
```

`active_queues` should list every queue you passed via `-q`. If `ping` times out, the worker probably can't reach the broker — surface the broker URL and the last 10 lines of the worker log (`~/Library/Logs/harqis-worker.log` on macOS, `logs/work.harqis.worker.log` on Windows).

> **Note:** historic per-queue scripts have been replaced by the cross-platform `python scripts/launch.py worker --queues <list>` — one process can subscribe to multiple queues via the comma-separated list. Prefer `-q hud,tcg` over launching multiple workers in parallel.

---

## Step 7 — Start host-only services (frontend, MCP, Kanban)

**Skip the entire step if `role=node`.**

For each component below, the launch is cross-platform via `python scripts/launch.py <service>` (auto-start across boots via `python scripts/deploy.py --register`).

7a. **Frontend (FastAPI dashboard)** — runs `python scripts/launch.py frontend`. Probe `http://localhost:8000/health` until it returns 200, max 15s. Skip if `--no-frontend`.

7b. **MCP server daemon** — runs `python scripts/launch.py mcp`. Note: typically the MCP server is spawned as a stdio subprocess by Claude Desktop, so this daemon is only needed for SSH-stdio remote access or HTTP-transport setups. Skip if `--no-mcp`.

7c. **Projects orchestrator (acts as 1 agent worker on the host)** — runs `python scripts/launch.py kanban` (module is `agents.projects.orchestrator.local`). Default `KANBAN_NUM_AGENTS=1`. If `--num-agents N` was passed, export it before launching. If `--dry-run`, set `KANBAN_DRY_RUN=1`. Skip if `--no-kanban`.

After loading, tail the last 5 lines of `logs/projects_audit.jsonl` to confirm the orchestrator is polling. If the file doesn't exist yet, that's fine — it's created on the first poll.

7d. **Flower (Celery task monitor)** — runs `python scripts/launch.py flower`. Listens on `127.0.0.1:5555` by default with HTTP Basic auth (`FLOWER_USER` + `FLOWER_PASSWORD` from `.env/apps.env`). To expose over Tailscale set `FLOWER_ADDRESS=0.0.0.0` before deploy. Probe `http://localhost:5555/api/workers` (with the configured basic auth) until it returns 200, max 15s. Skip if `--no-flower`. **Required env vars:** if `FLOWER_USER` or `FLOWER_PASSWORD` are unset, the daemon will exit immediately — surface the error and either set them or pass `--no-flower`.

---

## Step 8 — Teardown (if `--down` was passed)

For `host`: stop every active component for the role, then `docker compose down` (preserves volumes).
For `node`: stop only the worker; do NOT touch Docker (it doesn't run on nodes).

Use the cross-platform Python entry point:

```bash
python scripts/deploy.py --role <role> --down
# Internally: stop registered daemons (launchd / systemd / Scheduled Task) and PIDs from .run/ ; docker compose down (host only)
# Add --unregister to also remove any auto-start registrations.
```

Confirm everything stopped:
```bash
docker ps --filter label=com.docker.compose.project=harqis-work
# (Plus OS-native check: launchctl list | grep work.harqis  /  systemctl status harqis-*  /  Get-ChildItem .\.run\*.pid)
```

---

## Step 9 — Health check + summary

Print a single block:

```
HARQIS-WORK deploy complete (role=<role>)

Started:
  ✓ Docker stack       (rabbitmq, redis, elasticsearch, kibana, n8n, mosquitto, owntracks)   [host only]
  ✓ Scheduler          (Celery Beat — global dispatcher)                                      [host only]
  ✓ Worker             queues: <q1,q2,q3>      broker: <CELERY_BROKER_URL>
  ✓ Frontend           http://localhost:8000                                                  [host, optional]
  ✓ MCP server         daemon (stdio)                                                          [host, optional]
  ✓ Kanban orchestrator agents=<n>, profiles=<count>                                          [host, optional]
  ✓ Flower              http://localhost:5555  (basic-auth: $FLOWER_USER:$FLOWER_PASSWORD)    [host, optional]

Logs:
  ~/Library/Logs/harqis-scheduler.log
  ~/Library/Logs/harqis-worker.log
  ~/Library/Logs/harqis-frontend.log
  ~/Library/Logs/harqis-kanban.log
  ~/Library/Logs/harqis-flower.log
  logs/projects_audit.jsonl

Stop:
  python scripts/deploy.py --role <role> --down
```

For each `✗` (failed component), print remediation: log file path + the exact command to retry that component.

---

## Appendix A — LaunchAgent plist template

LaunchAgent plists are generated automatically by `python scripts/deploy.py --register`. Each plist's `ProgramArguments` invokes the cross-platform launcher with the appropriate service name:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$REPO_ROOT/.venv/bin/python</string><string>$REPO_ROOT/scripts/launch.py</string><string>SERVICE</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/harqis-LABEL.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/harqis-LABEL.err.log</string>
</dict></plist>
```

Standard label-to-service mapping:

| Plist label | Service (`python scripts/launch.py <service>`) |
|---|---|
| `work.harqis.scheduler` | `scheduler` |
| `work.harqis.worker` | `worker` |
| `work.harqis.frontend` | `frontend` |
| `work.harqis.mcp` | `mcp` |
| `work.harqis.kanban` | `kanban` |
| `work.harqis.flower` | `flower` |

---

## Appendix B — Linux equivalents (for VPS nodes)

On Linux nodes, `python scripts/deploy.py --register` writes a systemd user unit. The generated unit looks like:

```ini
# ~/.config/systemd/user/harqis-worker.service (or /etc/systemd/system/ for system-wide)
[Unit]
Description=HARQIS Celery worker
After=network-online.target

[Service]
WorkingDirectory=/opt/harqis
EnvironmentFile=/opt/harqis/.env/apps.env
Environment=WORKFLOW_QUEUE=default
ExecStart=/opt/harqis/.venv/bin/python /opt/harqis/scripts/launch.py worker
Restart=on-failure

[Install]
WantedBy=default.target
```

Enable: `systemctl --user enable --now harqis-worker`. Repeat for `harqis-scheduler.service` (host only).

---

## Appendix C — Windows (Scheduled Tasks)

On Windows, `python scripts/deploy.py --register` (must run elevated) installs each daemon as a Scheduled Task that runs `AtStartup` and invokes the cross-platform launcher.

**Service mapping:**

| Scheduled Task name | Launcher invocation |
|---|---|
| `work.harqis.scheduler` | `python scripts/launch.py scheduler` |
| `work.harqis.worker` | `python scripts/launch.py worker` |
| `work.harqis.frontend` | `python scripts/launch.py frontend` |
| `work.harqis.mcp` | `python scripts/launch.py mcp` |
| `work.harqis.kanban` | `python scripts/launch.py kanban` |
| `work.harqis.flower` | `python scripts/launch.py flower` |

**Foreground launch (ad-hoc — survives console close, dies on logout):**

```powershell
python scripts/deploy.py --role host
python scripts/deploy.py --role node --queues hud,tcg,default
python scripts/deploy.py --role host --down
```

PIDs are tracked in `.run\<label>.pid`. Logs go to `logs\<label>.log` and `logs\<label>.log.err`.

**Persistent (production — Scheduled Task that runs `AtStartup`):**

```powershell
# One-time registration on a fresh machine (must run elevated)
python scripts/deploy.py --role host --register

# Subsequent restarts (auto-start fires on boot)
python scripts/deploy.py --role host
Start-ScheduledTask -TaskName work.harqis.worker  # or via Scheduled Task

# Remove all persistent registrations
python scripts/deploy.py --role host --down --unregister
```

`scripts/deploy.py` auto-strips whitespace from `--queues`, exports `WORKFLOW_QUEUE` for the worker daemon, exports `KANBAN_NUM_AGENTS` for the kanban daemon, and never starts Beat on a node (the rule is enforced by the role-to-service mapping table).

**Caveats:**
- `git rev-parse --show-toplevel` must work — install Git for Windows (`scoop install git` or `winget install Git.Git`).
- `python` must resolve to the `.venv\Scripts\python.exe` after `Activate.ps1` runs — verified inside the launcher.
- `docker compose` requires Docker Desktop. For Windows nodes that only run workers (no Docker), pass `--role node` to skip the Docker block entirely.
- Execution policy: to make `python` invocations on PowerShell painless, `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

---

## Quality checklist (verify before finishing)

- [ ] Role validated (`host` or `node` only)
- [ ] Queue list parsed cleanly (no spaces, comma-separated)
- [ ] Prereqs checked before any service starts
- [ ] Docker stack healthy before workers attach (host)
- [ ] **Beat scheduler started on host *only*** (never on node — would duplicate every periodic task)
- [ ] Worker `WORKFLOW_QUEUE` exported with the resolved queue list
- [ ] Worker registered with broker (`celery inspect ping` succeeds)
- [ ] Worker subscribed to every requested queue (`celery inspect active_queues` lists all of them)
- [ ] Frontend `/health` returns 200 (host, unless `--no-frontend`)
- [ ] Kanban orchestrator polling (host, unless `--no-kanban`)
- [ ] Flower `/api/workers` returns 200 with `FLOWER_USER:FLOWER_PASSWORD` basic auth (host, unless `--no-flower`)
- [ ] If `FLOWER_USER`/`FLOWER_PASSWORD` are unset, the Flower daemon errored cleanly — surface the missing env var rather than silently skipping
- [ ] Failures surface log path + retry command (no silent failures)
- [ ] `--down` cleanly stops all components for the role and only those

---

## Maintenance

When **new components** are added to harqis-work (a new daemon, a new orchestrator, a new always-on service), update this skill in three places:

1. **Step 7 host-only services** — add a new `7d/7e/...` subsection
2. **Appendix A and Appendix C** label-to-service tables — add the new launcher mapping
3. **Quality checklist** — add a verification line item

Also update:
- `scripts/launch.py` — add a new service handler so `python scripts/launch.py <name>` works
- `scripts/deploy.py` — add a new entry + a `--no-<name>` CLI flag

When **new MCP apps** are added (via `/new-service-app`), no update to this skill is needed — they're picked up automatically by `mcp/server.py` on next MCP daemon start.
