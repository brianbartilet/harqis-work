# scripts/

Operational scripts for the **harqis-work** platform: deployment, Celery workers/scheduler, Flower monitoring, environment setup, Tailscale ACLs, and a Claude-powered docs agent.

The tree is organised by runtime:

| Path | Purpose |
|---|---|
| [`sh/`](#sh--linuxmacos-bash) | Bash scripts (Linux / macOS) |
| `*.bat` at the root | Windows equivalents of the bash scripts |
| [`tailscale/`](#tailscale) | Tailscale ACL policy (`.hujson`) |
| [`run_agent_prompt.py`](#run_agent_promptpy) | Claude-driven doc / code-smell regeneration |

Two scripts drive everything else:

- **Stack lifecycle** → [`sh/deploy.sh`](#shdeploysh) (macOS/Linux) — brings the Docker stack up/down and optionally starts Celery workers in one shot.
- **Env bootstrap** → [`sh/set_env_workflows.sh`](#shset_env_workflowssh) / [`set_env_workflows.bat`](#set_env_workflowsbat) — sourced by every worker/scheduler script. Loads `.env/apps.env`, sets `PYTHONPATH`, `ROOT_DIRECTORY`, `WORKFLOW_CONFIG`, `APP_CONFIG_FILE`.

All scripts assume they are run from inside the `harqis-work` repo (they use `git rev-parse --show-toplevel` to find the root).

---

## `sh/` — Linux/macOS bash

### `sh/deploy.sh`
Starts (or stops, or restarts) the full OpenClaw server stack defined in `docker-compose.yml`, and optionally also the Celery workers + Beat scheduler.

**Usage**
```bash
./scripts/sh/deploy.sh               # docker compose up -d
./scripts/sh/deploy.sh --workers     # also start Beat + default + adhoc + tcg workers
./scripts/sh/deploy.sh --with-core   # also include harqis-core's compose (Prism mock)
./scripts/sh/deploy.sh --down        # stop everything
./scripts/sh/deploy.sh --restart     # down + up -d
./scripts/sh/deploy.sh --help
```

**What it does, step by step**

1. **Resolve paths.** `REPO_ROOT` via `git rev-parse --show-toplevel`; `VENV=$REPO_ROOT/.venv`.
2. **Parse flags** — `--workers`, `--with-core`, `--down`, `--restart`, `-h|--help`.
3. **Load secrets.** In priority order:
   1. macOS Keychain (generic-password, account `harqis`) — keys read: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `HARQIS_FERNET_KEY`, `CLOUDFLARE_TUNNEL_TOKEN`.
   2. Fallback `.env/apps.env` at repo root (sourced with `set -a`).
   3. Otherwise prints a warning and continues.
4. **Build compose file list.** Always includes `$REPO_ROOT/docker-compose.yml`. If `--with-core`, also resolves `harqis-core`'s bundled compose via `python -c "import core..."` from the venv, and adds it (adds the Prism mock server).
5. **Docker compose** — based on `MODE`:
   - `up`: `docker compose … up -d`
   - `down`: `docker compose … down`
   - `restart`: `down` then `up -d`
6. **Per-service, the compose stack brings up:**
   | Container | Image | Purpose |
   |---|---|---|
   | `rabbitmq` | `rabbitmq:3-management-alpine` | Celery broker (AMQP 5672, mgmt UI 15672) |
   | `redis` | `redis:7-alpine` | Celery result backend (6379) |
   | `mosquitto` | `eclipse-mosquitto:latest` | MQTT broker (1883) |
   | `owntracks-recorder` | `owntracks/recorder:latest` | GPS/location sink (8083) |
   | `n8n` | `docker.n8n.io/n8nio/n8n:latest` | Workflow UI + webhooks (5678) |
   | `elasticsearch` | `elasticsearch:8.13.0` | Task / app log store (9200) |
   | `kibana` | `kibana:8.13.0` | Log visualisation (5601) |
   | `cloudflared` | `cloudflare/cloudflared:latest` | Cloudflare Tunnel (no local port) |
   | `ngrok` | `ngrok/ngrok:latest` | Fallback public tunnel |
7. **Start Celery workers** (only if `--workers` and not `--down`):
   1. `source $VENV/bin/activate`
   2. `source $REPO_ROOT/scripts/linux/set_env_workflows.sh` *(see note on path mismatch below)*
   3. Fires four background Python processes:
      - `python run_workflows.py beat` — Celery Beat scheduler
      - `WORKFLOW_QUEUE=default python run_workflows.py worker`
      - `WORKFLOW_QUEUE=adhoc   python run_workflows.py worker`
      - `WORKFLOW_QUEUE=tcg     python run_workflows.py worker`
   4. Prints `pkill -f run_workflows.py` as the stop hint.
8. **Summary.** If not `--down`, prints `docker compose … ps` as a final status table.

> **Note — header / source path mismatch.** The script's usage header says `./scripts/macos/deploy.sh` and line 111 sources `scripts/linux/set_env_workflows.sh`, but the actual file is at `scripts/sh/set_env_workflows.sh`. Either fix the sourced path or symlink `scripts/linux` → `scripts/sh` before using `--workers`.

---

### `sh/set_env_workflows.sh`
Sources env vars for Celery. **Source** this (`source …`), don't execute.

1. Resolves `path_git_root` (via `git rev-parse --show-toplevel`) and its own script dir.
2. Reads `$REPO_ROOT/.env/apps.env` line-by-line, skipping blanks and `#` comments, trimming surrounding quotes, and `export`ing each `KEY=VALUE`.
3. Updates `PYTHONPATH` to include the repo root + its own dir.
4. Exports app paths:
   - `ROOT_DIRECTORY` = repo root
   - `PATH_APP_CONFIG` = repo root
   - `PATH_APP_CONFIG_SECRETS` = `$REPO_ROOT/.env`
5. Exports Celery / Sprout config:
   - `WORKFLOW_CONFIG=workflows.config`
   - `APP_CONFIG_FILE=apps_config.yaml`

---

### `sh/set_env.sh`
**Older, simpler variant** of `set_env_workflows.sh`. Only sets `PYTHONPATH` (adds repo root + `core/` + script dir) and `WORKFLOW_CONFIG=WORKFLOW_CONFIG=demo.builder.config` *(sic — double-prefixed string)*. Kept for the demo builder path; new scripts should use `set_env_workflows.sh`.

---

### `sh/run_workflow_scheduler.sh`
Starts Celery Beat (the periodic task scheduler):

1. `source set_env_workflows.sh`
2. `cd $ROOT_DIRECTORY`
3. `python run_workflows.py scheduler`

---

### `sh/run_workflow_worker.sh`
Starts a Celery worker on the **default** queue:

1. `source set_env_workflows.sh`
2. `cd $ROOT_DIRECTORY`
3. `export WORKFLOW_QUEUE=default`
4. `python run_workflows.py worker`

### `sh/run_workflow_worker_hud.sh`
Same as `run_workflow_worker.sh` but `WORKFLOW_QUEUE=hud`. Used on the N100 Windows / HUD node.

### `sh/run_workflow_worker_tcg.sh`
Same as above but `WORKFLOW_QUEUE=tcg`. Used for the TCG marketplace tasks.

> `adhoc` queue has no dedicated `.sh` — start it via `deploy.sh --workers` or inline: `WORKFLOW_QUEUE=adhoc python run_workflows.py worker`.

---

### `sh/flower.sh`
Starts the **Celery Flower** monitoring UI:

1. `source set_env_workflows.sh`
2. `cd $ROOT_DIRECTORY`
3. Requires `FLOWER_USER` and `FLOWER_PASS` env vars (from `.env/apps.env`); exits 1 if missing.
4. Runs:
   ```
   python -m celery -A core.apps.sprout.app.celery:SPROUT flower \
       --port=5555 --address=127.0.0.1 \
       --basic-auth="${FLOWER_USER}:${FLOWER_PASS}"
   ```
5. Binds to `127.0.0.1` — reach it only via `ssh -L` tunnel or Tailscale Serve/Funnel.

---

## Top-level `.bat` — Windows

Each `.bat` pairs with a matching `.sh`. The pattern in every worker/scheduler batch is:
```bat
call ..\.venv\Scripts\activate.bat
call set_env_workflows.bat
cd ..
set "WORKFLOW_QUEUE=<queue>"
python run_workflows.py worker
```

Equivalents:

| Windows | Linux/macOS | Queue |
|---|---|---|
| `run_workflow_scheduler.bat` | `sh/run_workflow_scheduler.sh` | (Beat, not a worker) |
| `run_workflow_worker.bat` | `sh/run_workflow_worker.sh` | `default` |
| `run_workflow_worker_adhoc.bat` | *(none — use inline)* | `adhoc` |
| `run_workflow_worker_hud.bat` | `sh/run_workflow_worker_hud.sh` | `hud` |
| `run_workflow_worker_tcg.bat` | `sh/run_workflow_worker_tcg.sh` | `tcg` |
| `flower.bat` | `sh/flower.sh` | (monitoring) |
| `set_env_workflows.bat` | `sh/set_env_workflows.sh` | — |

### `set_env_workflows.bat`
Same responsibilities as the `.sh` version:
1. Resolves `path_git_root` via `git rev-parse --show-toplevel`.
2. Reads `%path_git_root%\.env\apps.env`, skips `#` comments and blank lines, `set`s each `KEY=VALUE`.
3. Updates `PYTHONPATH`, sets `ROOT_DIRECTORY`, `PATH_APP_CONFIG`, `PATH_APP_CONFIG_SECRETS`, `WORKFLOW_CONFIG=workflows.config`, `APP_CONFIG_FILE=apps_config.yaml`.

### `flower.bat`
Windows version of `flower.sh`. **Known bug:** line 24 uses `%FLOWER_PASSWORD%` but the validated variable is `%FLOWER_PASS%` — Flower will start with an empty password on Windows until fixed.

### `run_hud_tasks.bat`
Ad-hoc helper — **not** started by any scheduler. Activates the venv, sources env, then runs:
```
python ..\workflows\n8n\utilities\send_flower_task.py \
       --send-all --queue hud --user harqistesting --password H3ll0p0z1v23
```
Fires all HUD tasks at the `hud` queue via Flower's REST API. **The basic-auth credentials are hard-coded in this file** — move them to `FLOWER_USER` / `FLOWER_PASS` in `.env/apps.env` if this script is used beyond local development.

---

## `tailscale/`

### `tailscale/acl-policy.hujson`
The authoritative ACL for the harqis-work / OpenClaw tailnet. **This file is gitignored** — it lives only on the local machine and is not committed to the repo. A copy is kept in Google Drive at `harqis/backup-20260421-000004.tgz` (original backup location) for recovery.

To apply the policy, paste it into <https://login.tailscale.com/admin/acls> or run:
```bash
tailscale acls set --file scripts/tailscale/acl-policy.hujson
```

**Tag model** (run on each machine once after `tailscale up`):
| Machine | Tag |
|---|---|
| Mac Mini (server) | `tag:server` |
| VPS workers | `tag:worker` |
| N100 Windows (HUD) | `tag:hud-node` |
| Laptop / phone | `tag:personal` |

**Rules:**
- `tag:worker` → `tag:server` on `5672` (RabbitMQ), `6379` (Redis), `9200` (Elasticsearch)
- `tag:hud-node` → `tag:server` on `5672`, `6379` (broker + result backend only)
- `tag:personal` → `tag:server:*` (full access)
- `tag:server` → `tag:worker:22`, `tag:hud-node:22` (SSH for deploy / health)
- `tag:personal` → `tag:server:22`, `tag:worker:22` (SSH)
- `dns.magic = true` — short-names like `harqis-ones-mac-mini` resolve without `.ts.net`.

Port reference is inline at the top of the file.

---

## `run_agent_prompt.py`

Claude-powered regenerator for top-level docs. Reads a prompt from `prompts/`, builds repo context, calls the Anthropic API, and overwrites the output file.

**Usage**
```bash
python scripts/run_agent_prompt.py --agent docs          # regenerate README.md
python scripts/run_agent_prompt.py --agent code_smells   # regenerate CODE_SMELLS.md
python scripts/run_agent_prompt.py --agent both
```

**Steps**

1. Validate `ANTHROPIC_API_KEY` is set (exits 1 otherwise).
2. Load the agent config from `AGENT_CONFIG`:
   - `docs`: prompt `prompts/docs_agent.md` → output `README.md`
   - `code_smells`: prompt `prompts/code_smells.md` → output `CODE_SMELLS.md`
3. Build system prompt = prompt-file contents + an *Output instruction* that tells Claude to emit raw Markdown (no fences wrapping the whole file).
4. Build context via the agent's `context_fn`:
   - **docs**: current `README.md` + `CLAUDE.md`, a depth-3 dir tree (skipping `__pycache__`, `.venv`, `node_modules`, caches, etc.), all `apps/*/README.md`, all `workflows/*/README.md`.
   - **code_smells**: existing `CODE_SMELLS.md`, dir tree, and a hard-coded list of ~18 key source files (HUD tasks, TCG workflows, Rainmeter helpers, workflow config, etc.).
5. Call `client.messages.create` with `model="claude-opus-4-6"`, `max_tokens=8096`.
6. Strip any outer ```` ``` ```` fence Claude may have wrapped around the output.
7. Write to `README.md` or `CODE_SMELLS.md` at the repo root; print the token usage.

**Guardrails** — `MAX_FILE_CHARS = 60_000` per file, `MAX_CONTEXT_CHARS = 180_000` total; both truncate with a `[file truncated]` / `[context truncated]` marker when exceeded.

---

## Quick recipes

**Bring the stack up on the Mac Mini (server):**
```bash
./scripts/sh/deploy.sh --workers
```

**Stop everything:**
```bash
./scripts/sh/deploy.sh --down
```

**Just the HUD worker on the N100 (Windows):**
```cmd
scripts\run_workflow_worker_hud.bat
```

**Watch Celery from the Mac Mini (localhost only):**
```bash
./scripts/sh/flower.sh
# then browse http://127.0.0.1:5555 (use tailscale serve or ssh -L to expose)
```

**Regenerate docs after big changes:**
```bash
python scripts/run_agent_prompt.py --agent both
```
