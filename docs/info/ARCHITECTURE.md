# Architecture and runtime

[Overview](../../README.md) · [Documentation index](README.md)

## Architecture

### Directory Structure

```
harqis-work/
│
├── agents/                         # AI agent layer
│   ├── projects/                   # Kanban-driven autonomous agent system
│   │   ├── adapters/               # Trello + Jira provider implementations
│   │   ├── agent/                  # Claude tool-use loop + tool registry
│   │   │   └── tools/              # filesystem, kanban, MCP bridge tools
│   │   ├── orchestrator/           # Local polling orchestrator
│   │   ├── permissions/            # Tool/filesystem/network/git enforcer
│   │   ├── profiles/               # YAML agent profile schema + registry
│   │   │   └── examples/           # base, agent:code, agent:write profiles
│   │   ├── security/               # SecretStore, OutputSanitizer, AuditLogger
│   │   └── tests/                  # Unit and integration tests
│   └── prompts/                    # Shared AI prompt templates (.md files)
│
├── apps/                           # App integrations (one folder per service)
│   ├── .template/                  # Template for new apps
│   ├── aaa/                        # Philippine stock exchange (Selenium)
│   ├── airtable/                   # Airtable bases, tables, records (CRUD)
│   ├── alpha_vantage/              # Stock/FX/news/fundamentals/technicals/crypto/commodities
│   ├── android_emulator/           # Android AVDs + device control (ADB, scrcpy)
│   ├── antropic/                   # Anthropic Claude API
│   ├── apify/                      # Web scraping actors + social-media trends aggregation
│   ├── appsheet/                   # AppSheet tables — find/add/edit/delete rows
│   ├── browser/                    # HTTP fetching and web scraping
│   ├── confluence/                 # Confluence pages, spaces, search (Cloud + Server/DC)
│   ├── desktop/                    # Windows desktop automation
│   ├── discord/                    # Discord bot
│   ├── echo_mtg/                   # MTG collection management
│   ├── file_index/                 # Metadata catalog and share packages
│   ├── filesystem/                 # Local file and directory operations
│   ├── gemini/                     # Google Gemini AI (generation, embeddings)
│   ├── git/                        # Local git CLI wrapper
│   ├── github/                     # GitHub repos, issues, PRs, file content
│   ├── google_apps/                # Google Workspace (Calendar, Gmail, Drive…)
│   ├── google_drive/               # Google Drive upload/download/export
│   ├── grok/                       # xAI Grok LLM (chat, web search, X search, embeddings)
│   ├── hfl_corpus/                 # HFL Activity Corpus REST client + OpenAPI contract
│   ├── investagrams/               # Philippine stock analytics (web scraping)
│   ├── jira/                       # Jira project management
│   ├── justtcg/                    # Multi-game TCG pricing analytics API
│   ├── linkedin/                   # LinkedIn API
│   ├── moo/                        # Futu/Moo trading stub
│   ├── mpc/                        # MakePlayingCards.com proxy-card autofill (Playwright)
│   ├── notion/                     # Notion pages, databases, blocks
│   ├── oanda/                      # Forex trading
│   ├── open_ai/                    # OpenAI GPT
│   ├── orgo/                       # Cloud VM desktop control
│   ├── own_tracks/                 # GPS location tracking
│   ├── perplexity/                 # Perplexity Sonar (chat + search + embeddings)
│   ├── plaud/                      # Plaud AI voice recorder (cloud + export folder)
│   ├── playwright/                 # Headless browser automation
│   ├── pokemon_tcg/                # Pokemon TCG card database (cards, sets, rarities)
│   ├── rainmeter/                  # Windows desktop HUD
│   ├── reddit/                     # Reddit API
│   ├── scryfall/                   # MTG card database
│   ├── spotify/                    # Spotify listening history (recently-played, top tracks/artists)
│   ├── sqlite_vec/                 # Local persistent vector store and KNN search
│   ├── stripe/                     # Stripe payments — balance, charges, customers, invoices, subscriptions
│   ├── tcg_mp/                     # TCG Marketplace
│   ├── telegram/                   # Telegram Bot
│   ├── trello/                     # Trello Kanban
│   ├── typesafe/                   # Jev typed decision tools
│   ├── ynab/                       # Personal budgeting
│   └── youtube/                    # YouTube data and channel analytics
│
├── workflows/                      # Celery task definitions
│   ├── config.py                   # Master Celery Beat schedule
│   ├── queues.py                   # WorkflowQueue enum + queue topology
│   ├── desktop/                    # Git pulls, window mgmt, file sync
│   ├── dumps/                      # Daily dump collection (Android/Termux → harqis-server)
│   ├── finance/                    # Manual PDF-to-YNAB transaction import
│   ├── files/                      # Discovery, Drive publication and expiry
│   ├── git_forks/                  # Fork fleet discovery and drift analysis
│   ├── hfl/                        # Homework-for-Life capture/ingest/express pipeline
│   ├── hud/                        # Desktop HUD, fallback, and compatibility tasks
│   ├── knowledge/                  # RAG / knowledge-base ingest and query workflows
│   ├── notes/                      # Git-backed note push/pull workflow; feeds HFL ingest
│   ├── mobile/                     # Android screen capture plus emulator/device controls
│   ├── n8n/                        # n8n utility helpers
│   ├── purchases/                  # TCG card resale pipeline
│   ├── second_brain/               # Context-aware advisory feed and delivery
│   ├── social/                     # Monthly LinkedIn posting
│   ├── tcg/                        # Pokedex proxy-printing pipeline (MPC)
│   ├── testing/                    # Test farm (Gherkin scenario generation)
│   └── workers/                    # Worker-pool location broadcast
│
├── frontend/                       # Web dashboard (FastAPI + HTMX + Alpine.js)
│   ├── main.py
│   ├── registry.py                 # Loads generated registry.json
│   ├── generate_registry.py        # Regenerates registry from tasks_config.py
│   └── templates/                  # Jinja2 HTML templates
│
├── mcp/                            # MCP server (FastMCP)
│   ├── server.py                   # Exposes all app tools over MCP protocol
│   └── claude_desktop_config.json.template  # Render per-machine (actual file is gitignored)
│
├── docs/                           # Documentation and design docs
│   ├── images/
│   └── thesis/                     # Architecture design documents
│
├── scripts/                        # Startup and utility scripts (.bat / .sh)
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
agents/projects/profiles/
├── schema.py                   # AgentProfile dataclass (model, tools, permissions, secrets)
├── registry.py                 # Resolves cards to profiles by label/assignee
└── examples/
    ├── base.yaml               # Base defaults (all profiles extend this)
    ├── agent_code.yaml         # Software development agent
    └── agent_write.yaml        # Writing and research agent
```

---

## Platform Runtime

> Full deployment guide: [`docs/info/HERMES-HOST.md`](HERMES-HOST.md)

### Goal

HARQIS-Work is designed to run as an **always-on, self-managing automation hub** anchored to a single host machine (Mac Mini M4 or equivalent server). The goal is that every repetitive task — checking email, tracking trades, updating a desktop HUD, processing a Kanban card, sending a Telegram alert — happens automatically, without manual intervention, and is reachable by AI agents as a tool.

The three driving principles:
1. **Everything is a tool** — every app integration is callable via MCP, so Claude agents can use any service as naturally as a function call
2. **Schedules, not crons** — Celery Beat replaces fragile shell crons; tasks are Python functions with typed inputs, retries, and live logs
3. **The agent reasons; the platform persists** — Hermes keeps its memory and lessons locally under `~/.hermes/` and calls the platform's MCP tools, so reasoning stays separate from the durable integration layer

### How Everything Is Wired Together

```
  Messaging channels                    Developer / Operator
  (Telegram · cron delivery)            (Claude Desktop · Claude Code CLI)
           │                                        │
           ▼                                        ▼
   ┌──────────────────────────────────────────────────────────┐
   │                  Hermes Agent Runtime                    │
   │       memory · lessons · plans · cron (agent/no_agent)   │
   │            local per-machine under ~/.hermes/            │
   └─────────────────────────┬────────────────────────────────┘
                             │  calls tools via
                             ▼
   ┌──────────────────────────────────────────────────────────┐
   │                   MCP Server  (mcp/)                     │
   │   Tools from the shared catalog — OANDA, YNAB, Gmail,    │
   │    Telegram, Discord, Trello, Jira, Scryfall, TCG …      │
   └──────┬──────────────────────────────────┬────────────────┘
          │ reads / writes                   │ triggers
          ▼                                  ▼
   ┌────────────────┐              ┌────────────────────────────┐
   │   apps/        │              │  Celery Worker + Beat      │
   │  REST clients  │              │  workflows/ tasks run on   │
   │  for every     │              │  schedule (hud, purchases, │
   │  3rd-party API │              │  desktop, finance …)       │
   └────────────────┘              └──────────────┬─────────────┘
                                                  │ output to
                                   ┌──────────────▼───────────┐
                                   │ Rainmeter HUD · Frontend │
                                   │ Elasticsearch · Kibana   │
                                   │ Telegram alerts · n8n    │
                                   └──────────────────────────┘

  ── All of the above runs on the Hermes Host ──────────────────
  ── Worker nodes (VPS, N100 Windows) connect via Tailscale VPN ─
```

### Key Components and Their Roles

| Component | Where | What it does |
|---|---|---|
| **Hermes agent** | `~/.hermes/` (local per-machine) | Agent runtime: persistent memory, distilled lessons, plans, and cron jobs (agent / `no_agent` modes) — see [`docs/info/HERMES.md`](HERMES.md) |
| **MCP server** | `mcp/server.py` | Registers the configured application and knowledge tools via `tools/catalog.py`; the live surface depends on `MCP_ENABLED_APPS` and successful module registration |
| **Celery Beat** | `workflows/config.py` | Runs all scheduled automation — HUD updates, MTG resale pipeline, desktop sync |
| **RabbitMQ + Redis** | Docker stack | Celery broker and result backend |
| **Frontend** | `frontend/main.py` | Web dashboard — manually trigger any task, inspect run history |
| **Kanban agents** | `agents/projects/` | Autonomous Claude agents that process Trello/Jira cards as task assignments |
| **Tailscale VPN** | Host + workers | Secure mesh network connecting Mac Mini, VPS workers, and Windows N100 nodes |
| **n8n** | Docker stack | Low-code webhook glue — bridges external events into Celery tasks |
| **Elasticsearch + Kibana** | Docker stack | Log shipping and observability for all task outputs |

### Runtime Startup Order

```sh
# 1. Ensure the Docker stack is up (RabbitMQ, Redis, n8n, Mosquitto, Elasticsearch, Kibana, OwnTracks)
docker compose -f docker-compose.yml up -d

# 2. On macOS — verify LaunchAgents (scheduler, worker, frontend, canonical HFL API)
launchctl list | grep work.harqis

# 3. If anything is down, run the deploy script (cross-platform)
python scripts/deploy.py

# 4. Start the MCP server for Claude Desktop / Claude Code
python mcp/server.py
```

See [`docs/info/HERMES-HOST.md`](HERMES-HOST.md) for the full deployment guide, Tailscale ACL setup, worker node configuration, monitoring runbook, and multi-agent topology.

---
