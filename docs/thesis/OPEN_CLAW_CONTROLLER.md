# HARQIS-Work — OpenClaw Controller Guide

![OpenClaw Employee](docs/images/openclaw-employee.png)

A practical guide to running **harqis-work** as a general-purpose, multi-agent automation platform using OpenClaw, Claude skills, and MCP-connected apps.

---

## What This Is

**harqis-work** is a code-first automation platform. At its core:

- **Apps** (`apps/`) — 19 REST/local service integrations (finance, trading, calendar, messaging, etc.)
- **Workflows** (`workflows/`) — Celery tasks that run on schedules, trigger actions, push data to a desktop HUD
- **MCP server** (`mcp/`) — Exposes every app as a callable tool to Claude agents
- **Frontend** (`frontend/`) — Web dashboard to manually trigger any task
- **OpenClaw workspace** (`.openclaw/workspace/`) — Persistent agent identity, memory, and behavior rules

The idea: **OpenClaw agents use MCP tools + Celery workflows + n8n to automate real tasks across real services, with Claude as the reasoning layer.**

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  CONTROL LAYER                      │
│                                                     │
│  OpenClaw Agent ◄──► Claude (via MCP)               │
│       │                    │                        │
│       │              55 MCP tools                   │
│       │         (finance, calendar, GPS,             │
│       │          messaging, trading, cards)          │
│       │                                              │
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

---

## 1. Running This on Another Machine

### Prerequisites

- Python 3.12+
- Docker Desktop (for RabbitMQ, Elasticsearch, OwnTracks)
- OpenClaw installed ([openclaw.ai](https://openclaw.ai))
- Claude Desktop or Claude Code with MCP support

### Clone and Install

```bash
git clone https://github.com/brianbartilet/harqis-work.git
cd harqis-work

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

pip install -r requirements.txt
```

### Configure Environment

Copy and fill in the env template:

```bash
cp .env/apps.env.example .env/apps.env  # if example exists, otherwise copy from README
```

Key variables to fill in:

```env
# Required for most workflows
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...

# Messaging (for agent notifications)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_DEFAULT_CHAT_ID=...

# Finance (optional — only if you use these)
OANDA_BEARER_TOKEN=...
YNAB_ACCESS_TOKEN=...

# Project management (optional)
JIRA_DOMAIN=your.jira.io
JIRA_API_TOKEN=...
TRELLO_API_KEY=...
TRELLO_API_TOKEN=...

# Google (OAuth — requires credentials.json)
GOOGLE_APPS_API_KEY=...
```

### Start Infrastructure

```bash
# Start RabbitMQ + any other Docker services
docker compose up -d   # if root docker-compose.yml exists

# Or start OwnTracks GPS tracker specifically
cd apps/own_tracks
docker compose up -d
```

### Start Celery Workers

```bash
# Worker + Beat scheduler (all queues)
celery -A workflows worker --beat -l INFO -Q default,hud,tcg

# Or separate processes
celery -A workflows worker -l INFO -Q hud
celery -A workflows beat -l INFO
```

### Connect MCP to Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "harqis-work": {
      "command": "C:\\path\\to\\harqis-work\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\harqis-work\\mcp\\server.py"]
    }
  }
}
```

See `mcp/claude_desktop_config.json` for the exact format.

### Start the Web Dashboard

```bash
cd frontend
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` — you can manually trigger any Celery task from here.

---

## 2. OpenClaw Agent Setup

OpenClaw runs a persistent Claude agent that reads from `.openclaw/workspace/` on every session. This workspace defines who the agent is and how it behaves.

### Workspace Files

| File | Purpose |
|---|---|
| `AGENTS.md` | Session startup rules, memory conventions, group chat etiquette, heartbeat behavior |
| `SOUL.md` | Agent personality — concise, opinionated, resourceful, not sycophantic |
| `USER.md` | Who the agent is helping — their context, preferences, work style |
| `TOOLS.md` | Environment-specific notes (device names, SSH hosts, voice preferences) |
| `HEARTBEAT.md` | Checklist of periodic background checks (email, calendar, mentions) |
| `MEMORY.md` | Long-term curated memory — only loaded in direct/main sessions |
| `memory/YYYY-MM-DD.md` | Daily raw logs — what happened, decisions made, context |

### Session Startup Sequence

Every time an OpenClaw agent starts, it automatically:

1. Reads `SOUL.md` — establishes identity
2. Reads `USER.md` — loads user context
3. Reads today + yesterday's `memory/YYYY-MM-DD.md` — recent context
4. In main/direct sessions: also reads `MEMORY.md` (personal long-term memory)

This means the agent **wakes up knowing who it is and what's been happening**, without you re-explaining context every session.

### Heartbeat (Background Polling)

OpenClaw periodically polls the agent with a heartbeat message. The agent reads `HEARTBEAT.md` and either:

- Acts on any listed tasks (check email, check calendar, run a workflow)
- Replies `HEARTBEAT_OK` if nothing needs attention

Edit `HEARTBEAT.md` to customize what the agent monitors:

```markdown
# HEARTBEAT.md
- Check Telegram for unread messages
- Check Google Calendar for events in next 2 hours
- If OANDA has open trades, get current P&L
- Check Celery queue — are any jobs failing?
```

### Multiple Agents on Multiple Machines

To run coordinated agents across machines:

1. **Clone the repo** on each machine with its own `.env/apps.env` (different credentials if needed)
2. **Each machine gets its own agent profile** in `.openclaw/agents/` — different identity, same workspace files
3. **Agents coordinate via shared services**: Telegram messages, Trello cards, n8n webhooks, or a shared Elasticsearch index
4. **Task routing**: Use Celery queue names (`default`, `hud`, `tcg`) to route work to the right machine's worker

Example: Machine A (home) handles `hud` + `desktop` queues. Machine B (server) handles `tcg` + `purchases` queues.

---

## 3. Monitoring Agents and Machines

### Built-In Options

**Flower** (Celery task monitor):
```bash
celery -A workflows flower --port=5555
```
Open `http://localhost:5555` — shows all workers, queues, task history, failures.

**Frontend Dashboard** (`http://localhost:8000`):
- Trigger any task manually
- See last 20 run results per task with JSON output
- Real-time status polling via HTMX

**Elasticsearch** (optional, auto-logging):
- Every task decorated with `@log_result()` writes to Elasticsearch
- Query via Kibana at `http://localhost:5601`
- Index: `harqis-elastic-logging`

### External Monitoring Options

**[orgo.ai](https://orgo.ai)** or similar agent monitoring:
- Connect via the MCP server — any monitoring tool that supports MCP can query task status, get Celery queue depth, and read Elasticsearch logs through the tool layer
- Alternatively, expose a `/health` endpoint from the frontend (`GET /health` already exists) for uptime monitoring

**Telegram as a monitoring channel**:
The Telegram MCP tool (`send_telegram_message`) is the simplest agent-to-human notification channel. Add to heartbeat:

```python
# In any workflow task
from apps.telegram.references.web.api.messages import ApiServiceTelegramMessages
from apps.telegram.config import CONFIG

ApiServiceTelegramMessages(CONFIG).send_message(
    chat_id=CONFIG.app_data['default_chat_id'],
    text="Task X completed: result summary here"
)
```

Or via MCP: ask Claude to `send_telegram_message_to_default` with a status update.

**n8n** (local workflow monitoring):
- n8n at `http://localhost:5678` can poll Celery via Flower HTTP API
- Build notification flows: task fails → send Telegram → update Trello card
- `workflows.mapping` exposes all scheduled tasks to n8n dynamically

---

## 4. Connecting Apps via MCP

The MCP server (`mcp/server.py`) exposes **55 tools** across 10 integrated services. Any Claude agent (Desktop, Claude Code, OpenClaw) connected to this server can call any of these tools.

### Available Tool Categories

| Category | Tools |
|---|---|
| **Finance** | OANDA trades, YNAB budgets/accounts/transactions |
| **Productivity** | Google Calendar, Gmail, Google Keep notes |
| **Project Mgmt** | Jira issues/projects/users, Trello boards/cards/members |
| **Messaging** | Telegram send/receive/chat info; Discord messages, guilds, webhooks |
| **Trading Cards** | Scryfall card lookup, Echo MTG collection, TCG Marketplace listings/orders |
| **Location** | OwnTracks last position, location history, device list |
| **Cloud VMs** | Orgo cloud computers — provision, screenshot, bash, control |

### Adding a New App

1. Follow the standard app template:

```
apps/<new_app>/
├── config.py
├── references/
│   ├── web/
│   │   ├── base_api_service.py   # Extends BaseFixtureServiceRest
│   │   └── api/
│   │       └── service.py        # @deserialized(dict) methods
│   └── dto/
├── mcp.py                        # register_<app>_tools(mcp: FastMCP)
└── tests/
```

Or use the Claude skill:
```
/new-app <app_name>
```

2. Register in `mcp/server.py`:

```python
from apps.<new_app>.mcp import register_<new_app>_tools
# ...
register_<new_app>_tools(mcp)
```

3. Add config to `apps_config.yaml` and env vars to `.env/apps.env`

### Multi-App Automation Example

Here's what a Claude agent can do in a single session using MCP tools:

> "Check if I have any Jira tickets due today, cross-reference with my Google Calendar, send me a Telegram summary, and if OANDA has open trades post their P&L too."

Claude calls:
1. `search_jira_issues` — JQL: `assignee = currentUser() AND due = today`
2. `get_google_calendar_events_today` — today's schedule
3. `get_oanda_open_trades` — current forex positions
4. `send_telegram_message_to_default` — combined summary

No code written. No manual steps. The MCP layer makes every service directly callable.

---

## 5. Claude Skills and How They Work with OpenClaw

### What Claude Skills Are

Claude skills (slash commands) are markdown files in `.claude/commands/` that expand into full prompts when invoked. They are **reusable instructions** for Claude Code.

Available skills in this repo:

| Skill | Command | What It Does |
|---|---|---|
| New App | `/new-app <name>` | Scaffolds full app integration structure under `apps/` |
| New Workflow | `/new-workflow <name>` | Creates workflow directory with Celery task template |
| Run Tests | `/run-tests <app>` | Runs pytest for a specific app with correct flags |
| Generate Registry | `/generate-registry` | Rebuilds `frontend/registry.py` from all `tasks_config.py` files |
| Agent Prompt | `/agent-prompt <name>` | Runs a named prompt file from `prompts/` against the codebase |

### How Skills Are Defined

Each skill is a markdown file in `.claude/commands/`:

```markdown
# .claude/commands/new-app.md

Scaffold a new app integration under `apps/`.

The argument $ARGUMENTS is the new app name in snake_case.

Steps:
1. Create directory apps/$ARGUMENTS/ with standard structure
2. Write config.py using the standard pattern
3. Remind user to add section to apps_config.yaml
```

When you type `/new-app telegram` in Claude Code, it substitutes `$ARGUMENTS` → `telegram` and runs the full instructions as a prompt.

### Skills + OpenClaw Together

OpenClaw agents can invoke Claude Code (and its skills) as a subprocess tool. This means:

- OpenClaw agent receives a Telegram message: *"add a new Jira workflow that posts overdue tickets to Telegram daily"*
- Agent calls Claude Code with `/new-workflow jira_digest`
- Claude Code scaffolds the workflow, writes the task, registers it in `tasks_config.py`
- Agent commits the change, runs tests via `/run-tests jira`
- Agent notifies you via Telegram when done

The agent becomes a **hands-free developer** — it can extend this codebase in response to natural language instructions.

### Creating Your Own Skills

Add a `.md` file to `.claude/commands/`:

```markdown
# .claude/commands/deploy-workflow.md

Deploy a specific workflow to the Celery worker.

Steps:
1. Run `python frontend/generate_registry.py` to update the registry
2. Restart the Celery beat scheduler
3. Confirm the task appears in `workflows.mapping`
4. Send a Telegram notification confirming deployment
```

Then invoke it: `/deploy-workflow`

Skills work in Claude Code sessions. For OpenClaw to use them, it either:
1. Runs Claude Code as a subprocess (`claude /skill-name args`)
2. Or the skill logic is replicated in `AGENTS.md` as agent instructions

---

## 6. Recommended Multi-Agent Topology

For a fully autonomous setup across machines:

```
Machine A (Home / Desktop)
├── OpenClaw agent (main session — WhatsApp/Telegram UI)
├── MCP server → Claude Desktop
├── Celery worker (hud, desktop queues)
├── Rainmeter HUD (live data widgets)
└── n8n (orchestration)

Machine B (Server / Headless)
├── OpenClaw agent (background worker)
├── Celery worker (purchases, tcg queues)
├── Elasticsearch + Kibana (log aggregation)
└── Docker: RabbitMQ, OwnTracks

Shared Coordination Layer
├── Telegram (agent ↔ human messaging + status notifications)
├── Trello (task board — agents create/update cards)
├── Jira (issue tracking — agents log findings)
└── YNAB (finance agent writes budget updates)
```

Each agent:
- Has its own `USER.md` and `TOOLS.md` (machine-specific config)
- Shares `SOUL.md` and `AGENTS.md` (common identity + rules)
- Coordinates through the shared services above
- Reports failures to Telegram, logs everything to Elasticsearch

---

## 7. Quick Reference

### Start Everything (Single Machine)

```bash
# 1. Infrastructure
docker compose up -d

# 2. Celery
celery -A workflows worker --beat -l INFO -Q default,hud,tcg,purchases

# 3. Frontend
cd frontend && uvicorn main:app --port 8000

# 4. Flower (monitoring)
celery -A workflows flower --port 5555

# 5. MCP server (auto-started by Claude Desktop)
# Configured in claude_desktop_config.json
```

### Key URLs

| Service | URL |
|---|---|
| Frontend Dashboard | `http://localhost:8000` |
| Flower (Celery monitor) | `http://localhost:5555` |
| n8n | `http://localhost:5678` |
| Kibana | `http://localhost:5601` |
| OwnTracks Recorder | `http://localhost:8083` |

### Common Agent Commands (via MCP / Claude)

```
"Where is my phone?" → get_last_location
"Any Jira tickets due today?" → search_jira_issues(jql="due = today")
"What's my YNAB budget looking like?" → get_ynab_budget_summary
"Any open OANDA trades?" → get_oanda_open_trades
"Send me a Telegram summary" → send_telegram_message_to_default
"Check my calendar for today" → get_google_calendar_events_today
```

---

## Further Reading

- `CLAUDE.md` — Full codebase guide for Claude Code (architecture, patterns, known issues)
- `mcp/README.md` — All 55 MCP tools documented
- `apps/<name>/README.md` — Per-app setup and usage
- `.openclaw/workspace/AGENTS.md` — Agent behavior rules
- `.openclaw/workspace/SOUL.md` — Agent personality and values
