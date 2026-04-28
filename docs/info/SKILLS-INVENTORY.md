# Claude Code Skills Inventory

Skills are slash commands available in any Claude Code session opened in this repo. They encode multi-step workflows so Claude executes them end-to-end without step-by-step prompting.

Invoke with `/skill-name [arguments]` in the Claude Code prompt.  
Skill files live in `.claude/commands/*.md`. The first line of each file is the short description shown in the skill picker.

---

## Skill Inventory

| Skill | Command | Description |
|---|---|---|
| **agent-prompt** | `/agent-prompt <prompt_name>` | Run a named AI prompt from `agents/prompts/` against the codebase. `prompt_name` is the filename without extension (e.g. `code_smells`, `docs_agent`, `desktop_analysis`). |
| **generate-registry** | `/generate-registry` | Regenerate `frontend/registry.py` by scanning all `workflows/*/tasks_config.py` files. Run after adding or removing any Celery task. |
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

### `/generate-registry`

Scans all `workflows/*/tasks_config.py` files and rewrites `frontend/registry.py` with the current task list. Run this any time a task is added, renamed, or removed so the frontend dashboard stays in sync.

```
/generate-registry
```

No arguments. Reports what changed (added / removed task keys).

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
