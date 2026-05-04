Sweep the root `README.md` (or a targeted doc) against the live state of the codebase, surface drift between docs and reality, and apply the smallest necessary edits.

## When to use

- User asks to **update**, **review**, **check**, or **refresh** docs / documentation / a README
- Right after adding or removing an app, workflow, queue, agent profile, slash command, or major component
- Before cutting a release or onboarding someone new

## Argument

`<target>` is optional and free-form:

| Token | Effect |
|---|---|
| (nothing) | Walk root `README.md` |
| `<path>` | Walk that file (e.g. `scripts/README.md`, `workflows/README.md`, `docs/info/HARQIS-CLAW-HOST.md`, `apps/<app>/README.md`) |
| `--dry-run` | Report drift only, write nothing |
| `--related-only` | Skip the target itself, only sweep files that reference it |

## Per-section data sources (root README.md)

For each H2/H3 section, cross-check against the table below. If a section isn't listed, leave it alone.

| Section | Source of truth | Drift signs to look for |
|---|---|---|
| **App Inventory** | `apps/*/` directory listing, `apps_config.yaml`, each app's `config.py` `APP_NAME` | New app dirs not listed; removed apps still listed; integration type mismatch (REST/Selenium/Local) |
| **AI Agents · Project Kanban** | `agents/projects/profiles/`, `agents/projects/orchestrator/local.py` (CLI defaults) | Profile count, profile names, `--num-agents` defaults, lifecycle steps |
| **AI Agents · OpenClaw** | `agents/openclaw/` if present, `harqis-openclaw-sync` link, channels listed | New mediums (Telegram/Discord/WhatsApp/etc.) added or removed |
| **MCP Server** | `mcp/server.py` `@mcp.tool()` count, exposed apps | Tool count, list of exposed app modules |
| **Workflow Inventory** | `workflows/*/tasks_config.py` — count entries per `WORKFLOWS_*` dict | Task counts per workflow, status (active vs. stub), description |
| **Celery Task Queues** | `workflows/queues.py` (`WorkflowQueue` enum), `workflows/config.py` (`task_queues` and `task_routes`) | Missing/added queues, direct vs. fanout split, route patterns |
| **Beat schedule** | `workflows/config.py` `CONFIG_DICTIONARY = …` line | Missing `WORKFLOW_*` modules in the union |
| **Desktop HUD** | `workflows/hud/tasks/`, `apps/rainmeter/` skin layouts | New/removed panels, schedule changes |
| **Frontend Dashboard** | `frontend/registry.py` `TASK_REGISTRY`, `frontend/main.py` routes | Task count, panel registration |
| **Architecture · Directory Structure** | Top-level dirs (`apps/`, `workflows/`, `agents/`, `mcp/`, `frontend/`, `scripts/`, `core/`, `docs/`) and their immediate children | New top-level dirs, renames, moved files (e.g. `machines.toml` lives at root, not under `scripts/`) |
| **Platform Runtime** | `scripts/deploy.py` `SERVICES` dict, `scripts/launch.py` subcommands, `core/apps/sprout/` | New services, lifecycle order, runtime startup |
| **Configuration · Environment Variables** | `.env/apps.env` (or `.example`), `core/config/env_variables.py` `ENV_*` constants | New env vars introduced (especially `WORKFLOW_*`, `FLOWER_*`, `CONFIG_*`) |
| **Running Services** | `scripts/deploy.py` argparse, `scripts/README.md` | Stale CLI flags, new flags missing from this README |

## Targeted-doc sweep

If `<target>` is a path other than the root README, walk that file's sections instead — most non-root READMEs document a smaller scope. Common targets and their sources:

| Target | Source of truth |
|---|---|
| `scripts/README.md` | `scripts/deploy.py` argparse + `SERVICES`, `scripts/launch.py` subcommands, `machines.toml` example |
| `workflows/README.md` | `workflows/config.py`, `workflows/queues.py`, each workflow's `tasks_config.py` |
| `apps/<app>/README.md` | That app's `config.py`, `references/web/api/*` modules, test count |
| `mcp/README.md` | `mcp/server.py` tool registrations |
| `docs/info/HARQIS-CLAW-HOST.md` | `scripts/deploy.py`, `machines.toml`, Docker compose, `apps_config.yaml` |
| `frontend/README.md` | `frontend/registry.py`, `frontend/main.py` |

## Cross-reference fan-out

Whenever you edit a doc, `grep` for the doc's path across all `*.md` files in the repo. Any other doc that mentions the target may need a parallel update — for example, editing `scripts/README.md` should also refresh:
- The root `README.md` "Running Services" / "Architecture" sections that reference `scripts/`
- Slash-command docs in `.claude/commands/*.md` that mention `python scripts/deploy.py …`
- `docs/info/HARQIS-CLAW-HOST.md` if it linked to the moved file

Apply the same drift check to those files. **Skip the cross-reference step** when invoked with `--related-only` (the user is doing only the cascading update).

## Steps

1. **Identify the target.** Default = root `README.md`. Explicit path overrides.
2. **Read the target.** List its H2/H3 sections.
3. **For each known section:** read the source-of-truth files, build the live state, diff against the doc.
4. **Compose a per-section drift report.** Compact lines:
   - `App Inventory: 24 listed, 26 present in apps/. Missing: <a>, <b>.`
   - `Celery Task Queues: 3 listed, 12 in WorkflowQueue. Missing: host, peon, agent, worker, adhoc, default_broadcast, hud_broadcast, workers_broadcast, agents_broadcast.`
   - `Beat schedule: 3 modules in CONFIG_DICTIONARY, 5 in workflows/. Missing: WORKFLOW_SOCIAL, WORKFLOW_KNOWLEDGE.`
5. **Apply the smallest-possible edits** with the Edit tool. Preserve table column order, voice, and existing markup style.
6. **Run cross-reference fan-out** (unless `--related-only`).
7. **Propose a commit message** in the result:
   - One section: `docs(repo): refresh <Section Name> in README`
   - Multiple sections: `docs(repo): refresh README sections from code state`
   - Targeted file: `docs(<scope>): refresh <filename> from code state`

If `--dry-run`, stop after step 4 (don't apply edits).

## Hard rules

- **Don't fabricate.** Only surface entities that exist in the code. If an app's purpose is ambiguous from its code, keep the existing description.
- **Don't reformat or reorder unrelated sections.** Headings, anchor links, and section order stay put.
- **Don't add example commands the doc didn't already have.** Drift fixes only.
- **Tables stay tables, lists stay lists.** Don't rewrite a list section as a table or vice versa.
- **Skip ambiguous descriptions** — if the code says "REST API" but the doc says "REST (native SDK)", don't auto-flatten unless the SDK is genuinely gone.
- **Don't touch hand-written prose paragraphs** unless they reference a renamed/removed file or function.
- **Never delete a section** to "clean up." If a section is fully obsolete, surface it in the report and ask.
