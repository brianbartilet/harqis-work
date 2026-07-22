# Agent Tools — Setup and Wiring Guide

HARQIS can be operated by Claude, OpenAI models, and other reasoning-model
agents. Repository behavior is defined independently from any one model; the
active harness determines how skills are discovered, which tools are exposed,
and how permissions are enforced.

## Sources of truth

| Source | What it holds | Persistence |
|---|---|---|
| `harqis-work/.agents/skills/` | Canonical, model-neutral HARQIS skill instructions | Git |
| `harqis-work/.claude/skills/` | Generated Claude Code compatibility copy | Gitignored; regenerate |
| `harqis-work/.claude/settings*.json` | Claude Code-specific settings and local permissions | Shared or machine-local as named |
| `~/.hermes/` | Hermes plans, memory, lessons, scripts, and logs | Local per machine; never committed |
| `.env/apps.env` | Application secrets | Local; never committed |
| `HFL_SESSION_AUDIT_PATH` | Sanitized prompt/outcome audit artifacts and retry spool | Local per machine unless explicitly placed on shared storage |

Refresh or validate the Claude compatibility copy with
`scripts/agents/repo-quality/sync_agent_skills.py`. Never maintain canonical
skill content in both trees.

## Paths

| Source | macOS | Windows | Linux / VPS |
|---|---|---|---|
| Repository | `$HOME/GIT/harqis-work` | `%USERPROFILE%\GIT\harqis-work` | `~/GIT/harqis-work` |
| Canonical skills | `<repo>/.agents/skills` | `<repo>\.agents\skills` | `<repo>/.agents/skills` |
| Hermes memory | `$HOME/.hermes` | `%USERPROFILE%\.hermes` | `~/.hermes` |

From inside the repository, use `git rev-parse --show-toplevel`; do not hardcode
a machine-specific checkout path.

## Reasoning-model agent harnesses

A compatible harness should:

1. Load relevant skill instructions from `.agents/skills/<name>/SKILL.md`.
2. Expose only the tools and filesystem/network scope required for the task.
3. Treat user approval requirements in a skill as mandatory checkpoints.
4. Load machine environment through repository launch/deploy helpers before
   importing `apps.*` or `workflows.*`.
5. Keep secrets out of prompts, logs, committed files, and Hermes memory.

Skill invocation may appear as `/name`, `$name`, a UI picker, or direct loading.
That syntax is a harness concern, not part of the skill's business logic.

## Claude Code compatibility

Claude Code reads its runtime settings from `.claude/`. Project skills are
generated into `.claude/skills/` from the canonical `.agents/skills/` tree:

```powershell
python scripts/agents/repo-quality/sync_agent_skills.py
python scripts/agents/repo-quality/sync_agent_skills.py --check
```

Put shared hooks in `.claude/settings.json` and machine-specific permissions in
`.claude/settings.local.json`. Do not put Hermes memory or secrets there.

The repository's shared Claude `UserPromptSubmit` and `Stop` hooks feed the HFL
prompt audit adapter. Codex uses the equivalent project `.codex/hooks.json`;
review it with `/hooks` after the hook definition changes. Hermes and OpenClaw
use the model-neutral `/capture-hfl-session` fallback and common JSON envelope.

## Hermes

Hermes is the always-on runtime that registers HARQIS MCP tools and runs agent
or no-agent cron jobs. Its memory is local to each machine under `~/.hermes/`:

- `memory/agent_lessons.md` — recurring lessons
- `memory/` — long-term narrative memory
- `plans/` — planning artifacts
- `scripts/` — cron helpers
- `logs/` — runtime logs

Hermes does not replace canonical repository skills and its memory is not a
cross-machine sync repository. Confirm MCP registration with `hermes mcp list`;
restart the HARQIS MCP service with `python scripts/deploy.py --restart mcp`.

## New-machine setup

```bash
cd ~/GIT
git clone git@github.com:brianbartilet/harqis-work.git
cd harqis-work
python -m venv .venv
# macOS/Linux: .venv/bin/pip install -r requirements.txt
# Windows: .venv\Scripts\pip install -r requirements.txt
```

Populate the gitignored `.env/apps.env`, configure the machine in
`machines.local.toml`, and use `scripts/launch.py` or `scripts/deploy.py` so
environment and machine overlays load consistently.

## Write boundaries

| Change | Location |
|---|---|
| New or updated agent skill | `.agents/skills/<name>/SKILL.md` |
| Generated Claude skill adapter | `.claude/skills/` via the sync script |
| Claude Code hook or setting | `.claude/settings*.json` |
| Hermes lesson or long-term memory | `~/.hermes/memory/` |
| Planning artifact | `~/.hermes/plans/` or ignored repo-local `.hermes/plans/` |
| App integration | `apps/<name>/` plus its README and root inventory |
| Celery workflow | `workflows/<category>/` plus its category README |

## Related documentation

- [`SKILLS-GUIDE.md`](SKILLS-GUIDE.md) — portable skill format and lifecycle
- [`SKILLS-INVENTORY.md`](SKILLS-INVENTORY.md) — current HARQIS skills
- [`HERMES.md`](HERMES.md) — Hermes runtime and memory model
- [`HERMES-HOST.md`](HERMES-HOST.md) — host deployment and operations
- [`AGENTS-TASKS-KANBAN.md`](AGENTS-TASKS-KANBAN.md) — Kanban-driven agent system
- [`scripts/README.md`](../../scripts/README.md) — skill compatibility synchronization
