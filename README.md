<p align="center">
  <img src="docs/images/banner.jpg" alt="HARQIS Work — multi-armed automation orchestrator" width="800">
</p>

# HARQIS Work

## Introduction

**HARQIS-Work** is a self-hosted automation platform designed to eliminate repetitive manual work — built initially as a personal system, but structured to scale to real-world business workflows and production requirements. It connects 20+ third-party services and orchestrates them as a coordinated set of Python integrations, scheduled tasks, and AI agents.

It provides an extensible portfolio of automated routines spanning business operations, developer productivity, personal finance, trading, and lifestyle management. Every integration is a standalone Python module; every routine is a schedulable Celery task; every repetitive job is a candidate for an AI agent. The platform started as a code-first RPA system and has since evolved into AI-driven automation — while still fully supporting traditional scheduled tasks and browser-based RPA workflows where needed.

At its core the platform has three layers:

- **App integrations** (`apps/`) — REST clients and service wrappers for every connected third-party (Google Workspace, Discord, Jira, Trello, OANDA, YNAB, LinkedIn, Reddit, and more), each exposable as an MCP tool so AI agents can call them directly.
- **Scheduled workflows** (`workflows/`) — Celery Beat tasks that run on a defined schedule: pushing live data to a desktop HUD, processing MTG card resale pipelines, syncing git repos, posting monthly LinkedIn summaries, and more.
- **AI agent layer** (`agents/`) — Claude-powered agents that operate autonomously: a Kanban agent that picks up Trello/Jira cards and executes them as tool-use loops, and an OpenClaw persistent agent reachable over Telegram, Discord, and WhatsApp with its own synced memory and identity.
- **Core framework** — built on [HARQIS-core](https://github.com/brianbartilet/harqis-core), which provides the base service fixtures, configuration loading, and test infrastructure that every app integration extends.

---

## App Inventory

| App | Integration | Type | Tests | Links |
|-----|-------------|------|-------|-------|
| `aaa` | Philippine stock exchange (PSEI) | Selenium | Yes | [Site](https://aaa-equities.com.ph/) |
| `airtable` | Airtable bases, tables, fields, and full record CRUD with formula filters and upsert | REST API | Yes | [API Docs](https://airtable.com/developers/web/api/introduction) · [Site](https://airtable.com/) |
| `alpha_vantage` | Stock quotes, FX rates, news & sentiment, fundamentals, technical indicators, crypto, commodities, economic indicators | REST API | Yes | [API Docs](https://www.alphavantage.co/documentation/) · [MCP](https://mcp.alphavantage.co/) · [Site](https://www.alphavantage.co/) |
| `antropic` | Anthropic Claude API | REST (native SDK) | Yes | [API Docs](https://docs.anthropic.com/en/api/) · [Console](https://console.anthropic.com/) |
| `apify` | Web scraping platform — run actors, fetch datasets, social-media trends aggregation (Google Trends, IG, FB, TikTok, Reddit) | REST API | Yes | [API Docs](https://docs.apify.com/api/v2) · [Store](https://apify.com/store) · [Console](https://console.apify.com/) |
| `appsheet` | AppSheet tables — find/add/edit/delete rows via the v2 REST API | REST API | Yes | [API Docs](https://support.google.com/appsheet/answer/10105768) · [Site](https://www.appsheet.com/) |
| `browser` | HTTP fetching and web scraping (httpx + BeautifulSoup) | Local | No | — |
| `desktop` | Windows desktop automation | Local | No | — |
| `discord` | Discord bot — messaging, guilds, webhooks | REST API | Yes | [API Docs](https://discord.com/developers/docs/reference) · [Portal](https://discord.com/developers/applications) |
| `echo_mtg` | MTG collection management | REST API | Yes | [API Docs](https://www.echomtg.com/api/) · [Site](https://www.echomtg.com/) |
| `filesystem` | Local file and directory operations (pathlib) | Local | No | — |
| `gemini` | Google Gemini — text generation, token counting, embeddings | REST API | Yes | [API Docs](https://ai.google.dev/api/rest) · [Console](https://aistudio.google.com/) |
| `git` | Local git repository operations (CLI wrapper) | Local | No | — |
| `github` | GitHub repos, issues, PRs, commits, branches, file content | REST API | Yes | [API Docs](https://docs.github.com/en/rest) · [Site](https://github.com/) |
| `google_apps` | Calendar, Gmail, Keep, Sheets, Tasks, Drive, Translation | REST API (OAuth + API key) | Yes | [API Docs](https://developers.google.com/workspace) · [Console](https://console.cloud.google.com/) |
| `google_drive` | Google Drive — upload, download, export, manage files/folders | REST API (OAuth) | No | [API Docs](https://developers.google.com/drive/api/reference/rest/v3) · [Console](https://console.cloud.google.com/) |
| `grok` | xAI Grok — chat completions, live web search, X post search, embeddings | REST (native SDK) | Yes | [API Docs](https://docs.x.ai/api-reference) · [Console](https://console.x.ai/) |
| `investagrams` | Philippine stock analytics | Web scraping | No | [Site](https://www.investagrams.com/) |
| `jira` | Jira project management | REST API (DC/Bearer) | Yes | [API Docs](https://developer.atlassian.com/server/jira/platform/rest-apis/) · [Site](https://www.atlassian.com/software/jira) |
| `linkedin` | LinkedIn — profile, posts, sharing | REST API (OAuth2) | Yes | [API Docs](https://learn.microsoft.com/en-gb/linkedin/shared/api-guide/concepts) · [Portal](https://www.linkedin.com/developers/apps) |
| `moo` | Futu/Moo trading stub | Stub | No | [API Docs](https://openapi.futunn.com/futu-api-doc/en/) · [Site](https://www.futunn.com/) |
| `notion` | Notion — pages, databases, blocks, search | REST API | Yes | [API Docs](https://developers.notion.com/reference/intro) · [Site](https://www.notion.so/) |
| `oanda` | Forex trading | REST API | Yes | [API Docs](https://developer.oanda.com/rest-live-v20/introduction/) · [Site](https://www.oanda.com/) |
| `open_ai` | OpenAI — Responses API, Code Interpreter, Assistants v2 (deprecated) | REST (native SDK) | Yes | [API Docs](https://platform.openai.com/docs/api-reference) · [Site](https://platform.openai.com/) |
| `orgo` | Cloud VM desktop control for AI agents | REST API | Yes | [API Docs](https://docs.orgo.ai/api-reference/introduction) · [Site](https://orgo.ai/) |
| `own_tracks` | GPS location tracking | REST API + Docker/MQTT | Yes | [API Docs](https://owntracks.org/booklet/tech/http/) · [Site](https://owntracks.org/) |
| `perplexity` | Perplexity Sonar — chat with live web search, search API, embeddings | REST API | No | [API Docs](https://docs.perplexity.ai/) · [Site](https://www.perplexity.ai/) |
| `playwright` | Headless browser automation — screenshot, click, fill, evaluate | Local | No | [Docs](https://playwright.dev/python/) |
| `rainmeter` | Windows desktop HUD skinning | Local | No | [Docs](https://docs.rainmeter.net/) · [Site](https://www.rainmeter.net/) |
| `reddit` | Reddit — subreddits, posts, comments, inbox | REST API (OAuth2) | Yes | [API Docs](https://www.reddit.com/dev/api/) · [Apps](https://www.reddit.com/prefs/apps) |
| `scryfall` | MTG card database | REST API | Yes | [API Docs](https://scryfall.com/docs/api) · [Site](https://scryfall.com/) |
| `tcg_mp` | TCG Marketplace | REST API | Yes | [Site](https://thetcgmarketplace.com/) |
| `telegram` | Telegram Bot messaging | REST API | Yes | [API Docs](https://core.telegram.org/bots/api) · [Site](https://telegram.org/) |
| `trello` | Kanban board management | REST API | Yes | [API Docs](https://developer.atlassian.com/cloud/trello/rest/) · [Site](https://trello.com/) |
| `ynab` | Personal budgeting | REST API | Yes | [API Docs](https://api.ynab.com/) · [Site](https://www.ynab.com/) |

---

## AI Agents

HARQIS-Work includes a layer of Claude-powered AI agents that go beyond scheduled tasks — they act autonomously on Kanban cards, respond to conversational inputs, and use all connected app integrations as tools.

### Claude Code Skills (`.claude/skills/`)

> Full reference: [`docs/info/SKILLS-INVENTORY.md`](docs/info/SKILLS-INVENTORY.md)

**Skills are slash commands that build the three core repo features for you: app integrations, workflows, and HUD widgets.** Open any Claude Code session in the repo and type `/<skill-name>` — Claude executes a multi-step recipe end-to-end (no step-by-step prompting), guided by the skill's `SKILL.md` under `.claude/skills/<name>/`. Every artefact in `apps/`, `workflows/`, and the Rainmeter HUD started life as a single slash command; the skill encodes the file layout, decorator stack, registry wiring, and tests so each new piece lands consistent with what's already there.

#### Building the core features

| What you're adding | Skill |
|---|---|
| **App integration** — REST API wrapper (service + DTO + MCP tool) under `apps/<name>/` | `/create-new-service-app <name> [<openapi_url>]` |
| **Workflow / scheduled task** — Celery RPA chaining apps with cron + queue routing | `/create-new-workflow [<category>] <description_or_diagram>` |
| **Visual workflow outside Celery** — n8n flows for branching automations or vendor connectors not in `apps/` | `/create-new-n8n-workflow <description_or_diagram>` |
| **HUD widget** — Rainmeter desktop display fed by an app or workflow | `/create-new-hud <title> <description_or_screenshot>` |

Re-run `/generate-registry` after a workflow or HUD task lands so the dashboard picks it up. See [`docs/info/SKILLS-INVENTORY.md`](docs/info/SKILLS-INVENTORY.md) for every skill (operations, deploy, agent profiles, Zapier wiring, commits, tests).

#### Why skills, not docs

Every skill is the executable form of an internal convention. With `/create-new-service-app`, the convention IS the skill — when the file layout changes, the skill changes, and every future scaffold gets the new pattern for free. The `SKILL.md` files double as living documentation — they are the source of truth for "how do we do X here".

---

### Project Kanban Agent System (`agents/projects/`)

> Full reference: [`docs/info/AGENTS-TASKS-KANBAN.md`](docs/info/AGENTS-TASKS-KANBAN.md)

**Goal:** Use Trello or Jira as the human-AI task interface. Humans create cards; Claude agents pick them up, execute work with scoped tools, and post results back — all visible on the same board. Every agent behavior is declared in a YAML profile; no code change is needed to add a new agent type.

#### How it works

```
Human creates card → [Backlog]  (Trello or Jira)
          ↓
LocalOrchestrator polls every 30s
  ├── matches card label → AgentProfile (YAML)
  ├── scopes secrets: only vars declared in profile.secrets.required
  ├── card → Pending → In Progress
  └── BaseKanbanAgent: Claude tool-use loop
            ├── read_file · write_file · glob · grep · bash
            ├── post_comment · move_card · check_item
            └── MCP bridge: Gmail, Calendar, Jira, Discord, YNAB, OANDA …
                      ↓
              OutputSanitizer scrubs secrets from all tool output
                      ↓
              Result posted as card comment → card → Done
                      ↓
              AuditLogger → logs/kanban_audit.jsonl
```

#### Agent Profiles

YAML files in `agents/projects/profiles/`. Each profile declares model, tools, permissions, and secrets. Profiles support `extends:` inheritance.

| Profile | Extra tools vs base | MCP apps |
|---|---|---|
| `base` | read_file, glob, grep, post_comment, move_card, check_item | — |
| `agent:code` | + write_file, bash | Jira, Trello, Gmail, Calendar, Discord, YNAB, OANDA, Reddit, Echo MTG, Scryfall, TCG MP |
| `agent:write` | + write_file (no bash) | Google Apps, Trello, Discord, Telegram |

New agent type = new YAML file. No orchestrator code changes.

#### Security model

- **Secret scoping** — agents see only the env-vars listed in `secrets.required`; the rest of `.env` is invisible
- **Output sanitization** — all tool output scrubbed for known secret values before Claude sees it or it is posted to the board
- **Permission enforcer** — filesystem (glob patterns), network (domain allowlists), and git (branch protection) checked before every tool call
- **Audit log** — every tool call, permission decision, and secret access written to `logs/kanban_audit.jsonl`
- **Encrypted payloads** — `SecretStore` supports Fernet encryption for future Celery worker dispatch

#### Quick start

```sh
python -m agents.projects.orchestrator.local           # poll every 30s
python -m agents.projects.orchestrator.local --dry-run # match cards, no execution
```

```env
KANBAN_PROVIDER=trello   KANBAN_BOARD_ID=<id>
ANTHROPIC_API_KEY=...    TRELLO_API_KEY=...    TRELLO_API_TOKEN=...
```

Board columns: `Backlog → Pending → In Progress → Done / Failed / Blocked`

Tests: `pytest agents/projects/tests/ -m "not integration"` — 75 unit tests, fully offline.

---

### OpenClaw Agent

[OpenClaw](https://openclaw.ai) is a local AI agent runtime that hosts Claude agents and connects them to messaging channels (WhatsApp, Telegram, Discord) with a persistent, file-based memory and identity system.

#### Primary use case: wiring and manual triggering

OpenClaw's role in this platform is **not** to build integrations — that happens in `harqis-work`. Its role is to **wire things together** and act as the human-facing control surface:

- **Trigger workflows on demand** — invoke any Celery task in `harqis-work` manually via a chat message without opening a terminal (e.g. "run the TCG price update now", "kick off the LinkedIn post job")
- **Local scheduling for single apps** — set up lightweight, ad-hoc schedules for a single app or task that don't warrant a full Celery Beat entry (e.g. "remind me to check OANDA at 9am", "poll my inbox every hour today")
- **Wire integrations into conversational flows** — chain MCP tools from `harqis-work` across a conversation turn: fetch data from one app, process it, push the result to another, without writing a new workflow

**Separation of concerns:**

| Repo | Role | What lives here |
|---|---|---|
| `harqis-work` | **Build** — the platform structure | App integrations, Celery workflows, MCP server, scheduled tasks, core config |
| `harqis-openclaw-sync` | **Wire** — the pipes and control surface | Agent identity, memory, rules, ad-hoc schedules, manual trigger scripts |

The rule of thumb: if it needs to run reliably on a cron or be reused by multiple consumers, it belongs in `harqis-work`. If it's a one-off connection, a manual trigger, or a conversational shortcut, it belongs in OpenClaw.

#### Workspace layout

The OpenClaw workspace is **not stored in this repo**. It lives in its own dedicated sync repository — [`harqis-openclaw-sync`](https://github.com/brianbartilet/harqis-openclaw-sync) — so that the agent's identity, memory, and rules are shared consistently across every host (Mac Mini, VPS, Windows worker nodes) without mixing agent state into the platform codebase.

```
harqis-openclaw-sync/          ← separate git repo, cloned alongside harqis-work
└── .openclaw/workspace/
    ├── SOUL.md        # Agent personality and core values
    ├── USER.md        # Who the agent assists and how
    ├── AGENTS.md      # Session startup rules, memory discipline, group chat etiquette
    ├── MEMORY.md      # Long-term narrative memory index
    ├── TOOLS.md       # Machine-specific tool notes (SSH, cameras, TTS, paths)
    ├── HEARTBEAT.md   # Periodic background task checklist (email, calendar, monitoring)
    └── memory/
        └── YYYY-MM-DD.md  # Daily session notes (auto-committed by the agent)
```

**Why it's separate:** the agent auto-commits and pushes to `harqis-openclaw-sync` after every memory update. Keeping it out of `harqis-work` means the platform repo stays under manual maintainer control while the agent writes its own memory continuously. Losing one repo does not affect the other.

**Cross-machine sync:** an auto-pull job runs every 30 minutes on each host (macOS LaunchAgent, Windows Task Scheduler, Linux cron) and pulls both repos. This is what makes HARQIS-CLAW behave identically on any node — it always has the latest identity and memory files before starting a session.

> Setup, sync scripts, and per-OS wiring details: [`docs/info/AI-TOOLS-WIRING.md`](docs/info/AI-TOOLS-WIRING.md)  
> Host deployment and service inventory: [`docs/info/HARQIS-CLAW-HOST.md`](docs/info/HARQIS-CLAW-HOST.md)  
> Sync repo architecture: [`docs/info/OPENCLAW-SYNC.md`](docs/info/OPENCLAW-SYNC.md)

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
| `social` | Active | 1 | Monthly LinkedIn post — git history → Claude → LinkedIn draft + Gmail notification |
| `mobile` | Active | 1 (unscheduled) | Android screen capture and OCR logging |
| `finance` | Stub | 0 | No tasks defined |
| `n8n` | Utilities | — | Shell utilities and ngrok helpers for n8n integration |

### Celery Task Queues

Declared in `workflows/queues.py` (`WorkflowQueue` enum) and registered with RabbitMQ in `workflows/config.py` (`SPROUT.conf.task_queues`). Workers consume specific queues based on each machine's `queues = […]` list in `machines.toml`.

**Direct (competing-consumers)** — exactly one worker handles each published task:

| Queue | Used by |
|-------|---------|
| `default` | Catch-all / unrouted tasks; fallback when a task has no `options.queue` |
| `hud` | All `workflows.hud.tasks.*` (auto-routed via `task_routes`) — calendar, TCG orders, YNAB, AI logs |
| `peon` | Work-context HUD tasks (Jira boards, calendar focus, etc.) |
| `tcg` | TCG marketplace pipeline — Scryfall bulk, card matching, listings, pricing |
| `adhoc` | One-off / manual triggers (no schedule) |
| `host` | Tasks that must run on the host (Docker, broker access) |
| `agent` | AI agent task dispatch (Kanban / OpenClaw worker invocations) |
| `worker` | Generic background worker pool (cross-app jobs) |

**Broadcast (fanout)** — every subscribed worker runs each task; tasks **must** be idempotent. A worker only receives broadcasts when its `queues` list includes the broadcast name (otherwise the exchange isn't declared and beat publishes fail with `NOT_FOUND`):

| Queue | Used by |
|-------|---------|
| `default_broadcast` | Cluster-wide jobs that every node must run locally — e.g. `git_pull_on_paths` so each node refreshes its own working tree |
| `hud_broadcast` | HUD-level fanout — `workflows.hud.tasks.broadcast_*` (auto-routed); reload skin config / refresh-all-HUDs cluster-wide |
| `workers_broadcast` | Worker-pool-wide control messages (declared in enum; reserved) |
| `agents_broadcast` | Agent-pool-wide control messages (declared in enum; reserved) |

> Routing override: a task can target any queue via `options={"queue": WorkflowQueue.X}` in its Beat schedule entry, regardless of `task_routes` patterns.

### Beat schedule

```python
# workflows/config.py
CONFIG_DICTIONARY = WORKFLOW_PURCHASES | WORKFLOWS_HUD | WORKFLOWS_DESKTOP
SPROUT.conf.beat_schedule = CONFIG_DICTIONARY
```

### Task decorator pattern

```python

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

### Calendar-driven visibility

**The HUD is wired with Google Calendar.** Every widget is tagged with a `ScheduleCategory` (defined in `apps/google_apps/references/constants.py`), and Rainmeter only shows widgets whose category matches the **current calendar event's name**. The dashboard reshapes itself across the day with no manual toggling — schedule a `"Finance | Investing | Business"` block on your calendar at 9am and the OANDA, PC Daily Sales, and YNAB widgets pop in; transition into a `"Career | Work"` block at 10am and the Jira board takes over; drop into a `"Mischief | Misdirection | Play"` block in the evening and the TCG widgets surface.

| Category | Calendar event name | Widgets that surface |
|---|---|---|
| `PINNED` | (always visible — no event needed) | Calendar Info, Desktop Logs, HUD Profiles, Agents Core, Failed Jobs |
| `WORK` | `"Career \| Work"` | Jira Board |
| `FINANCE` | `"Finance \| Investing \| Business"` | OANDA Account, PC Daily Sales, Budgeting Info |
| `PLAY` | `"Mischief \| Misdirection \| Play"` | TCG Orders, TCG Sell Cart |
| `ORGANIZE` | `"Organization \| Everyman Skills"` | Mouse Bindings (also `WORK`) |
| `DEACTIVATED` | — | Never auto-shows; manual trigger only |

Widgets are wired to categories in each task's `@init_meter(..., schedule_categories=[ScheduleCategory.<X>])` decorator. A widget can list multiple categories (e.g. `Mouse Bindings` is both `ORGANIZE` and `WORK`) so it surfaces during any matching block.

### Panel inventory

| Panel | Visibility | Data source | Update frequency |
|-------|-----------|-------------|------------------|
| **Calendar Info** | Always | Google Calendar — today's events and upcoming schedule | Every 15 min |
| **Desktop Logs** | Always | Claude Haiku — AI summary of captured activity screenshots | Every 5 min |
| **HUD Profiles** | Always | Rainmeter / iCUE — active HUD profile selector and load/save | Daily at midnight |
| **Agents Core** | Always | n8n + ElevenLabs — chat agent and voice assistant launcher | Daily at midnight |
| **Failed Jobs Today** | Always | Celery — tasks that errored since midnight | Every 15 min |
| **OANDA Account** | Finance block | OANDA — forex account NAV and open trades | Every 15 min (Mon–Fri) |
| **PC Daily Sales** | Finance block | AppSheet `INVOICE` table — gross daily sales grouped by month, last 60 days, scrollable | Every hour |
| **Budgeting Info** | Finance block | YNAB — budget balances in PHP and SGD with overspend warnings | Every 4 hours |
| **Jira Board** | Work block | Jira Software — In-Review / In-Progress / Ready / In-Analysis tickets | Weekdays every hour |
| **Mouse Bindings** | Organize + Work | iCUE Corsair Scimitar — active macro bindings for the foreground app | Every 15 sec |
| **TCG Orders** | Play block | TCG Marketplace — open and pending orders with card art | Every hour |
| **TCG Sell Cart** | Play block | TCG Marketplace — match listings to active want-to-buy bids | Sundays at midnight |

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
│   │   │   └── tools/              # filesystem, kanban, MCP bridge tools
│   │   ├── orchestrator/           # Local polling orchestrator
│   │   ├── permissions/            # Tool/filesystem/network/git enforcer
│   │   ├── profiles/               # YAML agent profile schema + registry
│   │   │   └── examples/           # base, agent:code, agent:write profiles
│   │   ├── security/               # SecretStore, OutputSanitizer, AuditLogger
│   │   └── tests/                  # 75 unit + 2 integration tests
│   └── prompts/                    # Shared AI prompt templates (.md files)
│
├── apps/                           # App integrations (one folder per service)
│   ├── .template/                  # Template for new apps
│   ├── aaa/                        # Philippine stock exchange (Selenium)
│   ├── airtable/                   # Airtable bases, tables, records (CRUD)
│   ├── alpha_vantage/              # Stock/FX/news/fundamentals/technicals/crypto/commodities
│   ├── anthropic/                  # Anthropic Claude API
│   ├── apify/                      # Web scraping actors + social-media trends aggregation
│   ├── appsheet/                   # AppSheet tables — find/add/edit/delete rows
│   ├── browser/                    # HTTP fetching and web scraping
│   ├── desktop/                    # Windows desktop automation
│   ├── discord/                    # Discord bot
│   ├── echo_mtg/                   # MTG collection management
│   ├── filesystem/                 # Local file and directory operations
│   ├── gemini/                     # Google Gemini AI (generation, embeddings)
│   ├── git/                        # Local git CLI wrapper
│   ├── github/                     # GitHub repos, issues, PRs, file content
│   ├── google_apps/                # Google Workspace (Calendar, Gmail, Drive…)
│   ├── google_drive/               # Google Drive upload/download/export
│   ├── grok/                       # xAI Grok LLM (chat, web search, X search, embeddings)
│   ├── jira/                       # Jira project management
│   ├── linkedin/                   # LinkedIn API
│   ├── notion/                     # Notion pages, databases, blocks
│   ├── oanda/                      # Forex trading
│   ├── open_ai/                    # OpenAI GPT
│   ├── orgo/                       # Cloud VM desktop control
│   ├── own_tracks/                 # GPS location tracking
│   ├── perplexity/                 # Perplexity Sonar (chat + search + embeddings)
│   ├── playwright/                 # Headless browser automation
│   ├── rainmeter/                  # Windows desktop HUD
│   ├── reddit/                     # Reddit API
│   ├── scryfall/                   # MTG card database
│   ├── tcg_mp/                     # TCG Marketplace
│   ├── telegram/                   # Telegram Bot
│   ├── trello/                     # Trello Kanban
│   └── ynab/                       # Personal budgeting
│
├── workflows/                      # Celery task definitions
│   ├── config.py                   # Master Celery Beat schedule
│   ├── desktop/                    # Git pulls, window mgmt, file sync
│   ├── finance/                    # Stub — no tasks yet
│   ├── hud/                        # Desktop HUD tasks (15 tasks)
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

> Full deployment guide: [`docs/info/HARQIS-CLAW-HOST.md`](docs/info/HARQIS-CLAW-HOST.md)

### Goal

HARQIS-Work is designed to run as an **always-on, self-managing automation hub** anchored to a single host machine (Mac Mini M4 or equivalent server). The goal is that every repetitive task — checking email, tracking trades, updating a desktop HUD, processing a Kanban card, sending a Telegram alert — happens automatically, without manual intervention, and is reachable by AI agents as a tool.

The three driving principles:
1. **Everything is a tool** — every app integration is callable via MCP, so Claude agents can use any service as naturally as a function call
2. **Schedules, not crons** — Celery Beat replaces fragile shell crons; tasks are Python functions with typed inputs, retries, and live logs
3. **Identity travels with the agent** — OpenClaw's workspace (SOUL.md, MEMORY.md, AGENTS.md) is git-synced across machines so the agent behaves identically on any node

### How Everything Is Wired Together

```
  Messaging channels                    Developer / Operator
  (Telegram · Discord · WhatsApp)       (Claude Desktop · Claude Code CLI)
           │                                        │
           ▼                                        ▼
   ┌──────────────────────────────────────────────────────────┐
   │                  OpenClaw Agent Runtime                  │
   │         SOUL.md · AGENTS.md · MEMORY.md · USER.md        │
   │       identity synced via harqis-openclaw-sync repo      │
   └─────────────────────────┬────────────────────────────────┘
                             │  calls tools via
                             ▼
   ┌──────────────────────────────────────────────────────────┐
   │                   MCP Server  (mcp/)                     │
   │    55 tools across 16 modules — OANDA, YNAB, Gmail,      │
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

  ── All of the above runs on the HARQIS-CLAW Host ──────────────
  ── Worker nodes (VPS, N100 Windows) connect via Tailscale VPN ─
```

### Key Components and Their Roles

| Component | Where | What it does |
|---|---|---|
| **OpenClaw agent** | [`harqis-openclaw-sync`](https://github.com/brianbartilet/harqis-openclaw-sync) — `.openclaw/workspace/` | Persistent AI agent identity, memory, heartbeat tasks, and behavioral rules — shared across all hosts via auto-sync |
| **MCP server** | `mcp/server.py` | Exposes all 20+ app integrations as callable tools over the Model Context Protocol |
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

# 2. On macOS — verify LaunchAgents (scheduler, worker, frontend)
launchctl list | grep work.harqis

# 3. If anything is down, run the deploy script (cross-platform)
python scripts/deploy.py

# 4. Start the MCP server for Claude Desktop / Claude Code
python mcp/server.py
```

See [`docs/info/HARQIS-CLAW-HOST.md`](docs/info/HARQIS-CLAW-HOST.md) for the full deployment guide, Tailscale ACL setup, worker node configuration, monitoring runbook, and multi-agent topology.

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

This is the canonical list of every env var consumed across the platform. Keep it
in sync with the actual `.env/apps.env` whenever an app is added — the
`/create-new-service-app` skill includes this update as a mandatory step.

```env
# ── Core / harness ────────────────────────────────────────────────────────────
APP_CONFIG_FILE=                  # default: apps_config.yaml
WORKFLOW_CONFIG=                  # default: workflows.config

# ── Frontend dashboard ────────────────────────────────────────────────────────
APP_USERNAME=
APP_PASSWORD=
APP_SECRET_KEY=

# ── RabbitMQ / Celery broker ──────────────────────────────────────────────────
DOCKER_HOST_PORT_RABBIT_MQ=       # default: 15672
CELERY_BROKER=                    # default: amqp://guest:guest@localhost:5672/

# ── Elasticsearch + Kibana ────────────────────────────────────────────────────
ELASTIC_HOST=                     # default: http://localhost:9200
ELASTIC_USER=
ELASTIC_PASSWORD=
ELASTICSEARCH_PASSWORD=
KIBANA_HOST=                      # default: http://localhost:5601
KIBANA_SYSTEM_USER=               # default: kibana_system
KIBANA_SYSTEM_PASSWORD=
KIBANA_ANON_PASSWORD=
ELASTIC_API_KEY=

# ── n8n ───────────────────────────────────────────────────────────────────────
N8N_BASIC_AUTH_ACTIVE=            # true | false
N8N_BASIC_AUTH_USER=              # default: admin
N8N_API_KEY=

# ── Flower (Celery monitor) ───────────────────────────────────────────────────
FLOWER_USER=
FLOWER_PASSWORD=

# ── ngrok ─────────────────────────────────────────────────────────────────────
NGROK_AUTHTOKEN=

# ── Python runner ─────────────────────────────────────────────────────────────
PYTHON_EXE=                       # absolute path to your venv python
ENV_ROOT=                         # absolute path to repo root on this host

# ── AI / LLM ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=
ANTHROPIC_ADMIN_KEY=
OPENAI_API_KEY=
OPENAI_ASSISTANT_ID=
OPENAI_ASSISTANT_DESKTOP=
OPENAI_ASSISTANT_REPORTER=
GROK_API_KEY=
PERPLEXITY_API_KEY=

# ── ElevenLabs ────────────────────────────────────────────────────────────────
ELEVEN_LABS_API_KEY=
ELEVEN_AGENT_N8N=
ELEVEN_AGENT_N8N_CHAT=
ELEVEN_AGENT_N8N_CHAT_TESTS=

# ── Productivity / project management ─────────────────────────────────────────
TRELLO_API_KEY=
TRELLO_API_TOKEN=
JIRA_DOMAIN=                      # e.g. yourcompany.atlassian.net
JIRA_EMAIL=
JIRA_API_TOKEN=
NOTION_API_TOKEN=
AIRTABLE_API_TOKEN=               # personal access token (pat...)
APPSHEET_APPLICATION_ACCESS_KEY=  # per-app key — Manage → Integrations in your AppSheet app
APPSHEET_DEFAULT_APP_ID=          # default AppSheet app id (overridable per call)

# Kanban orchestrator
KANBAN_BOARD_ID=                  # Trello board id or Jira project key

# Kanban agent personas (Mode A — per-agent Trello accounts).
# One pair per profile; leave blank to use Mode B (shared bot account
# + signed comments). Add new ones via `/create-new-kanban-profile <name>`.
TRELLO_AGENT_API_KEY__CODE=
TRELLO_AGENT_API_TOKEN__CODE=
TRELLO_AGENT_API_KEY__WRITE=
TRELLO_AGENT_API_TOKEN__WRITE=
TRELLO_AGENT_API_KEY__FULL=
TRELLO_AGENT_API_TOKEN__FULL=

# ── GitHub ────────────────────────────────────────────────────────────────────
GITHUB_API_TOKEN=                 # fine-grained PAT (ghp_...)

# ── Communication ─────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN=
DISCORD_DEFAULT_GUILD_ID=
DISCORD_DEFAULT_CHANNEL_ID=
TELEGRAM_BOT_TOKEN=
TELEGRAM_DEFAULT_CHAT_ID=
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_REDIRECT_URI=            # e.g. http://localhost:8099
LINKEDIN_PERSON_ID=
LINKEDIN_DEFAULT_POST_URN=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USERNAME=
REDDIT_PASSWORD=
REDDIT_USER_AGENT=                # e.g. harqis-work:v1.0 (by /u/<you>)
REDDIT_DEFAULT_SUBREDDIT=

# ── Finance ───────────────────────────────────────────────────────────────────
ALPHA_VANTAGE_API_KEY=
OANDA_BEARER_TOKEN=
OANDA_MT4_ACCOUNT_ID=
YNAB_ACCESS_TOKEN=
YNAB_BUDGET_PHP=
YNAB_BUDGET_SGD=

# ── Magic: The Gathering ──────────────────────────────────────────────────────
ECHO_MTG_BEARER_TOKEN=
ECHO_MTG_USER=
ECHO_MTG_PASSWORD=
ECHO_MTG_BULK_BEARER_TOKEN=
ECHO_MTG_BULK_USER=
ECHO_MTG_BULK_PASSWORD=
SCRY_DOWNLOADS_PATH=              # local download dir for Scryfall bulk files
TCG_MP_USERNAME=
TCG_MP_PASSWORD=
TCG_MP_USER_ID=
TCG_SAVE=                         # local save dir for TCG marketplace exports

# ── Web scraping / market research ────────────────────────────────────────────
APIFY_API_KEY=

# ── Cloud / infrastructure ────────────────────────────────────────────────────
ORGO_API_KEY=
GOOGLE_APPS_API_KEY=
OWN_TRACKS_HOST=                  # default: localhost
OWN_TRACKS_PORT=                  # default: 8083
OWN_TRACKS_USERNAME=
OWN_TRACKS_PASSWORD=
OWN_TRACKS_DEFAULT_USER=
OWN_TRACKS_DEFAULT_DEVICE=

# ── Desktop capture / Rainmeter (Windows) ─────────────────────────────────────
ACTIONS_LOG_PATH=                 # absolute path
ACTIONS_ARCHIVE_PATH=             # absolute path
ACTIONS_SCREENSHOT_PATH=          # absolute path
DESKTOP_PATH_DEV=                 # repo path on this host
DESKTOP_PATH_RUN=                 # runtime path on this host
DESKTOP_PATH_FEED=                # feed output path
DESKTOP_PATH_I_CUE_PROFILES=      # Corsair iCUE profiles dir
RAINMETER_BIN_PATH=               # path to Rainmeter.exe
RAINMETER_STATIC_PATH=
RAINMETER_WRITE_SKINS_TO_PATH=
RAINMETER_WRITE_FEED_TO_PATH=
```

> The actual `.env/apps.env` file is **gitignored** — values shown here are
> placeholders. Each entry corresponds to a `${ENV_VAR}` reference in
> `apps_config.yaml`. Apps without a matching env var simply skip registration
> at MCP server boot (logged as a warning, not an error).

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
pytest agents/projects/tests/ -m "not integration"

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
python -m agents.projects.orchestrator.local
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
