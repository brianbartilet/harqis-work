# HARQIS Agent Skills Guide

HARQIS skills are reusable operating playbooks for reasoning-model agents. The
canonical, source-controlled definitions live under `.agents/skills/`; they are
written to be usable by Claude, OpenAI models, and other capable reasoning
models. A runtime still needs an agent harness that can read instructions and
provide the tools named by a skill.

Invocation and discovery are harness-specific. A runtime may expose a skill as
`/skill-name`, `$skill-name`, a picker entry, or instructions loaded directly
from `SKILL.md`. Do not interpret model-neutral content as a promise that every
chat interface automatically discovers repository skills.

## Canonical and compatibility paths

```text
.agents/skills/<skill-name>/
├── SKILL.md             # required; canonical instructions
├── scripts/             # optional deterministic helpers
├── references/          # optional supporting material
└── assets/              # optional reusable output assets

.claude/skills/          # generated Claude Code compatibility copy
```

Edit `.agents/skills/` only. Refresh the generated Claude compatibility tree
with:

```powershell
python scripts/agents/repo-quality/sync_agent_skills.py
```

Use `--check` in validation or CI. `.claude/settings.json` and
`.claude/settings.local.json` remain Claude Code runtime configuration; they are
not canonical skill definitions.

## Skill format

Every skill is a directory containing `SKILL.md`. Frontmatter provides the
machine-readable name and discovery description:

```yaml
---
name: example-skill
description: Explain what the skill does and when an agent should use it.
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---
```

Keep the body imperative and outcome-oriented. Put decision rules and the main
workflow in `SKILL.md`; move lengthy reference material or deterministic logic
to `references/` or `scripts/`. Runtime-specific syntax should be identified as
an adapter example, not presented as a portable requirement.

## Using a skill

1. Select the skill whose description matches the task.
2. Read its complete `SKILL.md` before acting.
3. Resolve referenced files relative to that skill directory.
4. Follow its confirmation, safety, testing, and hand-off requirements.
5. Treat user instructions as the final authority on requested scope.

Some skills intentionally chain into others. For example,
`create-new-service-app` may hand off MCP work to `create-new-mcp`, while
`create-new-workflow` owns Celery task, schedule, queue, test, and documentation
wiring.

## Creating or updating a skill

1. Create or edit `.agents/skills/<name>/SKILL.md`.
2. Use a lowercase hyphenated directory and matching `name`.
3. Write a specific description that says both what the skill does and when it
   applies.
4. Reuse repository scripts and templates rather than duplicating large blocks.
5. Update [`SKILLS-INVENTORY.md`](SKILLS-INVENTORY.md).
6. Run the compatibility check and refresh generated adapters when needed.
7. Search current operational docs for stale paths or behavior claims.

## Documentation contract

Skills that create or materially change repository features must leave their
documentation current:

- App integrations: `apps/<name>/README.md`, root app inventory, config and
  environment guidance, MCP surface, and test commands.
- Workflows: `workflows/<category>/README.md`, scheduled/manual task surface,
  apps chained, data flow, schedule, queue/OS, config, outputs, and failure
  behavior.
- Frontend modules: user-facing name, route, behavior, configuration, and tests
  in `frontend/README.md`.
- Skills: canonical inventory entry plus compatibility-path validation.

Use `/update-docs [target]` for a targeted drift sweep after implementation.

## Hermes integration

Hermes memory remains machine-local under `~/.hermes/`; repository skills stay
under `.agents/skills/`. A skill may read relevant Hermes memory or call HARQIS
MCP tools when the active harness provides access, but it must not copy secrets
into instructions, memory, logs, or committed files.

The repository-local `.hermes/plans/` directory is also ignored and may be used
for planning artifacts. It is not a skill source.

## Related documentation

- [`SKILLS-INVENTORY.md`](SKILLS-INVENTORY.md) — current repository skill list
- [`AI-TOOLS-WIRING.md`](AI-TOOLS-WIRING.md) — model/runtime wiring and write boundaries
- [`HERMES.md`](HERMES.md) — Hermes runtime and memory
- [`AGENTS-TASKS-KANBAN.md`](AGENTS-TASKS-KANBAN.md) — Kanban-driven agents
- [`scripts/README.md`](../../scripts/README.md) — compatibility synchronization
