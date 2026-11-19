# Agent and tool reference

[Overview](../../README.md) · [Documentation index](README.md)

## AI Agents

HARQIS-Work includes a reasoning-model agent layer that goes beyond scheduled tasks — agents act autonomously on Kanban cards, respond to conversational inputs, and use connected app integrations as tools. The same repository skills can guide Claude, OpenAI models, and other capable reasoning models when their agent harness supports loading repository instructions and tools.

### Agent Skills (`.agents/skills/`)

> Full reference: [`docs/info/SKILLS-INVENTORY.md`](SKILLS-INVENTORY.md)

**Skills are reusable agent playbooks for building and operating the repository's core features: app integrations, workflows, HUD widgets, deployment, testing, and maintenance.** The canonical, source-controlled definition is `.agents/skills/<name>/SKILL.md`. A compatible agent can invoke a skill by name (often as `/<skill-name>` or `$<skill-name>`) or load its instructions directly; exact discovery and invocation depend on the runtime. Claude compatibility files under `.claude/skills/` are generated from `.agents/skills/` and are not a second source of truth.

#### Building the core features

| What you're adding | Skill |
|---|---|
| **Automation runtime decision** — classify Celery, agent, or hybrid ownership before implementation | `/choose-automation-runtime <automation description>` |
| **App integration** — REST API wrapper with CLI-first and compatible MCP adapters | `/create-new-service-app <name> [<openapi_url>]` |
| **Workflow / scheduled task** — Celery RPA chaining apps with cron + queue routing | `/create-new-workflow [<category>] <description_or_diagram>` |
| **Visual workflow outside Celery** — n8n flows for branching automations or vendor connectors not in `apps/` | `/create-new-n8n-workflow <description_or_diagram>` |
| **HUD widget** — portable Second Brain dashboard widget fed by an app or workflow | `/create-new-hud <title> <description_or_screenshot>` |
| **HUD fallback twin** — keep a HUD task's `@feed`/ES logs flowing on the always-on host when the Windows box is offline | `/create-data-only-from-hud <task_fn>` |
| **Fork fleet governance** — inspect drift, cherry-pick changes, test, deploy, and publish reviewed PRs across harqis-work forks | `/manage-fork-fleet` |
| **Fork feature shipping** — preflight a SHA/range/PR across all managed forks, then test and publish an explicitly approved rollout | `/ship-feature-to-forks` |

Re-run `/generate-registry` after a workflow or HUD task lands so the dashboard picks it up. See [`docs/info/SKILLS-INVENTORY.md`](SKILLS-INVENTORY.md) for every skill (operations, deploy, agent profiles, Zapier wiring, commits, tests).

#### Why skills, not docs

Every skill is the executable form of an internal convention. With `/create-new-service-app`, the convention IS the skill — when the file layout changes, the skill changes, and every future scaffold gets the new pattern for free. The `SKILL.md` files double as living documentation — they are the source of truth for "how do we do X here".

---

### Project Kanban Agent System (`agents/projects/`)

> Full reference: [`docs/info/AGENTS-TASKS-KANBAN.md`](AGENTS-TASKS-KANBAN.md)

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
| `base` | read_file, glob, grep, post_comment, move_card, check_item, ask_human | — |
| `agent:default` | Same as base (read-only filesystem; no write/bash) — fallback for unlabelled cards, bound to the host in-process worker | — |
| `agent:code` | + write_file, bash | Google Apps, YouTube, Trello, Discord, Jira, Telegram, YNAB, OANDA, Reddit, Echo MTG, Scryfall, TCG MP |
| `agent:write` | + write_file (no bash) | Google Apps, YouTube, Trello, Discord, Telegram |
| `agent:full` | + write_file, bash, git (status/branch/commit/push/PR) — generalist catch-all that opens PRs as `claude[bot]` | Google Apps, YouTube, Trello, Discord, Jira, Telegram |

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

Tests: `pytest agents/projects/tests/ -m "not integration"` — excludes marked live integration tests.

---

### Hermes Agent

Activity Corpus actions and pinned instructions can use **Trusted Hermes** with
the selected profile's MCP integrations and task-relevant host access. App Settings
controls profile/model selection, recipient defaults and execution limits; Gmail
delivery supports attachments and durable retry receipts. See the
[Activity Corpus agent guide](HFL-AGENT-BRIDGE.md) for setup, capability
verification, authorization boundaries and troubleshooting.

**Hermes** is the agent runtime that hosts Claude agents on top of this platform, registers the harqis-work MCP server, and schedules cron jobs (with or without a reasoning loop). It supersedes the deprecated OpenClaw Gateway; agent memory, plans, and logs now live locally under `~/.hermes/` on each machine (no separate sync repo).

#### Primary use case: wiring and manual triggering

Hermes's role in this platform is **not** to build integrations — that happens in `harqis-work`. Its role is to **wire things together** and act as the human-facing control surface:

- **Trigger workflows on demand** — invoke any Celery task in `harqis-work` manually via a chat message without opening a terminal (e.g. "run the TCG price update now", "kick off the LinkedIn post job")
- **Local scheduling for single apps** — set up lightweight, ad-hoc cron jobs (agent or `no_agent` mode) for a single app or task that don't warrant a full Celery Beat entry (e.g. "remind me to check OANDA at 9am", "poll my inbox every hour today")
- **Wire integrations into conversational flows** — chain MCP tools from `harqis-work` across a conversation turn: fetch data from one app, process it, push the result to another, without writing a new workflow

**Separation of concerns:**

| Layer | Role | What lives here |
|---|---|---|
| `harqis-work` | **Build** — the platform structure | App integrations, Celery workflows, MCP server, scheduled tasks, core config |
| Hermes (`~/.hermes/`) | **Wire** — the pipes and control surface | Agent memory, lessons, plans, ad-hoc cron jobs, manual trigger scripts |

The rule of thumb: if it needs to run reliably on a cron or be reused by multiple consumers, it belongs in `harqis-work`. If it's a one-off connection, a manual trigger, or a conversational shortcut, it belongs in Hermes.

#### Memory layout

Hermes memory is **not stored in this repo** and is **not synced across machines** — it is local per-machine under the user's home directory, so the platform codebase stays free of agent state.

```
~/.hermes/                     ← local per-machine (not committed, not synced)
├── memory/
│   ├── agent_lessons.md   # recurring lessons distilled from past runs (weekly)
│   └── ...                # long-term narrative memory
├── plans/                 # plans written by /max-plan and planning passes
├── scripts/               # cron-invoked helper scripts
└── logs/                  # job logs
```

**Why it's local:** Hermes writes memory continuously without touching the platform repo, so `harqis-work` stays under manual maintainer control. There is no auto-commit/auto-pull sync job to operate.

> Hermes runtime, MCP, and cron model: [`docs/info/HERMES.md`](HERMES.md)
>
> Setup and per-OS wiring details: [`docs/info/AI-TOOLS-WIRING.md`](AI-TOOLS-WIRING.md)
>
> Host deployment and service inventory: [`docs/info/HERMES-HOST.md`](HERMES-HOST.md)
>
> Legacy OpenClaw sync model (**deprecated**): [`docs/info/OPENCLAW-SYNC.md`](OPENCLAW-SYNC.md)

---

### MCP Server (`/mcp/`)

A FastMCP server that exposes configured app tools from the shared catalog over the Model Context Protocol. Used by:
- Claude Desktop (via `mcp/claude_desktop_config.json`)
- The Kanban agent MCP bridge (in-process, no separate server needed)
- Any MCP-compatible AI client

```sh
# Start the MCP server
python mcp/server.py
```

For coding agents with shell access, prefer the lazy JSON CLI so app schemas are discovered only
when needed:

```sh
python -m tools apps
python -m tools commands trello
python -m tools schema trello create_trello_card
```

The CLI and both MCP surfaces share `tools/catalog.py`; existing MCP names remain compatible.

The `hfl_corpus` adapter exposes canonical frontend API operations,
including entities, timeline, ideas, maps, goals and facets. Use the coverage
checker below for current counts and unreviewed routes rather than a fixed snapshot.
Internal sharing inputs remain protocol-only, not general MCP tools. The
[endpoint manifest](../../frontend/mcp_coverage.json) records reviewed routes; the
[frontend MCP coverage report](FRONTEND_MCP_COVERAGE.md) explains
coverage and remaining session/protocol work. CI checks the reviewed endpoint
manifest with `python -m tools.frontend_coverage --check`.

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
