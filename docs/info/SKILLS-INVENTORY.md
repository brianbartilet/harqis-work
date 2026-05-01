# Claude Code Skills Inventory

Skills are slash commands available in any Claude Code session opened in this repo. They encode multi-step workflows so Claude executes them end-to-end without step-by-step prompting.

Invoke with `/skill-name [arguments]` in the Claude Code prompt.  
Skill files live in `.claude/commands/*.md`. The first line of each file is the short description shown in the skill picker.

---

## Skill Inventory

| Skill | Command | Description |
|---|---|---|
| **agent-prompt** | `/agent-prompt <prompt_name>` | Run a named AI prompt from `agents/prompts/` against the codebase. `prompt_name` is the filename without extension (e.g. `code_smells`, `docs_agent`, `desktop_analysis`). |
| **commit** | `/commit [<subject hint>] [<pathspec>...] [--type <t>] [--scope <s>] [--no-untracked] [--dry-run]` | Stage all working-tree changes and commit with a Conventional-Commit message inferred from the diff, following [COMMIT-MESSAGE-GUIDE.md](COMMIT-MESSAGE-GUIDE.md). **Calling `/commit` is your sign-off — no confirmation prompt.** Auto-detects type and scope from the layer of changed files (`apps/<name>`, `workflows/<name>`, `agents/kanban`, `mcp`, `frontend`, `repo`). Pass pathspecs to limit staging. Skips `.env*` files for safety. Never pushes, never amends, never bypasses hooks. |
| **deploy-harqis** | `/deploy-harqis <host\|node> [-q queues] [-p profile] [--hw labels] [--down] [--no-frontend] [--no-mcp] [--no-kanban] [--num-agents N] [--dry-run]` | End-to-end reusable deploy of the harqis-work platform — **cross-platform**, auto-detects macOS / Linux / Windows. `host` brings up the full stack (Docker + Beat scheduler + worker + frontend + MCP + Kanban + Flower); the host's Kanban orchestrator defaults to `agent:default` so the host also acts as 1 default-queue agent worker. `node` runs a Celery worker plus a profile-scoped Kanban orchestrator (the skill **asks** for `-p` if missing). `--hw` filters by `hw:*` labels (auto-detected from OS otherwise). Tear down with `--down`. |
| **generate-registry** | `/generate-registry` | Regenerate `frontend/registry.py` by scanning all `workflows/*/tasks_config.py` files. Run after adding or removing any Celery task. |
| **new-fork-repository** | `/new-fork-repository <business_or_client_name> [--owner <gh_owner>] [--visibility public\|private\|internal] [--description "..."] [--keep <list>] [--strip <list>] [--apps-keep <list>] [--apps-keep-all] [--target-dir <path>] [--remote <url>] [--no-create-repo] [--no-push] [--no-git-init] [--dry-run]` | Fork `harqis-work` into a clean business-/client-scoped baseline at `harqis-work-fork-<slug>`. Strips host-local AI tooling (`.claude/`, `.openclaw/`, `logs/`, `data/`), every pre-built workflow category (keeps only `.template`), and all real credentials (regenerates `.example` variants). **Apps are pruned to a curated 16-item set by default** (override with `--apps-keep` or `--apps-keep-all`); the prune cascades through `apps_config.yaml.example`, `.env/apps.env.example`, `mcp/server.py`'s `APP_REGISTRARS`, agent profiles' `mcp_apps`, and the README app inventory. Rewrites `README.md`, `workflows/README.md`, `workflows/config.py`, `workflows/queues.py`. **Auto-creates a private GitHub repo via `gh repo create` and pushes the initial commit by default** — pass `--no-create-repo` or `--no-push` to opt out, `--visibility public` to publish openly. |
| **new-kanban-profile** | `/new-kanban-profile <profile_name> [--display-name "..."] [--email "..."] [--role "..."] [--no-mode-a]` | Scaffold a new Kanban agent profile YAML under `agents/kanban/profiles/examples/`. Includes a persona block (signed comments — Mode B, default-on) and commented-out Mode A scaffolding. Adds blank `TRELLO_AGENT_API_KEY__<SUFFIX>` / `TRELLO_AGENT_API_TOKEN__<SUFFIX>` placeholders to `.env/apps.env`. Prints the manual Trello-account setup checklist. |
| **new-n8n-workflow** | `/new-n8n-workflow <description_or_diagram>` | Build and deploy an n8n workflow directly into the local n8n instance (`localhost:5678`) from a drawio diagram, XML/BPMN file, or free-text description. |
| **new-service-app** | `/new-service-app <app_name> [<spec_or_url>] [--workflow <name>]` | Scaffold a complete app integration under `apps/`. With a spec URL, generates real service classes, DTOs, and MCP tools from the API. Without a spec, creates a skeleton stub. Pass `--workflow` to also scaffold a Celery task that uses the new app. |
| **new-workflow** | `/new-workflow [<category>] <task_description_or_diagram> [--merge <file>] [--new-file <name>]` | Design and implement an RPA-style Celery workflow that chains app integrations. Parses drawio diagrams or text descriptions, resolves missing app and Python package dependencies, writes the task file, registers the schedule, and produces tests. |
| **run-tests** | `/run-tests [<app_name_or_path>]` | Run the test suite. Without arguments runs the full suite; with an app name (e.g. `echo_mtg`) or a pytest path runs only that scope. |
| **zapier-mcp** | `/zapier-mcp <task_or_app> [--enable] [--workflow <name>] [--research]` | Search Zapier's 9,000+ app catalogue for actions that match a task, enable them on the Zapier MCP server, infer parameters from context, and optionally wire them into a Celery workflow. Use `--research` for discovery only. |

---

## Skill Details

### `/agent-prompt`

Loads a prompt file from `agents/prompts/` and runs it as a full Claude agent pass over the codebase.

```
/agent-prompt code_smells
/agent-prompt docs_agent
/agent-prompt desktop_analysis
```

Available prompts:

| Prompt file | Purpose |
|---|---|
| `code_smells.md` | Review changed files for anti-patterns and quality issues |
| `docs_agent.md` | Generate or update documentation from code |
| `desktop_analysis.md` | Analyse desktop HUD log screenshots |
| `kanban_agent_default.md` | Default system prompt used by `BaseKanbanAgent` |

---

### `/commit`

Stages all working-tree changes and commits in one shot with a Conventional-Commit message inferred from the diff. **Calling `/commit` is your sign-off** — there is no confirmation prompt. Implements the rules in [COMMIT-MESSAGE-GUIDE.md](COMMIT-MESSAGE-GUIDE.md).

```
/commit                                       # stage everything tracked + new files, commit
/commit workflows/hud                         # only stage paths under workflows/hud
/commit "mirror tcg qr downloads into now"    # subject hint
/commit --type fix --scope workflows/hud      # force type/scope
/commit --no-untracked                        # skip new files, only modified/deleted
/commit --dry-run                             # preview message, do not commit
```

**Format produced:** `<type>(<scope>): <subject>` — single line, ≤72 chars, imperative, lower-case.

**Staging behaviour:**

| Situation | What `/commit` stages |
|---|---|
| Pathspecs given | Only those paths (`git add -- <paths>`). |
| Something already staged, no pathspecs | Whatever was staged. Unstaged working-tree changes left alone, mentioned once. |
| Nothing staged, no pathspecs | Tracked modifications + deletions (`git add -u`) **plus** untracked files (unless `--no-untracked`). |
| `.env*` files | **Always skipped** from auto-staging, listed in the post-commit summary. Stage manually if intentional. |

| Detection | Source |
|---|---|
| **Type** | All test files → `test`. All `*.md` → `docs` (with `.claude/commands/*.md` exception → `feat`). Dockerfiles → `build`. CI files → `ci`. Repo plumbing (`requirements.txt`, `.gitignore`, `apps_config.yaml`, `.env*`, `pytest.ini`) → `chore`. Otherwise inspects diff for new defs/classes (`feat`), bug language (`fix`), pure restructure (`refactor`), or whitespace (`style`). |
| **Scope** | First common path segment of staged files: `apps`, `workflows`, `agents`, `mcp`, `frontend`, `docs`, `scripts`. Adds sub-scope if all files share one (`apps/google`, `workflows/hud`). Cross-layer or root-only → `repo`. |
| **Subject** | Drafted from the diff, biased by any free-text hint in `$ARGUMENTS`. |

**Hard rules baked into the skill:**

- Never amends, never force-pushes, never passes `--no-verify`. Pre-commit hook failures stop the skill (with the staged state preserved) so you can fix the root cause and re-run.
- Never pushes — the user pushes when ready.
- Never blindly `git add -A`. Auto-staging is `git add -u` plus enumerated untracked files, with `.env*` excluded.
- No `Co-Authored-By` footer — repo style is subject-only.
- If the staged set spans unrelated scopes, the post-commit summary suggests `git reset HEAD~` + a split using pathspecs.

`--dry-run` drafts and prints the message but does not commit. Anything staged in Step 1 stays staged so you can inspect and commit manually if you prefer.

---

### `/deploy-harqis`

End-to-end deploy of the harqis-work platform on the current machine. Decides what to start based on the **role** argument and a **queue list**:

```
/deploy-harqis host                              # full stack, default queue
/deploy-harqis host -q default,adhoc,tcg         # host also drains adhoc + tcg queues
/deploy-harqis host --no-kanban                  # skip Kanban orchestrator
/deploy-harqis host --num-agents 3               # 3 concurrent in-process Kanban agents
/deploy-harqis node -q hud,tcg,default           # N100: hardware queues + default
/deploy-harqis node -q code,write,default        # VPS: dev/research queues
/deploy-harqis host --down                       # tear down host
```

| Role | Components started |
|---|---|
| `host` | Docker stack · **Beat scheduler** · worker (queues from `-q`, default `default`) · FastAPI frontend · MCP daemon · Kanban orchestrator (1 agent worker) |
| `node` | Celery worker only — subscribes to every queue in `-q` (single process, multi-queue via Celery's native `-Q`). Connects to host's broker. Never runs Beat. |

**Beat scheduler runs on the host only** — there must be exactly one Beat across the cluster, otherwise scheduled tasks duplicate. Workers are role-agnostic: pass whichever queues this machine should consume via `-q`.

The skill validates Docker / venv / broker connectivity before making changes, surfaces per-component log paths on any failure, and supports clean teardown via `--down`. **OS auto-detection** dispatches to:

| OS | Underlying script | Daemon wrappers | Hosting |
|---|---|---|---|
| macOS | `scripts/sh/deploy.sh` | `scripts/sh/run_*_daemon.sh` | LaunchAgent plists |
| Linux | `scripts/sh/deploy.sh` | `scripts/sh/run_*_daemon.sh` | systemd or `nohup` (Appendix B) |
| Windows | `scripts/ps/deploy.ps1` | `scripts/ps/run_*_daemon.ps1` | `Start-Process -WindowStyle Hidden` (default) or Scheduled Tasks (`-Register`, Appendix C) |

When new always-on components are added to harqis-work (a new daemon or orchestrator), the skill's "Maintenance" section lists the three places that must be updated to keep the deploy reproducible. See also [HARQIS-CLAW-HOST.md §4](HARQIS-CLAW-HOST.md#4-deploy-pipeline-host-vs-node) for the full pipeline diagram.

---

### `/new-kanban-profile`

Scaffolds a new Kanban agent profile under `agents/kanban/profiles/examples/<file_basename>.yaml` and registers Mode A env-var placeholders in `.env/apps.env`. Designed so each profile = one persona = one user-facing identity on the Trello/Jira board.

```
/new-kanban-profile finance
/new-kanban-profile research --display-name "Claude · Research" --role "Research agent"
/new-kanban-profile sandbox --no-mode-a       # ephemeral profile, no env-var registration
```

**What it generates:**
- A YAML profile with all the standard sections + a `persona` block (display name, email, role, signature) and a **commented** `provider_credentials` block.
- Two new lines in `.env/apps.env` under a `# KANBAN AGENT PERSONAS` section: `TRELLO_AGENT_API_KEY__<SUFFIX>=` and `TRELLO_AGENT_API_TOKEN__<SUFFIX>=` (blank — the user fills these in only if they want Mode A).
- A printed checklist explaining the manual Trello-account setup (sign up, verify email, invite to board, generate token).

**Mode B (default, immediate):** the new agent runs **right now** under the shared `TRELLO_API_KEY` / `TRELLO_API_TOKEN` and signs every comment with its persona block. No manual setup required.

**Mode A (opt-in):** activates automatically when both `TRELLO_AGENT_API_KEY__<SUFFIX>` and `TRELLO_AGENT_API_TOKEN__<SUFFIX>` are populated **and** the profile's `provider_credentials` block is uncommented. Trello then attributes every action (comment / move / claim) to the agent's own Trello account natively — its avatar appears, no signature prefix needed.

The orchestrator picks the mode automatically per profile at runtime via `LocalOrchestrator.provider_for_profile()`. No code change required to flip an agent over — just set the env vars and uncomment the YAML block.

---

### `/generate-registry`

Scans all `workflows/*/tasks_config.py` files and rewrites `frontend/registry.py` with the current task list. Run this any time a task is added, renamed, or removed so the frontend dashboard stays in sync.

```
/generate-registry
```

No arguments. Reports what changed (added / removed task keys).

---

### `/new-fork-repository`

Forks `harqis-work` into a fresh, business-/client-scoped baseline that another team can adopt as the starting point for their own automation host. Keeps the platform skeleton (`apps/`, `agents/`, deploy scripts, core framework hooks) but strips local AI tooling and pre-built workflow categories so the consuming agents have a clean slate.

```
/new-fork-repository "Acme Logistics"
/new-fork-repository "Acme Logistics" --owner acme-corp --description "Logistics ops automation for Acme"
/new-fork-repository test-client --no-push                       # init + create repo, do not push
/new-fork-repository test-client --no-create-repo                # local-only fork, no GitHub
/new-fork-repository test-client --keep .template,n8n            # also preserve the n8n category
/new-fork-repository test-client --visibility public              # explicit opt-in to public
/new-fork-repository test-client --dry-run                       # preview without writing
```

**Arguments:**

| Token | Required | Description |
|---|---|---|
| `business_or_client_name` | Yes | Slugified to kebab-case for the repo / folder name. Final repo: `harqis-work-fork-<slug>`. |
| `--owner <gh_org_or_user>` | No | Owner under which to create the GitHub repo. Defaults to the authenticated `gh` user. |
| `--visibility public\|private\|internal` | No | Visibility for the auto-created GitHub repo. **Default: `private`** — never silently public. |
| `--description "..."` | No | One-paragraph project description; also passed to `gh repo create --description`. |
| `--target-dir <path>` | No | Disk location for the fork. Default: sibling of source repo. |
| `--remote <url>` | No | Skip `gh repo create` and use this URL as `origin` instead. |
| `--keep <list>` | No | Workflow categories to preserve (default: only `.template`). |
| `--strip <list>` | No | Extra top-level folders to remove. |
| `--apps-keep <list>` | No | `apps/<name>` integrations to keep (default: curated 16-item set). Always include `.template`. |
| `--apps-keep-all` | No | Skip the apps prune entirely; copy every upstream app. |
| `--no-create-repo` | No | Init + commit only; the user wires the GitHub remote manually. |
| `--no-push` | No | Init + (optionally) create repo, but skip the `git push`. |
| `--no-git-init` | No | Skip git entirely. Implies `--no-create-repo` and `--no-push`. |
| `--dry-run` | No | Print the plan and stop without writing or invoking `gh`. |

**Default app keep list** (16 entries): `.template, airtable, antropic, browser, filesystem, gemini, git, github, google_apps, google_drive, grok, open_ai, perplexity, playwright, telegram, trello`. Anything not on this list is stripped from `apps/` and the cascade prunes every dependent surface.

**What it does:**

1. **Plans the strip vs. keep lists** and prints them for confirmation.
2. **Copies** the source tree into `<parent>/harqis-work-fork-<slug>` with excludes for `.claude/`, `.openclaw/`, `.idea/`, `.run/`, `.venv/`, `.pytest_cache/`, `__pycache__/`, `data/`, `logs/`, `app.log*`, `celerybeat-schedule.*`, `apps_config.yaml`, `.env/*` (non-`.example`), and every workflow category not in the keep list.
3. **Regenerates** the minimal `workflows/` scaffold — empty `CONFIG_DICTIONARY` in `config.py`, only `DEFAULT` + `ADHOC` queues in `queues.py`, instructions-only `README.md`, and an empty `__init__.py`.
4. **Rewrites the top-level `README.md`** for the business — origin notice, App Inventory pruned to the kept apps, getting-started block (all real values redacted), upstream-sync section.
5. **Prunes `apps/` to the keep list** and cascades the prune through every dependent surface:
   - `apps_config.yaml.example` — sections matching stripped apps removed (infrastructure sections like `CELERY_TASKS`, `ELASTIC_LOGGING` are preserved).
   - `.env/apps.env.example` — env-var blocks for stripped apps removed; redaction still applied.
   - `mcp/server.py` — `APP_REGISTRARS` filtered so the MCP server boots without "skipping module" warnings.
   - `agents/kanban/profiles/examples/agent_*.yaml` — `mcp_apps` lists filtered to kept apps.
   - The README's App Inventory table — rows for stripped apps removed.
6. **Sanitizes secrets** — every credential replaced by `<REPLACE_ME>`. OAuth/service-account JSON files under `.env/` are deleted outright (the host operator obtains fresh ones).
7. **Sweeps the docs** for stale references to stripped folders/apps. Code imports get a `# TODO: re-introduce after building <name>` marker; markdown references are listed in the activation checklist for the consuming team to review.
8. **Initializes git** in the fork (unless `--no-git-init`).
9. **Auto-publishes to GitHub** via `gh repo create` (private by default) and pushes the initial commit. Skipped only if `--no-create-repo` or `--no-push` was passed. The skill verifies `gh auth status` before invoking and never force-pushes.
10. **Prints the activation checklist** with the published URL, file inventory (kept / removed / generated), stale-doc-refs report, and next steps for the host operator.

**Defaults that are non-negotiable unless explicitly overridden:**

- Visibility = `private` (forks may carry client business context).
- Real credentials are never copied — `.env/*` and `apps_config.yaml` are always redacted to `.example` templates.
- The fork's `.claude/` and `.openclaw/` are always stripped (the consuming team installs its own).
- `apps/` is pruned to the curated 16-item keep list (override with `--apps-keep` or `--apps-keep-all`).
- Force-push is never used.

---

### `/new-n8n-workflow`

Builds and deploys an n8n workflow into the local n8n instance at `localhost:5678`.

```
/new-n8n-workflow "when a Jira ticket is created, post a Slack message"
/new-n8n-workflow path/to/diagram.drawio
```

**Accepts:** free-text description, drawio file path, or XML/BPMN file path.

**What it does:**
1. Parses the input into an ordered list of n8n nodes
2. Maps each step to an existing n8n node type (HTTP Request, Webhook, Code, etc.)
3. Generates the n8n workflow JSON
4. Deploys it to the running n8n instance via the n8n REST API
5. Returns a direct link to the workflow in the n8n UI

---

### `/new-service-app`

Scaffolds a complete harqis-work app integration under `apps/<app_name>/`.

```
/new-service-app stripe https://stripe.com/docs/api
/new-service-app openweather                          # skeleton stub only
/new-service-app hubspot https://developers.hubspot.com/docs/api/overview --workflow crm_sync
```

**Arguments:**

| Token | Required | Description |
|---|---|---|
| `app_name` | Yes | snake_case name, e.g. `stripe`, `openweather` |
| `spec_or_url` | No | OpenAPI JSON/YAML URL, local spec file, or docs page URL. Omit for skeleton-only mode. |
| `--workflow <name>` | No | After scaffolding, also create a Celery workflow that uses the new app. |

**Generated structure:**

```
apps/<app_name>/
├── config.py                        # loads section from apps_config.yaml
├── mcp.py                           # registers MCP tools with FastMCP
├── references/
│   ├── web/base_api_service.py      # auth + base HTTP client
│   └── web/api/<resource>.py        # one class per endpoint group
│   └── dto/<resource>.py            # @dataclass DTOs, all fields Optional
└── tests/test_<resource>.py         # live integration tests, @pytest.mark.smoke
```

**Also updates automatically:**
- `mcp/server.py` — registers tools with the MCP server
- `agents/kanban/agent/tools/mcp_bridge.py` — adds to `_APP_LOADERS`
- `apps_config.yaml` — appends new app block with `${ENV_VAR}` placeholders
- `.env/apps.env` — appends empty env var stubs
- `README.md` — adds row to App Inventory table
- `mcp/README.md` — adds tool reference section

---

### `/new-workflow`

Designs and implements an RPA-style Celery workflow that chains multiple app integrations.

```
/new-workflow finance "fetch OANDA rates, summarise with Claude, post to Discord"
/new-workflow hud path/to/diagram.drawio --merge hud_finance.py
/new-workflow purchases "MTG card pipeline" --new-file tcg_resale.py
```

**Arguments:**

| Token | Required | Description |
|---|---|---|
| `category` | Inferred or asked | `desktop`, `finance`, `hud`, `purchases`, `mobile`, or a new one |
| `task_description_or_diagram_path` | Yes | Free-text description or path to a `.drawio`/`.xml` diagram |
| `--merge <file>` | No | Append new task function(s) to an existing task file |
| `--new-file <name>` | No | Force creation of a new task file with this name |

**Steps performed:**

1. Clarifies category, trigger, schedule, apps needed, and credentials
2. Parses drawio/XML diagrams into ordered steps (if a file is provided)
3. Resolves missing `apps/` integrations — calls `/new-service-app` for any app not in the repo
4. **Resolves Python package dependencies (Step 3b):**
   - Identifies packages the task will import that aren't in `requirements.txt`
   - Searches PyPI to confirm the canonical package name and version
   - Installs into `.venv/bin/pip install <package>`
   - Appends `<package>>=<version>` to `requirements.txt`
   - Runs a quick `python -c "import <pkg>"` smoke check
5. Writes the Celery task file following the decorator stack pattern (`@SPROUT.task`, `@log_result`, `@feed`, `@init_meter`)
6. Generates an AI prompt file under `workflows/<category>/prompts/` if Claude is used in the workflow
7. Adds a commented-out schedule block to `workflows/<category>/tasks_config.py`
8. Registers the category import in `workflows/config.py`
9. Wires credentials — checks `apps_config.yaml` and `.env/apps.env`, prints missing snippets
10. Writes tests in `workflows/<category>/tests/`
11. Updates `workflows/<category>/README.md`
12. Prints the activation checklist

**Decorator stack (applied bottom-up, innermost first):**

| Decorator | When to use |
|---|---|
| `@SPROUT.task()` | Always — every task |
| `@log_result()` | Always — ships output to Elasticsearch |
| `@feed()` | When task pushes data to the desktop HUD |
| `@init_meter(...)` | When task controls a Rainmeter widget |

---

### `/run-tests`

Runs pytest for a specific app or the full suite.

```
/run-tests                        # full suite (excludes workflows/)
/run-tests echo_mtg               # apps/echo_mtg/tests/
/run-tests agents/kanban/tests/   # direct pytest path
/run-tests -m smoke               # by marker
```

**Markers in use:**

| Marker | Meaning |
|---|---|
| `smoke` | Fast, read-only integration checks |
| `sanity` | Broader coverage, may write data |
| `integration` | Requires live credentials and external services |

All app tests are live integration tests — no mocking. Kanban agent tests (`agents/kanban/tests/`) are fully offline (75 unit tests).

---

### `/zapier-mcp`

Searches Zapier's 9,000+ app catalogue via the Zapier MCP server, enables actions, infers parameters, and optionally wires them into Celery workflows.

```
/zapier-mcp "send a Slack message when a workflow completes"
/zapier-mcp HubSpot --research
/zapier-mcp "create a Google Calendar event" --enable --workflow hud_calendar_sync
```

**Arguments:**

| Token | Required | Description |
|---|---|---|
| `task_or_app_description` | Yes | Task to accomplish or app name to research |
| `--enable` | No | Auto-enable the best matching action without prompting |
| `--workflow <name>` | No | Scaffold a Celery task that calls the action via REST and trigger `/new-workflow` |
| `--research` | No | Discovery only — list matches, do not enable anything |

**Steps performed:**

1. Verifies Zapier MCP server is connected (prints setup instructions if not)
2. Checks existing `apps/` and MCP tools — uses native integration if it already covers the task
3. Calls `discover_zapier_actions(query=...)` and presents a ranked results table
4. Enables the selected action via `enable_zapier_action`
5. Infers action parameters from task description, workflow context, and `apps_config.yaml`; uses `get_zapier_action_schema` for ambiguous fields
6. Test-executes via `execute_zapier_write_action` or `execute_zapier_read_action`
7. Optionally scaffolds a Celery task using Zapier's REST API (`actions.zapier.com/api/v1/exposed/<id>/execute/`)

**Zapier MCP server setup** (one-time):

```
1. Go to https://mcp.zapier.com → create or open a server
2. Copy your Personal Integration URL from the "Connect" tab
3. Add to .claude/settings.json:
   {
     "mcpServers": {
       "zapier": { "url": "<your-personal-integration-url>" }
     }
   }
4. Restart Claude Code
```

**When to use Zapier vs native `apps/`:**

| Situation | Recommendation |
|---|---|
| App already in `apps/` (Discord, Trello, Jira…) | Use native — faster, more control |
| App not in `apps/`, full integration not justified | Zapier MCP — zero code required |
| Exploring what's available for a new app | `/zapier-mcp <app> --research` |
| Need real-time / sub-second response | Native app preferred |

**Agentic mode tools used:**

| Tool | Purpose |
|---|---|
| `discover_zapier_actions` | Search available apps and actions |
| `enable_zapier_action` | Add an action to your MCP server |
| `list_enabled_zapier_actions` | List currently enabled actions |
| `execute_zapier_write_action` | Run a create/send/update action |
| `execute_zapier_read_action` | Run a search/find/get action |
| `get_zapier_action_schema` | Get full parameter schema for an action |

---

## Adding a New Skill

1. Create `.claude/commands/<skill-name>.md`. The **first line** (before any heading) is the one-line description shown in the skill picker.
2. Add a row to the **Skill Inventory** table above.
3. Add a **Skill Details** section if the skill has flags, multi-step behaviour, or generated file structures worth documenting.
4. Update the overview paragraph in `README.md` if the new skill changes the total skill count.
