# Trello-Driven Agent Kanban Ecosystem — Solution Design

Use Trello as a shared task interface between humans and AI agents. Humans create cards; agents claim them, execute work within a scoped context, and post results back — all visible on the same board. The system is reusable across domains: personal productivity, software development, QA/testing, and research.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Hardware Ecosystem](#2-hardware-ecosystem)
3. [Kanban Board Design](#3-kanban-board-design)
4. [Card Anatomy and Context](#4-card-anatomy-and-context)
5. [Agent Profiles](#5-agent-profiles)
6. [Agent Types and Labels](#6-agent-types-and-labels)
7. [Permission Model](#7-permission-model)
8. [Agent Design and Implementation](#8-agent-design-and-implementation)
9. [Kanban Provider Interface](#9-kanban-provider-interface)
10. [Orchestration Architecture](#10-orchestration-architecture)
11. [Reusability Framework — Domain Packs](#11-reusability-framework--domain-packs)
12. [Trigger Strategy](#12-trigger-strategy)
13. [Challenges, Risks, and Milestones](#13-challenges-risks-and-milestones)
14. [Tips and Best Practices](#14-tips-and-best-practices)

---

## 1. System Overview

```
Human (Trello)
  │  creates card → [Backlog]
  │
  ▼
Orchestrator (Mac Mini)
  ├── polls board / receives webhook
  ├── resolves agent profile from card label + assignee
  ├── injects scoped context (repos, secrets, hardware)
  └── dispatches task to Worker Node (N100)
         │
         ▼
    Agent Process (Claude Code / Anthropic SDK)
         ├── reads full card context (description, checklists, attachments, custom fields)
         ├── executes work using scoped tools
         ├── posts result as card comment
         └── moves card → [Done] or [Done]
```

The Trello board is the single source of truth for task state. The orchestrator is stateless between polls — all task state lives on the card.

---

## 2. Hardware Ecosystem

### 2.1 Topology

```
┌─────────────────────────────────────────────────────┐
│                  Local Network / VPN                │
│                                                     │
│  ┌──────────────────┐       ┌──────────────────┐   │
│  │   Mac Mini M4     │       │   N100 Node 1    │   │
│  │  (Orchestrator)  │◄─────►│  (Worker: code)  │   │
│  │                  │       └──────────────────┘   │
│  │  - Trello poller │       ┌──────────────────┐   │
│  │  - Webhook recv  │◄─────►│   N100 Node 2    │   │
│  │  - Profile store │       │  (Worker: test)  │   │
│  │  - Secret vault  │       └──────────────────┘   │
│  │  - Task router   │       ┌──────────────────┐   │
│  │  - Result agg    │◄─────►│   N100 Node 3    │   │
│  └──────────────────┘       │  (Worker: data)  │   │
│           │                 └──────────────────┘   │
│           │                 ┌──────────────────┐   │
│           └────────────────►│   N100 Node N    │   │
│                             │  (Worker: web)   │   │
│                             └──────────────────┘   │
└─────────────────────────────────────────────────────┘
         │
         ▼
   External Services
   (Trello, GitHub, Jira, Claude API, ...)
```

### 2.2 Mac Mini — Orchestrator Role

| Responsibility | Implementation |
|---|---|
| Trello board polling / webhook listener | FastAPI + APScheduler |
| Agent profile resolution | YAML profile store |
| Secret injection | HashiCorp Vault / `pass` / macOS Keychain |
| Task dispatch to N100 nodes | Celery broker (Redis) |
| Result aggregation | Writes final comment + moves card |
| Hardware assignment | Maps card `hw:` label to a specific node |
| Health monitoring | Periodic ping to each N100; dead node reassigns card |

**Specs target:** Mac Mini M4 (16 GB RAM minimum). Runs the broker, profile server, and lightweight orchestrator process. Does not execute heavy agent work itself.

### 2.3 N100 Nodes — Worker Role

Each N100 is a Celery worker registered to one or more queues. The orchestrator assigns tasks based on the agent profile's `node_affinity` setting.

| Node | Assigned Queue(s) | Primary Agent Types |
|---|---|---|
| N100-1 | `code`, `default` | software-dev, git, CI |
| N100-2 | `test`, `default` | QA, browser automation, pytest |
| N100-3 | `data`, `default` | queries, analytics, YNAB, ETL |
| N100-N | `web`, `write` | research, scraping, content |

**Node bootstrap:** Each N100 runs a `harqis-core` Celery worker, Docker (for isolated agent sandboxes), and optionally Claude Code CLI. Nodes mount shared NFS for large file outputs.

### 2.4 Hardware Context on Cards

Cards can carry a `hw:<node>` label to pin execution to a specific node — for example when an agent needs a USB-connected device, a local display, or a specific GPU.

```
hw:mac-mini    → runs on orchestrator itself (desktop automation, Rainmeter)
hw:n100-1      → pinned to node 1 (e.g. code signing key is there)
hw:any         → default; orchestrator picks least-loaded node
```

---

## 3. Kanban Board Design

### 3.1 Board Columns

| Column | Purpose | Who Moves Here |
|---|---|---|
| **Backlog** | New tasks awaiting pickup | Human |
| **Pending** | Agent has locked the card (race-condition guard) | Agent (immediately on pickup) |
| **In Progress** | Agent actively working | Agent |
| **Blocked** | Agent waiting on dependency or human input | Agent |
| **Done** | Result posted, awaiting human approval | Agent |
| **Done** | Verified and closed | Human or auto-close rule |
| **Failed** | Agent encountered unrecoverable error | Agent |

### 3.2 Multi-Board Strategy

One Trello board per **domain pack** (see Section 10). Boards share the same agent profile store but have different default permission sets.

| Board | Domain | Example Labels |
|---|---|---|
| `harqis-work` | Personal automation | `agent:hud`, `agent:purchases`, `agent:finance` |
| `harqis-dev` | Software development | `agent:code`, `agent:review`, `agent:ci` |
| `harqis-qa` | Testing | `agent:test`, `agent:perf`, `agent:browser` |
| `harqis-personal` | Personal workflows | `agent:write`, `agent:research`, `agent:schedule` |

---

## 4. Card Anatomy and Context

### 4.1 Card Fields

| Field | Purpose | Agent Access |
|---|---|---|
| **Title** | One-line task instruction | `card.name` |
| **Label(s)** | Route to agent type + hardware pin | `card.labels[].name` |
| **Description** | Full prompt, parameters, acceptance criteria | `card.desc` |
| **Assignee** | Pin to specific named agent instance | `card.idMembers` |
| **Checklist** | Sub-tasks; agent checks them off as it works | `card.checklists[]` |
| **Attachments** | Input files, specs, images, repos | `card.attachments[]` |
| **Custom Fields** | Typed parameters (string, number, dropdown, date) | `card.customFieldItems[]` |
| **Due Date** | Deadline; agent can respect or flag overdue | `card.due` |
| **Comments** | Agent result output + human feedback thread | `card.actions[].data.text` |
| **Cover** | Visual status indicator (agent sets color) | `card.cover` |

### 4.2 Custom Fields as Agent Parameters

Define board-level custom fields to pass structured inputs to agents without encoding them in the description:

| Field Name | Type | Example Use |
|---|---|---|
| `repo_url` | String | Target GitHub repo for code agents |
| `branch` | String | Branch to operate on |
| `environment` | Dropdown | `dev / staging / prod` |
| `max_tokens` | Number | Override LLM max tokens |
| `output_format` | Dropdown | `markdown / json / plain` |
| `notify_channel` | String | Discord/Telegram channel for result |
| `priority` | Dropdown | `critical / high / normal / low` |
| `timeout_minutes` | Number | Hard deadline for agent execution |

### 4.3 Attachment Context

Agents fetch and read attachments as part of their context window:

```python
def build_card_context(card: TrelloCard) -> AgentContext:
    ctx = AgentContext()
    ctx.prompt     = card.desc
    ctx.checklists = card.checklists
    ctx.params     = {f.name: f.value for f in card.custom_fields}
    ctx.files      = []
    for att in card.attachments:
        if att.is_url:
            ctx.files.append(fetch_url(att.url))   # Trello-hosted or external
        elif att.mime in TEXT_MIMES:
            ctx.files.append(read_attachment(att))  # inline text
    return ctx
```

Large binary attachments (images, PDFs) are passed as base64 to multimodal Claude calls.

### 4.4 Checklist as Sub-Task Protocol

Agents use checklists to show granular progress:

1. Orchestrator converts checklist items into ordered sub-steps.
2. Agent checks each item off via `PUT /1/cards/{cardId}/checkItem/{checkItemId}` as it completes them.
3. If blocked on a checklist item, agent moves card to **Blocked** and comments with the blocker.
4. Human resolves blocker, moves card back to **In Progress**, and agent resumes from the last unchecked item.

---

## 5. Agent Profiles

An agent profile is a YAML file that fully describes one logical agent — its identity, context, tools, permissions, and hardware affinity. Profiles are stored on the orchestrator and referenced by card labels or assignee names.

### 5.1 Profile Schema

```yaml
# profiles/agent_code_harqis.yaml
id: agent:code:harqis          # unique identifier; matches Trello label
name: "Harqis Code Agent"
description: "Full-stack dev agent for harqis-work repo"
version: "1.0"

# ── Model ───────────────────────────────────────────────────────────────────
model:
  provider: anthropic           # anthropic | openai | local
  model_id: claude-sonnet-4-6
  max_tokens: 8192
  system_prompt_file: prompts/system/code_agent.md
  tool_choice: auto

# ── Context ─────────────────────────────────────────────────────────────────
context:
  repos:
    - url: https://github.com/brianbartilet/harqis-work
      local_path: /workspace/harqis-work
      branch_policy: feature-branch-only   # never commit to main directly
    - url: https://github.com/brianbartilet/harqis-core
      local_path: /workspace/harqis-core
      branch_policy: read-only
  working_directory: /workspace/harqis-work
  env_files:
    - /secrets/harqis/apps.env
  config_files:
    - /workspace/harqis-work/apps_config.yaml

# ── Tools (MCP + native) ────────────────────────────────────────────────────
tools:
  allowed:
    - bash                      # shell execution in working_directory only
    - read_file
    - write_file
    - glob
    - grep
    - git_commit
    - git_push
    - run_tests
    - trello_comment            # post back to card
    - trello_move_card
  denied:
    - web_search                # no external browsing for this agent
    - send_email
  mcp_servers:
    - name: harqis-work
      scope: [trello, jira, discord]

# ── Permissions ─────────────────────────────────────────────────────────────
permissions:
  filesystem:
    allow: ["/workspace/harqis-work/**", "/workspace/harqis-core/**"]
    deny:  ["/workspace/harqis-work/.env/**", "/secrets/**"]
  network:
    allow: ["api.anthropic.com", "api.trello.com", "api.github.com"]
    deny:  ["*"]                # default deny all other egress
  secrets:
    vault_path: "secret/harqis/code-agent"
    inject_as_env: true
  git:
    can_push: true
    protected_branches: ["main", "prod"]
    require_pr: true

# ── Hardware ─────────────────────────────────────────────────────────────────
hardware:
  node_affinity: n100-1         # preferred node
  fallback_nodes: [n100-2]
  requires_display: false
  requires_usb: false
  min_ram_gb: 4

# ── Lifecycle ────────────────────────────────────────────────────────────────
lifecycle:
  timeout_minutes: 30
  on_timeout: move_to_failed
  on_error: post_error_comment_and_fail
  on_success: move_to_review    # or done if auto_approve: true
  auto_approve: false           # human review required
  max_retries: 2
  retry_delay_seconds: 60
```

### 5.2 Profile Inheritance

Profiles support `extends` to share common config across a domain pack:

```yaml
# profiles/base_harqis.yaml
id: base:harqis
model:
  provider: anthropic
  model_id: claude-sonnet-4-6
permissions:
  network:
    allow: ["api.anthropic.com", "api.trello.com"]
    deny: ["*"]
lifecycle:
  timeout_minutes: 20
  on_error: post_error_comment_and_fail

---
# profiles/agent_write.yaml
extends: base:harqis
id: agent:write:harqis
name: "Writing Agent"
tools:
  allowed: [read_file, write_file, web_search, trello_comment, trello_move_card]
context:
  repos: []   # no code repo access
```

### 5.3 Profile Registry

The orchestrator maintains a profile registry loaded at startup:

```python
class ProfileRegistry:
    def load_all(self, profiles_dir: Path) -> None: ...
    def resolve(self, label: str) -> AgentProfile: ...
    def resolve_for_card(self, card: TrelloCard) -> AgentProfile: ...
    # Priority: assignee name > most-specific label > wildcard label
```

---

## 6. Agent Types and Labels

### 6.1 Core Agent Labels

| Label | Name | Responsibility | Key Tools |
|---|---|---|---|
| `agent:code` | Code Agent | Write, refactor, review code | bash, git, read/write file |
| `agent:test` | Test Agent | Generate + run tests, coverage | bash, pytest, browser |
| `agent:review` | Done Agent | PR review, code quality analysis | git, grep, web_search |
| `agent:ci` | CI Agent | Trigger pipelines, parse failures | bash, http, trello |
| `agent:web` | Web Agent | Browse, scrape, search | browser, web_search |
| `agent:write` | Write Agent | Draft, edit, summarise | write_file, web_search |
| `agent:data` | Data Agent | Query, analyse, transform data | bash, db, pandas |
| `agent:read` | Read Agent | Parse docs, OCR, extract structure | read_file, vision |
| `agent:research` | Research Agent | Deep-dive topic analysis | web_search, write_file |
| `agent:hud` | HUD Agent | Update desktop widgets, alerts | rainmeter, trello |
| `agent:finance` | Finance Agent | YNAB, OANDA, budget reports | ynab_api, oanda_api |
| `agent:schedule` | Schedule Agent | Calendar, reminders, task planning | gcal_api, trello |
| `agent:desktop` | Desktop Agent | Window mgmt, file sync, git pulls | bash, orgo, desktop |
| `agent:mobile` | Mobile Agent | Android screen capture, automation | orgo, adb |

### 6.2 Domain-Specific Agent Labels

These are mounted per board:

**harqis-dev board:**
```
agent:code:backend    agent:code:frontend    agent:code:infra
agent:test:unit       agent:test:integration agent:test:e2e
agent:review:security agent:review:perf
```

**harqis-personal board:**
```
agent:write:blog      agent:write:email      agent:write:social
agent:research:stock  agent:research:travel  agent:schedule:weekly
```

---

## 7. Permission Model

### 7.1 Permission Scopes

Permissions are declared in the agent profile and enforced at the orchestrator layer before any tool is executed.

```
┌────────────────────────────────────────────────────┐
│              Permission Scope Hierarchy            │
│                                                    │
│  Board-level defaults                              │
│    └── Profile-level overrides                     │
│          └── Card-level custom fields              │
│                └── Runtime checks (tool wrapper)  │
└────────────────────────────────────────────────────┘
```

### 7.2 Permission Categories

| Category | Scope Keys | Example |
|---|---|---|
| **Filesystem** | `allow[]`, `deny[]` glob paths | Allow `/workspace/**`, deny `/secrets/**` |
| **Network** | `allow[]`, `deny[]` hostnames | Allow `api.github.com`, deny `*` |
| **Git** | `can_push`, `protected_branches`, `require_pr` | Can push to feature branches only |
| **Secrets** | `vault_path`, `inject_as_env` | Inject `GITHUB_TOKEN` into env |
| **Tools** | `tools.allowed[]`, `tools.denied[]` | Allow `bash`, deny `send_email` |
| **MCP servers** | `mcp_servers[].scope[]` | harqis-work MCP, scoped to `[trello]` only |
| **Hardware** | `node_affinity`, `requires_display` | Pin to N100-1, no display needed |
| **Trello** | `can_move_to_done`, `can_delete_card` | Move to Done only; human closes |

### 7.3 Permission Enforcement Architecture

```python
class PermissionEnforcer:
    """Wraps every tool call. If denied, raises PermissionDenied and posts card comment."""

    def check_filesystem(self, path: str, profile: AgentProfile) -> bool: ...
    def check_network(self, host: str, profile: AgentProfile) -> bool: ...
    def check_tool(self, tool_name: str, profile: AgentProfile) -> bool: ...
    def check_git(self, branch: str, action: str, profile: AgentProfile) -> bool: ...

    def wrap_tool(self, tool_fn, profile: AgentProfile):
        def guarded(*args, **kwargs):
            self.check_tool(tool_fn.__name__, profile)
            return tool_fn(*args, **kwargs)
        return guarded
```

### 7.4 Secrets Management

```
Orchestrator Vault (HashiCorp Vault or SOPS)
  │
  ├── secret/harqis/code-agent/
  │     GITHUB_TOKEN, ANTHROPIC_API_KEY
  │
  ├── secret/harqis/finance-agent/
  │     YNAB_TOKEN, OANDA_API_KEY
  │
  └── secret/shared/
        TRELLO_API_KEY, TRELLO_TOKEN
```

Secrets are injected into the agent process environment at task startup and never written to disk or card comments.

---

## 8. Agent Design and Implementation

### 8.1 Agent Architecture

Each agent is implemented as a **Claude-powered tool-use loop** running inside a Celery task. The loop continues until the model emits a final `text` response with no further tool calls.

```python
# core pattern for every agent
class BaseKanbanAgent:
    def __init__(self, profile: AgentProfile, card: TrelloCard):
        self.profile  = profile
        self.card     = card
        self.client   = anthropic.Anthropic(api_key=profile.secrets["ANTHROPIC_API_KEY"])
        self.enforcer = PermissionEnforcer(profile)
        self.tools    = self._build_tool_registry()

    def build_messages(self) -> list[dict]:
        ctx = build_card_context(self.card)
        return [{"role": "user", "content": ctx.to_prompt()}]

    def run(self) -> str:
        messages = self.build_messages()
        while True:
            response = self.client.messages.create(
                model=self.profile.model.model_id,
                max_tokens=self.profile.model.max_tokens,
                system=self.profile.system_prompt,
                tools=self.tools.definitions(),
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                return self._extract_text(response)

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = self.enforcer.wrap_tool(
                        self.tools.call(block.name, block.input)
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    })
            messages.append({"role": "user", "content": tool_results})
```

### 8.2 Implementing with Claude Code CLI

For agents that need full IDE-level code understanding, run Claude Code CLI as the execution engine:

```python
import subprocess

class ClaudeCodeAgent(BaseKanbanAgent):
    """Delegates to Claude Code CLI for filesystem-aware code tasks."""

    def run(self) -> str:
        prompt = build_card_context(self.card).to_prompt()
        result = subprocess.run(
            ["claude", "--print", "--no-confirm", prompt],
            capture_output=True, text=True,
            cwd=self.profile.context.working_directory,
            env=self.profile.secrets.as_env(),
            timeout=self.profile.lifecycle.timeout_minutes * 60,
        )
        if result.returncode != 0:
            raise AgentError(result.stderr)
        return result.stdout
```

Claude Code CLI brings: file read/write/edit, glob, grep, bash, git operations, and the full project CLAUDE.md context — all without reimplementing those tools manually.

### 8.3 Tool Registry

```python
# tools/registry.py
TOOL_REGISTRY = {
    "bash":           BashTool(cwd=profile.cwd, enforcer=enforcer),
    "read_file":      ReadFileTool(enforcer=enforcer),
    "write_file":     WriteFileTool(enforcer=enforcer),
    "glob":           GlobTool(),
    "grep":           GrepTool(),
    "git_commit":     GitCommitTool(enforcer=enforcer),
    "git_push":       GitPushTool(enforcer=enforcer),
    "run_tests":      RunTestsTool(cmd="pytest", cwd=profile.cwd),
    "web_search":     WebSearchTool(enforcer=enforcer),
    "trello_comment": TrelloCommentTool(card_id=card.id),
    "trello_move":    TrelloMoveTool(card_id=card.id, enforcer=enforcer),
    "trello_checklist": TrelloChecklistTool(card_id=card.id),
    "discord_notify": DiscordNotifyTool(channel=card.custom_fields.get("notify_channel")),
}
```

### 8.4 System Prompt Design

System prompts are stored as markdown files in `prompts/system/` and injected at agent startup:

```markdown
<!-- prompts/system/code_agent.md -->
You are a software development agent operating within the harqis-work automation platform.

## Your Identity
- Agent ID: {{profile.id}}
- Working directory: {{profile.context.working_directory}}
- Active repos: {{profile.context.repos | join(', ', attribute='url')}}

## Your Constraints
- Never commit directly to protected branches: {{profile.permissions.git.protected_branches | join(', ')}}
- Always create a feature branch named `agent/{{card.id}}/{{card.slug}}`
- Always run tests before committing: `pytest`
- Report sub-task progress by updating checklist items on the card

## Your Output Protocol
1. Post a `claimed-by: {{profile.name}}` comment immediately
2. Check off each checklist item as you complete it
3. Post final result as a comment with format: `## Result\n<output>`
4. If blocked, post `## Blocked\n<reason>` and stop — do not guess
5. On error, post `## Error\n<traceback>` — do not retry silently
```

### 8.5 Using Claude API Extended Features

```python
# Prompt caching — cache system prompt + static card context across retries
response = client.messages.create(
    model="claude-sonnet-4-6",
    system=[{
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"}   # cache for up to 5 min
    }],
    ...
)

# Extended thinking — for architecture or planning agents
response = client.messages.create(
    model="claude-opus-4-6",
    thinking={"type": "enabled", "budget_tokens": 10000},
    ...
)

# Vision — for cards with image attachments
messages = [{
    "role": "user",
    "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
        {"type": "text", "text": card.desc}
    ]
}]
```

### 8.6 Claude Code as Orchestrator (Claude Code SDK)

For complex multi-step agent tasks, use the Claude Code SDK (Anthropic Managed Agents) to spawn sub-agents:

```python
from anthropic import Anthropic

client = Anthropic()

# Create a session that persists across multiple turns
session = client.beta.sessions.create(
    model="claude-sonnet-4-6",
    system=system_prompt,
    tools=tool_definitions,
)

# Resume session for long-running tasks (e.g., checklist with 10 steps)
for checklist_item in card.checklists[0].items:
    response = client.beta.sessions.messages.create(
        session_id=session.id,
        messages=[{"role": "user", "content": f"Complete: {checklist_item.name}"}],
    )
    trello.check_item(card.id, checklist_item.id)
```

---

## 9. Kanban Provider Interface

The orchestrator treats the Kanban board as a pluggable backend. All orchestrator and agent code talks to a `KanbanProvider` abstract interface — never directly to the Trello or Jira REST API. Swapping providers requires only a config change and a new adapter.

### 9.1 Abstract Interface

```python
# kanban/interface.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class KanbanCard:
    id: str
    title: str
    description: str
    labels: list[str]
    assignees: list[str]
    checklists: list["KanbanChecklist"]
    attachments: list["KanbanAttachment"]
    custom_fields: dict[str, str]
    column: str
    due_date: Optional[str]
    url: str
    raw: dict                      # provider-native object for advanced use

@dataclass
class KanbanChecklist:
    id: str
    name: str
    items: list["KanbanChecklistItem"]

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

@dataclass
class KanbanColumn:
    id: str
    name: str

class KanbanProvider(ABC):
    """Implemented once per Kanban backend. All orchestrator code depends only on this."""

    # ── Board / Column ───────────────────────────────────────────────────────
    @abstractmethod
    def get_columns(self, board_id: str) -> list[KanbanColumn]: ...

    @abstractmethod
    def get_column_by_name(self, board_id: str, name: str) -> KanbanColumn: ...

    # ── Cards ────────────────────────────────────────────────────────────────
    @abstractmethod
    def get_cards(self, board_id: str, column: str,
                  label: Optional[str] = None) -> list[KanbanCard]: ...

    @abstractmethod
    def get_card(self, card_id: str) -> KanbanCard: ...

    @abstractmethod
    def move_card(self, card_id: str, column: str) -> None: ...

    @abstractmethod
    def assign_card(self, card_id: str, agent_id: str) -> None: ...

    # ── Comments ─────────────────────────────────────────────────────────────
    @abstractmethod
    def add_comment(self, card_id: str, text: str) -> None: ...

    @abstractmethod
    def get_comments(self, card_id: str) -> list[str]: ...

    # ── Checklists ───────────────────────────────────────────────────────────
    @abstractmethod
    def check_item(self, card_id: str, item_id: str, checked: bool = True) -> None: ...

    # ── Attachments ──────────────────────────────────────────────────────────
    @abstractmethod
    def get_attachments(self, card_id: str) -> list[KanbanAttachment]: ...

    @abstractmethod
    def add_attachment(self, card_id: str, name: str,
                       content: bytes, mime_type: str) -> None: ...

    # ── Labels ───────────────────────────────────────────────────────────────
    @abstractmethod
    def add_label(self, card_id: str, label: str) -> None: ...

    @abstractmethod
    def remove_label(self, card_id: str, label: str) -> None: ...

    # ── Custom Fields ────────────────────────────────────────────────────────
    @abstractmethod
    def get_custom_fields(self, card_id: str) -> dict[str, str]: ...

    @abstractmethod
    def set_custom_field(self, card_id: str, field_name: str, value: str) -> None: ...

    # ── Webhooks ─────────────────────────────────────────────────────────────
    @abstractmethod
    def register_webhook(self, board_id: str, callback_url: str) -> str: ...

    @abstractmethod
    def delete_webhook(self, webhook_id: str) -> None: ...
```

### 9.2 Trello Adapter

```python
# kanban/adapters/trello.py
import requests
from kanban.interface import KanbanProvider, KanbanCard, KanbanColumn

class TrelloProvider(KanbanProvider):
    BASE = "https://api.trello.com/1"

    def __init__(self, api_key: str, token: str):
        self._auth = {"key": api_key, "token": token}

    def get_cards(self, board_id: str, column: str,
                  label: str | None = None) -> list[KanbanCard]:
        col = self.get_column_by_name(board_id, column)
        r = requests.get(f"{self.BASE}/lists/{col.id}/cards",
                         params={**self._auth, "customFieldItems": "true",
                                 "attachments": "true", "checklists": "all"})
        r.raise_for_status()
        cards = [self._map(c) for c in r.json()]
        if label:
            cards = [c for c in cards if label in c.labels]
        return cards

    def move_card(self, card_id: str, column: str) -> None:
        # resolve column name → id from cached board state
        col_id = self._resolve_column_id(column)
        requests.put(f"{self.BASE}/cards/{card_id}",
                     params={**self._auth, "idList": col_id}).raise_for_status()

    def add_comment(self, card_id: str, text: str) -> None:
        requests.post(f"{self.BASE}/cards/{card_id}/actions/comments",
                      params={**self._auth, "text": text}).raise_for_status()

    def check_item(self, card_id: str, item_id: str, checked: bool = True) -> None:
        state = "complete" if checked else "incomplete"
        requests.put(f"{self.BASE}/cards/{card_id}/checkItem/{item_id}",
                     params={**self._auth, "state": state}).raise_for_status()

    def register_webhook(self, board_id: str, callback_url: str) -> str:
        r = requests.post(f"{self.BASE}/webhooks",
                          params={**self._auth,
                                  "callbackURL": callback_url,
                                  "idModel": board_id})
        r.raise_for_status()
        return r.json()["id"]

    def _map(self, raw: dict) -> KanbanCard:
        return KanbanCard(
            id=raw["id"], title=raw["name"], description=raw.get("desc", ""),
            labels=[lb["name"] for lb in raw.get("labels", [])],
            assignees=[m for m in raw.get("idMembers", [])],
            checklists=self._map_checklists(raw.get("checklists", [])),
            attachments=self._map_attachments(raw.get("attachments", [])),
            custom_fields={f["idCustomField"]: f.get("value", {}).get("text", "")
                           for f in raw.get("customFieldItems", [])},
            column=raw.get("idList", ""),
            due_date=raw.get("due"),
            url=raw.get("shortUrl", ""),
            raw=raw,
        )
```

### 9.3 Jira Adapter

```python
# kanban/adapters/jira.py
from jira import JIRA
from kanban.interface import KanbanProvider, KanbanCard, KanbanColumn, KanbanAttachment

class JiraProvider(KanbanProvider):
    """
    Maps Jira concepts to the KanbanProvider interface:
      Board     → Jira Board (Scrum or Kanban)
      Column    → Jira Board Column / Sprint Status
      Card      → Jira Issue
      Label     → Jira Label or Issue Type
      Checklist → Jira Subtasks or Checklist field (Jira Cloud + plugin)
      Comment   → Jira Comment
      Attachment→ Jira Attachment
      Custom Field → Jira Custom Field
      Assignee  → Jira Assignee
    """

    def __init__(self, server: str, email: str, api_token: str):
        self._j = JIRA(server=server, basic_auth=(email, api_token))

    def get_columns(self, board_id: str) -> list[KanbanColumn]:
        statuses = self._j.board_statuses(board_id)
        return [KanbanColumn(id=s["id"], name=s["name"]) for s in statuses]

    def get_cards(self, board_id: str, column: str,
                  label: str | None = None) -> list[KanbanCard]:
        jql = f'status = "{column}"'
        if label:
            jql += f' AND labels = "{label}"'
        issues = self._j.search_issues(jql, maxResults=50, fields="*all")
        return [self._map(i) for i in issues]

    def move_card(self, card_id: str, column: str) -> None:
        transitions = self._j.transitions(card_id)
        target = next((t for t in transitions if t["name"] == column), None)
        if not target:
            raise ValueError(f"No Jira transition named '{column}' for issue {card_id}")
        self._j.transition_issue(card_id, target["id"])

    def add_comment(self, card_id: str, text: str) -> None:
        self._j.add_comment(card_id, text)

    def check_item(self, card_id: str, item_id: str, checked: bool = True) -> None:
        # Jira subtask: transition to Done / To Do
        status = "Done" if checked else "To Do"
        self.move_card(item_id, status)

    def get_custom_fields(self, card_id: str) -> dict[str, str]:
        issue = self._j.issue(card_id)
        raw = issue.raw["fields"]
        return {k: str(v) for k, v in raw.items()
                if k.startswith("customfield_") and v is not None}

    def register_webhook(self, board_id: str, callback_url: str) -> str:
        # Jira Data Center: REST webhook
        wh = self._j.create_webhook(
            name=f"kanban-agent-{board_id}",
            url=callback_url,
            events=["jira:issue_created", "jira:issue_updated"],
            filters={"issue-related-events-section": f"project = {board_id}"},
        )
        return str(wh.id)

    def _map(self, issue) -> KanbanCard:
        f = issue.fields
        return KanbanCard(
            id=issue.key,
            title=f.summary,
            description=f.description or "",
            labels=list(f.labels),
            assignees=[f.assignee.name] if f.assignee else [],
            checklists=self._map_subtasks(f.subtasks),
            attachments=[self._map_attachment(a) for a in f.attachment],
            custom_fields=self.get_custom_fields(issue.key),
            column=f.status.name,
            due_date=getattr(f, "duedate", None),
            url=issue.permalink(),
            raw=issue.raw,
        )
```

### 9.4 Provider Factory

```python
# kanban/factory.py
from kanban.interface import KanbanProvider
from kanban.adapters.trello import TrelloProvider
from kanban.adapters.jira import JiraProvider

PROVIDERS: dict[str, type[KanbanProvider]] = {
    "trello": TrelloProvider,
    "jira":   JiraProvider,
    # future: "linear": LinearProvider, "github": GitHubProjectsProvider
}

def create_provider(config: dict) -> KanbanProvider:
    kind = config["provider"]
    cls  = PROVIDERS[kind]
    return cls(**{k: v for k, v in config.items() if k != "provider"})
```

### 9.5 Provider Configuration

```yaml
# config/kanban.yaml
active_provider: trello    # switch to "jira" for software development boards

providers:
  trello:
    provider: trello
    api_key: "${TRELLO_API_KEY}"
    token:   "${TRELLO_TOKEN}"
    boards:
      default:     "harqis-work-board-id"
      software_dev: "harqis-dev-board-id"

  jira:
    provider: jira
    server:    "https://jira.yourcompany.com"
    email:     "${JIRA_EMAIL}"
    api_token: "${JIRA_API_TOKEN}"
    boards:
      default:     "HARQ"     # Jira project key
      software_dev: "DEV"

# Column name mapping — normalize provider-specific names to canonical names
column_map:
  trello:
    Backlog:     "Backlog"
    Pending:     "Pending"
    "In Progress": "In Progress"
    Blocked:     "Blocked"
    Done:        "Done"
    Failed:      "Failed"
  jira:
    Backlog:     "Backlog"
    Pending:     "In Review"       # closest Jira default
    "In Progress": "In Progress"
    Blocked:     "Blocked"
    Done:        "Done"
    Failed:      "Rejected"
```

### 9.6 Label Convention Across Providers

| Canonical Label | Trello | Jira |
|---|---|---|
| `agent:code` | Card label named `agent:code` | Issue label `agent:code` OR issue type `Agent Task` + label |
| `agent:test` | Card label `agent:test` | Label `agent:test` |
| `hw:n100-1` | Card label `hw:n100-1` | Custom field `Agent Node = n100-1` |
| `priority:critical` | Red card label | Jira priority `Blocker` |

The Jira adapter normalises these during `_map()` so the orchestrator always receives canonical `KanbanCard` objects regardless of backend.

### 9.7 Extending to Other Providers

To add a new Kanban backend (e.g. Linear, GitHub Projects, Asana):

1. Create `kanban/adapters/<name>.py` implementing `KanbanProvider`
2. Add it to `PROVIDERS` in `kanban/factory.py`
3. Add a `column_map` entry in `config/kanban.yaml`
4. Optionally add a pack that targets the new board convention

No orchestrator, agent, or profile code needs to change.

---

## 10. Orchestration Architecture


### 10.1 Orchestrator Process (Mac Mini)

```python
# orchestrator/main.py
class KanbanOrchestrator:
    def __init__(self):
        self.trello   = TrelloClient()
        self.registry = ProfileRegistry.from_dir("profiles/")
        self.celery   = CeleryDispatcher(broker=REDIS_URL)
        self.vault    = VaultClient()

    def poll_board(self, board_id: str):
        backlog_cards = self.trello.get_cards(list="Backlog", board=board_id)
        for card in backlog_cards:
            profile = self.registry.resolve_for_card(card)
            if not profile:
                continue   # no matching agent; leave card in Backlog
            secrets  = self.vault.read(profile.permissions.secrets.vault_path)
            self.trello.move_card(card.id, "Pending")
            self.trello.add_comment(card.id, f"claimed-by: {profile.name}")
            self.celery.dispatch(
                queue=profile.hardware.queue,
                task="run_agent",
                args={"profile": profile.id, "card_id": card.id, "secrets": secrets},
                node_affinity=profile.hardware.node_affinity,
            )

    def run(self):
        scheduler = APScheduler()
        scheduler.add_job(self.poll_board, "interval", seconds=30, args=[BOARD_ID])
        scheduler.start()
```

### 10.2 Worker Task (N100 Node)

```python
# workers/tasks.py
@SPROUT.task(bind=True, queue="code")
def run_agent(self, profile_id: str, card_id: str, secrets: dict):
    profile = ProfileRegistry.load(profile_id)
    card    = TrelloClient(secrets).get_card(card_id)
    agent   = AgentFactory.create(profile, card, secrets)

    trello.move_card(card_id, "In Progress")
    try:
        result = agent.run()
        trello.add_comment(card_id, f"## Result\n{result}")
        destination = "Done" if profile.lifecycle.auto_approve else "Done"
        trello.move_card(card_id, destination)
    except AgentTimeout:
        trello.add_comment(card_id, "## Timeout\nAgent exceeded time limit.")
        trello.move_card(card_id, "Failed")
    except PermissionDenied as e:
        trello.add_comment(card_id, f"## Permission Denied\n{e}")
        trello.move_card(card_id, "Failed")
    except Exception as e:
        trello.add_comment(card_id, f"## Error\n```\n{traceback.format_exc()}\n```")
        trello.move_card(card_id, "Failed")
        if profile.lifecycle.max_retries > self.request.retries:
            raise self.retry(countdown=profile.lifecycle.retry_delay_seconds)
```

### 10.3 Webhook Listener (Production Mode)

```python
# orchestrator/webhook.py  (FastAPI)
@app.post("/trello/webhook")
async def trello_webhook(event: TrelloWebhookEvent):
    if event.action.type == "createCard" and event.action.data.list.name == "Backlog":
        await orchestrator.handle_new_card(event.action.data.card)
    elif event.action.type == "updateCard" and event.action.data.list.name == "In Progress":
        # card moved back to In Progress by human (unblocked)
        await orchestrator.resume_card(event.action.data.card)
```

---

## 11. Reusability Framework — Domain Packs

A **domain pack** is a collection of:
- One Trello board configuration
- A set of agent profiles (YAML files)
- A set of system prompts (`prompts/system/`)
- A `pack.yaml` manifest

Packs can be cloned, customised, and activated without touching orchestrator code.

### 11.1 Pack Manifest

```yaml
# packs/software-dev/pack.yaml
id: software-dev
name: "Software Development Pack"
description: "Code, review, test, and CI agents for a software project"
board_template: templates/board_software_dev.json   # Trello board template export
profiles:
  - profiles/agent_code.yaml
  - profiles/agent_test.yaml
  - profiles/agent_review.yaml
  - profiles/agent_ci.yaml
prompts_dir: prompts/system/
variables:
  repo_url:    ""    # override at activation time
  branch:      "main"
  test_cmd:    "pytest"
  notify_channel: ""
```

### 11.2 Available Domain Packs

| Pack ID | Use Case | Key Agent Types |
|---|---|---|
| `software-dev` | Feature development, refactoring | `agent:code`, `agent:test`, `agent:review`, `agent:ci` |
| `qa-testing` | Test generation, regression, perf | `agent:test:unit`, `agent:test:e2e`, `agent:test:perf` |
| `personal-productivity` | Calendar, writing, research, email | `agent:schedule`, `agent:write`, `agent:research` |
| `content-creation` | Blog, social, LinkedIn, video scripts | `agent:write:blog`, `agent:write:social`, `agent:read` |
| `finance-personal` | Budgets, trades, portfolio review | `agent:finance`, `agent:data`, `agent:research:stock` |
| `harqis-work` | This repo — all automation workflows | All types |

### 11.3 Activating a Pack

```bash
# CLI to activate a pack against a Trello board
python -m orchestrator.cli pack activate \
  --pack software-dev \
  --board-id <trello_board_id> \
  --var repo_url=https://github.com/org/repo \
  --var test_cmd="pytest apps/" \
  --var notify_channel=#dev-alerts
```

### 11.4 Card Template per Pack

Each pack ships Trello card templates (via Butler automations or manual copy) so humans can create well-formed cards quickly:

```
[software-dev] Feature Card Template
─────────────────────────────────────
Title:   Implement <feature name>

Label:   agent:code

Custom Fields:
  repo_url:     https://github.com/org/repo
  branch:       feature/xxx
  environment:  dev

Description:
  ## Goal
  <what to build>

  ## Acceptance Criteria
  - [ ] Unit tests pass
  - [ ] No regressions in existing tests
  - [ ] PR opened against main

Checklist: Implementation Steps
  [ ] Read existing code
  [ ] Write implementation
  [ ] Write tests
  [ ] Run pytest
  [ ] Open PR
```

---

## 12. Trigger Strategy

| Approach | Latency | Complexity | When to Use |
|---|---|---|---|
| **Polling** (cron every 30s) | ~30s | Low | Dev/local, no public URL |
| **Trello Webhook** | <1s | Medium | Production, event-driven |
| **Hybrid** | <1s + fallback | Medium | Recommended; webhook primary, poll as catch-all |
| **Manual CLI trigger** | Instant | None | One-off tasks or debugging |

**Webhook registration:**
```bash
curl -X POST "https://api.trello.com/1/webhooks" \
  -d "callbackURL=https://orchestrator.local/trello/webhook" \
  -d "idModel=<board_id>" \
  -d "key=${TRELLO_API_KEY}" \
  -d "token=${TRELLO_TOKEN}"
```

---

## 13. Challenges, Risks, and Milestones

### 13.1 Technical Challenges

| Challenge | Detail | Mitigation |
|---|---|---|
| **Race conditions** | Two agent instances claiming the same card simultaneously | Atomic "Pending" column move + `claimed-by` comment written before any work |
| **Context window limits** | Large repos + card context exceeding model limits | Chunked file reads; RAG over repo (embedding search before passing to agent) |
| **Secret leakage** | Agent posts secret value in card comment | Post-processing filter on all comment writes; deny `echo $SECRET` in bash tool |
| **Node failure** | N100 node goes down mid-task | Celery task ack only after success; heartbeat moves orphaned "In Progress" cards back to Pending for re-dispatch |
| **Runaway agents** | Agent loops indefinitely or burns tokens | Hard `timeout_minutes` in profile enforced by Celery task `soft_time_limit` |
| **Permission bypass** | Agent uses bash to access denied paths | Sandbox with Docker + read-only bind mounts; deny shell wildcards that escape allowed paths |
| **Profile drift** | Profile changes invalidate running tasks | Profiles are immutable once injected; version field in profile; apply changes only to new tasks |
| **Trello API rate limits** | High-frequency polling hits 300 req/10s limit | Exponential backoff; cache board state; prefer webhooks |

### 13.2 Risks

| Risk | Severity | Likelihood | Response |
|---|---|---|---|
| Agent commits broken code to production branch | Critical | Low | Protected branch rules + `require_pr: true` in profile |
| Anthropic API outage | High | Low | Graceful degradation: move cards to Blocked, retry when API resumes |
| Secret exposed via card comment | High | Medium | Output sanitization wrapper; audit log of all comments posted |
| N100 node compromised | High | Low | Network egress allow-list per node; agents run in Docker with no host network |
| Trello loses card data | Medium | Very Low | Periodic board export to Git; critical outputs also saved as repo commits |
| Token cost overrun | Medium | Medium | Per-profile `max_tokens` cap; monthly budget alert via YNAB/cost tracking |
| Agent misunderstands card and does wrong work | Medium | High | Clear card templates; checklist confirmation before destructive actions; Done gate |

### 13.3 Milestones

#### Phase 1 — Foundation (Weeks 1–2)
- [ ] Orchestrator running on Mac Mini (polling mode)
- [ ] Single agent profile working end-to-end (`agent:code:harqis`)
- [ ] Card anatomy defined; custom fields created on `harqis-work` board
- [ ] Secrets vault operational (SOPS or Vault)
- [ ] `Pending → In Progress → Done → Done` flow working
- [ ] Error handling: Failed column, error comment

#### Phase 2 — Multi-Agent and Hardware (Weeks 3–4)
- [ ] N100-1 running as Celery worker with `code` queue
- [ ] N100-2 running with `test` queue
- [ ] Profile registry with inheritance (`extends`)
- [ ] Permission enforcer wrapping all tool calls
- [ ] `hw:` label routing to specific nodes
- [ ] At least 4 agent types operational

#### Phase 3 — Card Context Richness (Weeks 5–6)
- [ ] Attachment fetching and injection into agent context
- [ ] Checklist sub-task protocol (check-off as work progresses)
- [ ] Custom fields parsed as typed agent parameters
- [ ] Blocked column flow (agent stops, human unblocks, agent resumes)
- [ ] Vision support for image attachments

#### Phase 4 — Domain Packs and Reusability (Weeks 7–8)
- [ ] `software-dev` pack complete and documented
- [ ] `qa-testing` pack complete
- [ ] `personal-productivity` pack complete
- [ ] Pack CLI (`pack activate`, `pack list`, `pack deactivate`)
- [ ] Card templates per pack published to Trello Butler

#### Phase 5 — Production Hardening (Weeks 9–10)
- [ ] Webhook mode replacing polling as primary trigger
- [ ] Docker sandbox per agent (no host network)
- [ ] Cost monitoring per agent type (token usage logged to Elasticsearch)
- [ ] Node health monitoring + auto-reassignment on node failure
- [ ] Audit log: every tool call, permission check, and comment posted
- [ ] Load testing: 20 concurrent agent tasks across 3 N100 nodes

#### Phase 6 — Intelligence Layer (Weeks 11–12)
- [ ] Extended thinking enabled for `agent:review` and `agent:research`
- [ ] Prompt caching on system prompts (reduce latency + cost)
- [ ] Managed sessions for multi-turn checklist execution
- [ ] Agent-to-agent handoff: code agent opens PR, review agent auto-picks it up
- [ ] Retrospective agent: weekly summary of Done cards posted to Discord

---

## 14. Tips and Best Practices

**Card hygiene**
- One agent label per card. If a task needs two agents, split it into two cards linked via description.
- Write descriptions as if briefing a capable-but-new team member — include context, not just instructions.
- Use checklists for tasks with more than 3 steps; agents can show progress granularly.

**Race condition prevention**
- The orchestrator moves a card to **Pending** in a single atomic API call before dispatching to any worker. Workers never poll Backlog directly.
- Add a `claimed-by: <agent-id>` comment immediately after claiming. If a card is in Pending for >5 minutes with no In Progress transition, the orchestrator reclaims it.

**Outputs**
- Post large outputs (files, CSVs, generated code) as **card attachments**, not comment text. Comments are for summaries.
- For code changes, the PR URL is the output. The agent posts the PR link as a comment and attaches the diff.

**Security**
- Never allow agents to read their own profile secrets file. Secrets are injected as environment variables and the file path is not in the allowed filesystem scope.
- Rotate `ANTHROPIC_API_KEY` per agent profile so a compromised agent can be revoked without affecting others.
- Enable Trello's audit log. Done it weekly for unexpected card moves or comments.

**Cost control**
- Use `claude-haiku-4-5` for high-volume, simple routing decisions (e.g., labelling cards, summarising short texts).
- Use `claude-sonnet-4-6` for the majority of work tasks.
- Reserve `claude-opus-4-6` for planning, architecture review, and extended-thinking tasks.
- Log input/output tokens per task to Elasticsearch; alert when a single task exceeds a threshold.

**Extending the system**
- New agent type: add a YAML profile + system prompt. No orchestrator code changes needed.
- New domain: create a pack manifest + board template. Clone and activate in minutes.
- New hardware: add the node to Celery broker, define its queues, add `node_affinity` entries in relevant profiles.
