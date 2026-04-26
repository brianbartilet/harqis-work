# Kanban-Driven Agent Task System

Turn a Trello or Jira board into an AI task interface. Humans create cards; Claude agents pick them up, execute work with scoped tools, and post results back — all visible on the same board. Every agent behavior is declared in a YAML profile; no agent code changes are needed to add a new agent type.

**Related docs:**
- [HARQIS-CLAW-HOST.md](HARQIS-CLAW-HOST.md) — host deployment, service inventory, worker nodes
- [SKILLS-GUIDE.md](SKILLS-GUIDE.md) — Claude Code skills and OpenClaw integration
- [AI-TOOLS-SETUP.md](AI-TOOLS-WIRING.md) — Claude Code and OpenClaw workspace setup
- [mcp/README.md](../../mcp/README.md) — full MCP tool catalog (all 16 app modules)

---

## Table of Contents

1. [Goals](#1-goals)
2. [System Overview](#2-system-overview)
3. [Board Design](#3-board-design)
4. [Card Anatomy](#4-card-anatomy)
5. [Agent Profiles](#5-agent-profiles)
6. [Profile Registry](#6-profile-registry)
7. [Agent Types and Labels](#7-agent-types-and-labels)
8. [Permission Model](#8-permission-model)
9. [Security Layer](#9-security-layer)
10. [Agent Implementation](#10-agent-implementation)
11. [Tool System](#11-tool-system)
12. [MCP Bridge](#12-mcp-bridge)
13. [Kanban Provider Interface](#13-kanban-provider-interface)
14. [Orchestrator](#14-orchestrator)
15. [Running the Orchestrator](#15-running-the-orchestrator)
16. [Best Practices](#16-best-practices)
17. [Roadmap](#17-roadmap)

---

## 1. Goals

- **Kanban as the task interface** — humans write cards, not code. Any tool call, any service, any agent type is expressed as a card with a label and description.
- **Profile-driven, not hard-coded** — adding a new agent type is a new YAML file, not a code change.
- **Scoped security by default** — agents never see the full environment. Only the env-vars declared in the profile's `secrets.required` list are injected, and all output is scrubbed before posting to the board.
- **Auditable** — every tool call, permission check, and secret access is written to a JSONL audit log.
- **Provider-agnostic** — the same orchestrator and agent code works with Trello or Jira. Swapping providers is a config change.

---

## 2. System Overview

```
Human (Trello / Jira board)
  │  creates card → [Backlog]
  │
  ▼
LocalOrchestrator  (polls every 30s)
  ├── fetches Backlog cards
  ├── resolves profile from card label / assignee
  ├── scopes secrets (only what the profile declared)
  ├── moves card → Pending, then → In Progress
  └── runs BaseKanbanAgent in-process
            │
            ▼
      Claude tool-use loop
            ├── reads card context (description, checklists, custom fields, attachments)
            ├── calls tools: filesystem, kanban, bash, MCP apps
            ├── permission-checks every tool call before execution
            ├── sanitizes all tool output before returning to Claude
            └── posts result comment → moves card → Done (or Failed)
                        │
                        ▼
              AuditLogger → logs/kanban_audit.jsonl
```

The board is the single source of truth for task state. The orchestrator is stateless between polls — all state lives on the card.

---

## 3. Board Design

### Columns

| Column | Purpose | Who moves here |
|---|---|---|
| **Backlog** | New tasks awaiting pickup | Human |
| **Pending** | Orchestrator has claimed the card (race-condition guard) | Orchestrator |
| **In Progress** | Agent actively working | Orchestrator |
| **Blocked** | Agent waiting on a dependency or human input | Agent (via `move_card` tool) |
| **Done** | Result posted | Agent (via `move_card` tool) |
| **Failed** | Unrecoverable error; error comment posted | Orchestrator |

### Race-condition prevention

The orchestrator moves a card to **Pending** in a single atomic API call before starting the agent. If a card is found in Pending but never reaches In Progress within the poll window, a future poll will reprocess it.

---

## 4. Card Anatomy

### Fields the agent sees

| Field | How the agent receives it |
|---|---|
| **Title** (`name`) | Task heading in the context prompt |
| **Description** (`desc`) | Main task instruction (primary prompt body) |
| **Labels** | Used by the orchestrator for profile matching; also visible in context |
| **Checklists** | Rendered as `- [ ] item` sub-tasks in the prompt |
| **Custom Fields** | Rendered as a `Parameters` section in the prompt |
| **Text Attachments** | Fetched (up to 50 KB each) and inlined into the prompt |
| **Card URL** | Always appended to the prompt footer |

### What `AgentContext.to_prompt()` produces

```
## Task
<card description or title>

## Parameters
key: value
...

## Sub-tasks
- [ ] Step one
- [x] Step two (already done)
- [ ] Step three

## Attached Files
### filename.txt
<file contents>

---
Card: https://trello.com/c/...  (id: abc123)
```

### Custom fields as typed parameters

Board-level custom fields pass structured inputs without encoding them in the description:

| Field Name | Type | Example Use |
|---|---|---|
| `output_format` | Dropdown | `markdown / json / plain` |
| `notify_channel` | String | Discord/Telegram target |
| `max_tokens` | Number | Override model token limit |
| `environment` | Dropdown | `dev / staging / prod` |
| `branch` | String | Git branch for code agents |

---

## 5. Agent Profiles

A profile is a YAML file under `agents/kanban/profiles/` that fully declares an agent's identity, model, tools, permissions, and secrets. Profiles support single-level `extends` inheritance.

### Full schema

```yaml
# agents/kanban/profiles/examples/agent_code.yaml

id: agent:code           # matches Trello/Jira card label (required)
name: "Code Agent"
description: "Software development agent"
version: "1.0"
extends: base            # inherit and merge from base.yaml

# ── Model ─────────────────────────────────────────────────────────────────────
model:
  provider: anthropic    # always anthropic for now
  model_id: claude-sonnet-4-6
  max_tokens: 8192
  system_prompt: |       # inline system prompt (use OR system_prompt_file, not both)
    You are a software development agent ...
  system_prompt_file: prompts/code_agent.md   # path relative to profile dir

# ── Tools ─────────────────────────────────────────────────────────────────────
tools:
  allowed:               # whitelist — if set, only these tools are exposed to Claude
    - read_file
    - write_file
    - glob
    - grep
    - bash
    - post_comment
    - move_card
    - check_item
  denied: []             # blacklist — always blocked regardless of allowed list
  mcp_apps:              # which app MCP modules to load (see mcp/server.py)
    - google_apps
    - trello
    - jira
    - discord
    - telegram
    - ynab
    - oanda
    - reddit
    - echo_mtg
    - scryfall
    - tcg_mp

# ── Permissions ───────────────────────────────────────────────────────────────
permissions:
  filesystem:
    allow:               # fnmatch glob patterns; omit to allow all
      - "**"
    deny:                # checked before allow; these are always blocked
      - ".env/**"
      - "secrets/**"
      - ".git/config"
  network:
    allow:               # domain pattern list; omit to allow all
      - "api.anthropic.com"
      - "api.trello.com"
    deny: []             # use ["*"] for default-deny with explicit allow-list
  git:
    can_push: false      # if false, git push raises PermissionDenied
    protected_branches:  # push to these branches always raises PermissionDenied
      - main
      - master
      - prod
    require_pr: true

# ── Secrets ───────────────────────────────────────────────────────────────────
secrets:
  required:              # env-var names the agent may access; others are blocked
    - ANTHROPIC_API_KEY
    - TRELLO_API_KEY
    - TRELLO_API_TOKEN
    - GOOGLE_APPS_API_KEY
    - DISCORD_BOT_TOKEN
    - JIRA_EMAIL
    - JIRA_API_TOKEN

# ── Hardware ──────────────────────────────────────────────────────────────────
hardware:
  node_affinity: any     # "any" or a specific node label (future: Celery routing)
  fallback_nodes: []
  requires_display: false
  requires_usb: false
  min_ram_gb: 2
  queue: default         # Celery queue (future use)

# ── Lifecycle ─────────────────────────────────────────────────────────────────
lifecycle:
  timeout_minutes: 20
  on_timeout: move_to_failed
  on_error: post_error_comment_and_fail
  on_success: move_to_review
  auto_approve: false
  max_retries: 1
  retry_delay_seconds: 30
```

### Profile inheritance

```yaml
# agents/kanban/profiles/examples/base.yaml
id: base
model:
  model_id: claude-sonnet-4-6
  max_tokens: 4096
tools:
  allowed: [read_file, glob, grep, post_comment, move_card, check_item]
permissions:
  network:
    allow: [api.anthropic.com, api.trello.com]
lifecycle:
  timeout_minutes: 20
  on_timeout: move_to_failed
secrets:
  required: [ANTHROPIC_API_KEY, TRELLO_API_KEY, TRELLO_API_TOKEN]
```

`merge_base()` fills missing fields from the base profile. Lists are merged (child appends to base). Scalar fields: child overrides base if explicitly set.

### Resolved system prompt

`AgentProfile.model.resolved_system_prompt(base_dir)` returns:
1. The `system_prompt` string if set inline
2. The contents of `system_prompt_file` if set (path resolved relative to `base_dir`)
3. Falls back to `agents/prompts/kanban_agent_default.md` if neither is set

---

## 6. Profile Registry

**File:** `agents/kanban/profiles/registry.py`

```python
class ProfileRegistry:
    def register(self, profile: AgentProfile) -> None: ...
    def load_file(self, path: Path) -> None: ...        # loads + applies inheritance
    def load_dir(self, directory: Path) -> None: ...    # loads all .yaml/.yml files, two-pass
    def resolve(self, profile_id: str) -> AgentProfile: ...
    def resolve_for_card(self, card: KanbanCard) -> Optional[AgentProfile]: ...
    def list(self) -> list[AgentProfile]: ...

    @classmethod
    def from_dir(cls, directory: Path) -> ProfileRegistry: ...
```

### Card resolution priority

`resolve_for_card()` tries each strategy in order, returning the first match:

1. **Assignee name** — card's `assignees` list contains an exact profile `id`
2. **Exact label match** — card has a label that exactly matches a profile `id`
3. **Prefix match** — card label starts with a profile `id` (most-specific prefix wins)

Example: card with label `agent:code:backend` matches profile `agent:code` if no `agent:code:backend` profile exists.

---

## 7. Agent Types and Labels

The label on a card is the routing key. The matching profile defines everything else.

### Built-in profiles (in `agents/kanban/profiles/examples/`)

| Profile ID | Label | Primary Tools | MCP Apps |
|---|---|---|---|
| `base` | (base only; never used directly) | read_file, glob, grep, post_comment, move_card, check_item | — |
| `agent:code` | `agent:code` | + write_file, bash | google_apps, trello, jira, discord, telegram, ynab, oanda, reddit, echo_mtg, scryfall, tcg_mp |
| `agent:write` | `agent:write` | read_file, write_file, glob, grep, post_comment, move_card, check_item (no bash) | google_apps, trello, discord, telegram |

### Creating a new agent type

Add a YAML file to `agents/kanban/profiles/`:

```yaml
# agents/kanban/profiles/agent_finance.yaml
id: agent:finance
extends: base
name: "Finance Agent"
model:
  system_prompt: |
    You are a personal finance agent. Use YNAB and OANDA tools to
    summarize budgets and forex positions. Post your report as a card comment.
tools:
  allowed: [read_file, glob, post_comment, move_card]
  mcp_apps: [ynab, oanda, google_apps, telegram]
secrets:
  required: [ANTHROPIC_API_KEY, TRELLO_API_KEY, TRELLO_API_TOKEN,
             YNAB_ACCESS_TOKEN, OANDA_BEARER_TOKEN, GOOGLE_APPS_API_KEY]
lifecycle:
  timeout_minutes: 10
```

No code changes needed. The registry picks it up on next start.

---

## 8. Permission Model

### Enforcement layers

```
Profile YAML (declared)
  └── PermissionEnforcer.check_* (runtime, before every tool call)
        └── Raises PermissionDenied → agent sees error result
              └── AuditLogger records permission_check event
```

**File:** `agents/kanban/permissions/enforcer.py`

### What is checked

| Method | What it guards | Pattern matching |
|---|---|---|
| `check_tool(name)` | `tools.denied` and `tools.allowed` lists | Exact name match |
| `check_filesystem(path)` | `permissions.filesystem.allow/deny` | `fnmatch` glob on normalized path |
| `check_network(host)` | `permissions.network.allow/deny` | `fnmatch` domain pattern |
| `check_git_push(branch)` | `git.can_push`, `git.protected_branches` | Exact branch name |

### Filesystem permission logic

1. Resolve and normalize path (forward slashes)
2. If path matches any `deny` pattern → `PermissionDenied` immediately
3. If `allow` list is non-empty and path matches none → `PermissionDenied`
4. Otherwise → allowed

### Network permission logic

- If `deny` contains `"*"`, the allow list becomes the explicit whitelist
- Deny patterns are checked first, but any allow match overrides a deny-all

---

## 9. Security Layer

### SecretStore (`agents/kanban/security/secret_store.py`)

Scopes secrets from the full environment down to only what a profile declared.

```python
store = SecretStore(env=os.environ.copy())

# Returns only vars the profile asked for — raises KeyError if any are missing
scoped = store.scoped_for_profile(profile)

# Encrypt scoped secrets for future worker payloads (Fernet)
payload = store.pack(scoped)        # → encrypted base64 string
recovered = store.unpack(payload)   # → dict[str, str]

# Generate a new Fernet encryption key
key = SecretStore.generate_key()
```

Agents never see `os.environ` directly. The `McpBridge` temporarily injects scoped secrets into `os.environ` during a tool call (via a context manager) and restores the original state after.

### OutputSanitizer (`agents/kanban/security/sanitizer.py`)

```python
sanitizer = OutputSanitizer(secrets=scoped_secrets)

clean = sanitizer.scrub(text)                  # replaces secret values with [REDACTED]
sanitizer.scrub_messages(messages)             # mutates message history in-place
```

- Longest secret values matched first (prevents partial replacements)
- Secrets shorter than 8 characters are skipped (avoids false positives)
- Applied to every tool output before it is returned to Claude, and to the final result before it is posted as a card comment

### AuditLogger (`agents/kanban/security/audit.py`)

Writes JSONL records to `logs/kanban_audit.jsonl` (configurable via `KANBAN_AUDIT_LOG`).

| Event | When logged |
|---|---|
| `agent_start` | Agent loop begins |
| `tool_call` | Agent invokes any tool |
| `tool_result` | Tool returns (success or error) |
| `permission_check` | PermissionEnforcer makes an allow/deny decision |
| `secret_access` | SecretStore scopes secrets for a profile |
| `sanitizer_redact` | OutputSanitizer replaces a secret value |
| `card_lifecycle` | Card moves between columns |
| `agent_finish` | Agent loop exits (success, error, or iteration overflow) |

`NullAuditLogger` is a no-op drop-in for tests and dry-run mode.

---

## 10. Agent Implementation

**File:** `agents/kanban/agent/base.py`  
**Class:** `BaseKanbanAgent`

### Constructor

```python
BaseKanbanAgent(
    profile: AgentProfile,
    card: KanbanCard,
    provider: KanbanProvider,
    api_key: str,
    scoped_secrets: Optional[dict[str, str]] = None,
    audit: Optional[AuditLogger] = None,
)
```

### Tool-use loop

`run() -> str` executes the loop and returns the final sanitized result:

```
1. build_card_context(card) → AgentContext → AgentContext.to_prompt()
2. Resolve system prompt (profile → default prompt)
3. Append tool inventory to system prompt
4. Loop (max 50 iterations):
   a. Call Claude API: model, max_tokens, system, tools, messages
   b. stop_reason == "end_turn"  →  extract text, scrub, return
   c. stop_reason == "tool_use"  →  for each tool_use block:
        - enforcer.check_tool(name)       # raises PermissionDenied if denied
        - registry.call(name, inputs)     # execute tool
        - sanitizer.scrub(output)         # remove any leaked secrets
        - truncate to 40,000 chars        # prevent context overflow
        - build tool_result message block
   d. append assistant + tool_result messages, continue loop
5. Iteration overflow → return error message
```

### System prompt structure

The agent always sees:

```
<profile system prompt or kanban_agent_default.md>

Working directory: <profile.context.working_directory>
Repos: <repo URLs and branch policies if configured>

## Available Tools
- read_file: Read a file from the filesystem ...
- write_file: Write content to a file ...
- bash: Execute a shell command ...
...
```

---

## 11. Tool System

**Files:** `agents/kanban/agent/tools/`

### Native tools

| Tool name | File | What it does |
|---|---|---|
| `read_file` | `filesystem.py` | Read file text; optional `start_line`/`end_line` |
| `write_file` | `filesystem.py` | Write content; creates parent directories |
| `glob` | `filesystem.py` | Find files by glob pattern; permission-filtered results |
| `grep` | `filesystem.py` | Regex search across files; returns `path:line:text` (up to 500 lines) |
| `bash` | `filesystem.py` | Execute shell command; respects `working_directory`; 60s default timeout |
| `post_comment` | `kanban_tools.py` | Post markdown comment to the current card |
| `move_card` | `kanban_tools.py` | Move card to a column (`Backlog`, `Pending`, `In Progress`, `Blocked`, `Done`, `Failed`) |
| `check_item` | `kanban_tools.py` | Mark a checklist item checked/unchecked (case-insensitive partial match on name) |

### Tool registry (`agents/kanban/agent/tools/registry.py`)

```python
class ToolRegistry:
    def call(self, name: str, inputs: dict) -> Any: ...
    def definitions(self) -> list[dict]: ...   # filtered by profile's allowed/denied lists
```

`definitions()` returns the Anthropic-format tool definitions that Claude actually sees — filtered down to what the profile permits. MCP tools from the bridge are appended after native tools.

---

## 12. MCP Bridge

**File:** `agents/kanban/agent/tools/mcp_bridge.py`  
**Class:** `McpBridge`

The bridge imports each app's `register_*_tools(mcp)` function directly (no separate server process) and exposes registered tools to the agent via the same `call()` / `definitions()` interface as native tools.

### Supported `mcp_apps` values

| Value in profile | App module loaded |
|---|---|
| `google_apps` | Calendar, Gmail, Keep tools |
| `trello` | Trello card/board tools |
| `discord` | Discord messaging tools |
| `jira` | Jira issue tools |
| `linkedin` | LinkedIn tools |
| `oanda` | OANDA forex tools |
| `reddit` | Reddit tools |
| `telegram` | Telegram bot tools |
| `ynab` | YNAB budget tools |
| `echo_mtg` | Echo MTG inventory tools |
| `scryfall` | Scryfall card database tools |
| `tcg_mp` | TCG Marketplace tools |
| `orgo` | Orgo cloud VM tools |
| `own_tracks` | OwnTracks location tools |

### Secret injection during MCP calls

```python
# McpBridge uses a context manager to temporarily inject scoped secrets
with _injected_env(scoped_secrets):
    result = mcp_tool_fn(**inputs)
# os.environ restored to original state after the call
```

Agents can only call MCP tools for apps listed in their profile's `mcp_apps`. The tool definitions themselves are filtered by the ToolRegistry before being passed to Claude.

---

## 13. Kanban Provider Interface

**File:** `agents/kanban/interface.py`

### Core dataclasses

```python
@dataclass
class KanbanCard:
    id: str
    title: str
    description: str
    labels: list[str]
    assignees: list[str]
    column: str
    url: str
    checklists: list[KanbanChecklist]
    attachments: list[KanbanAttachment]
    custom_fields: dict[str, str]
    due_date: Optional[str]
    raw: dict           # provider-native object for advanced use

@dataclass
class KanbanChecklist:
    id: str
    name: str
    items: list[KanbanChecklistItem]

@dataclass
class KanbanChecklistItem:
    id: str
    name: str
    checked: bool

@dataclass
class KanbanAttachment:
    id: str
    name: str
    url: str
    mime_type: str
    is_inline: bool
    bytes_size: int
```

### Abstract `KanbanProvider`

All orchestrator and agent code depends only on this interface. The concrete adapter is swapped via the factory.

```python
class KanbanProvider(ABC):
    # Board
    def get_columns(self, board_id: str) -> list[KanbanColumn]: ...
    def get_column_by_name(self, board_id: str, name: str) -> KanbanColumn: ...
    # Cards
    def get_cards(self, board_id: str, column: str, label=None) -> list[KanbanCard]: ...
    def get_card(self, card_id: str) -> KanbanCard: ...
    def move_card(self, card_id: str, column: str) -> None: ...
    def assign_card(self, card_id: str, agent_id: str) -> None: ...
    # Comments
    def add_comment(self, card_id: str, text: str) -> None: ...
    def get_comments(self, card_id: str) -> list[str]: ...
    # Checklists
    def check_item(self, card_id: str, item_id: str, checked: bool = True) -> None: ...
    # Attachments
    def get_attachments(self, card_id: str) -> list[KanbanAttachment]: ...
    def add_attachment(self, card_id: str, name: str, content: bytes, mime_type: str) -> None: ...
    # Labels
    def add_label(self, card_id: str, label: str) -> None: ...
    def remove_label(self, card_id: str, label: str) -> None: ...
    # Custom fields
    def get_custom_fields(self, card_id: str) -> dict[str, str]: ...
    def set_custom_field(self, card_id: str, field_name: str, value: str) -> None: ...
    # Webhooks (optional)
    def register_webhook(self, board_id: str, callback_url: str) -> str: ...
    def delete_webhook(self, webhook_id: str) -> None: ...
```

### Trello adapter (`agents/kanban/adapters/trello.py`)

- `TrelloProvider(api_key, token, timeout=10)`
- Caches board column mappings (`_refresh_columns()`) to avoid repeated API calls
- `_resolve_board_id()` — converts short Trello links to full board IDs
- Full implementation of all `KanbanProvider` methods

### Jira adapter (`agents/kanban/adapters/jira.py`)

- `JiraProvider(server, email, api_token, api_version="3", timeout=15)`
- Uses Basic Auth (base64 `email:api_token`)
- Maps Jira concepts: Issues → cards, Statuses → columns, Subtasks → checklists
- ADF document body is parsed to plain text by `_extract_text()`

### Provider factory (`agents/kanban/factory.py`)

```python
from agents.kanban.factory import create_provider

provider = create_provider({
    "provider": "trello",
    "api_key": "...",
    "token": "...",
})
```

Supported values for `"provider"`: `"trello"`, `"jira"`.

### Jira concept mapping

| Kanban concept | Trello | Jira |
|---|---|---|
| Board | Trello Board | Jira Board (Scrum or Kanban) |
| Column | List | Status |
| Card | Card | Issue (identified by key, e.g. `HARQ-42`) |
| Label | Card label | Issue label |
| Checklist | Checklist | Subtasks |
| Comment | Card comment | Issue comment |
| Attachment | Card attachment | Issue attachment |
| Custom Field | Custom field | Custom field (`customfield_*`) |
| Assignee | Card member | Issue assignee |

---

## 14. Orchestrator

**File:** `agents/kanban/orchestrator/local.py`  
**Class:** `LocalOrchestrator`

### Constructor

```python
LocalOrchestrator(
    provider: KanbanProvider,
    registry: ProfileRegistry,
    api_key: str,
    board_id: str,
    secret_store: Optional[SecretStore] = None,
    poll_interval: int = 30,
    dry_run: bool = False,
    audit_log_path: Optional[Path] = None,
)
```

### Card lifecycle (one poll cycle)

```
poll_once()
  for card in provider.get_cards(board_id, "Backlog"):
    profile = registry.resolve_for_card(card)   # None → skip
    scoped  = secret_store.scoped_for_profile(profile)
    audit   = AuditLogger(profile.id, card.id, audit_log_path)

    process_card(card, profile, scoped, audit):
      provider.move_card(card.id, "Pending")
      provider.add_comment(card.id, "claimed-by: <profile.name>")
      provider.move_card(card.id, "In Progress")
      result = BaseKanbanAgent(...).run()
      provider.add_comment(card.id, f"## Result\n{result}")
      provider.move_card(card.id, "Done")

    _handle_error(card, exc):
      provider.add_comment(card.id, f"## Error\n```\n{traceback}\n```")
      provider.move_card(card.id, "Failed")
```

### Factory from environment

```python
orchestrator = LocalOrchestrator.from_env(profiles_dir=None)
```

| Env var | Required | Default | Purpose |
|---|---|---|---|
| `KANBAN_PROVIDER` | Yes | — | `trello` or `jira` |
| `KANBAN_BOARD_ID` | Yes | — | Trello board ID or Jira project key |
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `TRELLO_API_KEY` | If Trello | — | Trello API key |
| `TRELLO_API_TOKEN` | If Trello | — | Trello API token |
| `JIRA_SERVER` | If Jira | — | Jira server URL |
| `JIRA_EMAIL` | If Jira | — | Jira account email |
| `JIRA_API_TOKEN` | If Jira | — | Jira API token |
| `KANBAN_PROFILES_DIR` | No | `agents/kanban/profiles/examples` | Profile directory |
| `KANBAN_POLL_INTERVAL` | No | `30` | Poll interval (seconds) |
| `KANBAN_DRY_RUN` | No | `false` | Match cards but don't run agents |
| `KANBAN_AUDIT_LOG` | No | `logs/kanban_audit.jsonl` | Audit log path |

---

## 15. Running the Orchestrator

```sh
# From repo root with .env loaded
python -m agents.kanban.orchestrator.local

# Dry run — resolves profiles but does not execute agents
python -m agents.kanban.orchestrator.local --dry-run

# Custom profiles directory and poll interval
python -m agents.kanban.orchestrator.local \
  --profiles-dir agents/kanban/profiles \
  --poll-interval 60
```

Required `.env/apps.env` vars:

```env
KANBAN_PROVIDER=trello
KANBAN_BOARD_ID=<board-id>
ANTHROPIC_API_KEY=sk-ant-...
TRELLO_API_KEY=...
TRELLO_API_TOKEN=...
```

### Tests

```sh
# Offline unit tests (no API calls)
pytest agents/kanban/tests/ -m "not integration"

# Integration tests (requires live credentials)
pytest agents/kanban/tests/ -m integration
```

**Coverage:** 7 test files · ~1,116 lines · 75 unit tests · 2 integration tests

| Test file | Covers |
|---|---|
| `test_agent.py` | Tool-use loop, permission enforcement, system prompts |
| `test_orchestrator.py` | Card polling, processing, error handling, dry-run |
| `test_profiles.py` | YAML loading, inheritance, registry resolution |
| `test_permissions.py` | Filesystem / network / git permission checks |
| `test_security.py` | SecretStore, OutputSanitizer, AuditLogger |
| `test_trello_adapter.py` | Trello API mapping, column resolution |
| `test_interface.py` | Card context building, attachment handling |

---

## 16. Best Practices

### Card hygiene

- One agent label per card. If a task needs two agent types, split it into two linked cards.
- Write descriptions as if briefing a capable-but-new colleague — include context, acceptance criteria, and any constraints.
- Use checklists for tasks with more than 3 steps; agents mark items checked as they complete them.
- Use custom fields for structured parameters (repo URL, branch, output format) rather than encoding them in the description.

### Output hygiene

- Post large outputs (files, code, CSVs) as card attachments, not comment text. Comments are for summaries and status.
- For code changes, the PR URL is the primary output. Agent posts the PR link as a comment.

### Security

- Never add secrets to `permissions.filesystem.allow` paths. Agents read those paths.
- Rotate `ANTHROPIC_API_KEY` per agent profile so a compromised profile can be revoked without affecting others.
- Review `logs/kanban_audit.jsonl` periodically — it records every tool call and permission decision.
- The `deny` list in `permissions.filesystem` always wins. Put `.env/**` and `secrets/**` in every profile's deny list (inherited from `base`).

### Cost and performance

- Use `claude-haiku-4-5` for lightweight routing or summarization tasks; `claude-sonnet-4-6` for the majority of work.
- Set `max_tokens` conservatively in the profile — it caps cost per task.
- Log token usage via the audit logger and alert on tasks that exceed a threshold.
- Add `system_prompt_file` to your profiles and use Anthropic prompt caching for profiles with expensive system prompts.

---

## 17. Roadmap

The items below are designed but not yet implemented:

### Celery worker dispatch

Currently the orchestrator runs agents in-process. The planned extension is Celery-based dispatch to remote worker nodes (VPS or N100 Windows machines):

- `SecretStore.pack()` / `unpack()` (Fernet encryption) is already implemented for encrypted worker payloads
- `profile.hardware.queue` field is in the schema, ready for Celery routing
- Worker nodes would run `agents.kanban.workers.run_agent` as a Celery task
- See [`HARQIS-CLAW-HOST.md`](HARQIS-CLAW-HOST.md) for the planned multi-node topology

### Webhook trigger mode

Current trigger is polling (30s default). Planned:
- FastAPI webhook listener for Trello (`POST /trello/webhook`) and Jira issue events
- Hybrid mode: webhook as primary trigger, poll as catch-all fallback
- Webhook registration via `KanbanProvider.register_webhook()`

### Extended features

| Feature | Status | Notes |
|---|---|---|
| Docker sandbox per agent | Planned | Isolate agent process; read-only bind mounts |
| Extended thinking | Planned | `claude-opus-4-6` with `thinking` parameter for architecture/review tasks |
| Agent-to-agent handoff | Planned | Code agent opens PR → review agent auto-claims it |
| Multi-board routing | Planned | Different boards per domain; shared profile registry |
| Vision (image attachments) | Planned | Pass base64 image attachments as multimodal messages |
| Domain pack CLI | Planned | `pack activate / list / deactivate` for board templates |
| Cost tracking | Planned | Log token usage per task to Elasticsearch |
| Blocked-card resume | Planned | Agent moves to Blocked; human resolves; agent resumes from last checklist item |
