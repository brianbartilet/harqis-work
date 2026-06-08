# AI Tools — Setup & Wiring Guide

Wiring AI tools for this workspace, where each one writes, and the one-shot prompts to orient a fresh session on any machine.

---

## Why this matters

This setup spans **macOS** (primary server), **Windows** (worker nodes + primary laptop), and **Linux VPS** nodes. Two things keep the AI layer consistent across all of them:

| Source | What it holds | Sync model |
|---|---|---|
| [`harqis-work`](https://github.com/brianbartilet/harqis-work) | Platform code, app integrations, workflows, Claude Code customisation (`.claude/`) | Git — maintainer manages manually |
| `~/.hermes/` | Hermes agent memory, distilled lessons, plans, logs | **Local per-machine — not synced, not committed** |

Hermes keeps its memory **local to each machine** under `~/.hermes/`. There is no cross-machine sync repo (that was the deprecated OpenClaw model — see [`OPENCLAW-SYNC.md`](OPENCLAW-SYNC.md)). What makes a fresh machine behave correctly is cloning `harqis-work` (for code + Claude Code config) and letting Hermes build its own local memory over time.

**Key rule for both tools:** keep writes in the *right* place so they don't overlap or drift.

| Tool | Writes go to | Commit / persistence |
|---|---|---|
| **Claude Code** | `harqis-work/.claude/` | **Maintainer — manual git commit** |
| **Hermes agent** | `~/.hermes/` (local) | **Agent — local files, never committed** |

---

## Paths — resolve per-OS, never hardcode

| Source | macOS | Windows | Linux / VPS |
|---|---|---|---|
| `harqis-work` | `$HOME/GIT/harqis-work` | `%USERPROFILE%\GIT\harqis-work` | `~/GIT/harqis-work` |
| Hermes memory | `$HOME/.hermes` | `%USERPROFILE%\.hermes` | `~/.hermes` |

From inside the repo, `git rev-parse --show-toplevel` returns the root on any OS.

---

## Tool 1 — Claude Code

**Home dir in this repo:** `.claude/`
**Current contents:**
- `.claude/skills/` — project slash-commands:
  - `/agent-prompt` — run an AI agent prompt from `prompts/` against the codebase
  - `/generate-registry` — regenerate `frontend/registry.py` from all `workflows/*/tasks_config.py` files
  - `/create-new-service-app` — scaffold a complete app integration under `apps/`; with a spec/URL it generates real implementations, without one it creates a skeleton; chainable to `/create-new-workflow`
  - `/create-new-workflow` — scaffold a new workflow under `workflows/`
  - `/create-new-n8n-workflow` — build and deploy an n8n workflow from a drawio diagram, XML/BPMN file, or text description; imports directly into the local n8n instance via Docker CLI
  - `/max-plan` — Opus-level planning pass; writes the plan to `.hermes/plans/`
  - `/run-tests` — run tests for a specific app or the full suite
- `.claude/settings.local.json` — per-machine permissions (safe list of Bash/Read/etc.)
- `.claude/settings.json` — shared settings (currently empty; add hooks here when needed)

**What belongs here:**
- New slash-commands (`.md` files under `skills/`)
- Hooks (SessionStart, PreToolUse, etc. in `settings.json`)
- Permissions and project-scoped config
- Notes/docs about how the harness is wired for this repo

**What does NOT belong here:**
- Hermes agent memory (that lives locally under `~/.hermes/`)
- Secrets (those live in `.env/apps.env`, never in `.claude/`)
- Harness auto-memory (`~/.claude/projects/.../memory/`) — the auto-memory system Claude Code uses to persist context across sessions; stored locally per-machine, never git-tracked, and path-managed by Claude Code itself

### Orientation prompt for a fresh Claude Code session

Paste this at the start of a new session on any machine to point it at the right places:

```
You are working inside the harqis-work repo. Use project config at
./.claude/ (settings.json, settings.local.json, skills/) for all
Claude Code customisation. Write new slash-commands, hooks, and
project-scoped rules into ./.claude/ — never elsewhere.

Do NOT auto-commit anything inside harqis-work; the maintainer commits
this repo manually. After any edit under ./.claude/, surface `git status`
and wait for maintainer review before committing.

For Hermes agent memory and distilled lessons, read from ~/.hermes/
(memory/agent_lessons.md, plans/, logs/). That tree is local per-machine
and never committed — don't stage it from this session.

Before any harqis-work dependent work (MCP tools — OANDA, YNAB,
Google Apps, TCG Marketplace, Echo MTG, Scryfall, Telegram, Trello,
Jira, OwnTracks, Orgo, Discord, Reddit, LinkedIn, Notion, Anthropic
— Celery workflows, frontend):
  1. docker compose -f ./docker-compose.yml ps  # expect rabbitmq, redis,
     n8n, mosquitto, elasticsearch, kibana, owntracks-recorder up
  2. On macOS also: launchctl list | grep work.harqis  # expect scheduler,
     worker, frontend with PIDs
  3. If anything is down, run python scripts/deploy.py (cross-platform).

Search the current system — detect OS via `uname -s` or `$OSTYPE` on
POSIX, `ver` or `$env:OS` on Windows — and pick the matching flow.
Never hardcode macOS paths.
```

### First-time setup on a new machine

```bash
# 1. Clone the platform repo under your GIT folder
cd ~/GIT  # or %USERPROFILE%\GIT on Windows
git clone git@github.com:brianbartilet/harqis-work.git

# 2. Install harqis-work Python deps
cd harqis-work && python -m venv .venv
# macOS/Linux:  .venv/bin/pip install -r requirements.txt
# Windows:      .venv\Scripts\pip install -r requirements.txt

# 3. Populate .env/apps.env with the secrets (never committed)

# 4. Open Claude Code in this directory — it auto-picks up .claude/
#    (Hermes builds its own ~/.hermes/ memory locally over time.)
```

---

## Tool 2 — Hermes

**Memory dir (per-machine):** `~/.hermes/`

Hermes is the agent runtime that hosts Claude agents, registers the harqis-work MCP server, and schedules cron jobs. See [`HERMES.md`](HERMES.md) for the full reference. It supersedes the deprecated OpenClaw Gateway.

**What belongs under `~/.hermes/`:**
- `memory/agent_lessons.md` — recurring lessons distilled from past runs
- `memory/` — long-term narrative memory
- `plans/` — plans written by `/max-plan` and planning passes
- `scripts/` — cron-invoked helper scripts
- `logs/` — job logs

**What does NOT belong here:**
- Claude Code config (that lives in `harqis-work/.claude/`)
- Application code (that lives in `harqis-work/`)
- Secrets in plaintext (use `.env/apps.env`, or the machine Keychain)

### Orientation prompt for a Hermes agent

```
You are the Hermes agent for this workspace. Your memory lives locally on
this machine under:
  macOS:   $HOME/.hermes/
  Windows: %USERPROFILE%\.hermes\
  Linux:   ~/.hermes/

Read memory/agent_lessons.md and relevant memory/ notes at the start of a
multi-step task. Write new lessons and notes back under ~/.hermes/memory/.

This memory is local per-machine and is NOT synced or committed anywhere.
Do not attempt to clone or push a sync repo. The harqis-work repo is the
maintainer's to commit manually — never stage or commit it.

Call platform integrations through the harqis-work MCP server (confirm with
`hermes mcp list`). Schedule recurring work as Hermes cron jobs in agent
mode (reasoning loop) or no_agent mode (run a script, deliver output).
```

### MCP registration

```bash
hermes mcp list                       # confirm harqis-work is registered
python scripts/deploy.py --restart mcp  # (re)start the MCP server if missing
```

After a code update on this machine, restart the MCP server so Hermes picks up new tools.

---

## Why keep them separate?

| Concern | Claude Code | Hermes |
|---|---|---|
| Runtime identity | The harness tool (editor-side) | The agent runtime (runs 24/7) |
| Commit cadence | When the maintainer says so | Never — memory is local, uncommitted |
| Cross-machine sync | Via harqis-work pushes (maintainer's cadence) | None — `~/.hermes/` is per-machine |
| Secrets exposure | Permissions file (`.claude/settings.local.json`) may reveal paths | No secrets ever; memory holds lessons, not credentials |
| Failure mode if mis-routed | Cluttered git status in harqis-work | Lessons written to the wrong machine's `~/.hermes/` |

Keeping them separate means:
- The maintainer retains full control over what lands in the main code repo
- The Hermes agent can freely write memory without risking spurious commits in the code repo
- Searching `.claude/` vs `~/.hermes/` answers "whose config is this?" unambiguously
- Disaster recovery is per-scope: losing harqis-work doesn't lose Hermes memory, and vice versa

---

## Quick reference — "where does this go?"

| If you're writing… | Put it in |
|---|---|
| A new Claude Code slash-command | `harqis-work/.claude/skills/*/SKILL.md` |
| A Claude Code hook (SessionStart, PreToolUse, etc.) | `harqis-work/.claude/settings.json` |
| A permission allow-list entry | `harqis-work/.claude/settings.local.json` |
| A note about how Claude Code is wired for this project | `harqis-work/.claude/` (new file, plain markdown) |
| Hermes agent lessons / long-term memory | `~/.hermes/memory/` |
| A plan from a planning pass | `~/.hermes/plans/` (or repo-local `.hermes/plans/` via `/max-plan`) |
| A Hermes cron helper script | `~/.hermes/scripts/` |
| A new app integration | `harqis-work/apps/<name>/` |
| A new Celery task | `harqis-work/workflows/<name>/` |

---

## See also

- `docs/info/HERMES.md` — Hermes agent runtime, `~/.hermes/` layout, MCP + cron model
- `docs/info/HERMES-HOST.md` — full service inventory, host deployment, ports, worker nodes, migration guide
- `docs/info/AGENTS-TASKS-KANBAN.md` — Kanban agent system: board design, agent profiles, security layer, MCP bridge
- `docs/info/SKILLS-GUIDE.md` — Claude Code skills reference and Hermes integration patterns
- `docs/info/OS-COMPATIBILITY.md` — cross-platform notes
- `mcp/README.md` — MCP server tool inventory (OANDA, YNAB, Gmail, TCG, etc.)
- `docs/info/OPENCLAW-SYNC.md` — **deprecated** legacy OpenClaw sync model
