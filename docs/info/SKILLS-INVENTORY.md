# HARQIS Agent Skills Inventory

This is the current inventory of source-controlled skills in `.agents/skills/`.
The skills are model-neutral playbooks usable by Claude, OpenAI models, and
other reasoning-model agents when their harness provides the required tool and
instruction-loading support.

`.agents/skills/<name>/SKILL.md` is canonical. `.claude/skills/` is a generated,
gitignored compatibility copy for Claude Code; never edit it as a second source
of truth.

## Inventory

| Skill | Purpose |
|---|---|
| `/add-script` | Add or reorganize scripts using the repository's `scripts/` taxonomy and documentation conventions. |
| `/agent-prompt` | Run a named prompt from `agents/prompts/` against the codebase. |
| `/capture-hfl-session` | Capture a sanitized prompt/outcome pair for HFL when an automatic surface hook is unavailable or needs a manual retry. |
| `/clarify-feature` | Convert an enhancement request into an approved implementation spec before files change. |
| `/commit` | Review, stage, and create a Conventional Commit, with optional push and guarded host-sync chaining. |
| `/create-data-only-from-hud` | Add a host-safe data-only fallback twin for an existing Windows HUD task. |
| `/create-new-fork-repository` | Produce a clean client/business fork baseline while preserving the platform skeleton. |
| `/create-new-hud` | Scaffold a Rainmeter HUD task, configuration, imports, documentation, and optional queue wiring. |
| `/create-new-ingest-source-hfl` | Add an HFL/Activity Corpus source with capture, distillation, Markdown, and Elasticsearch persistence. |
| `/create-new-kanban-board` | Create a Trello board with canonical lists, labels, template card, and registration guidance. |
| `/create-new-kanban-profile` | Scaffold an agent profile and its manual Trello/env setup checklist. |
| `/create-new-mcp` | Build or extend MCP tools for an existing app integration. |
| `/create-new-n8n-workflow` | Build and deploy an n8n workflow from a diagram, XML/BPMN file, or text description. |
| `/create-new-service-app` | Scaffold or extend a complete app integration from a spec, URL, or named skeleton. |
| `/create-new-workflow` | Design and implement an RPA-style Celery workflow that chains app integrations. |
| `/deploy-harqis` | Deploy the platform as a host or worker node, including services, workers, frontend, MCP, and agents. |
| `/dumps-summary` | Generate the daily dumps summary Markdown through the canonical repository script. |
| `/generate-gherkin-scenarios` | Generate repository-standard Gherkin scenarios from requirements or tickets. |
| `/generate-registry` | Regenerate the frontend workflow catalogue from workflow task configurations. |
| `/manage-queues` | Maintain Celery task-to-queue assignments and report live machine coverage. |
| `/max-plan` | Perform a deep reasoning planning pass and persist the resulting plan. |
| `/migrate-to-core` | Move reusable generic code from `harqis-work` into `harqis-core`. |
| `/radar-sold-inventory` | Cross-reference sold TCG orders with inventory and radar data. |
| `/run-tests` | Run app-specific, targeted, or full pytest suites using repository conventions. |
| `/sync-host` | Preflight and synchronize configured local files to a remote HARQIS checkout over SSH. |
| `/time-capsule-synthesizer` | Synthesize a set of files into one period-based HFL time-capsule entry. |
| `/update-docs` | Audit documentation against current code and apply the smallest accurate corrections. |
| `/workflow-token-audit` | Estimate scheduled workflow API calls, model/token exposure, embedding usage, and cost drivers. |
| `/zapier-mcp` | Search, enable, and wire Zapier MCP actions into workflows or direct agent use. |

**Current canonical count: 29 skills.** The count is derived from directories
containing `.agents/skills/*/SKILL.md`; cache or generated directories do not
count.

## High-value entry points

| Goal | Start with |
|---|---|
| Add an external service | `/create-new-service-app` |
| Add scheduled automation | `/create-new-workflow` |
| Add tools for an existing app | `/create-new-mcp` |
| Add a desktop widget | `/create-new-hud` |
| Add an Activity Corpus source | `/create-new-ingest-source-hfl` |
| Capture a prompt audit event | `/capture-hfl-session` |
| Validate changes | `/run-tests` |
| Refresh documentation | `/update-docs` |
| Commit completed work | `/commit` |

## Maintenance rules

When adding, renaming, or removing a skill:

1. Change `.agents/skills/<name>/SKILL.md` and any required supporting files.
2. Add, update, or remove its row in this inventory in the same change.
3. Update cross-links in the root README, `SKILLS-GUIDE.md`, and operational
   documentation when its entry point or behavior changes.
4. Run `python scripts/agents/repo-quality/sync_agent_skills.py --check`.
5. If the check reports drift, run the script without `--check` to regenerate
   `.claude/skills/`; do not hand-edit the generated copy.

The `/update-docs` skill owns this inventory check. Skill-creation or
skill-editing work is incomplete until the canonical directory list and this
table agree.
