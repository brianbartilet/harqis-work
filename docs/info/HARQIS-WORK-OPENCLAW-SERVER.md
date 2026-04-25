# OpenClaw Server — Deployment & Migration Guide

**Hardware target:** Mac Mini M4, 16 GB RAM, 256 GB SSD.
**Related:** [VPS-CLUSTER-AGENT-DESIGN.md](../thesis/VPS-CLUSTER-AGENT-DESIGN.md) · [OPEN_CLAW_CONTROLLER.md](OPEN_CLAW_CONTROLLER.md)  
**Date:** 2026-04-14

---

## Table of Contents

1. [Overview — The OpenClaw Server Concept](#1-overview--the-openclaw-server-concept)
2. [Service Inventory](#2-service-inventory)
3. [Mac Mini Deployment Guide (macOS)](#3-mac-mini-deployment-guide-macos)
4. [Docker & docker-compose Review](#4-docker--docker-compose-review)
5. [Migrating from Windows N100 to Mac Mini](#5-migrating-from-windows-n100-to-mac-mini)
6. [OpenClaw Server Configuration](#6-openclaw-server-configuration)
7. [Connecting Worker Nodes](#7-connecting-worker-nodes)
8. [Monitoring and Observability](#8-monitoring-and-observability)
9. [Recommended Production docker-compose](#9-recommended-production-docker-compose)
10. [Maintenance Runbook](#10-maintenance-runbook)
11. [Tailscale VPN Access & Access Control](#11-tailscale-vpn-access--access-control)

---

## 1. Overview — The OpenClaw Server Concept

The **OpenClaw Server** is the Mac Mini acting as the always-on, on-premise hub of the harqis-work platform. 
It is not just a machine that runs services — it is the persistent identity of the OpenClaw agent system: secrets vault, task orchestrator, MCP endpoint, and long-term memory store.

```
                    ┌──────────────────────────────────┐
                    │        OpenClaw Server           │
                    │        (Mac Mini M4)             │
                    │                                  │
                    │  ┌─────────────────────────────┐ │
                    │  │   OpenClaw Agent Identity   │ │
                    │  │   .openclaw/workspace/      │ │
                    │  │   SOUL.md  AGENTS.md        │ │
                    │  │   USER.md  HEARTBEAT.md     │ │
                    │  └─────────────────────────────┘ │
                    │                                  │
                    │  HARQIS-WORK                     │
                    │  ------------------------------  │
                    │  RabbitMQ  Redis  n8n  Frontend  │
                    │  Flower  Elasticsearch  Kibana   │
                    │  MCP server  Celery Beat         │
                    │  Cloudflare Tunnel (webhook in)  |
                    └──────────────────────────────────┘
                              │  Tailscale VPN
                 ┌────────────┴────────────┐
                 ▼                         ▼
         VPS Worker nodes          N100 Windows nodes
         (code, write, default)    (hud, tcg, windows)
```

The host is the only machine that:
- Holds API keys and the Fernet master key
- Runs the Celery Beat scheduler (task dispatch)
- Hosts the RabbitMQ / Redis broker (local, never exposed to the internet)
- Provides the webhook entry point via Cloudflare Tunnel
- Maintains the OpenClaw agent workspace and long-term memory

---

## 2. Services Inventory

All services the Mac Mini runs, with ports and resource estimates:

| Service | Port | Protocol | Purpose | Memory est. |
|---------|------|----------|---------|-------------|
| RabbitMQ | 5672 (AMQP), 15672 (mgmt UI) | TCP | Celery task broker | ~200 MB |
| Redis | 6379 | TCP | Result backend, rate-limit counters | ~50 MB |
| n8n | 5678 | HTTP | Workflow orchestration, webhooks | ~300 MB |
| Mosquitto | 1883 | MQTT | OwnTracks GPS ingestion | ~30 MB |
| OwnTracks Recorder | 8083 | HTTP | GPS location API + storage | ~50 MB |
| Elasticsearch | 9200 | HTTP | Task log storage | ~512 MB |
| Kibana | 5601 | HTTP | Log visualisation | ~250 MB |
| Frontend (FastAPI) | 8000 | HTTP | Task dashboard, webhook receiver | ~100 MB |
| Flower | 5555 | HTTP | Celery monitoring | ~80 MB |
| MCP server | stdio | stdio | Claude tools (55 tools) | ~150 MB |
| Cloudflare Tunnel | — | outbound | Expose :8000 without static IP | ~30 MB |
| Celery Beat | — | internal | Scheduled task dispatch | ~100 MB |
| Tailscale | — | outbound | VPN mesh for worker nodes (no open port) | ~5 MB |

**Total estimated RAM:** ~1.9 GB for all services.  
With 16 GB RAM available on the M4, the Mac Mini comfortably hosts everything with headroom for local agent runs and system overhead.

### Ports to open in macOS Firewall

```
Inbound  8000/TCP   — Cloudflare Tunnel (localhost; no direct internet exposure)
```

Tailscale requires **no inbound ports** — it connects outbound through NAT. All broker ports (5672, 6379, 9200, 5555) remain LAN/VPN-only and are never exposed to the internet.

---

## 3. Deployment Guide
### 3.0 Target OS
 - macOS
 - linux

### 3.1 Prerequisites

```bash
# Install Homebrew
/bin/bash -c "$(curl -fsSL https://brew.sh)"

# Install system tools
brew install git python@3.12 cloudflared

# Install Tailscale
brew install tailscale

# Install Docker Desktop for Mac
brew install --cask docker
# Or: download from docker.com
```

### 3.2 Clone and Environment Setup

```bash
git clone https://github.com/brianbartilet/harqis-work.git /opt/harqis
cd /opt/harqis

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Create the env file from the template:

```bash
cp .env/apps.env.example .env/apps.env  # if example exists
# Or copy from the Windows machine's existing .env/apps.env
```

Set required variables in `.env/apps.env` — see `apps_config.yaml` for the full list of `${VAR_NAME}` references. Minimum required:

```env
# Core
ANTHROPIC_API_KEY=sk-ant-...
PYTHON_EXE=/opt/harqis/.venv/bin/python
ENV_ROOT=/opt/harqis

# Messaging (agent notifications)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_DEFAULT_CHAT_ID=...

# Broker URLs (local services)
# AMQP uses the default guest/guest for local RabbitMQ
# No variable needed unless you change the password

# Fernet master key (generate once, store in macOS Keychain)
# HARQIS_FERNET_KEY=<see section 6.2>
```

### 3.3 Keychain for Secrets

Store sensitive values in the Keychain rather than in `.env` files:

```bash
# Store a secret
security add-generic-password -a harqis -s ANTHROPIC_API_KEY -w "sk-ant-..."

# Retrieve in a script
ANTHROPIC_API_KEY=$(security find-generic-password -a harqis -s ANTHROPIC_API_KEY -w)
```

Create a loader script at `scripts/macos/load_keychain_secrets.sh`:

```bash
#!/usr/bin/env bash
# Load secrets from macOS Keychain into environment
_kcget() { security find-generic-password -a harqis -s "$1" -w 2>/dev/null; }

export ANTHROPIC_API_KEY=$(_kcget ANTHROPIC_API_KEY)
export OPENAI_API_KEY=$(_kcget OPENAI_API_KEY)
export HARQIS_FERNET_KEY=$(_kcget HARQIS_FERNET_KEY)
# ... add other secrets
```

Source this before starting workers:

```bash
source scripts/macos/load_keychain_secrets.sh
```

### 3.4 Start Infrastructure (Docker)

```bash
cd /opt/harqis
docker compose up -d
```

The consolidated compose now starts the full dependency stack in one shot: **RabbitMQ, Redis, Mosquitto, OwnTracks Recorder, n8n, Elasticsearch, Kibana, Flower, Cloudflared, and ngrok** (the last two are tunnel options — keep one or both depending on whether you have a Cloudflare tunnel token configured). See [§4.2](#42-docker-composeyml--consolidated-service-stack) for the per-service rationale.

```bash
docker compose ps   # verify all containers are healthy
```

The Celery `worker` and `beat` processes are **not** containerised — they run on the host (next sub-section). See §4.2 for the rationale.

### 3.5 Start Celery Workers

```bash
cd /opt/harqis
source .venv/bin/activate
source scripts/linux/set_env_workflows.sh

# Beat scheduler (runs on Mac Mini only — one instance globally)
python run_workflows.py beat &

# Default queue worker
WORKFLOW_QUEUE=default python run_workflows.py worker &

# Adhoc queue worker
WORKFLOW_QUEUE=adhoc python run_workflows.py worker &
```

HUD and TCG queues run on Windows N100 nodes (see Section 5). If migrating all queues to the Mac Mini:

```bash
WORKFLOW_QUEUE=hud python run_workflows.py worker &
WORKFLOW_QUEUE=tcg python run_workflows.py worker &
```

### 3.6 Start Frontend and Monitoring

```bash
# Frontend dashboard
cd /opt/harqis/frontend
uvicorn main:app --host 0.0.0.0 --port 8000 &

# Flower
source /opt/harqis/scripts/linux/set_env_workflows.sh
celery -A core.apps.sprout.app.celery:SPROUT flower --port=5555 &
```

### 3.7 Cloudflare Tunnel (Public Webhook Entry)

Replace ngrok with Cloudflare Tunnel for a stable, free endpoint:

```bash
# One-time login
cloudflared tunnel login

# Create a named tunnel
cloudflared tunnel create harqis-server

# Route the tunnel to the frontend
cloudflared tunnel route dns harqis-server harqis.yourdomain.com

# Run the tunnel
cloudflared tunnel run --url http://localhost:8000 harqis-server
```

This gives a stable `https://harqis.yourdomain.com` URL for n8n webhooks, Trello webhooks, and external agent callbacks — no static IP required, no ngrok subscription needed.

### 3.8 Run on Startup (launchd)

Create a launchd plist to auto-start services after reboot:

```xml
<!-- ~/Library/LaunchAgents/com.harqis.server.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.harqis.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/harqis/scripts/macos/start_server.sh</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/opt/harqis/scripts/app.log</string>
  <key>StandardErrorPath</key>
  <string>/opt/harqis/scripts/app-debug.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.harqis.server.plist
```

---

## 4. Docker & docker-compose Review

> **Status (2026-04-24):** the recommendations in this section are **implemented** in the repo — root `Dockerfile`, `.dockerignore`, and `docker-compose.yml` now match what's described below. Build verified with `docker build -t harqis-work:dev .` and `docker compose config --quiet`.

### 4.1 Root `Dockerfile` — Implemented Hardening

The original Dockerfile shipped without a `CMD`, ran as root, hardcoded `ENV=TEST`, and had no `HEALTHCHECK` — meaning images were unusable without an explicit entrypoint, exposed secrets if the build context was sloppy, and orchestrators couldn't detect a stuck container.

The current `Dockerfile` addresses each of those:

| Concern | Fix in current Dockerfile |
|---|---|
| Secrets leaking into image layers | `.dockerignore` excludes `.env/`, `**/.env`, `.git/`, `.openclaw/`, logs, IDE state, virtualenvs, docs |
| Container runs as root | `useradd --uid 1000 harqis`; `USER harqis` set before `pip install`; `COPY --chown=harqis:harqis` |
| No build-time env separation | `ARG ENV=production` (override with `--build-arg ENV=staging`) — the `ENV=TEST` hardcode is gone |
| Missing default entrypoint | `CMD ["python", "run_workflows.py", "worker"]` — Celery worker by default, override per-service in compose |
| Orchestrator can't detect unhealthy containers | `HEALTHCHECK` runs `python -c "import workflows"` every 30s — passes without needing a broker connection |
| Mutable runtime data | `VOLUME ["/app/data", "/app/.env"]` so secrets and emitted artifacts mount in, not bake in |

**Dependency-conflict workaround (kept from the prior Dockerfile):** `mcp>=1.0.0` requires `anyio>=4.5`, but `harqis-core` pins `anyio==4.3.0`. The build installs `requirements.txt` first, then upgrades `anyio` and installs `mcp` on top. pip prints conflict warnings about `pydantic`, `httpx`, etc., but the resulting image works — verified by `docker run --rm harqis-work:dev python -c "import workflows"` returning success and the non-root `harqis` user being active.

**Build it:**

```bash
docker build -t harqis-work:dev .

# Override the env label for a staging image
docker build -t harqis-work:staging --build-arg ENV=staging .
```

**Run it (worker):**

```bash
docker run --rm \
  --env-file .env/apps.env \
  -v "$(pwd)/.env:/app/.env:ro" \
  --network host \
  harqis-work:dev
```

`--network host` (or a bridge with broker URLs pointing at Docker service names) is needed so the container can reach `localhost:5672` for RabbitMQ — see the `apps_config.yaml` broker URL.

### 4.2 `docker-compose.yml` — Consolidated Service Stack

The root `docker-compose.yml` now hosts the full dependency stack. The previous gaps (RabbitMQ, Redis, Elasticsearch, Kibana, Flower) have all been added; the duplicate `apps/own_tracks/docker-compose.yml` was removed (its `container_name`s collided with the root file) and `apps/own_tracks/README.md` now points to the consolidated services.

| Service | Status | Notes |
|---|---|---|
| `rabbitmq` | ✅ added | `rabbitmq:3-management-alpine`, ports 5672/15672, healthcheck via `rabbitmq-diagnostics ping`, named volume `rabbitmq_data` |
| `redis` | ✅ added | `redis:7-alpine`, port 6379, healthcheck via `redis-cli ping`, named volume `redis_data` |
| `mosquitto` + `recorder` | ✅ moved from `apps/own_tracks/` | Bind-mounts `apps/own_tracks/{mosquitto,recorder_store}/`; same definitions, single source of truth |
| `n8n` | ✅ kept | `N8N_SECURE_COOKIE=false` for plain-HTTP Tailscale access (see §11.2); `depends_on: rabbitmq` |
| `elasticsearch` + `kibana` | ✅ added | ES capped at 512 MB heap (`ES_JAVA_OPTS`); Kibana waits on ES healthcheck |
| `flower` | ✅ added | `mher/flower:2.0`, port 5555, broker/result-backend via env so `${RABBITMQ_USER}`/`${RABBITMQ_PASS}` carry through; depends on rabbitmq + redis healthchecks |
| `cloudflared` | ✅ added | Stable public tunnel; expects `CLOUDFLARE_TUNNEL_TOKEN` in `.env/apps.env` |
| `ngrok` | ⚠️ retained alongside `cloudflared` | Useful for quick testing when Cloudflare isn't configured. Either tunnel can be commented out — `cloudflared` is the production choice |
| Celery `worker` / `beat` | ❌ host processes (intentional) | Run via `python run_workflows.py worker` / `beat` on the host; `apps_config.yaml` broker URL is `localhost:5672`, and Keychain-backed secrets don't survive container boundaries cleanly. Containerise once the Celery config is parameterised by env vars |

**Bring it up:**

```bash
docker compose up -d                         # full stack
docker compose up -d mosquitto recorder      # OwnTracks subset only
docker compose ps                            # verify health
docker compose logs -f flower                # tail Flower
```

**Tunnel choice:** `cloudflared` is the production entry point (free, stable subdomain, no rate limit). `ngrok` is kept as the fast-iteration fallback for when you don't have a tunnel token wired up.

The full production compose is reproduced in [§9](#9-recommended-production-docker-compose) for reference.

---

## 5. Migrating from Windows N100 to Mac Mini

### 5.1 What Changes

The N100 Windows machine currently handles:
- `hud` queue: Rainmeter HUD tasks, winsound alerts, Windows desktop automation
- `tcg` queue: MTG card pipeline (cross-platform)
- Celery Beat scheduler (runs `set_env_workflows.bat` + `run_workflow_scheduler.bat`)

The Mac Mini will take over:
- Celery Beat scheduler (Linux shell scripts already exist)
- `tcg` queue (Python, cross-platform — works on macOS)
- `default` and `adhoc` queues

The N100 retains (Windows-only, cannot migrate):
- `hud` queue: Rainmeter, iCUE, Win32 audio, winsound
- Desktop capture tasks (Windows-only screen APIs)

### 5.2 Migration Sequence

**Phase 1 — Parallel run (validate Mac Mini workers without stopping N100):**

1. Deploy harqis-work to Mac Mini following Section 3
2. Start workers on `default,adhoc,tcg` queues — N100 still runs the same queues
3. Let both run for 24–48 hours; confirm tasks complete correctly on Mac Mini
4. Monitor via Flower: compare success rates between machines

**Phase 2 — Shift scheduler to Mac Mini:**

1. Stop Celery Beat on the N100 (`run_workflow_scheduler.bat`)
2. Start Celery Beat on Mac Mini (`python run_workflows.py beat`)
3. Confirm scheduled tasks fire at expected times (check Flower task history)

**Phase 3 — Shift `tcg` queue to Mac Mini:**

1. Stop the `tcg` worker on N100 (`run_workflow_worker_tcg.bat`)
2. Confirm `tcg` tasks route to Mac Mini worker
3. Remove `tcg` queue from N100 worker startup

**Phase 4 — N100 becomes HUD-only:**

Update N100 worker script to only serve `hud,windows`:

```bat
REM run_workflow_worker_hud.bat (updated)
call ..\.venv\Scripts\activate.bat
call set_env_workflows.bat
set "WORKFLOW_QUEUE=hud,windows"
echo Starting HUD worker...
python run_workflows.py worker
```

N100 no longer runs Beat or `tcg`/`default` queues. The Mac Mini handles everything except Windows-native HUD tasks.

### 5.3 Environment Variable Mapping

Current Windows `.env/apps.env` variables that need macOS equivalents:

| Variable | Windows path | macOS equivalent |
|----------|-------------|-----------------|
| `PYTHON_EXE` | `C:\...\harqis-work\.venv\Scripts\python.exe` | `/opt/harqis/.venv/bin/python` |
| `ENV_ROOT` | `C:\Users\brian\GIT\run\harqis-work` | `/opt/harqis` |
| `RAINMETER_BIN_PATH` | Windows-only | Remove or set to empty |
| `RAINMETER_STATIC_PATH` | Windows-only | N/A on Mac |
| `DESKTOP_PATH_*` | Windows paths | macOS paths |
| `ACTIONS_SCREENSHOT_PATH` | Windows paths | macOS paths |

Windows-specific variables (`RAINMETER_*`, `DESKTOP_PATH_*`) can be set to empty strings on the Mac Mini — tasks that use them only run on the `hud` queue (N100 only).

### 5.4 File Sync: Replacing `copy_files_targeted`

Currently, code changes sync from `C:\Users\brian\GIT\harqis-work` (dev) to `C:\Users\brian\GIT\run\harqis-work` (prod) via the `copy_files_targeted` Celery task every 30 minutes.

On the Mac Mini, dev and prod are the same directory (`/opt/harqis`). The sync task is not needed. Instead, use a git-based deployment:

```bash
# Deploy latest code to Mac Mini
cd /opt/harqis
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt  # if requirements changed
# Restart workers (see Section 10)
```

Or automate via an n8n workflow: GitHub push webhook → SSH into Mac Mini → `git pull` → restart workers.

---

## 6. OpenClaw Server Configuration

### 6.1 Agent Identity Setup

- The OpenClaw agent workspace lives at `.openclaw/workspace/` or can be pointed to a sync repository to manage context across devices.  See here for more details [OPENCLAW-SYNC.md](../info/OPENCLAW-SYNC.md). 
- On the host, this persists between sessions and defines the server's agent identity.

```
/opt/harqis/.openclaw/workspace/
├── SOUL.md          # Agent personality — unchanged from repo
├── AGENTS.md        # Session startup rules + heartbeat behavior
├── USER.md          # Who this server assists
├── TOOLS.md         # Mac Mini-specific: MCP paths, SSH hosts
├── HEARTBEAT.md     # What the server checks periodically
├── MEMORY.md        # Long-term server memory index
└── memory/
    └── YYYY-MM-DD.md  # Daily logs
```

Update `TOOLS.md` for the Mac Mini environment:

```markdown
# TOOLS.md — OpenClaw Server

## Environment
- OS: macOS (Apple Silicon M4)
- Root: /opt/harqis
- Python: /opt/harqis/.venv/bin/python
- MCP server: /opt/harqis/mcp/server.py

## Connected Nodes (Tailscale VPN)
- mac-mini  — Mac Mini (this machine)
- vps1      — VPS Node 1 (Hetzner, code/write queues)
- n100      — N100 Windows (hud/tcg queues, home LAN)
# Run `tailscale status` to see current IPs

## SSH Aliases
- vps1: ssh harqis@vps1  (Tailscale SSH or standard SSH over Tailscale IP)
- n100: ssh harqis@n100  (if SSH enabled on Windows)

## Services
- RabbitMQ mgmt: http://localhost:15672
- Flower:        http://localhost:5555
- Frontend:      http://localhost:8000
- n8n:           http://localhost:5678
- Kibana:        http://localhost:5601
```

Update `HEARTBEAT.md` for server-side monitoring:

```markdown
# HEARTBEAT.md — OpenClaw Server

- Check Celery queue depths via Flower API (http://localhost:5555/api/queues)
- If any queue depth > 10 for 10+ minutes, alert via Telegram
- Check Telegram for unread messages
- Check Google Calendar for events in next 2 hours
- If VPS nodes are unresponsive (tailscale ping vps1), alert and log to Elasticsearch
- Check OANDA open trades if market is open (Mon–Fri 00:00–22:00 UTC)
- Write daily summary to .openclaw/workspace/memory/YYYY-MM-DD.md
```

### 6.2 Fernet Master Key

Generate the Fernet key once and store it in macOS Keychain:

```python
from cryptography.fernet import Fernet
key = Fernet.generate_key()
print(key.decode())  # copy this value
```

```bash
security add-generic-password -a harqis -s HARQIS_FERNET_KEY -w "<generated key>"
```

This key is used to encrypt scoped secrets sent to worker nodes. The key never leaves the Mac Mini.

### 6.3 MCP Server as the OpenClaw Endpoint

The MCP server (`mcp/server.py`) runs on the Mac Mini and exposes 55 tools. Configure Claude Desktop or Claude Code on any machine to connect to the Mac Mini's MCP server over SSH port forwarding:

```bash
# On a remote machine — forward Mac Mini MCP over SSH
ssh -L 9999:localhost:stdio user@mac-mini-ip \
  /opt/harqis/.venv/bin/python /opt/harqis/mcp/server.py
```

Or in `claude_desktop_config.json` on the remote machine:

```json
{
  "mcpServers": {
    "harqis-work": {
      "command": "ssh",
      "args": [
        "mac-mini",
        "/opt/harqis/.venv/bin/python",
        "/opt/harqis/mcp/server.py"
      ]
    }
  }
}
```

---

## 7. Connecting Worker Nodes

### 7.1 Tailscale VPN Setup

Tailscale creates a mesh VPN with no server to manage and no ports to open. All nodes authenticate via the Tailscale control plane and communicate peer-to-peer (or via DERP relay when NAT traversal isn't possible).

**Mac Mini (and every other node):**

```bash
# macOS — start the daemon and authenticate
sudo tailscaled &
tailscale up

# Opens a browser link — log in with your Tailscale account
# The Mac Mini gets a stable Tailscale IP (e.g. 100.x.x.x) and MagicDNS name
```

**VPS worker node (Linux):**

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
```

**N100 Windows node:**

Download and install the Tailscale Windows client from tailscale.com, then click "Log in" — no config files or key pairs needed.

**Verify all nodes are connected:**

```bash
tailscale status
# Shows every peer, its IP, and whether it's online
```

**Auto-start on macOS boot** — Tailscale installs a LaunchDaemon automatically via `brew install tailscale`. No extra plist needed.

> **Optional — Headscale (self-hosted control plane):** If you want zero dependency on Tailscale's servers, run [Headscale](https://github.com/juanfont/headscale) on one of the Hetzner VPS nodes and point all nodes at it with `tailscale up --login-server https://your-headscale-host`.

### 7.2 VPS Node Bootstrap

See [VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md#32-vps-worker-nodes) for the full bootstrap script. After joining Tailscale, use the Mac Mini's MagicDNS name or Tailscale IP as the broker address:

```bash
# On VPS worker — after tailscale up
export CELERY_BROKER_URL=amqp://guest:guest@mac-mini:5672/
export CELERY_RESULT_BACKEND=redis://mac-mini:6379/0
```

Or update `apps_config.yaml` for workers:

```yaml
CELERY_TASKS:
  application_name: 'workflow-harqis'
  broker: 'amqp://guest:guest@mac-mini:5672/'  # Mac Mini MagicDNS name
```

Replace `mac-mini` with the actual MagicDNS hostname shown in `tailscale status` (e.g. `mac-mini.tail1234.ts.net`) or the stable Tailscale IP (`100.x.x.x`).

### 7.3 N100 Windows Node (HUD Worker)

After installing the Tailscale Windows client and logging in, the N100 reaches the Mac Mini over the Tailscale mesh — no LAN IP guessing or router port-forwarding needed:

```bat
REM set_env_workflows.bat on N100
REM Use Mac Mini MagicDNS name (shown in Tailscale admin console)
set CELERY_BROKER=amqp://guest:guest@mac-mini:5672/
```

---

## 8. Monitoring and Observability

### 8.1 Flower Dashboard

Access at `http://localhost:5555` (or via SSH tunnel from a remote machine).

Key views:
- **Workers**: which nodes are online, which queues they serve
- **Tasks**: recent task history, success/failure rates
- **Queues**: current depth per queue — use to detect backlog

### 8.2 Elasticsearch Logging

All tasks decorated with `@log_result()` write to Elasticsearch at `http://localhost:9200`, index `harqis-elastic-logging`.

Query examples (via Kibana at `http://localhost:5601`):
```
# Failed tasks in last 24h
status:failed AND @timestamp:[now-24h TO now]

# Specific task type
task_name:workflows.hud.tasks.hud_gpt.get_desktop_logs
```

### 8.3 Alert Routing via Telegram

The server's heartbeat (Section 6.1) monitors queue depth and worker health. Wire critical alerts directly to Telegram:

```python
# In any monitoring task
from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages
from apps.telegram.config import CONFIG as TELEGRAM_CONFIG

def alert(message: str):
    ApiServiceTelegramMessages(TELEGRAM_CONFIG).send_message(
        chat_id=TELEGRAM_CONFIG.app_data['default_chat_id'],
        text=f"[OpenClaw Server] {message}"
    )
```

### 8.4 Health Check Endpoint

The frontend (`frontend/main.py`) exposes `GET /health`. Point uptime monitoring (UptimeRobot, Better Uptime, etc.) to the Cloudflare Tunnel URL:

```
https://harqis.yourdomain.com/health
```

Returns 200 when the server is up, enabling external alerting on downtime.

---

## 9. Recommended Production docker-compose

This is the canonical production `docker-compose.yml` — it matches the file checked in at the repo root. Differences in the live file should be reconciled here when intentional.

```yaml
# docker-compose.yml — OpenClaw Server (Mac Mini)
# Usage:
#   docker compose up -d                       # full stack
#   docker compose up -d mosquitto recorder    # OwnTracks subset only

services:

  # ── Message Broker ──────────────────────────────────────────────────────────

  rabbitmq:
    image: rabbitmq:3-management-alpine
    container_name: rabbitmq
    restart: unless-stopped
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      RABBITMQ_DEFAULT_USER: ${RABBITMQ_USER:-guest}
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASS:-guest}
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    healthcheck:
      test: rabbitmq-diagnostics ping
      interval: 30s
      timeout: 10s
      retries: 3

  redis:
    image: redis:7-alpine
    container_name: redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: redis-cli ping
      interval: 30s
      timeout: 5s
      retries: 3

  # ── OwnTracks ───────────────────────────────────────────────────────────────

  mosquitto:
    image: eclipse-mosquitto:latest
    container_name: mosquitto
    restart: unless-stopped
    ports:
      - "1883:1883"
    volumes:
      - ./apps/own_tracks/mosquitto/config:/mosquitto/config
      - ./apps/own_tracks/mosquitto/data:/mosquitto/data
      - ./apps/own_tracks/mosquitto/log:/mosquitto/log

  recorder:
    image: owntracks/recorder:latest
    container_name: owntracks-recorder
    restart: unless-stopped
    ports:
      - "8083:8083"
    environment:
      OTR_HOST: mosquitto
      OTR_PORT: 1883
      OTR_USER: ""
      OTR_PASS: ""
      OTR_HTTP_PORT: 8083
    volumes:
      - ./apps/own_tracks/recorder_store:/store
    depends_on:
      - mosquitto

  # ── n8n ─────────────────────────────────────────────────────────────────────

  n8n:
    image: docker.n8n.io/n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    ports:
      - "${HOST_PORT_N8N:-5678}:5678"
    volumes:
      - n8n_data:/home/node/.n8n
      - ./workflows.mapping:/data/workflows.mapping:ro
      - ./scripts.mapping:/data/scripts.mapping:ro
    environment:
      TZ: Asia/Singapore
      N8N_TIMEZONE: Asia/Singapore
      N8N_SECURE_COOKIE: "false"   # see §11.2 — Tailscale layer already encrypts
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      rabbitmq:
        condition: service_healthy

  # ── Observability ───────────────────────────────────────────────────────────

  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.13.0
    container_name: elasticsearch
    restart: unless-stopped
    ports:
      - "9200:9200"
    environment:
      discovery.type: single-node
      xpack.security.enabled: "false"
      ES_JAVA_OPTS: "-Xms256m -Xmx512m"
    volumes:
      - elastic_data:/usr/share/elasticsearch/data
    healthcheck:
      test: curl -s http://localhost:9200/_cluster/health | grep -q '"status":"green"\|"status":"yellow"'
      interval: 30s
      timeout: 10s
      retries: 5

  kibana:
    image: docker.elastic.co/kibana/kibana:8.13.0
    container_name: kibana
    restart: unless-stopped
    ports:
      - "5601:5601"
    environment:
      ELASTICSEARCH_HOSTS: http://elasticsearch:9200
    depends_on:
      elasticsearch:
        condition: service_healthy

  # ── Celery Monitoring ───────────────────────────────────────────────────────

  flower:
    image: mher/flower:2.0
    container_name: flower
    restart: unless-stopped
    command:
      - "celery"
      - "--broker=amqp://${RABBITMQ_USER:-guest}:${RABBITMQ_PASS:-guest}@rabbitmq:5672//"
      - "--result-backend=redis://redis:6379/0"
      - "flower"
      - "--port=5555"
      - "--address=0.0.0.0"
    ports:
      - "5555:5555"
    depends_on:
      rabbitmq:
        condition: service_healthy
      redis:
        condition: service_healthy

  # ── Public Tunnels ──────────────────────────────────────────────────────────
  # Use one or both. cloudflared = stable custom domain (production).
  # ngrok = quick testing when Cloudflare isn't configured.

  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: unless-stopped
    command: tunnel run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      - n8n

  ngrok:
    image: ngrok/ngrok:latest
    container_name: ngrok
    restart: unless-stopped
    command: ["http", "n8n:5678", "--log=stdout", "--log-format=json"]
    environment:
      NGROK_AUTHTOKEN: ${NGROK_AUTHTOKEN}
    env_file:
      - ./.env/apps.env
    ports:
      - "4040:4040"
    depends_on:
      - n8n

volumes:
  rabbitmq_data:
  redis_data:
  n8n_data:
  elastic_data:
```

**Notes on this compose:**
- **Celery workers and Beat run as host processes**, not containers — `apps_config.yaml` hardcodes broker URLs to `localhost`, and macOS Keychain-backed secret loading doesn't survive container boundaries cleanly. Containerise once those are env-var-driven.
- **Cloudflare Tunnel** requires a pre-created tunnel token (`cloudflared tunnel token <tunnel-name>`). Store as `CLOUDFLARE_TUNNEL_TOKEN` in `.env/apps.env`. Without it the container will restart-loop — comment the service out if you only want ngrok.
- **ngrok** needs `NGROK_AUTHTOKEN` in `.env/apps.env`. Without it, also restart-loops.
- **Elasticsearch** is capped at 512 MB heap (`ES_JAVA_OPTS`). Bump to 1 GB if log volume grows.
- **Flower** uses Docker service names (`rabbitmq`, `redis`) for its broker/backend URLs, independent of the host-side `localhost` URLs the workers use — both connect to the same broker over different network paths.
- All services use named volumes for persistence across container restarts.
- Per §11.1 the previously-loopback bindings (`127.0.0.1:`) are removed so Tailscale peers can reach the services.

---

## 10. Maintenance Runbook

### Restart Celery Workers

```bash
# Kill all workers gracefully
pkill -f "run_workflows.py worker"
sleep 3

# Restart
cd /opt/harqis
source .venv/bin/activate
source scripts/linux/set_env_workflows.sh
WORKFLOW_QUEUE=default python run_workflows.py worker &
WORKFLOW_QUEUE=adhoc  python run_workflows.py worker &
python run_workflows.py beat &
```

### Deploy Code Updates

```bash
cd /opt/harqis
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt  # only if requirements changed

# Restart workers (above)
```

### Restart All Docker Services

```bash
cd /opt/harqis
docker compose down
docker compose up -d
```

### Add a New VPS Worker Node

1. Provision VPS (Hetzner CX22 recommended)
2. Install Tailscale: `curl -fsSL https://tailscale.com/install.sh | sh && tailscale up`
3. Approve the node in the Tailscale admin console (tailscale.com/admin)
4. Verify connectivity from Mac Mini: `tailscale ping <new-node-hostname>`
5. Bootstrap node: `curl -sSL https://raw.githubusercontent.com/brianbartilet/harqis-work/main/scripts/linux/bootstrap_worker.sh | bash`
6. Node auto-starts Celery worker on `code,write,default` queues

### Rotate the Fernet Key

```bash
# Generate new key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Update in Keychain
security delete-generic-password -a harqis -s HARQIS_FERNET_KEY
security add-generic-password -a harqis -s HARQIS_FERNET_KEY -w "<new key>"

# Reload into environment and restart workers
source scripts/macos/load_keychain_secrets.sh
# restart workers
```

Old in-flight tasks encrypted with the previous key will fail to decrypt. Ensure no tasks are in-flight before rotating.

### Check Service Health

```bash
# All Docker containers
docker compose ps

# Celery workers
source scripts/linux/set_env_workflows.sh
celery -A core.apps.sprout.app.celery:SPROUT inspect active

# Queue depths
celery -A core.apps.sprout.app.celery:SPROUT inspect reserved

# Tailscale peers
tailscale status
```

---

## Summary

| Dimension | Value |
|-----------|-------|
| **Hardware** | Mac Mini M4, 16 GB RAM, 256 GB SSD |
| **All services** | RabbitMQ, Redis, n8n, Mosquitto, OwnTracks, Elasticsearch, Kibana, Frontend, Flower, Cloudflare Tunnel |
| **RAM usage** | ~1.9 GB (headroom: ~13 GB) |
| **Queues on Mac Mini** | `default`, `adhoc`, `tcg` |
| **Queues on N100** | `hud`, `windows` (Windows-native only) |
| **Public entry point** | Cloudflare Tunnel → `https://harqis.yourdomain.com` |
| **Secret storage** | macOS Keychain → Fernet-encrypted payloads to workers |
| **Code deployment** | `git pull` + worker restart |
| **Agent identity** | `.openclaw/workspace/` — persistent, persists across reboots |
| **Uptime protection** | UPS + `launchd` auto-restart |
| **Worker nodes** | VPS (Hetzner) + N100 Windows over Tailscale VPN |

Further reading:
- **[VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md)** — full cluster architecture, scaling, cost, and security model
- **[OPEN_CLAW_CONTROLLER.md](../info/OPEN_CLAW_CONTROLLER.md)** — OpenClaw agent setup, MCP tools, multi-agent topology

---

## 11. Tailscale VPN Access & Access Control

This section covers making all services reachable from other Tailscale nodes, fixing the n8n secure-cookie error, and restricting which nodes can access which services.

### 11.1 The Problem: `127.0.0.1` Port Bindings

By default several services in `docker-compose.yml` were bound to the loopback address (`127.0.0.1`). Tailscale MagicDNS routes traffic to the machine's Tailscale IP (`100.x.x.x`), which is a different network interface — loopback bindings are never reachable from other tailnet nodes even when the hostname resolves correctly.

**Port binding audit:**

| Container | Original bind | Fixed bind | Tailscale-reachable |
|-----------|--------------|-----------|---------------------|
| n8n | `0.0.0.0:5678` | unchanged | ✅ |
| owntracks-recorder | `0.0.0.0:8083` | unchanged | ✅ |
| mosquitto | `0.0.0.0:1883` | unchanged | ✅ |
| rabbitmq AMQP | `0.0.0.0:5672` | unchanged | ✅ |
| rabbitmq mgmt UI | `127.0.0.1:15672` | `15672` | ✅ fixed |
| redis | `127.0.0.1:6379` | `6379` | ✅ fixed |
| elasticsearch | `127.0.0.1:9200` | `9200` | ✅ fixed |
| kibana | `127.0.0.1:5601` | `5601` | ✅ fixed |

The fix in `docker-compose.yml` is simply removing the `127.0.0.1:` prefix so Docker binds to all interfaces including the Tailscale one. Tailscale ACLs (Section 11.3) then enforce who can actually connect.

### 11.2 Fixing the n8n Secure Cookie Error

When accessing n8n over a plain HTTP Tailscale URL (`http://harqis-ones-mac-mini:5678`), n8n refuses to set its session cookie because `N8N_SECURE_COOKIE` defaults to `true`, which requires HTTPS.

**Short-term fix** (already applied in `docker-compose.yml`):

```yaml
n8n:
  environment:
    N8N_SECURE_COOKIE: "false"
```

This is safe because all Tailscale traffic is already encrypted at the WireGuard layer — the HTTP transport inside the VPN is equivalent to HTTPS from a confidentiality standpoint.

**Long-term fix — Tailscale HTTPS (recommended):**

Tailscale can issue a valid TLS cert for your MagicDNS hostname and proxy traffic through it, removing the need for the `N8N_SECURE_COOKIE` workaround entirely.

```bash
# On the Mac Mini — get a TLS cert issued for your tailnet hostname
sudo tailscale cert harqis-ones-mac-mini.your-tailnet.ts.net

# Start a Tailscale HTTPS reverse proxy in front of n8n
tailscale serve --https=443 --bg http://localhost:5678
```

n8n is then available at `https://harqis-ones-mac-mini.your-tailnet.ts.net` with a browser-trusted cert. Once this is in place, re-enable the secure cookie:

```yaml
n8n:
  environment:
    N8N_SECURE_COOKIE: "true"
    N8N_HOST: harqis-ones-mac-mini.your-tailnet.ts.net
    N8N_PROTOCOL: https
    WEBHOOK_URL: https://harqis.yourdomain.com/   # Cloudflare tunnel URL for inbound webhooks
```

### 11.3 Tailscale ACL Policy (Per-Node Access Control)

The full policy lives at `scripts/tailscale/acl-policy.hujson`. Apply it at https://login.tailscale.com/admin/acls.

**Node tags and what each can reach on the server:**

| Tag | Nodes | Ports allowed on `tag:server` | Rationale |
|-----|-------|-------------------------------|-----------|
| `tag:server` | Mac Mini | — (it is the server) | |
| `tag:worker` | VPS Celery nodes | 5672, 6379, 9200 | Broker + result backend + ES logging |
| `tag:hud-node` | N100 Windows | 5672, 6379 | Celery HUD queue only; no admin UIs |
| `tag:personal` | Laptop, phone | all (`*`) | Full admin access |

**Tag each machine once** (run after `tailscale up`):

```bash
# Mac Mini
tailscale up --advertise-tags=tag:server

# VPS workers (run on each VPS)
tailscale up --advertise-tags=tag:worker

# N100 Windows — use the Tailscale admin console to assign tag:hud-node
# or run in an elevated PowerShell:
# tailscale up --advertise-tags=tag:hud-node

# Personal devices — assign tag:personal in the admin console
```

> **Note:** Tag ownership must be set in the ACL policy (`tagOwners`) before a node can self-assign a tag. The policy in `acl-policy.hujson` restricts tag assignment to `autogroup:admin` (Tailscale account owners).

### 11.4 macOS Firewall

The macOS application firewall is a separate layer from Tailscale ACLs. If it is enabled, it can silently drop incoming Tailscale connections even when `docker-compose.yml` binds to `0.0.0.0`.

Check the state:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
```

If the firewall is on, add Docker to the allow list:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /Applications/Docker.app/Contents/MacOS/Docker
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp /Applications/Docker.app/Contents/MacOS/Docker
```

Or use System Settings → Network → Firewall → Options to add Docker explicitly.

### 11.5 Redeploy After Changes

After updating `docker-compose.yml`:

```bash
cd /opt/harqis
docker compose down && docker compose up -d

# Verify all containers started cleanly
docker compose ps

# Confirm a previously-blocked port is now reachable from another tailnet node
# (run from your laptop or VPS)
curl http://harqis-ones-mac-mini:5601   # Kibana
curl http://harqis-ones-mac-mini:9200   # Elasticsearch
```

### 11.6 Security Notes for VPN-Exposed Services

Opening services to the Tailscale network rather than `127.0.0.1` increases the attack surface within the tailnet. Recommended hardening steps:

| Service | Default credentials | Recommended action |
|---------|--------------------|--------------------|
| RabbitMQ | `guest` / `guest` | Set `RABBITMQ_USER` and `RABBITMQ_PASS` in `.env/apps.env` and update all worker `CELERY_BROKER_URL` values |
| Redis | no password | Add `command: redis-server --requirepass ${REDIS_PASSWORD}` to compose and update `CELERY_RESULT_BACKEND` URLs |
| Elasticsearch | xpack security disabled | Acceptable for VPN-only; enable xpack if compliance requires it |
| Kibana | unauthenticated | Use Tailscale ACLs to limit to `tag:personal` only (already in policy) |
| n8n | basic auth via `N8N_BASIC_AUTH_*` | Already configured in `.env/apps.env` |
