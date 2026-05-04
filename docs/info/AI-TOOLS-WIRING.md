# AI Tools — Setup & Sync Guide

Wiring AI tools for workspaces, where each one writes, and the one-shot prompts to orient a fresh session on any machine.

---

## Why this matters — purpose of syncing

This setup spans **macOS** (primary server), **Windows** (worker nodes + primary laptop), and **Linux VPS** nodes. Two git repos keep identity, rules, and tooling consistent across all of them:

| Repo | What it holds | Remote |
|---|---|---|
| [`harqis-work`](https://github.com/brianbartilet/harqis-work) | Platform code, app integrations, workflows, Claude Code customisation (`.claude/`) | Maintainer manages manually |
| [`harqis-openclaw-sync`](https://github.com/brianbartilet/harqis-openclaw-sync) | OpenClaw agent identity, long-term memory, cross-machine workspace | Auto-commits (OpenClaw) |

**Without sync**, every machine starts blank: no personality, no remembered rules, no heartbeat context, no custom prompts. Pulling the right repo at session start is what makes "HARQIS-CLAW on the VPS" behave identically to "HARQIS-CLAW on the Mac Mini".

**Key rule for both tools:** keep writes in the *right* repo so they don't overlap or drift.

| Tool | Writes go to | Commit owner |
|---|---|---|
| **Claude Code** | `harqis-work/.claude/` | **Maintainer — manual** |
| **OpenClaw agent** | `harqis-openclaw-sync/.openclaw/workspace/` | **Agent — auto-commit+push** |

---

## Paths — resolve per-OS, never hardcode

| Repo | macOS | Windows | Linux / VPS |
|---|---|---|---|
| `harqis-work` | `$HOME/GIT/harqis-work` | `%USERPROFILE%\GIT\harqis-work` | `~/GIT/harqis-work` |
| `harqis-openclaw-sync` | `$HOME/GIT/harqis-openclaw-sync` | `%USERPROFILE%\GIT\harqis-openclaw-sync` | `~/GIT/harqis-openclaw-sync` |

From inside either repo, `git rev-parse --show-toplevel` returns the root on any OS.

---

## Tool 1 — Claude Code

**Home dir in this repo:** `.claude/`
**Current contents:**
- `.claude/commands/` — project slash-commands:
  - `/agent-prompt` — run an AI agent prompt from `prompts/` against the codebase
  - `/generate-registry` — regenerate `frontend/registry.py` from all `workflows/*/tasks_config.py` files
  - `/new-service-app` — scaffold a complete app integration under `apps/`; with a spec/URL it generates real implementations, without one it creates a skeleton; chainable to `/new-workflow`
  - `/new-workflow` — scaffold a new workflow under `workflows/`
  - `/new-n8n-workflow` — build and deploy an n8n workflow from a drawio diagram, XML/BPMN file, or text description; imports directly into the local n8n instance via Docker CLI
  - `/run-tests` — run tests for a specific app or the full suite
- `.claude/settings.local.json` — per-machine permissions (safe list of Bash/Read/etc.)
- `.claude/settings.json` — shared settings (currently empty; add hooks here when needed)

**What belongs here:**
- New slash-commands (`.md` files under `commands/`)
- Hooks (SessionStart, PreToolUse, etc. in `settings.json`)
- Permissions and project-scoped config
- Notes/docs about how the harness is wired for this repo

**What does NOT belong here:**
- OpenClaw identity files (those live in the sync repo)
- Secrets (those live in `.env/apps.env`, never in `.claude/`)
- Harness auto-memory (`~/.claude/projects/.../memory/`) — the auto-memory system Claude Code uses to persist context across sessions; stored locally per-machine, never git-tracked, and path-managed by Claude Code itself

### Orientation prompt for a fresh Claude Code session

Paste this at the start of a new session on any machine to point it at the right places:

```
You are working inside the harqis-work repo. Use project config at
./.claude/ (settings.json, settings.local.json, commands/) for all
Claude Code customisation. Write new slash-commands, hooks, and
project-scoped rules into ./.claude/ — never into the sync repo.

Do NOT auto-commit anything inside harqis-work; the maintainer commits
this repo manually. After any edit under ./.claude/, surface `git status`
and wait for maintainer review before committing.

For OpenClaw agent identity and long-term memory, read from the sibling
repo ./../harqis-openclaw-sync/.openclaw/workspace/ (files: SOUL.md,
USER.md, AGENTS.md, MEMORY.md, IDENTITY.md, TOOLS.md, HEARTBEAT.md,
plus memory/YYYY-MM-DD.md daily notes). That repo is auto-committed
by the agent — don't stage files there from this session.

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
# 1. Clone both repos side by side under your GIT folder
cd ~/GIT  # or %USERPROFILE%\GIT on Windows
git clone git@github.com:brianbartilet/harqis-work.git
git clone git@github.com:brianbartilet/harqis-openclaw-sync.git

# 2. Install harqis-work Python deps
cd harqis-work && python -m venv .venv
# macOS/Linux:  .venv/bin/pip install -r requirements.txt
# Windows:      .venv\Scripts\pip install -r requirements.txt

# 3. Populate .env/apps.env with the secrets (never committed)

# 4. Open Claude Code in this directory — it auto-picks up .claude/
```

---

## Tool 2 — OpenClaw

**Home dir across machines:** `harqis-openclaw-sync/.openclaw/workspace/`

**What belongs here:**
- `IDENTITY.md`, `SOUL.md`, `USER.md`, `AGENTS.md` — identity and rules
- `MEMORY.md` — long-term narrative memory
- `TOOLS.md`, `HEARTBEAT.md` — environment + periodic check tasks
- `memory/YYYY-MM-DD.md` — daily notes
- `memory/private.md` — sensitive info (gitignored)

**What does NOT belong here:**
- Claude Code config (that lives in `harqis-work/.claude/`)
- Application code (that lives in `harqis-work/`)
- Secrets in plaintext (use `memory/private.md` which is gitignored, or the machine Keychain)

### Orientation prompt for OpenClaw agent

```
You are HARQIS-CLAW, the automation agent for this workspace. Your canonical workspace
is the sync repo:
  macOS:   $HOME/GIT/harqis-openclaw-sync/.openclaw/workspace/
  Windows: %USERPROFILE%\GIT\harqis-openclaw-sync\.openclaw\workspace\
  Linux:   ~/GIT/harqis-openclaw-sync/.openclaw/workspace/

Read SOUL.md, USER.md, AGENTS.md, and MEMORY.md at session start.
Also read today's memory/YYYY-MM-DD.md if present.

ALWAYS write identity, memory, and workspace updates into the sync repo
— never into harqis-work/.openclaw/ (that's a legacy/local copy).

After any edit inside .openclaw/workspace/, auto-commit+push:
  git -C <SYNC_REPO> add .openclaw/workspace/
  git -C <SYNC_REPO> commit -m "(openclaw-commit) <short description>"
  git -C <SYNC_REPO> push origin main

Do it silently unless it fails. Surface the failure and wait for
maintainer input if push breaks (conflict, no network, auth).

Do NOT stage or commit anything outside .openclaw/workspace/. The
harqis-work repo is the maintainer's to commit manually.
```

### Auto-pull cadence

The auto-pull job pulls **both repos** in one shot — `harqis-openclaw-sync` (rebase) and `harqis-work` (`--ff-only` so a dirty tree or local commits never get clobbered). Scripts live in the sync repo: `scripts/sync-pull.sh` (bash) and `scripts/sync-pull.ps1` (PowerShell).

| OS | Wiring | Cadence |
|---|---|---|
| **macOS** | LaunchAgent `work.harqis.autopull` — install with `harqis-openclaw-sync/scripts/install-launchagent.sh` (renders `scripts/launchd/work.harqis.autopull.plist` into `~/Library/LaunchAgents/`, loads it, runs at load + every 30 min). Logs: `~/Library/Logs/harqis-autopull.log`. Uninstall: `install-launchagent.sh --uninstall`. | Every 30 min + at load |
| **Windows** | Task Scheduler — `harqis-openclaw-sync/scripts/install-scheduled-task.ps1` registers `OpenClaw-Auto-Pull` which runs `scripts/sync-pull.ps1` (now pulls **both** repos). Logs: `<sync-repo>\logs\sync-pull.log`. | Every 30 min |
| **Linux / VPS** | Run `scripts/sync-pull.sh` from a user-level systemd timer or cron entry (e.g. `*/30 * * * * /home/<user>/GIT/harqis-openclaw-sync/scripts/sync-pull.sh`). | Every 30 min (recommended) |

Override paths or skip a repo via env vars / switches:

```bash
# macOS / Linux
SYNC_REPO=/alt/path/sync WORK_REPO=/alt/path/work scripts/sync-pull.sh
SKIP_WORK=1 scripts/sync-pull.sh   # only pull the sync repo

# Windows
.\scripts\sync-pull.ps1 -SyncRepoPath D:\sync -WorkRepoPath D:\work
.\scripts\sync-pull.ps1 -SkipWork
```

After a sync-repo update the script also runs `openclaw gateway --no-restart` to reload config without dropping connections.

Always pull before trusting memory state — another machine may have pushed updates.

**Why `--ff-only` for harqis-work:** `harqis-work` is the maintainer's repo (manual commits). A fast-forward-only pull silently no-ops if there are local commits or a dirty tree, instead of merging or rebasing over uncommitted work. Failures are logged and surfaced on next manual interaction; nothing is auto-resolved.

---

## Why keep them separate?

| Concern | Claude Code | OpenClaw |
|---|---|---|
| Runtime identity | The harness tool (editor-side) | The agent persona (runs 24/7) |
| Commit cadence | When the maintainer says so | Automatic after every workspace edit |
| Cross-machine sync | Via harqis-work pushes (maintainer's cadence) | Via harqis-openclaw-sync pushes (agent-driven, ~continuous) |
| Secrets exposure | Permissions file (`.claude/settings.local.json`) may reveal paths | No secrets ever; `memory/private.md` is gitignored |
| Failure mode if mis-routed | Cluttered git status in harqis-work | Identity drift between machines |

Keeping them separate means:
- The maintainer retains full control over what lands in the main code repo
- The OpenClaw agent can freely write memory without risking spurious commits in the code repo
- Searching `.claude/` vs `.openclaw/workspace/` answers "whose config is this?" unambiguously
- Disaster recovery is per-scope: losing harqis-work doesn't lose OpenClaw memory, and vice versa

---

## Quick reference — "where does this go?"

| If you're writing… | Put it in |
|---|---|
| A new Claude Code slash-command | `harqis-work/.claude/commands/*.md` |
| A Claude Code hook (SessionStart, PreToolUse, etc.) | `harqis-work/.claude/settings.json` |
| A permission allow-list entry | `harqis-work/.claude/settings.local.json` |
| A note about how Claude Code is wired for this project | `harqis-work/.claude/` (new file, plain markdown) |
| OpenClaw agent rules (workspace conventions, heartbeat, red lines) | `harqis-openclaw-sync/.openclaw/workspace/AGENTS.md` |
| Long-term agent memory (narrative) | `harqis-openclaw-sync/.openclaw/workspace/MEMORY.md` |
| Today's session notes / learnings | `harqis-openclaw-sync/.openclaw/workspace/memory/YYYY-MM-DD.md` |
| Sensitive account info | `harqis-openclaw-sync/.openclaw/workspace/memory/private.md` (gitignored) |
| A new app integration | `harqis-work/apps/<name>/` |
| A new Celery task | `harqis-work/workflows/<name>/` |

---

## See also

- `docs/info/HARQIS-CLAW-HOST.md` — full service inventory, Mac Mini deployment, ports, controller setup, migration guide
- `docs/info/OPENCLAW-SYNC.md` — sync-repo architecture and setup across machines
- `docs/info/AGENTS-TASKS-KANBAN.md` — Kanban agent system: board design, agent profiles, security layer, MCP bridge
- `docs/info/SKILLS-GUIDE.md` — Claude Code skills reference and OpenClaw integration patterns
- `docs/info/OS-COMPATIBILITY.md` — cross-platform notes
- `mcp/README.md` — MCP server tool inventory (OANDA, YNAB, Gmail, TCG, etc.)
