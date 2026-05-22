# HARQIS Agent Prompts & Projects Context

**Canonical reference for how Claude Code understands agent operations within HARQIS-work.**

---

## Shared Agent Prompts

Location: `agents/prompts/`

### `kanban_agent_default.md`
- System prompt for BaseKanbanAgent operating in Trello-driven workflows
- **Feature Clarification Gate** (mandatory for non-scaffolding enhancements):
  1. Inspect card for new feature/enhancement intent
  2. Read relevant existing code (2-3 targeted calls)
  3. Use `ask_human` to post grouped clarifying questions
  4. Wait for user reply; synthesize into Feature Spec block
  5. Request explicit sign-off before implementation
  6. Skip for: tests, deploy, query, scaffolding commands, `skip:clarify` labels
- Trello rendering rules:
  - Tables MUST be wrapped in triple-backtick code blocks (prevents broken pipe chars)
  - ASCII only, ≤90 char width for mobile readability
  - Headers, lists, bold/italic, inline code: plain Markdown
  - Tabular data always inside code block
- Tool access principle: if a tool appears in the tool list, assume real access — never claim "cannot access"
- Progress discipline: post comment when starting long sub-tasks; check off checklist items as completed
- Final summary required: clear statement of what was done and result

### `docs_agent.md`
- Documentation maintainer for root `README.md`
- Responsibilities:
  1. Keep README in sync with codebase (structure, modules, architecture)
  2. Detect missing documentation (undocumented features, hidden workflows, complex setup, env vars, patterns)
  3. Improve clarity and structure (sections, terminology, concrete details)
- What to include (when applicable):
  - Project overview & purpose
  - Architecture overview (high-level)
  - Setup & installation
  - How to run (commands, services, dependencies)
  - Key workflows (jobs, pipelines, automation)
  - Project structure explanation
  - Development guide & conventions
  - Testing instructions
- Update rules: prefer incremental improvements over rewrites; never invent functionality

### `code_smells.md`
- Code review agent focused on maintainability, readability, reliability
- What to look for:
  1. **Complexity**: long methods, deep nesting, large classes, poor naming, magic numbers
  2. **Duplication**: repeated logic, copy-pasted code, repeated constants
  3. **Design problems**: SRP violations, tight coupling, god objects, leaky abstractions
  4. **Maintainability risks**: dead code, commented code, inconsistent patterns, large files, mutable shared state
  5. **Error handling**: silent failures, generic exceptions, missing validation, hidden side effects
  6. **Testability smells**: tight coupling, missing DI, heavy globals/static state
  7. **API/contract smells**: ambiguous behavior, inconsistent return types, boolean flags, poor command/query separation
- Also acts as documentation maintainer (updates README when patterns/workflows/setup changes)
- Output format:
  - 🔴 Top 3 critical issues (high-impact findings)
  - 🧠 Code smells (location, category, why it smells, impact, suggested improvement, confidence)
  - 📘 README improvements (patch-style or new section snippets)

### Prompt Loading
```python
from agents.prompts import load_prompt
text = load_prompt("kanban_agent_default")

# Save generated prompt (agents write here)
from agents.prompts import save_prompt
save_prompt("my_generated_prompt", content)
```

---

## Workflow-Specific Prompts

Co-located with their workflows:

### HFL Ingest & Synthesis
- `workflows/hfl/prompts/ingest_git.md` — parse git commit signals
- `workflows/hfl/prompts/ingest_browsing.md` — extract browsing activity patterns
- `workflows/hfl/prompts/ingest_chatgpt.md` — capture ChatGPT interaction history
- `workflows/hfl/prompts/ingest_ai.md` — generic AI session capture
- `workflows/hfl/prompts/memory_recall.md` — reconstruct what happened in a time window
- `workflows/hfl/prompts/summarize_week.md` — weekly synthesis from HFL corpus

### Desktop Signals
- `workflows/desktop/prompts/daily_summary.md` — daily activity summary
- `workflows/desktop/prompts/weekly_summary.md` — weekly review
- `workflows/hud/prompts/daily_radar.md` — daily radar signal

### Knowledge & RAG
- `workflows/knowledge/prompts/rag_answer.md` — Capture/Distill/Express via RAG pipeline

### Specialized
- `workflows/social/prompts/monthly_linkedin_post.md` — social sharing
- `workflows/finance/prompts/parse_transaction.md` — transaction parsing
- `workflows/hud/prompts/desktop_analysis.md` — HUD desktop log analysis

---

## agents/projects — Trello Workspace Orchestrator

**Multi-board Trello orchestrator with no Celery/Redis/Docker required for local development.**

### Core Concepts

| Term | Meaning |
|------|---------|
| **Workspace** | Trello organization (`TRELLO_WORKSPACE_ID`); orchestrator auto-discovers all boards |
| **Board** | Trello board with canonical lists (Templates, Draft, Ready, Pending, In Progress, Blocked, In Review, Done, Failed) |
| **Card** | Trello card routed by labels: `agent:*` (profile), `os:*` (OS filter), `human`/`manual`/`input` (skip) |
| **Profile** | YAML agent config defining model, tools, permissions, persona, integrations; matched by `agent:*` label |

### Setup

```bash
# 1. Install
pip install anthropic pyyaml requests

# 2. .env/agents.env (or .env/apps.env)
TRELLO_API_KEY=...
TRELLO_API_TOKEN=...
ANTHROPIC_API_KEY=sk-ant-...     # or CLAUDE_CODE_OAUTH_TOKEN=... for Max
TRELLO_WORKSPACE_ID=harqis-work  # auto-discover all boards
TRELLO_POLL_INTERVAL=30          # seconds
KANBAN_NUM_AGENTS=1              # concurrent workers
KANBAN_DRY_RUN=0

# 3. Create boards with these lists (in order):
# Templates, Draft, Ready, Pending, In Progress, Blocked, In Review, Done, Failed
```

### Card Labels (Case-Insensitive)

#### Routing Labels
| Label | Behavior |
|-------|----------|
| `agent:<profile>` | Route to named profile (e.g., `agent:default`, `agent:code`) |
| `os:<os>` | Filter by OS (e.g., `os:linux`, `os:macos`); auto-detected when unset |

#### Off-Limits (Skip Entirely)
| Label | Behavior |
|-------|----------|
| `human` | Skipped by every orchestrator; signals human-only task |
| `manual` | Same as `human` |
| `input` | Same — needs human input |

These trump all other labels: card with `human, agent:code` is still skipped.

### Card Lifecycle

1. **Ready** (intake) → orchestrator polls every `KANBAN_POLL_INTERVAL` seconds
2. **Pending** → orchestrator claims card, about to start
3. **In Progress** → agent actively working
4. **Blocked** → hard-stop dependency; re-queued to Ready when resolved
5. **In Review** → agent finished; awaiting human/reviewer approval (unless `auto_approve: true`)
6. **Done** → reviewed + accepted
7. **Failed** → unrecoverable error (limits, 4xx-5xx, unhandled); comment surfaces error

### Running the Orchestrator

```bash
# From repo root
python -m agents.projects.orchestrator.local

# With overrides
python -m agents.projects.orchestrator.local \
    --poll-interval 15 \
    --dry-run \
    --profile agent:default \
    --os os:linux,os:gpu
```

Per tick:
1. Re-discover workspace boards (if cadence up)
2. Poll In Progress for paused-for-question cards to resume
3. Poll Ready for new cards
4. Claim → Pending, start → In Progress, run agent
5. Post result as comment, move to In Review (or Done if `auto_approve`)
6. On error: post traceback, move to Failed
7. Periodically re-check Blocked and re-queue resolved cards

### Card Example

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

### Profiles

YAML files defining agent personality, model, tools, permissions, integrations.
Located: `agents/projects/profiles/`
Matched by `agent:*` label on Trello cards.

Example:
```yaml
profile_id: default
model: claude-opus
tools:
  - file_read
  - file_write
  - terminal
permissions:
  max_file_size: 1000000
  allowed_paths: ["/Users/harqis-one/GIT/harqis-work"]
lifecycle:
  auto_approve: false
```

---

## Key Principles for Claude Code

1. **Prompts are canonical** — Always read `agents/prompts/*.md` when designing or reviewing agent behavior
2. **Feature clarification first** — Before proposing code changes, ask structured questions and wait for explicit sign-off
3. **Workflow-local context** — Each workflow has its own prompts in `workflows/<name>/prompts/`
4. **Kanban routing is explicit** — Labels on Trello cards drive routing; respect `human`/`manual`/`input` as hard skips
5. **No Celery/Docker locally** — agents/projects runs as a single Python process for development
6. **Profiles define agent identity** — Model, tools, permissions, lifecycle all live in YAML profiles

---

## Ingestion Notes for Claude Code

- **When creating tasks from agents/projects input**: Extract card title, labels, body, and create structured Trello/task representation
- **When understanding agent intent**: Always refer back to relevant prompt (kanban_agent_default for orchestration tasks, code_smells for code review, docs_agent for README work)
- **When designing agent-driven workflows**: Use CODE+PARA framing; prompts encode the Capture/Organize/Distill/Express logic
- **When proposing changes to prompts**: Cite the current prompt location and explain the change in terms of agent behavior (what new capability, what refinement, what edge case)

---

Document source: `/Users/harqis-one/GIT/harqis-work/docs/AGENT-PROMPTS-CONTEXT.md`
Generated: 2026-05-22 (Claude Code context ingestion)
