# agents/projects — Trello workspace orchestrator

A multi-board Trello orchestrator that picks up cards across an entire
workspace and runs them through Claude agents. Cards flow through a
shared kanban (`Ready → Pending → In Progress → In Review → Done`),
get processed by humans or AI agents based on labels, and surface
results back as Trello comments + optional Discord posts +
Elasticsearch telemetry.

**No Celery. No Redis. No Docker required for local development.**
A single Python process can act as orchestrator, agent worker, and
multi-board poller all at once.

---

## Concepts

| Term | Meaning |
|---|---|
| **Workspace** | A Trello organization (`TRELLO_WORKSPACE_ID`). The orchestrator polls every board in it and auto-picks-up new boards as they're created. |
| **Board** | A Trello board. Holds the canonical lists below. One workspace contains N boards. |
| **Card** | A Trello card. Routed by labels (`agent:*`, `os:*`, `human`/`manual`/`input`). |
| **Profile** | A YAML file that defines an agent: model, tools, permissions, persona, integrations. Cards get matched to profiles by their `agent:*` label. |
| **Team member** | A combined notion: humans on the board + AI agents (one per profile) operating either as the shared bot account (Mode B) or as their own Trello account (Mode A). |

---

## Setup

### 1. Install dependencies

```bash
pip install anthropic pyyaml requests
```

### 2. Set up environment variables

Create `.env/agents.env` (or add to existing `.env/apps.env`):

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
TRELLO_API_KEY=...
TRELLO_API_TOKEN=...

# Board source — pick ONE of these
TRELLO_WORKSPACE_ID=harqis-work          # auto-discover every board in the org
# TRELLO_BOARD_IDS=board1,board2,board3  # OR explicit list
# KANBAN_BOARD_ID=<single_id>            # OR legacy single-board fallback

# Optional workspace filters
TRELLO_BOARD_NAME_FILTER=agent-          # substring match (case-insensitive)
TRELLO_BOARD_NAME_EXCLUDE=sandbox,test   # comma-separated, case-insensitive
TRELLO_REDISCOVER_SECONDS=300            # how often to re-fetch the workspace

# Optional Discord (per-agent allowlist defined in profile)
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...

# Optional Elasticsearch telemetry — auto-enabled when the
# core.apps.es_logging library can find its config in apps_config.yaml.
KANBAN_TELEMETRY_INDEX=harqis-projects-events  # override default index name

# Operations
KANBAN_POLL_INTERVAL=30        # seconds between board polls (default 30)
KANBAN_NUM_AGENTS=1            # concurrent in-process agent workers per board
KANBAN_DRY_RUN=0               # set to 1 to log without invoking Claude
KANBAN_PROFILES_DIR=           # override (default: bundled examples)
KANBAN_PROFILE_FILTER=         # restrict to one profile id
KANBAN_OS_LABELS=              # comma-separated; auto-detected when unset
```

### 3. Set up your boards

Use `/new-kanban-board` (TBD) or create boards manually with these lists,
in order. **List names must match exactly.**

| List | Orchestrator behaviour |
|---|---|
| `Templates` | Card templates the team copies from. Orchestrator never reads or writes here. |
| `Draft` | Cards being refined / spec'd. Orchestrator ignores. |
| `Ready` | Intake list. Orchestrator polls this every `KANBAN_POLL_INTERVAL` seconds. |
| `Pending` | Orchestrator claimed the card and is about to start. |
| `In Progress` | Agent is actively working. |
| `Blocked` | Hard-stop dependency unmet. Re-queued to `Ready` when resolved. |
| `In Review` | Agent finished; awaiting human (or reviewer-agent) approval. |
| `Done` | Reviewed + accepted. |
| `Failed` | Unrecoverable error (Anthropic limit / 4xx-5xx / unhandled). Comment header surfaces the error kind. |

Profiles with `lifecycle.auto_approve: true` skip `In Review` and go
straight `In Progress → Done`.

### 4. Create a card

Drop a card in `Ready` with a description and a label. Examples:

```
Title:  Summarise this repo
Label:  agent:write
Body:   Read CLAUDE.md and write a 1-paragraph summary as a comment.
```

```
Title:  Build a status dashboard
Labels: agent:code, os:linux
Body:   Add a /status endpoint to frontend/ that returns worker counts.
```

### 5. Start the orchestrator

```bash
# From the repo root
python -m agents.projects.orchestrator.local

# With overrides
python -m agents.projects.orchestrator.local \
    --poll-interval 15 --dry-run --profile agent:default --os os:linux,os:gpu
```

Per tick the orchestrator:
1. Re-discovers workspace boards if the cadence is up
2. Polls every board's `In Progress` for paused-for-question cards to resume
3. Polls every board's `Ready` for new cards
4. Claims (`→ Pending`), starts (`→ In Progress`), runs the agent
5. Posts the result as a comment, moves to `In Review` (or `Done` if `auto_approve`)
6. On error → posts traceback, moves to `Failed`
7. Every `blocked_poll_interval` seconds, re-checks `Blocked` and re-queues resolved cards

---

## Tags (label routing)

All labels are case-insensitive on the bare label.

### Off-limits to agents

| Label | Behaviour |
|---|---|
| `human` | Skipped by every orchestrator on every board. |
| `manual` | Same as `human`. |
| `input` | Same — signals the card needs human input. |

These three trump every other label. A card with `human, agent:code` is
still skipped — no claim, no comment, no move.

### `agent:*` — which profile handles the card

| Label | Resolved profile |
|---|---|
| `agent:code` | exact match → `agent:code` |
| `agent:write:article` | exact match → `agent:write:article` |
| `agent:write` (with no exact match but `agent:write:*` exists) | prefix match → most specific profile that matches |
| no `agent:*` label | falls back to `agent:default` |
| `agent:typo` (no profile matches) | **None** — card skipped (typo surfaced, not silently routed) |

### `os:*` — which orchestrator host can claim the card

| Label | Eligible orchestrators |
|---|---|
| (no `os:*` label) | Any orchestrator |
| `os:linux` | Linux hosts only |
| `os:darwin` / `os:macos` / `os:mac` | macOS hosts only |
| `os:windows` / `os:win` | Windows hosts only |
| `os:any` | Any orchestrator (always satisfied) |
| `os:linux, os:gpu` | At least one must intersect the host's `os_labels` |

Auto-detected from `platform.system()`. Override with `--os` flag or
`KANBAN_OS_LABELS` env var.

### `claimed-by:*` (automatic)

The orchestrator posts a `claimed-by: <profile_name>` comment on claim.
Informational — the audit trail of who picked the card up.

### `agent:question` / `agent:remember` (automatic)

Set by the `ask_human` tool when the agent pauses for human input.
The orchestrator removes them automatically when a human replies.

---

## Profiles

Profiles live in `profiles/examples/` (or override with `KANBAN_PROFILES_DIR`).
A profile defines one agent's identity, model, tools, permissions, and
integrations. Cards match profiles by their `agent:*` label.

### Minimal profile

```yaml
id: agent:write
name: "Write Agent"
model:
  model_id: claude-sonnet-4-6
  max_tokens: 4096
tools:
  allowed: [read_file, write_file, post_comment, move_card, check_item]
lifecycle:
  auto_approve: false   # → moves card to In Review, not Done
  timeout_minutes: 15
```

### Inheritance

```yaml
id: agent:code:myproject
extends: agent:code             # inherits model, tools, permissions
context:
  working_directory: /workspace/myproject
```

### Persona (Mode A vs Mode B)

| | Mode B — Signed comments (default) | Mode A — Real per-agent Trello account |
|---|---|---|
| Setup | 0 min | ~5 min: sign up, verify email, invite to board, generate token |
| Attribution | Shared bot account | Dedicated Trello account with avatar |
| Comment format | Persona signature block prepended | Native — no signature |
| When | Always (when `persona:` block is set) | When `provider_credentials` is set + env vars resolved |

Mode A activates when:
1. `provider_credentials.trello_api_key_env` + `trello_api_token_env` are set
2. Those env vars hold a real (key, token) pair

Otherwise the orchestrator logs once and falls back to Mode B for that profile.

Use `/create-new-kanban-profile <name>` to scaffold a new profile + register
placeholder env vars + print the manual Trello-account setup checklist.

### Specialized agents (system prompts)

Three layers compose every agent run:

| Layer | Source | Controls |
|---|---|---|
| **System prompt** | profile's `model.system_prompt` (or `system_prompt_file`) | Persona, constraints, output rules |
| **Task prompt** | Trello card (description, checklists, custom fields, attachments) | What to do |
| **Tool scope** | profile's `tools.allowed` + `tools.mcp_apps` | What the agent can touch |

Add a one-off override on a single card via the `system_prompt_addon`
custom field.

---

## Integrations

### Discord

Agents can post to Discord channels by inference, scoped to a
per-profile allowlist.

**Workspace setup** (one bot, all agents):
```bash
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...
```

**Per-profile allowlist** (in the profile YAML):
```yaml
integrations:
  discord:
    allowed_channels: [engineering, content, ops-alerts]
    channel_hints:
      engineering: "Code reviews, PR notifications, build/test status"
      content:     "Article drafts, copy reviews, marketing assets"
      ops-alerts:  "Operational issues, blocked deployments"
```

The agent gets a `discord_post(channel, message)` tool with the
allowlist baked into the schema enum, and the hints rendered in the
description so Claude can reason about which channel suits the message.
Channels not in the allowlist are rejected at runtime even if the schema
is bypassed.

If `DISCORD_BOT_TOKEN`/`DISCORD_GUILD_ID` are unset, the tool is silently
not registered for any agent — local dev keeps working without Discord.

Long messages (>2000 chars) are auto-split on line breaks across
multiple Discord messages.

### Elasticsearch telemetry

Lifecycle events are emitted to a single ES index (default
`harqis-projects-events`, override with `KANBAN_TELEMETRY_INDEX`).
Reuses `core.apps.es_logging.app.elasticsearch.post` from harqis-core
so auth/URL/SSL is identical to every other ES doc on the platform.

| Event | Fields |
|---|---|
| `card_claimed` | board_id, card_id, profile_id |
| `agent_started` | + model_id |
| `agent_finished` | + destination (`In Review`/`Done`), duration_seconds |
| `agent_failed` | + kind (api_usage_limit / api_rate_limit / api_error / unknown), detail |
| `card_blocked` | + reason |
| `card_paused` | + stateful (bool) |

All emissions are crash-safe: a broken ES connection logs a warning and
returns; cards keep processing. ES is also no-op when the harqis-core
wheel is absent or `apps_config.yaml` doesn't have an `ELASTIC_LOGGING`
section.

### MCP tools (per profile)

Workers reach the harqis-work MCP server through `tools.mcp_apps` in
their profile. Each profile scopes which apps it sees — workers never
get access beyond what the profile declares.

| Profile | Typical mcp_apps |
|---|---|
| `agent:write:article` | google_apps, discord, telegram |
| `agent:calculate` | oanda, ynab, google_apps |
| `agent:transcribe` | google_apps |
| `agent:code` | trello, discord |
| `agent:finance` | oanda, ynab, google_apps |

### OpenClaw (identity / long-term memory)

Set `OPENCLAW_SYNC_PATH` in env to the `harqis-openclaw-sync` repo root.
The orchestrator can prepend `SOUL.md` + `USER.md` + `MEMORY.md` +
today's daily note to the system prompt so every agent inherits the same
identity context. See `agent/persona.py` and the OpenClaw docs.

---

## Card data available to agents

| Source | How the agent sees it |
|---|---|
| Description | Main task prompt (under `# Task`) |
| Title | Fallback prompt if description is empty |
| Checklists | Listed under `# Sub-tasks`; agent ticks via `check_item` tool |
| Custom fields | Listed under `# Parameters` — repo URLs, branch names, env targets |
| Text attachments | Fetched and inlined under `# Attached Files` |
| URL | Appended at the bottom |
| `required_secrets` custom field | Hard dependency check; `Blocked` if any are missing |
| `system_prompt_addon` custom field | One-off addition to the profile's system prompt |

---

## Operations

### Run tests

```bash
pytest agents/projects/tests/ -m "smoke"            # fast unit tests (no API)
pytest agents/projects/tests/ -m "not integration"  # all unit tests
pytest agents/projects/tests/ -m "integration"      # live tests (needs creds)
pytest agents/projects/tests/ -v -s                 # all with output
```

### Audit log

Every claim, tool call, permission check, secret access, and finish writes
a JSONL record to `logs/projects_audit.jsonl`. Override path with
`KANBAN_AUDIT_LOG`.

### Pause for question (agent ↔ human)

Agents call the `ask_human(question)` tool to pause. The orchestrator
leaves the card in `In Progress` with the `agent:question` label. When a
human replies in the comments, the next poll resumes the agent. With the
`agent:remember` label set, the resume is **stateful** — the full prior
message history is reloaded; otherwise the agent gets a recap and
restarts fresh.

### Windows vs Linux vs macOS

Fully cross-platform:
- All paths use `pathlib.Path` (no hardcoded slashes).
- `BashTool` uses `subprocess.run(shell=True)` — `cmd.exe` on Windows, `bash` on POSIX.
- Profile `context.working_directory` accepts both `C:\path` and `/path`.
- OS auto-detection adds the right `os:*` labels per host.

### Production path

When ready to scale beyond a single machine:

1. **Celery** — replace `WorkspaceOrchestrator` with Celery task dispatch.
2. **Redis** — Celery broker for N worker nodes.
3. **Docker** — sandbox each agent with `docker run --rm`.
4. **Webhooks** — replace polling with Trello webhooks for <1s latency.
5. **Vault** — replace env vars with HashiCorp Vault for secrets.
6. **Hardware routing** — already supported via `os:*` labels.

The interface layer (`TrelloClient`, `AgentProfile`, `BaseKanbanAgent`)
is unchanged throughout this evolution — only the orchestration loop
changes.

---

## Directory structure

```
agents/projects/
├── README.md                  # this file
│
├── trello/                    # Trello backend
│   ├── client.py              # TrelloClient — REST API v1 wrapper
│   ├── models.py              # KanbanCard, KanbanColumn, KanbanChecklist, ...
│   └── workspace.py           # TrelloWorkspace — auto-discover boards in an org
│
├── orchestrator/
│   ├── lists.py               # Canonical list names + transitions
│   ├── routing.py             # is_human_card, detect_local_os_labels, card_os_required
│   ├── board.py               # BoardOrchestrator — single-board logic
│   ├── workspace.py           # WorkspaceOrchestrator — multi-board polling loop
│   ├── blocked_handler.py     # Re-queues Blocked cards when deps resolve
│   └── local.py               # CLI entry + from_env() factory
│
├── profiles/
│   ├── schema.py              # AgentProfile + sub-configs (Discord, persona, ...)
│   ├── registry.py            # Loads profiles, resolves card → profile
│   └── examples/
│       ├── base.yaml
│       ├── agent_default.yaml # Fallback agent
│       ├── agent_code.yaml    # Code agent (bash, git, PR creation)
│       ├── agent_write.yaml   # Write agent
│       └── agent_full.yaml    # Full agent (all tools, claude[bot] author)
│
├── permissions/
│   └── enforcer.py            # PermissionEnforcer — fs/network/git checks
│
├── security/
│   ├── secret_store.py        # Per-profile env-var scoping
│   ├── sanitizer.py           # OutputSanitizer — scrubs secrets from output
│   └── audit.py               # JSONL audit logger
│
├── dependencies/
│   └── detector.py            # Detects required_secrets / service deps
│
├── agent/
│   ├── base.py                # BaseKanbanAgent — Claude tool-use loop
│   ├── context.py             # AgentContext — builds prompt from card data
│   ├── persona.py             # Mode B comment signing
│   ├── question.py            # ask_human pause/resume protocol
│   └── tools/
│       ├── registry.py        # ToolRegistry — maps names to callables
│       ├── filesystem.py      # ReadFile, WriteFile, Glob, Grep, Bash
│       ├── git_tools.py       # GitStatus, GitCreateBranch, GitCommit, GitPush, GitCreatePR
│       ├── kanban_tools.py    # post_comment, move_card, check_item, ask_human
│       ├── discord_tool.py    # DiscordPostTool (gated on profile + env)
│       └── mcp_bridge.py      # Reach into the MCP server
│
├── integrations/
│   ├── discord.py             # DiscordClient (Bot API)
│   └── telemetry.py           # ES emitter (reuses harqis-core es_logging)
│
└── tests/                     # 218+ unit tests; see "Run tests" above
```
