# agents/kanban — Trello/Jira Agent Kanban POC

A self-contained, provider-agnostic Kanban-to-AI-agent pipeline.
Create a card → an agent claims it, runs Claude, posts the result back.

**No Celery. No Redis. No Docker required for local development.**
Your dev machine runs as both orchestrator and worker.

---

## Quick Start (Local Dev)

### 1. Install dependencies

```bash
pip install anthropic pyyaml requests
# or add to your requirements:
# anthropic>=0.40.0
# pyyaml>=6.0
# requests>=2.31.0
```

### 2. Set up environment variables

Create `.env/agents.env` (or add to existing `.env/apps.env`):

```bash
# Kanban provider
KANBAN_PROVIDER=trello        # or "jira"
KANBAN_BOARD_ID=<your_trello_board_id>

# Claude
ANTHROPIC_API_KEY=sk-ant-...

# Trello credentials (already in apps.env if using harqis-work)
TRELLO_API_KEY=...
TRELLO_API_TOKEN=...

# Optional
KANBAN_POLL_INTERVAL=60       # seconds between board polls (default: 60)
KANBAN_PROFILES_DIR=          # path to custom profiles dir (default: bundled examples)
KANBAN_DRY_RUN=0              # set to 1 to poll without running agents
```

### 3. Create your Trello board

Create a Trello board with these lists (exact names):

| List Name     | Purpose                                     |
|---------------|---------------------------------------------|
| `Draft`       | Sandbox to write and organize tasks to send |
| `Backlog`     | New tasks — orchestrator picks from here    |
| `Pending`     | Agent claimed the card                      |
| `In Progress` | Agent actively working                      |
| `Blocked`     | Hard-stop dependency — auto re-queued when resolved |
| `Done`        | Agent done — awaiting maintainer review     |
| `Failed`      | Agent encountered an unrecoverable error    |

**Get your board ID:** Open any card on the board, copy its URL
(`https://trello.com/c/<card_id>`), then call:
```
GET https://api.trello.com/1/cards/<card_id>?key=KEY&token=TOKEN
→ look for "idBoard"
```
Or from the board URL: `https://trello.com/b/<board_id>/...`

### 4. Create a test card

1. Create a card in **Backlog**
2. Add the label `agent:write` or `agent:code` to it
3. Write your task in the card description

Example card:
```
Title: Summarise this repo
Label: agent:write
Description: Read the CLAUDE.md file in this directory and write a one-paragraph summary of what harqis-work does. Post the summary as a comment.
```

### 5. Start the orchestrator

```bash
# From the repo root
python -m agents.kanban.orchestrator.local

# With options
python -m agents.kanban.orchestrator.local --poll-interval 15 --dry-run
```

The orchestrator will:
1. Poll the Backlog every 30 seconds
2. Find cards with `agent:write` or `agent:code` labels
3. Claim them (move to Pending → In Progress)
4. Run the Claude agent
5. Post the result as a comment
6. Move to Done (or Done if `auto_approve: true` in the profile)

---

## Running Tests

```bash
# Unit tests only (no API calls)
pytest agents/kanban/tests/ -m "smoke"

# All unit tests
pytest agents/kanban/tests/

# Integration tests (requires real credentials in env)
pytest agents/kanban/tests/ -m "integration"

# Verbose with output
pytest agents/kanban/tests/ -v -s
```

---

## Directory Structure

```
agents/kanban/
├── interface.py              # KanbanProvider ABC + dataclasses (KanbanCard, etc.)
├── factory.py                # create_provider(config) — builds Trello or Jira adapter
│
├── adapters/
│   ├── trello.py             # TrelloProvider — Trello REST API v1
│   └── jira.py               # JiraProvider — Jira REST API v2/v3
│
├── dependencies/
│   ├── __init__.py
│   └── detector.py           # DependencyDetector — identifies blocking / soft deps from card
│
├── profiles/
│   ├── schema.py             # AgentProfile dataclass + YAML loader
│   ├── registry.py           # ProfileRegistry — loads and resolves profiles
│   └── examples/
│       ├── base.yaml         # Base profile (inherited by others)
│       ├── agent_code.yaml   # Code agent — bash, read/write files, git
│       ├── agent_write.yaml  # Write agent — read/write files, research
│       └── agent_full.yaml   # Full agent — deps, git tools, PR creation, claude[bot] author
│
├── permissions/
│   └── enforcer.py           # PermissionEnforcer — checks tools, FS, network, git
│
├── agent/
│   ├── context.py            # AgentContext — builds prompt from card data + repo snapshot
│   ├── base.py               # BaseKanbanAgent — Claude tool-use loop
│   └── tools/
│       ├── registry.py       # ToolRegistry — maps tool names to callables + Claude defs
│       ├── filesystem.py     # ReadFileTool, WriteFileTool, GlobTool, GrepTool, BashTool
│       ├── git_tools.py      # GitStatusTool, GitCreateBranchTool, GitCommitTool, GitPushTool, GitCreatePRTool
│       └── kanban_tools.py   # TrelloCommentTool, TrelloMoveTool, ChecklistTool
│
├── orchestrator/
│   ├── local.py              # LocalOrchestrator — single-process polling loop + CLI
│   └── blocked_handler.py    # BlockedCardHandler — re-queues cards when deps are resolved
│
└── tests/
    ├── conftest.py            # Shared fixtures (cards, profiles)
    ├── test_interface.py      # KanbanCard + AgentContext
    ├── test_trello_adapter.py # TrelloProvider (mocked HTTP)
    ├── test_profiles.py       # Profile loading + registry
    ├── test_permissions.py    # PermissionEnforcer
    ├── test_agent.py          # BaseKanbanAgent (mocked Claude)
    ├── test_orchestrator.py   # LocalOrchestrator (mocked provider + agent)
    ├── test_git_tools.py      # Git tools (mocked subprocess)
    ├── test_dependencies.py   # DependencyDetector
    └── test_blocked_handler.py # BlockedCardHandler
```

---

---

## New Features

### Dependency Detection & BLOCKED State

Before the agent runs, the orchestrator scans the card for hard-stop dependencies:

| Signal | How it's detected |
|---|---|
| `required_secrets` custom field | Explicit list of env var names that must be set |
| Service name in description | e.g. "OANDA" → checks `OANDA_ACCESS_TOKEN` |
| "new workflow" in description | Soft dep — agent scaffolds from template |
| "new app" in description | Soft dep — agent scaffolds from template |

If **blocking** dependencies are unmet, the orchestrator:
1. Posts a comment on the card listing what's needed
2. Moves the card to **Blocked**

The orchestrator then polls the Blocked column on a separate interval (default 300 s). When all required env vars are present, the card is automatically moved back to Backlog for retry.

**Maintainer workflow for a blocked card:**
1. Card arrives in Blocked with a comment describing the missing secret
2. Maintainer adds the secret to `.env/agents.env` and restarts the orchestrator
3. On the next blocked-column poll, the card is re-queued automatically

To declare explicit blocking deps on a card, add a custom field:

```
required_secrets = SPOTIFY_CLIENT_ID,SPOTIFY_CLIENT_SECRET
```

---

### Git Tools & Pull Request Creation

All agents now have access to five git tools (controlled by the profile's `tools.allowed` list):

| Tool | Purpose |
|---|---|
| `git_status` | Show working tree status |
| `git_create_branch` | Create `agent/<card_id>/<slug>` branch |
| `git_commit` | Stage + commit attributed to `claude[bot]` |
| `git_push` | Push branch to origin (requires `git.can_push: true`) |
| `git_create_pr` | Open a GitHub PR via `gh pr create` |

All commits are attributed to the `claude[bot]` GitHub contributor:

```
Author: claude[bot] <claude[bot]@users.noreply.github.com>
```

Override the author in a profile's `permissions.git` section:

```yaml
permissions:
  git:
    can_push: true
    author_name: "my-bot[bot]"
    author_email: "my-bot[bot]@users.noreply.github.com"
```

The `agent:full` profile enables the complete git workflow end-to-end.

---

### Repository Context Injection

When a profile sets `context.working_directory`, the agent's initial prompt automatically includes:

- **CLAUDE.md** contents (if present, first 3000 chars)
- **Existing MCP apps** (names from `apps/` directory)
- **Existing workflows** (names from `workflows/` directory)

This lets the agent reuse existing integrations rather than rebuilding them.

---

## Agent Profiles

Profiles are YAML files that define an agent's identity, model, tools, and permissions.

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
  auto_approve: false
  timeout_minutes: 15
```

Save it anywhere and point `KANBAN_PROFILES_DIR` at the directory.

### Profile inheritance

```yaml
id: agent:code:myproject
name: "MyProject Code Agent"
extends: agent:code          # inherits model, tools, permissions from agent:code
context:
  working_directory: /workspace/myproject
  repos:
    - url: https://github.com/me/myproject
      local_path: /workspace/myproject
      branch_policy: feature-branch-only
```

### Matching profiles to cards

| Priority | How it works |
|---|---|
| 1 | Card assignee name matches profile `id` |
| 2 | Card label exactly matches profile `id` |
| 3 | Label prefix match (e.g. label `agent:code` matches profile `agent:code:myproject`) |

---

## Specialized Agents & System Prompt Architecture

### How prompts are layered

Every agent run composes three independent layers:

| Layer | Source | Controls |
|---|---|---|
| **System prompt** | YAML profile (`model.system_prompt` or `model.system_prompt_file`) | Who the agent is — persona, constraints, output rules |
| **Task prompt** | Trello card (description, checklists, custom fields, attachments) | What to do on this specific card |
| **Tool scope** | Profile `tools.allowed` + `tools.mcp_apps` | What the agent can touch — files, APIs, MCP services |

The card carries the **task**. The profile carries the **persona**. You never repeat the persona on every card — putting the `agent:write:article` label on a card is enough to load the right identity.

---

### Building a specialized agent

To add a new agent type (e.g. article writer, calculator, transcriber):

1. Create a YAML profile in `agents/kanban/profiles/examples/`:

```yaml
# profiles/examples/agent_write_article.yaml
extends: base
id: agent:write:article
name: "Article Writing Agent"
model:
  model_id: claude-sonnet-4-6
  max_tokens: 8192
  system_prompt: |
    You are a professional article writing agent. Given a topic and brief,
    you research, outline, draft, and refine long-form written content.
    Write in clear, engaging prose. Always confirm target audience, tone,
    and desired length if not specified in the card.
tools:
  allowed: [read_file, write_file, web_search, post_comment, move_card, check_item]
  mcp_apps: [google_apps, discord, telegram]
hardware:
  queue: write
```

```yaml
# profiles/examples/agent_calculate.yaml
extends: base
id: agent:calculate
name: "Calculation Agent"
model:
  model_id: claude-sonnet-4-6
  max_tokens: 4096
  system_prompt: |
    You are a numerical analysis and calculation agent. Perform financial
    calculations, data transformations, statistical analysis, and formula
    evaluation. Show working step-by-step. Return results in the format
    specified by the card's output_format custom field.
tools:
  allowed: [bash, read_file, write_file, post_comment, move_card, check_item]
  mcp_apps: [oanda, ynab, google_apps]
hardware:
  queue: data
```

```yaml
# profiles/examples/agent_transcribe.yaml
extends: base
id: agent:transcribe
name: "Transcription Agent"
model:
  model_id: claude-sonnet-4-6
  max_tokens: 8192
  system_prompt: |
    You are an information transcription and structuring agent. Extract,
    clean, and reformat information from attachments, images, PDFs, or
    raw text into structured output. Preserve accuracy over brevity.
    Flag anything ambiguous rather than guessing.
tools:
  allowed: [read_file, write_file, post_comment, move_card, check_item]
  mcp_apps: [google_apps]
hardware:
  queue: default
```

2. On Trello, label a card `agent:write:article` (or `agent:calculate`, `agent:transcribe`). The orchestrator resolves label → profile → system prompt automatically. No other changes needed.

---

### Card-level system prompt additions

For one-off prompt instructions without changing the profile, add a `system_prompt_addon` custom field to the card. The agent appends it to the base system prompt at runtime:

```
Card custom field: system_prompt_addon = "Write in Spanish. Use formal register."
```

This is handled in `agents/kanban/agent/base.py` in `_system_prompt()`. The split is:

| Where | What you put there |
|---|---|
| Profile `system_prompt` | Permanent persona — who the agent is for all tasks of this type |
| Card description | The task — topic, source material, parameters |
| Card custom field `system_prompt_addon` | One-off overrides for this card only |
| Card checklists | Sub-steps the agent checks off as it works |
| Card attachments | Source files, reference docs, images |

---

### MCP tool scope per agent

Worker agents access the harqis-work MCP server running on the orchestrator node. Each profile scopes which MCP apps it needs via `tools.mcp_apps` — workers never get access beyond what the profile declares.

Recommended scope by agent type:

| Agent | MCP apps |
|---|---|
| `agent:write:article` | `google_apps` (Drive/Gmail for research), `discord`, `telegram` |
| `agent:calculate` | `oanda` (forex data), `ynab` (budget data), `google_apps` (Sheets) |
| `agent:transcribe` | `google_apps` (Drive source files) |
| `agent:code` | `trello`, `jira`, `discord` (notifications) |
| `agent:finance` | `oanda`, `ynab`, `google_apps` |

Workers call the MCP server over stdio or HTTP/SSE — they do not run their own instance.

---

### OpenClaw integration

OpenClaw provides persistent identity and long-term memory from the `harqis-openclaw-sync` repo. There are two integration points:

**1. Identity injection at task startup (recommended)**

The orchestrator reads the OpenClaw workspace files before creating the agent and prepends them to the system prompt. Add the following to `agents/kanban/orchestrator/local.py`:

```python
from datetime import date
from pathlib import Path

def _load_openclaw_context() -> str:
    sync_root = Path(os.environ.get("OPENCLAW_SYNC_PATH", ""))
    workspace = sync_root / ".openclaw" / "workspace"
    if not workspace.exists():
        return ""
    sections = []
    for fname in ["SOUL.md", "USER.md", "MEMORY.md"]:
        p = workspace / fname
        if p.exists():
            sections.append(f"## {fname}\n{p.read_text()}")
    today = workspace / "memory" / f"{date.today()}.md"
    if today.exists():
        sections.append(f"## Today's Notes\n{today.read_text()}")
    return "\n\n".join(sections)
```

Set `OPENCLAW_SYNC_PATH` in your env to the `harqis-openclaw-sync` repo root. The injected context prepends USER.md (who the user is), SOUL.md (agent personality), and MEMORY.md + today's notes to every agent's system prompt — no card needs to carry any of that.

**2. Memory write-back (for agents that update memory)**

Give the agent `read_file` / `write_file` scoped to the sync repo path, plus a git push tool scoped to `harqis-openclaw-sync`. The agent can then append to `memory/YYYY-MM-DD.md` and auto-commit exactly as the OpenClaw agent does natively.

**End-to-end flow with OpenClaw:**

```
Card labelled agent:write:article added to Backlog
  ↓
Orchestrator reads SOUL.md + USER.md + MEMORY.md from sync repo
  ↓
Injects OpenClaw context + article agent system prompt + tool inventory
  ↓
Agent receives: [who the user is] + [article persona] + [this card's task]
  ↓
Runs with MCP scope: google_apps, discord, telegram
  ↓
Posts result, moves card to Done, optionally writes to daily memory note
```

---

## Adding a New Kanban Provider

1. Create `agents/kanban/adapters/myprovider.py` implementing `KanbanProvider`
2. Register it in `agents/kanban/factory.py`:
   ```python
   from agents.kanban.adapters.myprovider import MyProvider
   providers["myprovider"] = MyProvider
   ```
3. Set `KANBAN_PROVIDER=myprovider` in env

No orchestrator, agent, or profile code changes needed.

---

## Card Data Available to Agents

| Source | How agent sees it |
|---|---|
| Card description | Main task prompt |
| Card title | Fallback prompt if description is empty |
| Checklists | Listed under `# Sub-tasks` in prompt; agent checks them off via `check_item` tool |
| Custom fields | Listed under `# Parameters` — use for repo URLs, branch names, env targets |
| Text attachments | Fetched and inlined under `# Attached Files` |
| Card URL | Appended at the bottom; agent can reference it in output |

---

## Windows vs Linux

The module is fully cross-platform:

- All paths use `pathlib.Path` — no hardcoded slashes
- `BashTool` uses `subprocess.run(shell=True)` — runs `cmd.exe` on Windows, `bash` on Linux
- Profile `context.working_directory` accepts both `C:\path` and `/path` syntax
- Environment variable loading via `_load_dotenv` works on both platforms

---

## Production Path

When ready to scale beyond a single machine:

1. **Add Celery**: Replace `LocalOrchestrator` with Celery task dispatch
2. **Add Redis**: Celery broker for N100 worker nodes
3. **Add Docker**: Sandbox each agent with `docker run --rm`
4. **Add Webhooks**: Replace polling with Trello/Jira webhooks for <1s latency
5. **Add Vault**: Replace env vars with HashiCorp Vault for secret injection
6. **Hardware routing**: Use `hw:<node>` card labels with `node_affinity` in profiles

The interface layer (`KanbanProvider`, `AgentProfile`, `BaseKanbanAgent`) is unchanged
throughout this evolution — only the orchestration layer changes.
