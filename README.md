# HARQIS Work

## Introduction

- Real-world implementation of [HARQIS-core](https://github.com/brianbartilet/harqis-core), integrating 16+ third-party applications and automation layers.
- Demonstrates **RPA-like capabilities** implemented entirely in Python with Celery, n8n, and AI-driven workflows.
- Provides an extensible portfolio of automated routines for business, productivity, and personal systems.
- Think of it as a code-first RPA platform — every integration is a Python module, every scheduled routine is a Celery task, and every repetitive job is a candidate for an AI agent.

---

## App Inventory

| App | Integration | Type | Tests | Links |
|-----|-------------|------|-------|-------|
| `aaa` | Philippine stock exchange (PSEI) | Selenium | Yes | [Site](https://aaa-equities.com.ph/) |
| `antropic` | Anthropic Claude API | REST (native SDK) | Yes | [API Docs](https://docs.anthropic.com/en/api/) · [Console](https://console.anthropic.com/) |
| `desktop` | Windows desktop automation | Local | No | — |
| `discord` | Discord bot — messaging, guilds, webhooks | REST API | Yes | [API Docs](https://discord.com/developers/docs/reference) · [Portal](https://discord.com/developers/applications) |
| `echo_mtg` | MTG collection management | REST API | Yes | [API Docs](https://www.echomtg.com/api/) · [Site](https://www.echomtg.com/) |
| `google_apps` | Calendar, Gmail, Keep, Sheets, Tasks, Drive, Translation | REST API (OAuth + API key) | Yes | [API Docs](https://developers.google.com/workspace) · [Console](https://console.cloud.google.com/) |
| `investagrams` | Philippine stock analytics | Web scraping | No | [Site](https://www.investagrams.com/) |
| `jira` | Jira project management | REST API (DC/Bearer) | Yes | [API Docs](https://developer.atlassian.com/server/jira/platform/rest-apis/) · [Site](https://www.atlassian.com/software/jira) |
| `linkedin` | LinkedIn — profile, posts, sharing | REST API (OAuth2) | Yes | [API Docs](https://learn.microsoft.com/en-gb/linkedin/shared/api-guide/concepts) · [Portal](https://www.linkedin.com/developers/apps) |
| `moo` | Futu/Moo trading stub | Stub | No | [API Docs](https://openapi.futunn.com/futu-api-doc/en/) · [Site](https://www.futunn.com/) |
| `oanda` | Forex trading | REST API | Yes | [API Docs](https://developer.oanda.com/rest-live-v20/introduction/) · [Site](https://www.oanda.com/) |
| `open_ai` | OpenAI GPT | REST (native SDK) | No | [API Docs](https://platform.openai.com/docs/api-reference) · [Site](https://platform.openai.com/) |
| `orgo` | Cloud VM desktop control for AI agents | REST API | Yes | [API Docs](https://docs.orgo.ai/api-reference/introduction) · [Site](https://orgo.ai/) |
| `own_tracks` | GPS location tracking | REST API + Docker/MQTT | Yes | [API Docs](https://owntracks.org/booklet/tech/http/) · [Site](https://owntracks.org/) |
| `rainmeter` | Windows desktop HUD skinning | Local | No | [Docs](https://docs.rainmeter.net/) · [Site](https://www.rainmeter.net/) |
| `reddit` | Reddit — subreddits, posts, comments, inbox | REST API (OAuth2) | Yes | [API Docs](https://www.reddit.com/dev/api/) · [Apps](https://www.reddit.com/prefs/apps) |
| `scryfall` | MTG card database | REST API | Yes | [API Docs](https://scryfall.com/docs/api) · [Site](https://scryfall.com/) |
| `tcg_mp` | TCG Marketplace | REST API | Yes | [Site](https://thetcgmarketplace.com/) |
| `telegram` | Telegram Bot messaging | REST API | Yes | [API Docs](https://core.telegram.org/bots/api) · [Site](https://telegram.org/) |
| `notion` | Notion — pages, databases, blocks, search | REST API | Yes | [API Docs](https://developers.notion.com/reference/intro) · [Site](https://www.notion.so/) |
| `trello` | Kanban board management | REST API | Yes | [API Docs](https://developer.atlassian.com/cloud/trello/rest/) · [Site](https://trello.com/) |
| `ynab` | Personal budgeting | REST API | Yes | [API Docs](https://api.ynab.com/) · [Site](https://www.ynab.com/) |

---

## AI Agents

HARQIS-Work includes a layer of Claude-powered AI agents that go beyond scheduled tasks — they act autonomously on Kanban cards, respond to conversational inputs, and use all connected app integrations as tools.

### Kanban Agent System (`agents/kanban/`)

A fully autonomous agent ecosystem that turns Trello or Jira cards into AI task assignments. Cards placed in **Backlog** are picked up, processed by a matching Claude agent, and moved to **Done** — all without manual intervention.

> Full design: [`docs/thesis/TRELLO-AGENT-KANBAN.md`](docs/thesis/TRELLO-AGENT-KANBAN.md)

#### How it works

```
Trello / Jira Board
  └── Backlog column
        └── Card (label: agent:code / agent:write)
              ↓  Orchestrator polls every 30s
        Profile matched by label
              ↓
        Secrets scoped (only what the profile declared)
              ↓
        BaseKanbanAgent runs Claude tool-use loop
          ├── Native tools: read_file, write_file, bash, glob, grep
          ├── Kanban tools: post_comment, move_card, check_item
          └── MCP tools: Jira, Gmail, Calendar, Discord, YNAB, Trello, …
              ↓
        Output sanitized (secrets redacted)
              ↓
        Result posted as card comment → card moved to Done
              ↓
        Audit log written to logs/kanban_audit.jsonl
```

#### Agent Profiles

Profiles are YAML files in `agents/kanban/profiles/` that define each agent's identity, model, tools, permissions, and secrets:

| Profile | Tools | MCP Apps |
|---------|-------|----------|
| `agent:code` | bash, read/write file, glob, grep | Jira, Trello, Gmail, Calendar, Discord, YNAB, OANDA, Reddit, Echo MTG, Scryfall, TCG MP |
| `agent:write` | read/write file, glob, grep | Google Apps, Trello, Discord, Telegram |

Profiles support `extends:` inheritance — child profiles merge with base defaults.

#### Security model

- **Secret scoping**: The orchestrator reads the full `.env` once. Each agent receives only the env-var names it declared under `secrets.required`. Agents never see unrelated credentials.
- **Output sanitization**: All text returned by tools or Claude is scrubbed for known secret values before being posted to Kanban comments.
- **Audit log**: Every tool call, permission check, and secret access is written as a JSONL record to `logs/kanban_audit.jsonl`.
- **Permission enforcer**: Filesystem (glob patterns), network (hostname allowlists), and git (branch protection) are checked before every tool execution.
- **Worker isolation (future)**: When Celery workers are added, scoped secrets will be Fernet-encrypted in the task payload — workers decrypt at task-start and discard after completion.

#### MCP Bridge

All 14 harqis-work app integrations are exposed to agents as tools via the MCP bridge (`agents/kanban/agent/tools/mcp_bridge.py`). Agents call `search_jira_issues`, `get_gmail_recent_emails`, `get_ynab_transactions`, etc. directly — no separate server process required.

#### Running the orchestrator

```sh
# Load env and start polling (default: every 30s)
python -m agents.kanban.orchestrator.local

# Dry run — match cards but don't execute agents
python -m agents.kanban.orchestrator.local --dry-run

# Custom profiles directory and poll interval
python -m agents.kanban.orchestrator.local --profiles-dir path/to/profiles --poll-interval 60
```

Required env vars:
```env
KANBAN_PROVIDER=trello          # or jira
KANBAN_BOARD_ID=<board-id>
ANTHROPIC_API_KEY=sk-ant-...
TRELLO_API_KEY=...
TRELLO_API_TOKEN=...
```

#### Board columns

```
Backlog → Pending → In Progress → Done
                               → Failed
                               → Blocked
```

#### Tests

```sh
# Run all kanban agent tests (offline, no API calls)
pytest agents/kanban/tests/ -m "not integration"

# Run integration tests (requires live Trello/Jira credentials)
pytest agents/kanban/tests/ -m integration
```

75 unit tests · 2 integration tests · fully offline mocked suite.

---

### OpenClaw Agent (`/.openclaw/`)

HARQIS-Work includes an [OpenClaw](https://openclaw.ai) agent workspace. OpenClaw is a local AI agent runtime that hosts Claude agents and connects them to messaging channels (WhatsApp, Telegram, Discord) with a persistent, file-based memory system.

```
.openclaw/workspace/
├── SOUL.md        # Agent personality and values
├── AGENTS.md      # Session startup, memory rules, group chat etiquette
├── TOOLS.md       # Machine-specific tool notes (SSH, cameras, TTS)
├── HEARTBEAT.md   # Periodic background task checklist (email, calendar)
└── BOOTSTRAP.md   # One-time first-run initialization (delete after use)
```

Only `workspace/` is committed — credentials, device identity, and flow registry are gitignored and machine-local.

---

### MCP Server (`/mcp/`)

A FastMCP server that exposes all harqis-work app tools over the Model Context Protocol. Used by:
- Claude Desktop (via `mcp/claude_desktop_config.json`)
- The Kanban agent MCP bridge (in-process, no separate server needed)
- Any MCP-compatible AI client

```sh
# Start the MCP server
python mcp/server.py
```

---

### Shared Prompt Library (`agents/prompts/`)

All AI prompt templates live in `agents/prompts/`. Workflow-specific prompts remain co-located with their workflow under `workflows/<workflow>/prompts/`.

```python
# Load a shared prompt
from agents.prompts import load_prompt
text = load_prompt("kanban_agent_default")

# Save a generated prompt (agents write here)
from agents.prompts import save_prompt
save_prompt("my_generated", content)
```

| File | Used by |
|------|---------|
| `kanban_agent_default.md` | `BaseKanbanAgent` default system prompt |
| `code_smells.md` | Code review tasks |
| `desktop_analysis.md` | HUD desktop log analysis |
| `docs_agent.md` | Documentation generation |

---

## Workflows

Celery-based scheduled automation. Tasks are registered with `@SPROUT.task` and run on a Beat schedule defined in `workflows/config.py`.

### Workflow Inventory

| Workflow | Status | Tasks | Description |
|----------|--------|-------|-------------|
| `hud` | Active | 12 | Calendar, forex, TCG orders, AI log analysis, YNAB budgets, Rainmeter skins |
| `purchases` | Active | 3 (+1 disabled) | MTG card resale pipeline: Scryfall bulk → card matching → listings → pricing → audit |
| `desktop` | Active | 7 | Git pulls, window management, file sync, activity capture, daily/weekly summaries |
| `mobile` | Active | 1 (unscheduled) | Android screen capture and OCR logging |
| `finance` | Stub | 0 | No tasks defined |
| `n8n` | Utilities | — | Shell utilities and ngrok helpers for n8n integration |

### Celery Task Queues

| Queue | Used by |
|-------|---------|
| `hud` | `workflows.hud.tasks.*` |
| `tcg` | TCG card processing tasks |
| `default` | Desktop and general tasks |

### Beat schedule

```python
# workflows/config.py
CONFIG_DICTIONARY = WORKFLOW_PURCHASES | WORKFLOWS_HUD | WORKFLOWS_DESKTOP
SPROUT.conf.beat_schedule = CONFIG_DICTIONARY
```

### Task decorator pattern

```python
@SPROUT.task(queue='hud')
@log_result()           # Logs output to Elasticsearch
@init_meter(...)        # Initializes Rainmeter desktop widget
@feed()                 # Pushes data to desktop HUD feed
def show_calendar_information(**kwargs):
    ...
```

---

## Desktop HUD

HARQIS drives a live desktop heads-up display using [Rainmeter](https://www.rainmeter.net/) on Windows. Celery tasks in `workflows/hud/` push data from connected services into Rainmeter skin files.

![HARQIS Desktop HUD](docs/images/windows-hud-sample.png)

| Panel | Data source | Update frequency |
|-------|-------------|-----------------|
| **Calendar Info** | Google Calendar — today's events and upcoming schedule | Every 15 min |
| **TCG Orders** | TCG Marketplace — open/pending orders with pricing | Every hour |
| **Budgeting Info** | YNAB — budget balances in PHP and SGD | Every 4 hours |
| **Mouse Bindings** | iCUE Corsair Scimitar — active macro mappings | Every 15 sec |
| **HUD Profiles** | Rainmeter — load/save profiles | Daily at midnight |
| **Desktop Logs** | Claude — AI analysis of captured activity screenshots | Every 5 min |
| **Failed Jobs Today** | Celery — tasks that errored since midnight | Every 15 min |
| **Agents Core** | n8n + ElevenLabs — automation agent and voice assistant state | Daily at midnight |

---

## Frontend Dashboard

A lightweight web dashboard for manually triggering Celery tasks and monitoring run status.

![HARQIS Dashboard](docs/images/dashboard-sample.png)

> Full setup: [`frontend/README.md`](frontend/README.md)

**Features:** login-protected · tabbed by workflow · one-click task triggering · live HTMX status polling · drag-and-drop card reordering · JSON output rendering · clickable file paths · Flower link

```sh
cd frontend && python main.py
# → http://localhost:8080
```

---

## Architecture

### Directory Structure

```
harqis-work/
│
├── agents/                         # AI agent layer
│   ├── kanban/                     # Kanban-driven autonomous agent system
│   │   ├── adapters/               # Trello + Jira provider implementations
│   │   ├── agent/                  # Claude tool-use loop + tool registry
│   │   │   └── tools/             # filesystem, kanban, MCP bridge tools
│   │   ├── orchestrator/           # Local polling orchestrator
│   │   ├── permissions/            # Tool/filesystem/network/git enforcer
│   │   ├── profiles/               # YAML agent profile schema + registry
│   │   │   └── examples/          # base, agent:code, agent:write profiles
│   │   ├── security/               # SecretStore, OutputSanitizer, AuditLogger
│   │   └── tests/                  # 75 unit + 2 integration tests
│   └── prompts/                    # Shared AI prompt templates (.md files)
│
├── apps/                           # App integrations (one folder per service)
│   ├── .template/                  # Template for new apps
│   ├── aaa/                        # Philippine stock exchange (Selenium)
│   ├── anthropic/                  # Anthropic Claude API
│   ├── desktop/                    # Windows desktop automation
│   ├── discord/                    # Discord bot
│   ├── echo_mtg/                   # MTG collection management
│   ├── google_apps/                # Google Workspace (Calendar, Gmail, Drive…)
│   ├── jira/                       # Jira project management
│   ├── linkedin/                   # LinkedIn API
│   ├── oanda/                      # Forex trading
│   ├── open_ai/                    # OpenAI GPT
│   ├── orgo/                       # Cloud VM desktop control
│   ├── own_tracks/                 # GPS location tracking
│   ├── rainmeter/                  # Windows desktop HUD
│   ├── reddit/                     # Reddit API
│   ├── scryfall/                   # MTG card database
│   ├── tcg_mp/                     # TCG Marketplace
│   ├── telegram/                   # Telegram Bot
│   ├── notion/                     # Notion pages, databases, blocks
│   ├── trello/                     # Trello Kanban
│   └── ynab/                       # Personal budgeting
│
├── workflows/                      # Celery task definitions
│   ├── config.py                   # Master Celery Beat schedule
│   ├── desktop/                    # Git pulls, window mgmt, file sync
│   ├── finance/                    # Stub — no tasks yet
│   ├── hud/                        # Desktop HUD tasks (12 tasks)
│   ├── mobile/                     # Android screen capture
│   ├── n8n/                        # n8n utility helpers
│   └── purchases/                  # TCG card resale pipeline
│
├── frontend/                       # Web dashboard (FastAPI + HTMX + Alpine.js)
│   ├── main.py
│   ├── registry.py                 # Auto-generated task registry (do not edit)
│   ├── generate_registry.py        # Regenerates registry from tasks_config.py
│   └── templates/                  # Jinja2 HTML templates
│
├── mcp/                            # MCP server (FastMCP)
│   ├── server.py                   # Exposes all app tools over MCP protocol
│   └── claude_desktop_config.json  # Claude Desktop integration config
│
├── docs/                           # Documentation and design docs
│   ├── images/
│   └── thesis/                     # Architecture design documents
│
├── scripts/                        # Startup and utility scripts (.bat / .sh)
├── .openclaw/workspace/            # OpenClaw agent workspace (versioned)
├── apps_config.yaml                # Central app configuration
├── pytest.ini                      # Test configuration
├── requirements.txt                # Python dependencies
├── workflows.mapping               # Auto-generated Celery task map (do not edit)
└── conftest.py                     # Pytest session fixtures
```

### App Structure

```
apps/<app_name>/
├── config.py                   # Loads app section from apps_config.yaml
├── mcp.py                      # Registers app tools with FastMCP
├── references/
│   ├── base_api_service.py     # Extends harqis-core BaseFixtureServiceRest
│   ├── dto/                    # Dataclass-based data transfer objects
│   ├── models/                 # Data models
│   ├── constants/              # Enums and static values
│   └── web/api/                # Concrete API service implementations
└── tests/
```

### Workflow Structure

```
workflows/<workflow>/
├── tasks_config.py             # Celery Beat schedule dict
├── tasks/                      # @SPROUT.task decorated functions
├── dto/                        # Task parameter DTOs
├── prompts/                    # Workflow-local prompt templates
└── tests/
```

### Agent Profile Structure

```
agents/kanban/profiles/
├── schema.py                   # AgentProfile dataclass (model, tools, permissions, secrets)
├── registry.py                 # Resolves cards to profiles by label/assignee
└── examples/
    ├── base.yaml               # Base defaults (all profiles extend this)
    ├── agent_code.yaml         # Software development agent
    └── agent_write.yaml        # Writing and research agent
```

---

## Getting Started

### Requirements

- **Python 3.12+**
- **RabbitMQ** (Celery broker, default: `amqp://guest:guest@localhost:5672/`)
- **Elasticsearch** (optional, for log shipping via `ELASTIC_LOGGING`)
- **Rainmeter** (Windows only, for desktop HUD)
- **n8n** (optional, for orchestration)

### Installation

```sh
git clone https://github.com/brianbartilet/harqis-work.git
cd harqis-work
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

To force-reinstall `harqis-core` from the latest commit:

```sh
pip install --upgrade --force-reinstall --no-cache-dir git+https://github.com/brianbartilet/harqis-core.git#egg=harqis-core
```

---

## Configuration

### Environment Variables (`.env/apps.env`)

```env
# Anthropic — Claude API
ANTHROPIC_API_KEY=

# Kanban orchestrator
KANBAN_PROVIDER=trello          # or jira
KANBAN_BOARD_ID=
KANBAN_POLL_INTERVAL=60
KANBAN_AUDIT_LOG=logs/kanban_audit.jsonl

# Trello
TRELLO_API_KEY=
TRELLO_API_TOKEN=

# Jira
JIRA_SERVER=
JIRA_EMAIL=
JIRA_API_TOKEN=

# OpenAI
OPENAI_API_KEY=
OPENAI_ASSISTANT_ID=
OPENAI_ASSISTANT_DESKTOP=
OPENAI_ASSISTANT_REPORTER=

# OANDA — Forex
OANDA_BEARER_TOKEN=
OANDA_MT4_ACCOUNT_ID=

# Echo MTG
ECHO_MTG_USER=
ECHO_MTG_PASSWORD=
ECHO_MTG_BULK_USER=
ECHO_MTG_BULK_PASSWORD=
ECHO_MTG_BULK_BEARER_TOKEN=

# Scryfall
SCRY_DOWNLOADS_PATH=

# TCG Marketplace
TCG_MP_USER_ID=
TCG_MP_USERNAME=
TCG_MP_PASSWORD=
TCG_SAVE=

# Rainmeter (Windows)
RAINMETER_BIN_PATH=
RAINMETER_STATIC_PATH=
RAINMETER_WRITE_SKINS_TO_PATH=
RAINMETER_WRITE_FEED_TO_PATH=

# Google Apps (OAuth)
GOOGLE_APPS_API_KEY=

# Elasticsearch
ELASTIC_API_KEY=
ELASTIC_USER=
ELASTIC_PASSWORD=

# Desktop capture
ACTIONS_LOG_PATH=
ACTIONS_ARCHIVE_PATH=
ACTIONS_SCREENSHOT_PATH=
DESKTOP_PATH_DEV=
DESKTOP_PATH_RUN=

# Notion
NOTION_API_TOKEN=

# YNAB
YNAB_ACCESS_TOKEN=
YNAB_BUDGET_PHP=
YNAB_BUDGET_SGD=

# ElevenLabs
ELEVEN_AGENT_N8N=
ELEVEN_AGENT_N8N_CHAT=

# Python runner (Windows)
PYTHON_EXE=
ENV_ROOT=
```

### `apps_config.yaml`

Central YAML at the repo root. Each section maps to one app. Sensitive values use `${ENV_VAR}` interpolation, loaded at import time via `ConfigLoaderService`.

### Google Apps OAuth

- `credentials.json` — OAuth client credentials (from Google Cloud Console)
- `storage.json` — Cached OAuth token (auto-generated on first run; delete to re-auth)

---

## Running Tests

```sh
# All tests (excludes workflows/)
pytest

# Kanban agent tests only (offline, no API needed)
pytest agents/kanban/tests/ -m "not integration"

# Specific app
pytest apps/echo_mtg/tests/

# By marker
pytest -m smoke
pytest -m sanity
```

All app tests are **live integration tests** — no mocking. Requires valid credentials.
Kanban agent tests are fully offline (75 unit tests, 2 integration tests).

---

## Running Services

### Kanban Orchestrator

```sh
python -m agents.kanban.orchestrator.local
```

### Celery Workers

```sh
# Worker + Beat (development)
celery -A workflows.config worker --beat --loglevel=info -Q hud,default,tcg

# Worker only
celery -A workflows.config worker --loglevel=info

# Beat scheduler only
celery -A workflows.config beat --loglevel=info
```

### Frontend Dashboard

```sh
cd frontend && python main.py
# → http://localhost:8080
```

### MCP Server

```sh
python mcp/server.py
```

---

## Mapping Files

Lightweight JSON-like files exposing Celery tasks and shell commands to n8n and AI orchestrators:

```text
{
    'run-job--example_task': {
        'task': 'workflows.module.tasks.example_task',
        'schedule': <crontab: */10 * * * *>,
        'args': ['PARAM'],
        'kwargs': {}
    },
    'command-run--open_notepad': { 'cmd': 'notepad' }
}
```

- `workflows.mapping` — auto-generated by a Celery management job (**do not edit**)
- `scripts.mapping` — manually maintained shell command bindings

---

## Known Issues

- `logger.warn()` (deprecated) used in `tcg_mp_selling.py` — should be `logger.warning()`
- `generate_tcg_mappings` task is commented out in `purchases/tasks_config.py` — must be triggered manually or via n8n
- Worker functions in `tcg_mp_selling.py` re-import dependencies inside the function body — required for `multiprocessing` on Windows (no `fork`)
- `own_tracks` requires the Docker stack running (`apps/own_tracks/docker compose up -d`) before tests pass
- `moo` app is a hollow stub with no services or tests
- `aaa` tests use `unittest.TestCase` (not pytest-style), placed in `unit_tests.py`
- `google_apps` Keep tests are permanently skipped — `googleapis.com/auth/keep` scope not available for third-party OAuth apps

---

## Contact

For questions or feedback: **[LinkedIn](https://www.linkedin.com/in/dbbartilet/)**

## License

Distributed under the [MIT License](LICENSE).
