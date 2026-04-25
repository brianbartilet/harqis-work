# HARQIS-CLAW Host — Deployment & Operations Guide

The **HARQIS-CLAW Host** is the always-on primary machine small11that acts as the hub
of the harqis-work platform. It is not just a service runner — it is the persistent identity
of the OpenClaw agent system: secrets vault, task orchestrator, MCP endpoint, and long-term
memory store.

**Related docs:**
- [AI-TOOLS-SETUP.md](AI-TOOLS-SETUP.md) — Claude Code orientation and workspace sync
- [SKILLS-GUIDE.md](SKILLS-GUIDE.md) — Claude Code skills and OpenClaw integration
- [OPENCLAW-SYNC.md](OPENCLAW-SYNC.md) — Sync repo architecture across machines
- [OS-COMPATIBILITY.md](OS-COMPATIBILITY.md) — Cross-platform notes
- [mcp/README.md](../../mcp/README.md) — Full MCP tool catalog
- [VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md) — Cluster architecture and scaling
- [TRELLO-AGENT-KANBAN.md](../thesis/TRELLO-AGENT-KANBAN.md) — Kanban-driven multi-agent design

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Service Inventory](#2-service-inventory)
3. [First-Time Setup](#3-first-time-setup)
4. [Host Deployment (Mac Mini / Primary Server)](#4-host-deployment-mac-mini--primary-server)
5. [OpenClaw Agent Configuration](#5-openclaw-agent-configuration)
6. [MCP Server & Tools](#6-mcp-server--tools)
7. [Claude Code Skills Integration](#7-claude-code-skills-integration)
8. [Worker Nodes & Networking](#8-worker-nodes--networking)
9. [Multi-Agent Topology](#9-multi-agent-topology)
10. [Monitoring & Observability](#10-monitoring--observability)
11. [Docker & Infrastructure](#11-docker--infrastructure)
12. [Maintenance Runbook](#12-maintenance-runbook)
13. [Tailscale VPN & Access Control](#13-tailscale-vpn--access-control)
14. [Quick Reference](#14-quick-reference)

---

## 1. Platform Overview

**harqis-work** is a code-first automation platform. At its core:

| Component | Path | Purpose |
|---|---|---|
| **Apps** | `apps/` | 20+ REST/local service integrations (finance, trading, calendar, messaging, etc.) |
| **Workflows** | `workflows/` | Celery tasks that run on schedules, trigger actions, push data to a desktop HUD |
| **MCP server** | `mcp/` | Exposes every app as a callable tool to Claude agents (55 tools) |
| **Frontend** | `frontend/` | Web dashboard to manually trigger any task |
| **OpenClaw workspace** | `harqis-openclaw-sync/.openclaw/workspace/` | Persistent agent identity, memory, and behavior rules |

The idea: **OpenClaw agents use MCP tools + Celery workflows + n8n to automate real tasks across
real services, with Claude as the reasoning layer.**

### Architecture

```
                    ┌──────────────────────────────────┐
                    │        HARQIS-CLAW Host          │
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
                    │  ─────────────────────────────── │
                    │  RabbitMQ  Redis  n8n  Frontend  │
                    │  Flower  Elasticsearch  Kibana   │
                    │  MCP server  Celery Beat         │
                    │  Cloudflare Tunnel (webhook in)  │
                    └──────────────────────────────────┘
                              │  Tailscale VPN
                 ┌────────────┴────────────┐
                 ▼                         ▼
         VPS Worker nodes          N100 Windows nodes
         (code, write, default)    (hud, tcg, windows)
```

```
┌─────────────────────────────────────────────────────┐
│                  CONTROL LAYER                      │
│                                                     │
│  OpenClaw Agent ◄──► Claude (via MCP)               │
│       │                    │                        │
│       │              55 MCP tools                   │
│       │         (finance, calendar, GPS,            │
│       │          messaging, trading, cards)         │
│       ▼                                             │
│  n8n Orchestrator ◄──► Celery Workers               │
│  (workflows.mapping)    (Celery Beat + RabbitMQ)    │
│                              │                      │
│                    ┌─────────┴────────┐             │
│                    │   APPS LAYER     │             │
│             OANDA  │  YNAB  │ Google  │             │
│             Jira   │ Trello │ Telegram│             │
│             TCG    │ Scry   │ OwnTrks │             │
│                    └──────────────────┘             │
└─────────────────────────────────────────────────────┘
```

The host is the **only** machine that:
- Holds API keys and the Fernet master key
- Runs the Celery Beat scheduler (global task dispatch)
- Hosts the RabbitMQ / Redis broker (local, never internet-exposed)
- Provides the webhook entry point via Cloudflare Tunnel
- Maintains the OpenClaw agent workspace and long-term memory

---

## 2. Service Inventory

All services the host runs, with ports and resource estimates:

| Service | Port | Protocol | Purpose | Memory est. |
|---|---|---|---|---|
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

**Total estimated RAM:** ~1.9 GB. With 16 GB available on the M4, the host runs everything
comfortably with headroom for local agent sessions.

**macOS Firewall:** Only one port needs attention:
```
Inbound  8000/TCP  — Cloudflare Tunnel (localhost; no direct internet exposure)
```
Tailscale requires **no inbound ports** — it connects outbound through NAT. All broker ports
(5672, 6379, 9200, 5555) remain LAN/VPN-only.

---

## 3. First-Time Setup

For a fresh machine (any OS). See [OS-COMPATIBILITY.md](OS-COMPATIBILITY.md) for platform notes.

### Prerequisites

- Python 3.12+
- Docker Desktop
- OpenClaw installed
- Claude Desktop or Claude Code with MCP support

### Clone and install

```bash
# 1. Clone both repos side by side
cd ~/GIT  # or %USERPROFILE%\GIT on Windows
git clone git@github.com:brianbartilet/harqis-work.git
git clone git@github.com:brianbartilet/harqis-openclaw-sync.git

# 2. Install Python deps
cd harqis-work
python -m venv .venv
# macOS/Linux:
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install --upgrade anyio && .venv/bin/pip install "mcp>=1.0.0"
# Windows:
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install --upgrade anyio && .venv\Scripts\pip install "mcp>=1.0.0"
```

> **Note:** `mcp` is installed in a separate step because `harqis-core` pins `anyio==4.3.0`
> while `mcp>=1.0.0` requires `anyio>=4.5`. Upgrading anyio after the base install is safe —
> harqis-core functions correctly with newer anyio versions.

### Configure environment

```bash
cp .env/apps.env.example .env/apps.env  # copy template if it exists
# Otherwise manually create .env/apps.env with the variables below
```

Minimum required variables:

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...

# Messaging
TELEGRAM_BOT_TOKEN=...
TELEGRAM_DEFAULT_CHAT_ID=...

# Finance (optional)
OANDA_BEARER_TOKEN=...
YNAB_ACCESS_TOKEN=...

# Project management (optional)
JIRA_DOMAIN=your.jira.io
JIRA_API_TOKEN=...
TRELLO_API_KEY=...
TRELLO_API_TOKEN=...

# Google (OAuth — requires credentials.json in .env/)
GOOGLE_APPS_API_KEY=...
```

### Start infrastructure and workers

```bash
# Infrastructure (Docker)
docker compose up -d

# Celery worker + Beat
celery -A workflows worker --beat -l INFO -Q default,hud,tcg,purchases

# Or separate processes
celery -A workflows worker -l INFO -Q hud
celery -A workflows beat -l INFO

# Frontend dashboard
cd frontend && uvicorn main:app --port 8000

# Flower (Celery monitor)
celery -A workflows flower --port 5555
```

### Connect MCP to Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "harqis-work": {
      "command": "/path/to/harqis-work/.venv/bin/python",
      "args": ["/path/to/harqis-work/mcp/server.py"]
    }
  }
}
```

See `mcp/claude_desktop_config.json` for a ready-to-paste snippet. Restart Claude Desktop
after editing — the harqis-work tools will appear in the tools panel.

---

## 4. Host Deployment (Mac Mini / Primary Server)

### 4.1 System prerequisites

```bash
# Install Homebrew
/bin/bash -c "$(curl -fsSL https://brew.sh)"

# System tools
brew install git python@3.12 cloudflared tailscale

# Docker Desktop for Mac
brew install --cask docker
```

### 4.2 Clone and environment setup

```bash
git clone https://github.com/brianbartilet/harqis-work.git /opt/harqis
cd /opt/harqis

python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install --upgrade anyio && pip install "mcp>=1.0.0"
```

### 4.3 Secrets in macOS Keychain

Store sensitive values in Keychain rather than `.env` files:

```bash
security add-generic-password -a harqis -s ANTHROPIC_API_KEY -w "sk-ant-..."
```

Create `scripts/macos/load_keychain_secrets.sh`:

```bash
#!/usr/bin/env bash
_kcget() { security find-generic-password -a harqis -s "$1" -w 2>/dev/null; }
export ANTHROPIC_API_KEY=$(_kcget ANTHROPIC_API_KEY)
export OPENAI_API_KEY=$(_kcget OPENAI_API_KEY)
export HARQIS_FERNET_KEY=$(_kcget HARQIS_FERNET_KEY)
```

Source before starting workers: `source scripts/macos/load_keychain_secrets.sh`

### 4.4 Start Celery workers

```bash
cd /opt/harqis
source .venv/bin/activate && source scripts/linux/set_env_workflows.sh

# Beat scheduler (one instance globally — run only on the host)
python run_workflows.py beat &

# Workers
WORKFLOW_QUEUE=default python run_workflows.py worker &
WORKFLOW_QUEUE=adhoc   python run_workflows.py worker &
```

HUD and TCG queues run on Windows N100 nodes. If consolidating all queues to the host:

```bash
WORKFLOW_QUEUE=hud python run_workflows.py worker &
WORKFLOW_QUEUE=tcg python run_workflows.py worker &
```

### 4.5 Cloudflare Tunnel (public webhook entry)

```bash
cloudflared tunnel login
cloudflared tunnel create harqis-server
cloudflared tunnel route dns harqis-server harqis.yourdomain.com
cloudflared tunnel run --url http://localhost:8000 harqis-server
```

This gives a stable `https://harqis.yourdomain.com` for n8n webhooks, Trello webhooks, and
external agent callbacks — no static IP required.

### 4.6 Run on startup (launchd)

```xml
<!-- ~/Library/LaunchAgents/com.harqis.server.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.harqis.server</string>
  <key>ProgramArguments</key>
  <array><string>/opt/harqis/scripts/macos/start_server.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/opt/harqis/scripts/app.log</string>
  <key>StandardErrorPath</key><string>/opt/harqis/scripts/app-debug.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.harqis.server.plist
```

### 4.7 Migrating queues from Windows N100 to Mac Mini

The N100 Windows machine handles `hud` and `tcg` queues. To shift `tcg` to the Mac Mini:

1. Start `tcg` worker on Mac Mini: `WORKFLOW_QUEUE=tcg python run_workflows.py worker &`
2. Stop `tcg` worker on N100 (`run_workflow_worker_tcg.bat`)
3. Beat scheduler: stop on N100, start on Mac Mini
4. N100 becomes HUD-only (`hud,windows` queues — Windows-native tasks that can't migrate)

**Key environment variables that differ between machines:**

| Variable | Windows (N100) | macOS (Mac Mini) |
|---|---|---|
| `PYTHON_EXE` | `C:\...\harqis-work\.venv\Scripts\python.exe` | `/opt/harqis/.venv/bin/python` |
| `ENV_ROOT` | `C:\Users\...\run\harqis-work` | `/opt/harqis` |
| `RAINMETER_*` | Windows-only | Set to empty |
| `DESKTOP_PATH_*` | Windows paths | macOS paths |

---

## 5. OpenClaw Agent Configuration

### 5.1 Workspace files

The OpenClaw workspace lives in the sync repo: `harqis-openclaw-sync/.openclaw/workspace/`.
On the host, this persists between sessions and defines the server's agent identity.

| File | Purpose |
|---|---|
| `SOUL.md` | Agent personality — concise, opinionated, resourceful, not sycophantic |
| `USER.md` | Who the agent assists — context, preferences, work style |
| `AGENTS.md` | Session startup rules, memory conventions, heartbeat behavior |
| `TOOLS.md` | Environment-specific: device names, SSH hosts, service URLs, voice prefs |
| `HEARTBEAT.md` | Checklist of periodic background checks |
| `MEMORY.md` | Long-term narrative memory index (loaded in direct/main sessions) |
| `memory/YYYY-MM-DD.md` | Daily raw logs — decisions made, context, task outcomes |
| `memory/private.md` | Sensitive info (gitignored) |

See [OPENCLAW-SYNC.md](OPENCLAW-SYNC.md) for how the sync repo is structured and kept
up-to-date across machines.

### 5.2 Session startup sequence

Every OpenClaw session automatically:

1. Reads `SOUL.md` — establishes identity
2. Reads `USER.md` — loads user context
3. Reads today + yesterday's `memory/YYYY-MM-DD.md` — recent context
4. In direct/main sessions: also reads `MEMORY.md` (long-term memory)

The agent **wakes up knowing who it is and what's been happening** without re-explanation every
session.

### 5.3 Heartbeat (background polling)

OpenClaw periodically polls the agent with a heartbeat message. The agent reads `HEARTBEAT.md`
and either acts on listed tasks or replies `HEARTBEAT_OK` if nothing needs attention.

Host-specific `HEARTBEAT.md` example:

```markdown
- Check Celery queue depths via Flower API (http://localhost:5555/api/queues)
- If any queue depth > 10 for 10+ minutes, alert via Telegram
- Check Telegram for unread messages
- Check Google Calendar for events in next 2 hours
- If VPS nodes are unresponsive (tailscale ping vps1), alert and log to Elasticsearch
- Check OANDA open trades if market is open (Mon–Fri 00:00–22:00 UTC)
- Write daily summary to .openclaw/workspace/memory/YYYY-MM-DD.md
```

### 5.4 Host-specific TOOLS.md

Update `TOOLS.md` to reflect the Mac Mini environment:

```markdown
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

## Services
- RabbitMQ mgmt: http://localhost:15672
- Flower:        http://localhost:5555
- Frontend:      http://localhost:8000
- n8n:           http://localhost:5678
- Kibana:        http://localhost:5601
```

### 5.5 Fernet master key

Generate once and store in Keychain:

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())   # copy this value
```

```bash
security add-generic-password -a harqis -s HARQIS_FERNET_KEY -w "<generated key>"
```

This key encrypts scoped secrets sent to worker nodes. It never leaves the host.

---

## 6. MCP Server & Tools

The MCP server (`mcp/server.py`) exposes **55 tools** across 16 integrated services. Any Claude
agent (Desktop, Claude Code, OpenClaw) connected to this server can call any tool.

See **[mcp/README.md](../../mcp/README.md)** for the full tool catalog and usage examples.

### Tool categories

| Category | Services | Example tools |
|---|---|---|
| **Finance** | OANDA, YNAB | `get_oanda_open_trades`, `get_ynab_budget_summary` |
| **Productivity** | Google Calendar, Gmail, Keep | `get_google_calendar_events_today`, `get_gmail_recent_emails` |
| **Project mgmt** | Jira, Trello | `search_jira_issues`, `get_trello_cards` |
| **Messaging** | Telegram, Discord | `send_telegram_message_to_default`, `send_discord_message` |
| **Trading cards** | Scryfall, Echo MTG, TCG MP | `get_scryfall_card`, `get_echo_mtg_collection` |
| **Location** | OwnTracks | `get_last_location`, `get_location_history` |
| **Cloud VMs** | Orgo | `provision_computer`, `take_screenshot`, `run_bash` |
| **AI** | Anthropic | `run_claude_prompt`, `list_models` |

### Multi-app automation example

```
"Check if I have any Jira tickets due today, cross-reference with my
Google Calendar, send me a Telegram summary, and if OANDA has open
trades post their P&L too."
```

Claude calls: `search_jira_issues` → `get_google_calendar_events_today` →
`get_oanda_open_trades` → `send_telegram_message_to_default`. No code written.

### MCP as a remote endpoint

The host MCP server can be reached from remote machines over SSH port forwarding:

```bash
# On a remote machine
ssh -L 9999:localhost:stdio user@mac-mini \
  /opt/harqis/.venv/bin/python /opt/harqis/mcp/server.py
```

Or in `claude_desktop_config.json` on a remote machine:

```json
{
  "mcpServers": {
    "harqis-work": {
      "command": "ssh",
      "args": ["mac-mini", "/opt/harqis/.venv/bin/python", "/opt/harqis/mcp/server.py"]
    }
  }
}
```

### Adding a new app

```bash
/new-app <app_name>   # Claude Code skill scaffolds the structure
```

Or manually:
```
apps/<new_app>/
├── config.py
├── mcp.py              # register_<app>_tools(mcp: FastMCP)
├── references/web/api/
└── tests/
```

Then register in `mcp/server.py` and add config to `apps_config.yaml`.

---

## 7. Claude Code Skills Integration

Claude Code skills (slash commands in `.claude/commands/`) and OpenClaw share the same host
filesystem. Skills can read OpenClaw identity files as live dynamic context, inject live service
data via MCP, and write back to the daily memory log.

See **[SKILLS-GUIDE.md](SKILLS-GUIDE.md)** for the full skills reference and OpenClaw
integration patterns.

### Skills in this repo

| Skill | Purpose |
|---|---|
| `/new-app <name>` | Scaffold a new app integration under `apps/` |
| `/new-workflow <name>` | Create a workflow directory with a Celery task template |
| `/run-tests <app>` | Run pytest for a specific app with correct flags |
| `/generate-registry` | Rebuild `frontend/registry.py` from all `tasks_config.py` files |
| `/agent-prompt <name>` | Run a named prompt from `agents/prompts/` against the codebase |

### Skills + OpenClaw as a hands-free developer

OpenClaw agents can invoke Claude Code (and its skills) as a subprocess:

1. Agent receives: *"add a new Jira workflow that posts overdue tickets to Telegram daily"*
2. Agent calls Claude Code: `/new-workflow jira_digest`
3. Claude Code scaffolds the workflow, writes the task, registers it in `tasks_config.py`
4. Agent commits, runs `/run-tests jira`, notifies via Telegram when done

The agent becomes a hands-free developer — extending this codebase in response to natural
language instructions.

---

## 8. Worker Nodes & Networking

### 8.1 Tailscale VPN setup

Tailscale creates a mesh VPN with no server to manage. All nodes authenticate via the Tailscale
control plane and communicate peer-to-peer.

```bash
# Mac Mini (host)
sudo tailscaled &
tailscale up
tailscale up --advertise-tags=tag:server

# VPS worker nodes (Linux)
curl -fsSL https://tailscale.com/install.sh | sh && tailscale up
tailscale up --advertise-tags=tag:worker

# Verify all nodes connected
tailscale status
```

N100 Windows: install the Tailscale Windows client → Log in → assign `tag:hud-node` in the
admin console.

### 8.2 Worker node configuration

After joining Tailscale, workers point to the host by MagicDNS name:

```bash
export CELERY_BROKER_URL=amqp://guest:guest@mac-mini:5672/
export CELERY_RESULT_BACKEND=redis://mac-mini:6379/0
```

Or in `apps_config.yaml`:

```yaml
CELERY_TASKS:
  broker: 'amqp://guest:guest@mac-mini:5672/'
```

Replace `mac-mini` with the actual MagicDNS hostname (`mac-mini.tail1234.ts.net`) or Tailscale
IP (`100.x.x.x`) from `tailscale status`.

### 8.3 Queue assignment

| Node | Queues | Primary agent types |
|---|---|---|
| Mac Mini (host) | `default`, `adhoc`, `tcg` | orchestrator, scheduler, general |
| VPS nodes | `code`, `write`, `default` | software-dev, research, content |
| N100 Windows | `hud`, `windows` | Windows-native HUD, desktop automation |

Use `hw:<node>` Trello card labels to pin specific tasks to specific hardware. See
[TRELLO-AGENT-KANBAN.md](../thesis/TRELLO-AGENT-KANBAN.md) for the full routing design.

### 8.4 Port binding and firewall

Some Docker services default to `127.0.0.1` bindings, which are unreachable from Tailscale
nodes. Remove the `127.0.0.1:` prefix so Docker binds to all interfaces:

| Service | Fixed binding | Tailscale-reachable |
|---|---|---|
| RabbitMQ mgmt (15672) | `15672` | ✅ |
| Redis (6379) | `6379` | ✅ |
| Elasticsearch (9200) | `9200` | ✅ |
| Kibana (5601) | `5601` | ✅ |

If the macOS application firewall is enabled, add Docker to the allow list:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw \
  --add /Applications/Docker.app/Contents/MacOS/Docker
sudo /usr/libexec/ApplicationFirewall/socketfilterfw \
  --unblockapp /Applications/Docker.app/Contents/MacOS/Docker
```

### 8.5 Tailscale ACL policy

The full ACL policy lives at `scripts/tailscale/acl-policy.hujson`. Apply at
`https://login.tailscale.com/admin/acls`.

| Tag | Nodes | Ports allowed on host | Rationale |
|---|---|---|---|
| `tag:server` | Mac Mini | — (it is the server) | |
| `tag:worker` | VPS Celery nodes | 5672, 6379, 9200 | Broker + result backend + ES logging |
| `tag:hud-node` | N100 Windows | 5672, 6379 | Celery HUD queue only; no admin UIs |
| `tag:personal` | Laptop, phone | all | Full admin access |

### 8.6 n8n secure cookie fix

When accessing n8n over plain HTTP on a Tailscale URL, set in `docker-compose.yml`:

```yaml
n8n:
  environment:
    N8N_SECURE_COOKIE: "false"   # safe — Tailscale traffic is WireGuard-encrypted
```

Long-term: use `tailscale serve --https=443 --bg http://localhost:5678` to get a TLS cert and
re-enable `N8N_SECURE_COOKIE: "true"`.

---

## 9. Multi-Agent Topology

For a fully autonomous setup across machines:

```
Mac Mini (Host / OpenClaw Server)
├── OpenClaw agent (main session — Telegram/WhatsApp UI)
├── MCP server → Claude Desktop + remote workers
├── Celery Beat scheduler (global)
├── Celery workers (default, adhoc, tcg)
├── n8n orchestration
└── All Docker infrastructure

VPS Workers (Hetzner, Tailscale)
├── Celery workers (code, write, default)
└── OpenClaw agent (background worker)

N100 Windows (Home LAN, Tailscale)
├── Celery workers (hud, windows — Windows-native only)
└── Rainmeter HUD (live data widgets)

Shared Coordination Layer
├── Telegram — agent ↔ human messaging + status notifications
├── Trello   — task board (agents create/update cards)
├── Jira     — issue tracking (agents log findings)
└── YNAB     — finance agent writes budget updates
```

Each agent:
- Has its own `TOOLS.md` (machine-specific paths and services)
- Shares `SOUL.md` and `AGENTS.md` (common identity and rules)
- Coordinates through shared services above
- Reports failures to Telegram, logs everything to Elasticsearch

See [TRELLO-AGENT-KANBAN.md](../thesis/TRELLO-AGENT-KANBAN.md) for the full Kanban-driven
agent orchestration design, including specialized agent profiles, permission model, and
hardware routing.

---

## 10. Monitoring & Observability

### Flower (Celery task monitor)

```bash
celery -A workflows flower --port=5555
# Access: http://localhost:5555
```

Key views: Workers (online/offline, queues served), Tasks (history, success/failure rates),
Queues (current depth — use to detect backlog).

### Frontend dashboard

`http://localhost:8000` — trigger any task manually, see last 20 run results per task with JSON
output, real-time status polling via HTMX.

### Elasticsearch + Kibana

Every task decorated with `@log_result()` writes to `http://localhost:9200`,
index `harqis-elastic-logging`. Query via Kibana at `http://localhost:5601`.

```
# Failed tasks in last 24h
status:failed AND @timestamp:[now-24h TO now]

# Specific task type
task_name:workflows.hud.tasks.hud_gpt.get_desktop_logs
```

### Telegram alerts

```python
from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages
from apps.telegram.config import CONFIG as TELEGRAM_CONFIG

ApiServiceTelegramMessages(TELEGRAM_CONFIG).send_message(
    chat_id=TELEGRAM_CONFIG.app_data['default_chat_id'],
    text="[HARQIS-CLAW Host] Task X completed: result summary"
)
```

Or via MCP: ask Claude to `send_telegram_message_to_default`.

### Health check endpoint

The frontend exposes `GET /health`. Point uptime monitoring (UptimeRobot, Better Uptime) to
the Cloudflare Tunnel URL: `https://harqis.yourdomain.com/health`.

### n8n monitoring flows

n8n at `http://localhost:5678` can poll Celery via Flower HTTP API. Example flow:
task fails → send Telegram → update Trello card. `workflows.mapping` exposes all scheduled
tasks to n8n dynamically.

---

## 11. Docker & Infrastructure

### Recommended production docker-compose

```yaml
# docker-compose.yml — HARQIS-CLAW Host
services:

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
    volumes:
      - ./apps/own_tracks/recorder_store:/store
    depends_on: [mosquitto]

  n8n:
    image: docker.n8n.io/n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    ports:
      - "${HOST_PORT_N8N:-5678}:5678"
    volumes:
      - n8n_data:/home/node/.n8n
    environment:
      TZ: Asia/Singapore
      N8N_TIMEZONE: Asia/Singapore
      N8N_SECURE_COOKIE: "false"   # remove after enabling Tailscale HTTPS
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      rabbitmq:
        condition: service_healthy

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

  cloudflared:
    image: cloudflare/cloudflared:latest
    container_name: cloudflared
    restart: unless-stopped
    command: tunnel run
    environment:
      TUNNEL_TOKEN: ${CLOUDFLARE_TUNNEL_TOKEN}
    depends_on: [n8n]

volumes:
  rabbitmq_data:
  redis_data:
  n8n_data:
  elastic_data:
```

Celery workers and Beat run as processes (not containers) to keep deployment simple.
Containerise them once the service is stable.

---

## 12. Maintenance Runbook

### Restart Celery workers

```bash
pkill -f "run_workflows.py worker"
sleep 3
cd /opt/harqis && source .venv/bin/activate && source scripts/linux/set_env_workflows.sh
WORKFLOW_QUEUE=default python run_workflows.py worker &
WORKFLOW_QUEUE=adhoc   python run_workflows.py worker &
python run_workflows.py beat &
```

### Deploy code updates

```bash
cd /opt/harqis
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt   # only if requirements changed
# restart workers (above)
```

### Restart all Docker services

```bash
cd /opt/harqis
docker compose down && docker compose up -d
```

### Add a new VPS worker node

1. Provision VPS (Hetzner CX22 recommended)
2. `curl -fsSL https://tailscale.com/install.sh | sh && tailscale up`
3. Approve in Tailscale admin console
4. Verify: `tailscale ping <new-node-hostname>`
5. Bootstrap: run `scripts/linux/bootstrap_worker.sh`
6. Node auto-starts Celery worker on `code,write,default` queues

### Rotate the Fernet key

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
security delete-generic-password -a harqis -s HARQIS_FERNET_KEY
security add-generic-password -a harqis -s HARQIS_FERNET_KEY -w "<new key>"
source scripts/macos/load_keychain_secrets.sh
# restart workers — old in-flight tasks encrypted with the previous key will fail
```

### Check service health

```bash
docker compose ps
celery -A core.apps.sprout.app.celery:SPROUT inspect active
tailscale status
```

---

## 13. Tailscale VPN & Access Control

See section [8. Worker Nodes & Networking](#8-worker-nodes--networking) for setup.

The full ACL policy is at `scripts/tailscale/acl-policy.hujson`. Key security notes for
VPN-exposed services:

| Service | Default credentials | Recommended action |
|---|---|---|
| RabbitMQ | `guest` / `guest` | Set `RABBITMQ_USER` and `RABBITMQ_PASS` in `.env/apps.env` |
| Redis | no password | Add `--requirepass ${REDIS_PASSWORD}` in compose |
| Elasticsearch | xpack disabled | Acceptable for VPN-only access |
| Kibana | unauthenticated | Restrict to `tag:personal` in Tailscale ACL |
| n8n | basic auth via env | Configure `N8N_BASIC_AUTH_*` in `.env/apps.env` |

> **Optional — Headscale (self-hosted control plane):** Run
> [Headscale](https://github.com/juanfont/headscale) on a Hetzner VPS and point all nodes at it
> with `tailscale up --login-server https://your-headscale-host` for zero dependency on
> Tailscale's servers.

---

## 14. Quick Reference

### Key URLs

| Service | URL |
|---|---|
| Frontend Dashboard | `http://localhost:8000` |
| Flower (Celery monitor) | `http://localhost:5555` |
| n8n | `http://localhost:5678` |
| Kibana | `http://localhost:5601` |
| RabbitMQ mgmt | `http://localhost:15672` |
| OwnTracks Recorder | `http://localhost:8083` |

### Start everything (single machine)

```bash
docker compose up -d
WORKFLOW_QUEUE=default python run_workflows.py worker &
WORKFLOW_QUEUE=adhoc   python run_workflows.py worker &
python run_workflows.py beat &
cd frontend && uvicorn main:app --port 8000 &
celery -A workflows flower --port 5555 &
# MCP server is auto-started by Claude Desktop
```

### Common agent commands (via MCP / Claude)

```
"Where is my phone?"              → get_last_location
"Any Jira tickets due today?"     → search_jira_issues(jql="due = today")
"What's my YNAB budget looking?"  → get_ynab_budget_summary
"Any open OANDA trades?"          → get_oanda_open_trades
"Send me a Telegram summary"      → send_telegram_message_to_default
"Check my calendar for today"     → get_google_calendar_events_today
```

### Host summary

| Dimension | Value |
|---|---|
| **Hardware** | Mac Mini M4, 16 GB RAM, 256 GB SSD |
| **All services** | RabbitMQ, Redis, n8n, Mosquitto, OwnTracks, ES, Kibana, Frontend, Flower, Cloudflare Tunnel |
| **RAM usage** | ~1.9 GB (headroom: ~13 GB) |
| **Queues on host** | `default`, `adhoc`, `tcg` |
| **Queues on N100** | `hud`, `windows` (Windows-native only) |
| **Public entry** | Cloudflare Tunnel → `https://harqis.yourdomain.com` |
| **Secret storage** | macOS Keychain → Fernet-encrypted payloads to workers |
| **Code deployment** | `git pull` + worker restart |
| **Agent identity** | `harqis-openclaw-sync/.openclaw/workspace/` — synced across machines |
| **Worker mesh** | Tailscale VPN (VPS + N100 Windows) |
