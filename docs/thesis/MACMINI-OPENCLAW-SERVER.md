# Mac Mini as OpenClaw Server — Deployment & Migration Guide

**Related:** [VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md) · [OPEN_CLAW_CONTROLLER.md](../info/OPEN_CLAW_CONTROLLER.md)  
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

---

## 1. Overview — The OpenClaw Server Concept

The **OpenClaw Server** is the Mac Mini acting as the always-on, on-premise hub of the harqis-work platform. It is not just a machine that runs services — it is the persistent identity of the OpenClaw agent system: secrets vault, task orchestrator, MCP endpoint, and long-term memory store.

```
                    ┌──────────────────────────────────┐
                    │        OpenClaw Server            │
                    │        (Mac Mini M4)              │
                    │                                   │
                    │  ┌─────────────────────────────┐  │
                    │  │   OpenClaw Agent Identity   │  │
                    │  │   .openclaw/workspace/       │  │
                    │  │   SOUL.md  AGENTS.md         │  │
                    │  │   USER.md  HEARTBEAT.md      │  │
                    │  └─────────────────────────────┘  │
                    │                                   │
                    │  RabbitMQ  Redis  n8n  Frontend   │
                    │  Flower  Elasticsearch  Kibana     │
                    │  MCP server  Celery Beat           │
                    │  Cloudflare Tunnel (webhook in)   │
                    └──────────────────────────────────┘
                              │  WireGuard VPN
                 ┌────────────┴────────────┐
                 ▼                         ▼
         VPS Worker nodes          N100 Windows nodes
         (code, write, default)    (hud, tcg, windows)
```

The Mac Mini is the only machine that:
- Holds API keys and the Fernet master key
- Runs the Celery Beat scheduler (task dispatch)
- Hosts the RabbitMQ / Redis broker (local, never exposed to the internet)
- Provides the webhook entry point via Cloudflare Tunnel
- Maintains the OpenClaw agent workspace and long-term memory

**Hardware target:** Mac Mini M4, 16 GB RAM, 256 GB SSD.

---

## 2. Service Inventory

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
| WireGuard | 51820 | UDP | VPN server for worker nodes | ~10 MB |

**Total estimated RAM:** ~1.9 GB for all services.  
With 16 GB RAM available on the M4, the Mac Mini comfortably hosts everything with headroom for local agent runs and system overhead.

### Ports to open in macOS Firewall

```
Inbound  51820/UDP  — WireGuard VPN (worker nodes only)
Inbound  8000/TCP   — Cloudflare Tunnel (localhost; no direct internet exposure)
```

All other ports are LAN or VPN-only. Never expose 5672, 6379, 9200, or 5555 to the internet.

---

## 3. Mac Mini Deployment Guide (macOS)

### 3.1 Prerequisites

```bash
# Install Homebrew
/bin/bash -c "$(curl -fsSL https://brew.sh)"

# Install system tools
brew install git python@3.12 wireguard-tools cloudflared

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

### 3.3 macOS Keychain for Secrets

Store sensitive values in the macOS Keychain rather than in `.env` files:

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

This starts: Mosquitto, OwnTracks Recorder, n8n, ngrok (see Section 4 for recommended changes).

**Start RabbitMQ and Redis** (not yet in docker-compose — see Section 4 for the improved compose):

```bash
# Temporary: run as standalone containers until compose is updated
docker run -d --name rabbitmq \
  -p 5672:5672 -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=guest \
  -e RABBITMQ_DEFAULT_PASS=guest \
  rabbitmq:3-management

docker run -d --name redis \
  -p 6379:6379 \
  redis:7-alpine
```

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

### 4.1 Root `Dockerfile` — Current State and Issues

**Current:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
VOLUME ["/app/data"]
RUN apt-get update && apt-get install -y git curl build-essential python3-dev
RUN python -m venv /app/venv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
ENV PYTHONPATH=/app
ENV ENV_ROOT_DIRECTORY=/app
ENV ENV=TEST
```

**Issues:**

| Issue | Risk | Fix |
|-------|------|-----|
| `COPY . .` copies `.env/apps.env` into the image | Secrets in image layer | Add `.dockerignore` |
| `ENV=TEST` hardcoded | No production/staging separation | Use `ARG ENV=production` |
| No `CMD` defined | Image is unusable without explicit entrypoint | Add default `CMD` |
| No non-root user | Container runs as root | Add `useradd harqis` |
| No healthcheck | Orchestrators can't detect unhealthy containers | Add `HEALTHCHECK` |

**Recommended fixes:**

Create `.dockerignore`:
```
.env/
.venv/
__pycache__/
*.pyc
.git/
scripts/app*.log
docs/
*.md
.openclaw/
```

Updated `Dockerfile`:
```dockerfile
ARG PYTHON_VERSION=3.12
ARG ENV=production

FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 harqis

RUN python -m venv /app/venv
ENV PATH=/app/venv/bin:$PATH

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY --chown=harqis:harqis . .

ENV PYTHONPATH=/app
ENV ENV_ROOT_DIRECTORY=/app
ARG ENV
ENV ENV=${ENV}

USER harqis
VOLUME ["/app/data", "/app/.env"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s \
  CMD python -c "import workflows" || exit 1

CMD ["python", "run_workflows.py", "worker"]
```

### 4.2 `docker-compose.yml` — Current State and Issues

**Current services:** Mosquitto, OwnTracks Recorder, n8n, ngrok.

**Missing services:**

| Missing | Impact |
|---------|--------|
| RabbitMQ | `apps_config.yaml` references `amqp://guest:guest@localhost:5672/` but no broker in compose |
| Redis | Required as Celery result backend; no service defined |
| Elasticsearch + Kibana | `ELASTIC_LOGGING` config exists but no service in compose |
| Flower | Monitoring has no container definition |
| Celery worker(s) | Workers start manually; not containerised |

**ngrok vs Cloudflare Tunnel:**
- ngrok requires an auth token and has rate limits on free tier
- Cloudflare Tunnel (`cloudflared`) is free, stable, and gives a custom domain
- Recommendation: replace `ngrok` service with `cloudflared`

See Section 9 for the complete recommended `docker-compose.yml`.

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

The OpenClaw agent workspace lives at `.openclaw/workspace/`. On the Mac Mini, this persists between sessions and defines the server's agent identity.

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
# TOOLS.md — OpenClaw Server (Mac Mini)

## Environment
- OS: macOS (Apple Silicon M4)
- Root: /opt/harqis
- Python: /opt/harqis/.venv/bin/python
- MCP server: /opt/harqis/mcp/server.py

## Connected Nodes (WireGuard VPN)
- 10.0.0.1  — Mac Mini (this machine)
- 10.0.0.2  — VPS Node 1 (Hetzner, code/write queues)
- 10.0.0.10 — N100 Windows (hud/tcg queues, home LAN)

## SSH Aliases
- vps1: ssh harqis@10.0.0.2
- n100: ssh harqis@10.0.0.10 (if SSH enabled on Windows)

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
- If VPS nodes are unresponsive (ping 10.0.0.2), alert and log to Elasticsearch
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

### 7.1 WireGuard VPN Setup (Mac Mini as Server)

```bash
# Generate server key pair
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key

# Create /etc/wireguard/wg0.conf
cat > /etc/wireguard/wg0.conf << EOF
[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = $(cat /etc/wireguard/server_private.key)

# VPS Node 1
[Peer]
PublicKey = <vps1_public_key>
AllowedIPs = 10.0.0.2/32

# N100 Windows Node
[Peer]
PublicKey = <n100_public_key>
AllowedIPs = 10.0.0.10/32
EOF

# Start VPN
wg-quick up wg0

# Auto-start on boot
sudo launchctl load /Library/LaunchDaemons/com.wireguard.wg0.plist
```

### 7.2 VPS Node Bootstrap

See [VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md#32-vps-worker-nodes) for the full bootstrap script. The broker URL changes from `localhost` to the Mac Mini VPN address:

```bash
# On VPS worker — after joining VPN
export CELERY_BROKER_URL=amqp://guest:guest@10.0.0.1:5672/
export CELERY_RESULT_BACKEND=redis://10.0.0.1:6379/0
```

Or update `apps_config.yaml` for workers:

```yaml
CELERY_TASKS:
  application_name: 'workflow-harqis'
  broker: 'amqp://guest:guest@10.0.0.1:5672/'  # Mac Mini VPN IP
```

### 7.3 N100 Windows Node (HUD Worker)

The N100 continues to connect to the RabbitMQ broker on the Mac Mini. If N100 is on the same LAN as the Mac Mini:

```bat
REM set_env_workflows.bat on N100
REM Point to Mac Mini IP on LAN (or VPN if preferred)
set CELERY_BROKER=amqp://guest:guest@192.168.1.x:5672/
```

If N100 joins the WireGuard VPN (recommended for consistency):

```bat
REM After WireGuard Windows client is configured
set CELERY_BROKER=amqp://guest:guest@10.0.0.1:5672/
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

The following replaces the current `docker-compose.yml` with a complete, production-ready service stack for the Mac Mini:

```yaml
# docker-compose.yml — OpenClaw Server (Mac Mini)
# Usage: docker compose up -d

services:

  # ── Message Broker ──────────────────────────────────────────────────────────

  rabbitmq:
    image: rabbitmq:3-management-alpine
    container_name: rabbitmq
    restart: unless-stopped
    ports:
      - "5672:5672"
      - "15672:15672"   # Management UI — bind to 127.0.0.1 in production
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

  owntracks-recorder:
    image: owntracks/recorder:latest
    container_name: owntracks-recorder
    restart: unless-stopped
    ports:
      - "8083:8083"
    environment:
      OTR_HOST: mosquitto
      OTR_PORT: 1883
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
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      rabbitmq:
        condition: service_healthy

  # ── Observability ────────────────────────────────────────────────────────────

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

  # ── Public Tunnel (replaces ngrok) ──────────────────────────────────────────

  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: unless-stopped
    command: tunnel run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on:
      - n8n

volumes:
  rabbitmq_data:
  redis_data:
  n8n_data:
  elastic_data:
```

**Notes on this compose:**
- Celery workers and Beat run as processes (not containers) to keep deployment simple. Containerise them once the service is stable.
- Cloudflare Tunnel requires a pre-created tunnel token (`cloudflared tunnel token <tunnel-name>`). Store it in `.env/apps.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
- Elasticsearch memory is capped at 512 MB via `ES_JAVA_OPTS`. Increase to 1 GB if log volume grows.
- All services use named volumes for persistence across container restarts.

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
2. Generate WireGuard key pair on new node: `wg genkey | tee private.key | wg pubkey`
3. Add node as peer in `/etc/wireguard/wg0.conf` on Mac Mini, assign IP `10.0.0.N`
4. Restart WireGuard: `wg-quick down wg0 && wg-quick up wg0`
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

# WireGuard peers
sudo wg show
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
| **Worker nodes** | VPS (Hetzner) + N100 Windows over WireGuard VPN |

Further reading:
- **[VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md)** — full cluster architecture, scaling, cost, and security model
- **[OPEN_CLAW_CONTROLLER.md](../info/OPEN_CLAW_CONTROLLER.md)** — OpenClaw agent setup, MCP tools, multi-agent topology
