# Claude Code Skills — Guide

Skills are reusable prompt-based workflows stored as markdown files. They create `/skill-name`
commands you (or Claude automatically) can invoke. They are the recommended replacement for
custom slash-commands in `.claude/commands/`.

---

## Skills vs Custom Commands

Both `.claude/commands/deploy.md` and `.claude/skills/deploy/SKILL.md` create a `/deploy`
command and behave identically. Skills are preferred because they add:

- **Supporting files** — keep `SKILL.md` focused; move reference material to sibling files
- **Invocation control** — `disable-model-invocation` and `user-invocable` fields
- **Subagent execution** — `context: fork` runs the skill in an isolated subagent
- **Dynamic context** — `` !`command` `` inlines live shell output before Claude reads the skill

Existing `.claude/commands/` files continue to work without changes.

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

## Skills in This Project

| Skill | Where defined | Purpose |
|---|---|---|
| `/run-tests` | `.claude/commands/run-tests.md` | Run tests for an app or the full suite |
| `/agent-prompt` | `.claude/commands/agent-prompt.md` | Run a prompt from `agents/prompts/` against the codebase |
| `/new-workflow` | `.claude/commands/new-workflow.md` | Scaffold a new workflow under `workflows/` |
| `/new-app` | `.claude/commands/new-app.md` | Scaffold a new app integration under `apps/` |
| `/generate-registry` | `.claude/commands/generate-registry.md` | Regenerate `frontend/registry.py` from all `tasks_config.py` files |
| `/review` | built-in | Review a pull request |
| `/security-review` | built-in | Security review of pending branch changes |
| `/simplify` | built-in | Review changed code for quality and fix issues |
| `/fewer-permission-prompts` | built-in | Scan transcripts and add a permission allowlist |
| `/update-config` | built-in | Configure `settings.json` / hooks |
| `/loop` | built-in | Run a prompt on a recurring interval |
| `/schedule` | built-in | Schedule a remote agent on a cron schedule |
| `/claude-api` | built-in | Build and debug Anthropic SDK apps |

Project commands live in `.claude/commands/`. To add a new one, create a `.md` file there or
use a full skill directory under `.claude/skills/`.

---

## See Also

- `docs/info/AI-TOOLS-SETUP.md` — Claude Code orientation and workspace sync guide
- `.claude/commands/` — current project slash-commands
- `.claude/settings.local.json` — per-machine permission allowlist
