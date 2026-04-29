Deploy the harqis-work platform on this machine — full stack ("host") or worker-only ("node"). Walks through Docker services, env loading, scheduler, workers, frontend, MCP server, and the Kanban agent orchestrator. **Auto-detects the OS** and dispatches to the right script set: macOS / Linux use `scripts/sh/deploy.sh` (LaunchAgents / systemd); Windows uses `scripts/ps/deploy.ps1` (Start-Process or Scheduled Tasks). If `host` is selected, the Kanban orchestrator also acts as 1 in-process agent worker.

## Arguments

`$ARGUMENTS` format:

```
<role> [-q <queues>] [-p <profile>] [--hw <labels>] [--down] [--no-frontend] [--no-mcp] [--no-kanban] [--no-flower] [--num-agents N] [--dry-run]
```

| Token | Required | Description |
|---|---|---|
| `role` | Yes | `host` or `node`. `host` is the always-on hub (Docker stack + Beat scheduler + worker + frontend + MCP + Kanban + Flower). `node` is a remote worker that connects to the host's broker — and **also** runs a profile-scoped Kanban orchestrator unless `--no-kanban` is set. |
| `-q`, `--queues <LIST>` | No | Comma-separated Celery queue list for the worker, e.g. `hud,tcg,default` or `code,write`. **Default:** `default` (both roles). |
| `-p`, `--profile <ID>` | Yes for `node`, optional for `host` | Kanban profile id this orchestrator owns (e.g. `agent:default`, `agent:code`, `agent:write`). The orchestrator only claims cards whose resolved profile matches. **Defaults:** host → `agent:default` (so the host also acts as 1 default-queue node); node → **no default — must be passed**. If the user invokes `/deploy-harqis node` without `-p`, **ask which profile** before continuing (list available profiles from `agents/kanban/profiles/examples/`). |
| `--hw <LABELS>` | No | Comma-separated `hw:*` labels this orchestrator satisfies, e.g. `hw:linux,hw:gpu`. Unset = auto-detect from `platform.system()` (darwin → `hw:darwin,hw:macos`; linux → `hw:linux`; windows → `hw:windows`). Cards with no `hw:*` label run on any node; cards with `hw:windows` only run on Windows nodes. |
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

### Kanban routing — profile + hw filters

The Kanban orchestrator runs on **both** host and node. Each instance polls the same Trello/Jira board but only claims cards that match its filters:

1. **Profile filter (`-p`)** — Card's resolved profile id must equal `--profile`. Cards with `agent:code` label go to the orchestrator filtered to `agent:code`; cards with no `agent:*` label fall back to `agent:default`.
2. **Hardware filter (`--hw`)** — Card's `hw:*` labels must intersect the orchestrator's `hw_labels`. Cards with no `hw:*` label match any orchestrator.

Both filters AND together. A card matching neither filter is skipped silently — another orchestrator is the intended owner.

If the user invokes `/deploy-harqis node` without `-p`, **stop and ask which profile** (e.g. `agent:code`, `agent:write`). List available profiles by reading filenames from `agents/kanban/profiles/examples/`. Don't guess.

---

## Step 1 — Validate role and detect environment

Resolve the absolute repo root using `git rev-parse --show-toplevel`. From here on, refer to it as `$REPO_ROOT`.

Detect the OS first — every subsequent step branches on this:

| Detection | macOS / Linux | Windows |
|---|---|---|
| Test | `uname -s` returns `Darwin`/`Linux` | `$env:OS` is `Windows_NT` (or `uname -s` not available) |
| Script directory | `$REPO_ROOT/scripts/sh/` | `$REPO_ROOT/scripts/ps/` |
| Deploy entrypoint | `bash scripts/sh/deploy.sh` | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ps/deploy.ps1` |
| Python venv | `.venv/bin/python` | `.venv\Scripts\python.exe` |
| Daemon mechanism | macOS LaunchAgent (`launchctl`); Linux systemd | `Start-Process -WindowStyle Hidden` (default) or Windows Scheduled Tasks (`-Register`) |
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
- For Kanban: `$REPO_ROOT/agents/kanban/profiles/examples/` should contain at least one `.yaml` profile.

**`node`:**
- `CELERY_BROKER_URL` must be set in `.env/apps.env` (or via `set_env_worker_remote.sh`) and point to the host's broker (e.g. `amqp://guest:guest@<host-tailscale-ip>:5672/`).
- Tailscale connectivity to the host (`tailscale ping <host>`) is recommended.

If any check fails, print the missing item and the exact command to fix it (e.g. "Run `open -a Docker` then re-run `/deploy-harqis host`"). Stop without making changes.

---

## Step 3 — Bring up Docker services (host only)

Run `bash "$REPO_ROOT/scripts/sh/deploy.sh" --role host --docker-only` (or, on `node`, skip this step).

After it returns, verify each container is healthy:
```bash
docker compose -f "$REPO_ROOT/docker-compose.yml" ps --format json
```

Wait up to 60s for `rabbitmq`, `redis`, and `elasticsearch` to report healthy. If any container is unhealthy after 60s, surface its last 20 log lines via `docker compose logs --tail=20 <name>` and stop — do not proceed to start workers against an unhealthy broker.

---

## Step 4 — Load environment

Source `$REPO_ROOT/scripts/sh/set_env_workflows.sh` to populate:
- `PYTHONPATH`, `ROOT_DIRECTORY`, `PATH_APP_CONFIG`, `PATH_APP_CONFIG_SECRETS`
- `WORKFLOW_CONFIG=workflows.config`, `APP_CONFIG_FILE=apps_config.yaml`
- `CELERY_BROKER_URL` (defaults to `amqp://guest:guest@localhost:5672/` on the host; node should override before sourcing).

For `node`, also source `set_env_worker_remote.sh` if the file exists — it sets `CONFIG_SOURCE=redis|http` and queue overrides.

---

## Step 5 — Start Celery Beat scheduler (host only)

Celery Beat is the dispatcher: it reads `workflows.config.beat_schedule` and emits scheduled tasks to the broker. **It must run on exactly one machine across the entire cluster.** Running it on a node would create a second scheduler and every periodic task would fire twice (or N times, for N nodes).

- **macOS host:** `launchctl load ~/Library/LaunchAgents/work.harqis.scheduler.plist` (plist's `ProgramArguments` runs `scripts/sh/run_scheduler_daemon.sh`). If the plist file doesn't exist, generate it from Appendix A and load it.
- **Linux host:** `systemctl start harqis-scheduler.service` (unit file in Appendix B), or background `nohup scripts/sh/run_scheduler_daemon.sh &`.
- **Windows host:** `deploy.ps1` calls `Start-Daemon` for `work.harqis.scheduler`, which spawns `scripts/ps/run_scheduler_daemon.ps1` via `Start-Process -WindowStyle Hidden` and writes the PID to `.run/work.harqis.scheduler.pid`. For persistence across reboots/logouts, pass `-Register` to install it as a Scheduled Task that runs `AtStartup`.
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

Then export and load — pick the OS:

```bash
# macOS / Linux
export WORKFLOW_QUEUE="<comma,separated,queue,list>"
launchctl unload "$HOME/Library/LaunchAgents/work.harqis.worker.plist" 2>/dev/null || true
launchctl load   "$HOME/Library/LaunchAgents/work.harqis.worker.plist"
```

```powershell
# Windows — deploy.ps1 already handles this; this is what it does internally:
$env:WORKFLOW_QUEUE = "<comma,separated,queue,list>"
.\scripts\ps\deploy.ps1 -Role node -Queues $env:WORKFLOW_QUEUE
```

Both `run_worker_daemon.sh` and `run_worker_daemon.ps1` honour `WORKFLOW_QUEUE` if pre-set in the environment, falling back to `default` only if unset.

Verify the worker registered with the broker (cross-platform):
```bash
celery -A core.apps.sprout.app.celery:SPROUT inspect ping --timeout=10
celery -A core.apps.sprout.app.celery:SPROUT inspect active_queues --timeout=10
```

`active_queues` should list every queue you passed via `-q`. If `ping` times out, the worker probably can't reach the broker — surface the broker URL and the last 10 lines of the worker log (`~/Library/Logs/harqis-worker.log` on macOS, `logs/work.harqis.worker.log` on Windows).

> **Note:** historic per-queue scripts (`run_workflow_worker_hud.sh`/`.bat`, `run_workflow_worker_tcg.sh`/`.bat`, etc.) still exist for ad-hoc launches but the deploy skill no longer uses them — they predate the multi-queue daemon and would spawn one process per queue, which is wasteful for nodes that own several queues. Prefer `-q hud,tcg` over launching the two scripts in parallel.

---

## Step 7 — Start host-only services (frontend, MCP, Kanban)

**Skip the entire step if `role=node`.**

For each component below, the launch mechanism depends on OS:
- **macOS:** `launchctl load <plist>` (auto-generate from Appendix A if missing)
- **Linux:** `systemctl start <unit>` (Appendix B)
- **Windows:** `deploy.ps1 -Role host` already started them via `Start-Process -WindowStyle Hidden` and tracks PIDs in `.run/<label>.pid`

7a. **Frontend (FastAPI dashboard)** — runs `run_frontend_daemon.{sh,ps1}`. Probe `http://localhost:8000/health` until it returns 200, max 15s. Skip if `--no-frontend`.

7b. **MCP server daemon** — runs `run_mcp_daemon.{sh,ps1}`. Note: typically the MCP server is spawned as a stdio subprocess by Claude Desktop, so this daemon is only needed for SSH-stdio remote access or HTTP-transport setups. Skip if `--no-mcp`.

7c. **Kanban orchestrator (acts as 1 agent worker on the host)** — runs `run_kanban_daemon.{sh,ps1}`. Default `KANBAN_NUM_AGENTS=1`. If `--num-agents N` was passed, export it before launching (the PowerShell deploy.ps1 sets `$env:KANBAN_NUM_AGENTS` automatically). If `--dry-run`, set `KANBAN_DRY_RUN=1`. Skip if `--no-kanban`.

After loading, tail the last 5 lines of `logs/kanban_audit.jsonl` to confirm the orchestrator is polling. If the file doesn't exist yet, that's fine — it's created on the first poll.

7d. **Flower (Celery task monitor)** — runs `run_flower_daemon.{sh,ps1}`. Listens on `127.0.0.1:5555` by default with HTTP Basic auth (`FLOWER_USER` + `FLOWER_PASSWORD` from `.env/apps.env`). To expose over Tailscale set `FLOWER_ADDRESS=0.0.0.0` before deploy. Probe `http://localhost:5555/api/workers` (with the configured basic auth) until it returns 200, max 15s. Skip if `--no-flower`. **Required env vars:** if `FLOWER_USER` or `FLOWER_PASSWORD` are unset, the daemon will exit immediately — surface the error and either set them or pass `--no-flower`.

If a plist file (macOS) is missing, generate it on-the-fly using Appendix A and persist it. On Windows, deploy.ps1 handles this automatically — no plist generation needed.

---

## Step 8 — Teardown (if `--down` was passed)

For `host`: stop every active component for the role, then `docker compose down` (preserves volumes).
For `node`: stop only the worker; do NOT touch Docker (it doesn't run on nodes).

Choose the right command per OS — both `deploy.sh --down` and `deploy.ps1 -Down` already implement these:

```bash
# macOS / Linux
./scripts/sh/deploy.sh --role <role> --down
# Internally: launchctl unload <plist>... ; docker compose down (host only)
```

```powershell
# Windows
.\scripts\ps\deploy.ps1 -Role <role> -Down
# Internally: kill PIDs from .run\<label>.pid ; docker compose down (host only)
# Add -Register to also Unregister-ScheduledTask if you previously registered.
```

Confirm everything stopped:
```bash
# macOS / Linux
launchctl list | grep work.harqis | wc -l                                # should be 0
docker ps --filter label=com.docker.compose.project=harqis-work | wc -l  # 0 on host
```

```powershell
# Windows
Get-ChildItem .\.run\*.pid 2>$null | Measure-Object | Select-Object Count   # should be 0
docker ps --filter label=com.docker.compose.project=harqis-work
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
  logs/kanban_audit.jsonl

Stop:
  ./scripts/sh/deploy.sh --role <role> --down
```

For each `✗` (failed component), print remediation: log file path + the exact command to retry that component.

---

## Appendix A — LaunchAgent plist template

When auto-generating a plist file in Step 7, use this skeleton (replace `LABEL` and `SCRIPT`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$REPO_ROOT/scripts/sh/SCRIPT</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/harqis-LABEL.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/harqis-LABEL.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
</dict></plist>
```

Standard label-to-script mapping:

| Plist label | Script |
|---|---|
| `work.harqis.scheduler` | `run_scheduler_daemon.sh` |
| `work.harqis.worker` | `run_worker_daemon.sh` |
| `work.harqis.frontend` | `run_frontend_daemon.sh` |
| `work.harqis.mcp` | `run_mcp_daemon.sh` |
| `work.harqis.kanban` | `run_kanban_daemon.sh` |
| `work.harqis.flower` | `run_flower_daemon.sh` |

---

## Appendix B — Linux equivalents (for VPS nodes)

On Linux nodes there are no LaunchAgents. Use either `tmux`/`nohup` for ad-hoc sessions or systemd units for production:

```ini
# /etc/systemd/system/harqis-worker.service
[Unit]
Description=HARQIS Celery worker
After=network-online.target

[Service]
User=harqis
WorkingDirectory=/opt/harqis
EnvironmentFile=/opt/harqis/.env/apps.env
Environment=WORKFLOW_QUEUE=default
ExecStart=/opt/harqis/scripts/sh/run_worker_daemon.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable: `sudo systemctl enable --now harqis-worker`. Repeat for `harqis-scheduler.service` (host only).

---

## Appendix C — Windows (PowerShell + Scheduled Tasks)

The Windows path uses PowerShell scripts in `scripts/ps/` and Windows-native daemon hosting via either `Start-Process -WindowStyle Hidden` (ad-hoc, default) or Task Scheduler (`-Register` flag, persistent across reboot/logout).

**Daemon scripts (one-to-one with the `.sh` versions):**

| Label | PowerShell script |
|---|---|
| `work.harqis.scheduler` | `scripts/ps/run_scheduler_daemon.ps1` |
| `work.harqis.worker` | `scripts/ps/run_worker_daemon.ps1` |
| `work.harqis.frontend` | `scripts/ps/run_frontend_daemon.ps1` |
| `work.harqis.mcp` | `scripts/ps/run_mcp_daemon.ps1` |
| `work.harqis.kanban` | `scripts/ps/run_kanban_daemon.ps1` |
| `work.harqis.flower` | `scripts/ps/run_flower_daemon.ps1` |

**Background launch (default — survives console close, dies on logout):**

```powershell
.\scripts\ps\deploy.ps1 -Role host
.\scripts\ps\deploy.ps1 -Role node -Queues hud,tcg,default
.\scripts\ps\deploy.ps1 -Role host -Down
```

PIDs are tracked in `.run\<label>.pid`. Logs go to `logs\<label>.log` and `logs\<label>.log.err`.

**Persistent (production — Scheduled Task that runs `AtStartup`):**

```powershell
# One-time registration on a fresh machine (must run elevated)
.\scripts\ps\deploy.ps1 -Role host -Register

# Subsequent restarts
.\scripts\ps\deploy.ps1 -Role host             # starts via Start-Process
Start-ScheduledTask -TaskName work.harqis.worker  # or via Scheduled Task

# Remove all persistent registrations
.\scripts\ps\deploy.ps1 -Role host -Down -Register
```

The PowerShell deploy script auto-strips whitespace from `-Queues`, exports `$env:WORKFLOW_QUEUE` for the worker daemon, exports `$env:KANBAN_NUM_AGENTS` for the kanban daemon, and never starts Beat on a node (the rule is enforced by the role-to-script mapping table).

**Caveats:**
- `git rev-parse --show-toplevel` must work — install Git for Windows (`scoop install git` or `winget install Git.Git`).
- `python` must resolve to the `.venv\Scripts\python.exe` after `Activate.ps1` runs — verified inside each daemon wrapper.
- `docker compose` requires Docker Desktop. For Windows nodes that only run workers (no Docker), omit `-Role host` and pass `-Role node` to skip the Docker block entirely.
- Execution policy: scripts assume `-ExecutionPolicy Bypass` is acceptable. To make this permanent for the user: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

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
2. **Appendix A and Appendix C** label-to-script tables — add the new plist label + script mapping (both `.sh` and `.ps1`)
3. **Quality checklist** — add a verification line item

Also update **all four** of:
- `scripts/sh/deploy.sh` — `PLIST_<NAME>`, `WITH_<NAME>` flag, `--no-<name>` cli flag
- `scripts/ps/deploy.ps1` — `$services` array entry + matching `-No<Name>` switch
- `scripts/sh/run_<component>_daemon.sh` — Bash daemon wrapper
- `scripts/ps/run_<component>_daemon.ps1` — PowerShell daemon wrapper

Both wrappers must source the env loader for their OS (`set_env_workflows.sh` or `set_env_workflows.ps1`) before exec-ing the Python entry point.

When **new MCP apps** are added (via `/new-service-app`), no update to this skill is needed — they're picked up automatically by `mcp/server.py` on next MCP daemon start.
