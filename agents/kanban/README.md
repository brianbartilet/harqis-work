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
KANBAN_POLL_INTERVAL=30       # seconds between board polls (default: 30)
KANBAN_PROFILES_DIR=          # path to custom profiles dir (default: bundled examples)
KANBAN_DRY_RUN=0              # set to 1 to poll without running agents
```

### 3. Create your Trello board

Create a Trello board with these lists (exact names):

| List Name | Purpose |
|---|---|
| `Backlog` | New tasks — orchestrator picks from here |
| `Claimed` | Agent claimed the card |
| `In Progress` | Agent actively working |
| `Blocked` | Agent waiting on human input |
| `Review` | Agent done — awaiting human approval |
| `Done` | Completed |
| `Failed` | Agent encountered an unrecoverable error |

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
3. Claim them (move to Claimed → In Progress)
4. Run the Claude agent
5. Post the result as a comment
6. Move to Review (or Done if `auto_approve: true` in the profile)

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
├── profiles/
│   ├── schema.py             # AgentProfile dataclass + YAML loader
│   ├── registry.py           # ProfileRegistry — loads and resolves profiles
│   └── examples/
│       ├── base.yaml         # Base profile (inherited by others)
│       ├── agent_code.yaml   # Code agent — bash, read/write files, git
│       └── agent_write.yaml  # Write agent — read/write files, research
│
├── permissions/
│   └── enforcer.py           # PermissionEnforcer — checks tools, FS, network, git
│
├── agent/
│   ├── context.py            # AgentContext — builds prompt from card data
│   ├── base.py               # BaseKanbanAgent — Claude tool-use loop
│   └── tools/
│       ├── registry.py       # ToolRegistry — maps tool names to callables + Claude defs
│       ├── filesystem.py     # ReadFileTool, WriteFileTool, GlobTool, GrepTool, BashTool
│       └── kanban_tools.py   # TrelloCommentTool, TrelloMoveTool, ChecklistTool
│
├── orchestrator/
│   └── local.py              # LocalOrchestrator — single-process polling loop + CLI
│
└── tests/
    ├── conftest.py            # Shared fixtures (cards, profiles)
    ├── test_interface.py      # KanbanCard + AgentContext
    ├── test_trello_adapter.py # TrelloProvider (mocked HTTP)
    ├── test_profiles.py       # Profile loading + registry
    ├── test_permissions.py    # PermissionEnforcer
    ├── test_agent.py          # BaseKanbanAgent (mocked Claude)
    └── test_orchestrator.py   # LocalOrchestrator (mocked provider + agent)
```

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
