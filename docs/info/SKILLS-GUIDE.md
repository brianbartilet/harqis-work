# Claude Code Skills — Guide

Skills are reusable prompt-based workflows stored as markdown files. They create `/skill-name`
commands you (or Claude automatically) can invoke. They are the recommended replacement for
custom slash-commands in `.claude/skills/`.

---

## Skills vs Custom Commands

Both `.claude/skills/deploy/SKILL.md` and `.claude/skills/deploy/SKILL.md` create a `/deploy`
command and behave identically. Skills are preferred because they add:

- **Supporting files** — keep `SKILL.md` focused; move reference material to sibling files
- **Invocation control** — `disable-model-invocation` and `user-invocable` fields
- **Subagent execution** — `context: fork` runs the skill in an isolated subagent
- **Dynamic context** — `` !`command` `` inlines live shell output before Claude reads the skill

Existing `.claude/skills/` files continue to work without changes.

---

## File Structure

```
~/.claude/skills/my-skill/      # global — available in all projects
.claude/skills/my-skill/        # project-scoped — this repo only
├── SKILL.md                    # required
├── reference.md                # optional supporting docs
└── scripts/
    └── helper.py               # optional scripts
```

Priority (higher wins): enterprise → personal (`~/.claude/`) → project (`.claude/`) → plugin.

---

## SKILL.md Format

```yaml
---
name: my-skill
description: What it does and when Claude should auto-invoke it
allowed-tools: Bash(git *) Read
---

Your instructions here. Use $ARGUMENTS or named args like $topic.
```

---

## Frontmatter Reference

| Field | Optional | Purpose |
|---|---|---|
| `name` | Yes | Display name → `/slash-command`. Defaults to directory name. |
| `description` | Recommended | Claude reads this to decide when to auto-invoke. |
| `when_to_use` | Yes | Extra trigger context, appended to description in listings. |
| `argument-hint` | Yes | Autocomplete hint, e.g. `[issue-number]`. |
| `arguments` | Yes | Named positional args — `arguments: [topic, tone]` → `$topic`, `$tone`. |
| `disable-model-invocation` | Yes | `true` = only the user can trigger (deploys, destructive ops). |
| `user-invocable` | Yes | `false` = hidden from `/` menu; only Claude can invoke. |
| `allowed-tools` | Yes | Pre-approves tools — no permission prompts while skill is active. |
| `model` | Yes | Override the session model for this skill only. |
| `effort` | Yes | Override effort level: `low`, `medium`, `high`, `xhigh`, `max`. |
| `context` | Yes | `fork` = run in isolated subagent instead of inline. |
| `agent` | Yes | Subagent type when `context: fork` (e.g. `Explore`, `Plan`, `general-purpose`). |
| `paths` | Yes | Glob patterns — skill activates only when working with matching files. |
| `shell` | Yes | `bash` (default) or `powershell`. |

---

## Invocation

```bash
/my-skill                           # no arguments
/my-skill write an article          # $ARGUMENTS = "write an article"
/my-skill topic="AI" tone="formal"  # named arguments
```

Claude also auto-invokes skills when your message matches the `description` field — unless
`disable-model-invocation: true` is set.

---

## Dynamic Context

Embed live shell output into the skill body before Claude sees it using `` !`command` ``:

```yaml
---
name: pr-summary
context: fork
agent: Explore
allowed-tools: Bash(gh *)
---

Current diff:
!`gh pr diff`

Summarize the changes above.
```

The command runs at invoke time and its output replaces the `` !`...` `` placeholder inline.

---

## Common Patterns

### Manual-only workflow (deploy, destructive ops)

```yaml
---
name: deploy
description: Deploy the application to production
disable-model-invocation: true
allowed-tools: Bash(git *) Bash(docker *) Read
---

Deploy $ARGUMENTS to production:
1. Run the test suite
2. Build the application
3. Push to the deployment target
4. Verify success
```

### Background project knowledge (Claude reads, not surfaced to user)

```yaml
---
name: legacy-auth-context
description: How the legacy authentication system works
user-invocable: false
---

The legacy auth system uses custom JWT tokens (non-standard), Oracle DB for session
storage, and a 30-minute TTL. Never recommend removing the token refresh middleware.
```

### Skill with named arguments

```yaml
---
name: migrate-component
description: Migrate a UI component between frameworks
arguments: [component, from, to]
---

Migrate the $component component from $from to $to.
Preserve all existing behavior, tests, and prop interfaces.
```

### Codebase exploration in isolated subagent

```yaml
---
name: find-dead-code
description: Scan for unused exports and unreachable functions
context: fork
agent: Explore
---

Search the codebase for:
- Exported symbols with no importers
- Functions that are defined but never called
- Files that are not imported anywhere

Report findings with file paths and line numbers.
```

### Skill with supporting reference file

```
.claude/skills/code-review/
├── SKILL.md
└── standards.md        # loaded on demand, keeps SKILL.md concise
```

```yaml
# SKILL.md
---
name: code-review
description: Review changed code against project standards
allowed-tools: Bash(git diff *) Read
---

Review the staged changes against [our standards](standards.md).
Flag any violations and suggest fixes.
```

---

## When to Create a Skill

- You keep pasting the same multi-step playbook into chat
- A CLAUDE.md section has grown into a procedure
- You want to pre-approve a known set of tools without per-use prompts
- You need to capture detailed reference material without bloating the context window
- You want to share a repeatable workflow with the team

---

## Skills & Hermes Integration

The host running `harqis-work` is also the **Hermes Host** — the machine where the
Hermes agent memory (`~/.hermes/`) and Claude Code share the same filesystem. This co-location
means a skill can read Hermes memory and lessons as live dynamic context, giving every Claude
Code session on this machine the same accumulated context that Hermes agents have.

> Hermes supersedes the deprecated OpenClaw Gateway. Memory is now **local per-machine** under
> `~/.hermes/` — there is no sync repo to pull. See [`HERMES.md`](HERMES.md).

### Co-location layout

```
$HOME/
├── GIT/harqis-work/
│   ├── .claude/
│   │   ├── settings.local.json   ← Claude Code permissions for this machine
│   │   └── skills/               ← project slash-commands
│   └── mcp/server.py             ← MCP server (55 tools) — runs locally
│
└── .hermes/                      ← Hermes memory (local, not synced, not committed)
    ├── memory/
    │   ├── agent_lessons.md      ← recurring lessons distilled from past runs
    │   └── ...                   ← long-term narrative memory
    ├── plans/                    ← plans from /max-plan and planning passes
    ├── scripts/                  ← cron-invoked helper scripts
    └── logs/                     ← job logs
```

The MCP server (`mcp/server.py`) also runs on this machine and is the tool endpoint for both
Claude Code sessions and remote worker agents. Skills that call MCP tools do so via the local
process — no network hop required.

### Injecting Hermes context into a skill

Use the `` !`command` `` dynamic context syntax to read Hermes memory at invoke time. The shell
command runs before Claude sees the skill body, so the content is part of the prompt rather than
something the agent has to go and fetch.

```yaml
---
name: hermes-context
description: Load Hermes memory and distilled lessons into the current session
user-invocable: false
allowed-tools: Read Bash(cat *)
---

## Hermes Memory

### Lessons
!`cat $HOME/.hermes/memory/agent_lessons.md 2>/dev/null || echo "(no lessons yet)"`

### Long-term memory
!`cat $HOME/.hermes/memory/MEMORY.md 2>/dev/null || echo "(no narrative memory yet)"`

---

You now have the Hermes agent's accumulated memory and lessons in context. Apply the lessons to
this session's work.
```

Setting `user-invocable: false` keeps this skill hidden from the `/` menu. Claude auto-invokes
it when the session description matches — or you can invoke it explicitly with `/hermes-context`
if you have overridden `user-invocable`.

Because Hermes memory is local per-machine, there is **no sync step** — nothing to pull before
reading (this was the deprecated OpenClaw model). The files are always current on the machine
that wrote them.

### Writing back to memory

A skill can append session learnings to the local Hermes memory. No commit/push — the tree is
local and uncommitted:

```yaml
---
name: log-memory
description: Append a note to the local Hermes memory
disable-model-invocation: true
allowed-tools: Bash(echo * >> *)
arguments: [note]
---

Appending note to Hermes memory:
!`echo "\n## $(date '+%Y-%m-%d %H:%M') — Claude Code session\n$note" >> $HOME/.hermes/memory/agent_lessons.md`

Memory note saved locally.
```

### MCP tools inside skills

Because the MCP server runs locally on this machine, a skill can call any registered MCP tool
directly without extra configuration. Tools are already scoped and available in any Claude Code
session that has the `harqis-work` MCP server connected:

```yaml
---
name: morning-brief
description: Pull today's calendar, latest email, and OANDA balance into context
context: fork
agent: general-purpose
---

Fetch and summarise:
1. Today's Google Calendar events — use the get_google_calendar_events_today MCP tool
2. The 5 most recent Gmail messages — use get_gmail_recent_emails with max_results=5
3. Current OANDA account balance — use get_oanda_account_details

Format as a morning brief: calendar first, then email summary, then financial snapshot.
```

### Summary — what lives where on this machine

| Item | Location | Commit owner |
|---|---|---|
| Skills and commands | `harqis-work/.claude/skills/` | Maintainer — manual |
| Claude Code permissions | `harqis-work/.claude/settings.local.json` | Maintainer — manual |
| Claude Code auto-memory | `~/.claude/projects/.../memory/` | Claude Code — local only, never committed |
| Hermes agent memory | `~/.hermes/` | Hermes agent — local only, never committed |
| MCP server | `harqis-work/mcp/server.py` | Maintainer — manual |

Skills bridge these two systems: they live in `harqis-work/.claude/` (maintainer-controlled) but
can read from and write to the local Hermes memory (`~/.hermes/`) at runtime using dynamic context
and tool calls.

---

## Skills in This Project

| Skill | Where defined | Purpose |
|---|---|---|
| `/run-tests` | `.claude/skills/run-tests/SKILL.md` | Run tests for an app or the full suite |
| `/agent-prompt` | `.claude/skills/agent-prompt/SKILL.md` | Run a prompt from `agents/prompts/` against the codebase |
| `/create-new-workflow` | `.claude/skills/create-new-workflow/SKILL.md` | Scaffold a new workflow under `workflows/` |
| `/create-new-service-app` | `.claude/skills/create-new-service-app/SKILL.md` | Scaffold an app integration under `apps/` — skeleton or from OpenAPI spec/URL; delegates the MCP layer to `/create-new-mcp`; chainable to `/create-new-workflow` |
| `/create-new-mcp` | `.claude/skills/create-new-mcp/SKILL.md` | Build/extend the MCP tool surface for an existing `apps/<app>` by wrapping its service endpoints; single source of truth for the MCP layer; loops back to `/create-new-service-app` for missing apps/endpoints |
| `/create-new-n8n-workflow` | `.claude/skills/create-new-n8n-workflow/SKILL.md` | Build and deploy an n8n workflow from a drawio diagram, XML/BPMN file, or text description into the local n8n instance |
| `/generate-registry` | `.claude/skills/generate-registry/SKILL.md` | Regenerate `frontend/registry.py` from all `tasks_config.py` files |
| `/review` | built-in | Review a pull request |
| `/security-review` | built-in | Security review of pending branch changes |
| `/simplify` | built-in | Review changed code for quality and fix issues |
| `/fewer-permission-prompts` | built-in | Scan transcripts and add a permission allowlist |
| `/update-config` | built-in | Configure `settings.json` / hooks |
| `/loop` | built-in | Run a prompt on a recurring interval |
| `/schedule` | built-in | Schedule a remote agent on a cron schedule |
| `/claude-api` | built-in | Build and debug Anthropic SDK apps |

Project commands live in `.claude/skills/`. To add a new one, create a `.md` file there or
use a full skill directory under `.claude/skills/`.

---

## See Also

- `docs/info/AI-TOOLS-WIRING.md` — Claude Code orientation and workspace sync guide
- `.claude/skills/` — current project slash-commands
- `.claude/settings.local.json` — per-machine permission allowlist
