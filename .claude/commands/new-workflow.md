Design and implement an RPA-style Celery workflow that chains harqis-work app integrations to automate a task. The workflow passes data between services — output of one app becomes the input of the next.

## Arguments

`$ARGUMENTS` format (parse left to right):

```
[<category>] [<task_description_or_diagram_path>] [--merge <existing_task_file>] [--new-file <filename>]
```

| Token | Required | Description |
|---|---|---|
| `category` | Inferred or asked | Workflow category: `desktop`, `finance`, `hud`, `purchases`, `mobile`, or a new one. Infer from the task description; ask if ambiguous. |
| `task_description_or_diagram_path` | Yes | Free-text description of what the workflow should do, OR a path to a `.drawio`/`.xml` diagram file. |
| `--merge <file>` | No | Append the new task function(s) to an existing task file, e.g. `--merge hud_finance.py`. |
| `--new-file <name>` | No | Force creation of a new task file with this name. If neither `--merge` nor `--new-file` is given, infer from context or ask the user. |

---

## Step 0 — Clarify inputs before writing any code

Before doing any implementation, collect the answers to these questions if they cannot be confidently inferred from `$ARGUMENTS`:

1. **Category** — which workflow category? (`desktop`, `finance`, `hud`, `purchases`, `mobile`, new?)
2. **Trigger** — how should this run? (schedule / on-demand / both)
3. **Schedule** — how often? (crontab pattern, timedelta, or "manual only")
4. **New file or merge** — add to an existing task file or create a new one?
5. **Apps needed** — confirm the app list you derived from the description. Are there apps the user wants to include that you missed?
6. **Credentials/secrets needed** — list any API keys or config you expect and confirm with user before writing env placeholders.

If a diagram file path is provided, parse it first (Step 1b) and use the extracted steps to answer most of these automatically — then only ask about gaps.

---

## Step 1a — Understand the workflow from text description

From the user's description, extract:

- **Goal** — one sentence: what does this workflow accomplish?
- **Input** — what triggers it or what data does it start with?
- **Steps** — numbered sequence of actions, each mapped to a specific app:
  ```
  1. Fetch X from AppA
  2. Transform / filter / enrich data
  3. Send result to AppB
  4. Optionally notify via AppC
  ```
- **Output** — what is the final side-effect or returned value?
- **Apps required** — list of `apps/<name>` modules needed

Check each required app:
```bash
ls apps/
```
For any app not found in the repo, note it as **missing** (handled in Step 3).

---

## Step 1b — Parse diagram file (if a `.drawio`, `.xml`, or similar path is provided)

Read the file. Drawio files are XML — parse the `<mxCell>` elements:
- Nodes (`vertex="1"`) → steps in the workflow (use the `value` attribute as the step label)
- Edges (`edge="1"`, with `source` and `target`) → data flow between steps
- Ellipses / rounded shapes often indicate start/end or decision points

Reconstruct the linear (or branching) flow in order. Map each node to:
1. A workflow step description
2. The most likely app in `apps/` that performs that operation

If the diagram has multiple pages, process all pages unless the user specifies one.

Ask the user to clarify any ambiguous nodes (e.g. a node labelled "process" with no clear app mapping).

---

## Step 2 — Analyse existing patterns

Before writing code, read these files to understand conventions:

```
workflows/.template/tasks/do_random.py        # minimal task pattern
workflows/.template/tasks_config.py           # schedule dict pattern
workflows/finance/tasks/parse_transaction.py  # multi-app RPA pattern with AI
workflows/hud/tasks/hud_calendar.py           # decorator stack pattern
workflows/hud/tasks_config.py                 # full schedule examples (crontab + kwargs + options)
workflows/queues.py                           # WorkflowQueue enum
workflows/config.py                           # how tasks_config dicts are merged
```

Also scan the target category directory for existing tasks and imports to avoid duplication and match style:

```bash
ls workflows/<category>/tasks/
grep -r "from apps\." workflows/<category>/tasks/
```

---

## Step 3 — Resolve missing app dependencies

For each app identified in Step 1 that does NOT exist in `apps/`:

1. Tell the user: `"App '<name>' is not in the repo. I will try to build it."`
2. Search for its public API documentation:
   - Try `WebFetch` on the service's official docs URL (e.g. `https://docs.<service>.com/api`)
   - Or ask the user for the API docs URL or OpenAPI spec
3. Invoke `/new-service-app <app_name> <spec_or_url>` to scaffold the full integration.
4. Wait for that skill to complete, then continue.
5. If the API cannot be found or building fails, mark the step as a **manual stub** and add a `# TODO: implement <app_name> integration` comment in the task.

---

## Step 4 — Create or extend the category directory

**If `workflows/<category>/` does not exist:**
```
workflows/<category>/
├── __init__.py
├── tasks_config.py          # start from .template pattern
├── tasks/
│   ├── __init__.py
│   └── <task_name>.py
├── prompts/
│   └── __init__.py
├── diagrams/                # copy diagram file here if one was provided
└── tests/
    └── __init__.py
```

**If `workflows/<category>/` already exists:**
- Do NOT touch existing files unless explicitly merging (Step 5).
- Only add the new task file and update `tasks_config.py` and `README.md`.

Copy the diagram file (if provided) into `workflows/<category>/diagrams/` for reference.

---

## Step 5 — Write the task implementation

**File location:**
- `--merge <file>` → append to `workflows/<category>/tasks/<file>`
- `--new-file <name>` → create `workflows/<category>/tasks/<name>.py`
- Neither given → infer from the workflow name (e.g. `notify_finance_summary.py`) or ask

**Task anatomy — follow this exact structure:**

```python
"""
workflows/<category>/tasks/<name>.py

<one-paragraph description of what this workflow does and which apps it chains>
"""

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result
from core.utilities.logging.custom_logger import create_logger
from apps.apps_config import CONFIG_MANAGER

# Import only the service classes actually used
from apps.<app_a>.references.web.api.<resource> import ApiService<AppA><Resource>
from apps.<app_b>.references.web.api.<resource> import ApiService<AppB><Resource>

_log = create_logger("<category>.<task_name>")


@SPROUT.task()
@log_result()
def <task_name>(**kwargs):
    """<One-line summary of what this task does>.

    Args:
        cfg_id__<app_a>: Config key for <AppA> (default '<APP_A>').
        cfg_id__<app_b>: Config key for <AppB> (default '<APP_B>').
        <other_param>:   Description.

    Returns:
        <description of the return value or side-effect>
    """
    cfg_id__<app_a> = kwargs.get('cfg_id__<app_a>', '<APP_A>')
    cfg_id__<app_b> = kwargs.get('cfg_id__<app_b>', '<APP_B>')

    cfg__<app_a> = CONFIG_MANAGER.get(cfg_id__<app_a>)
    cfg__<app_b> = CONFIG_MANAGER.get(cfg_id__<app_b>)

    # ── Step 1: Fetch from AppA ──────────────────────────────────────────────
    service_a = ApiService<AppA><Resource>(cfg__<app_a>)
    data = service_a.get_something()
    _log.info("<task_name>: fetched %d item(s) from <AppA>", len(data) if data else 0)

    if not data:
        _log.warning("<task_name>: no data from <AppA>, exiting early")
        return "No data"

    # ── Step 2: Transform / enrich ───────────────────────────────────────────
    processed = [item for item in data if <condition>]

    # ── Step 3: Send to AppB ─────────────────────────────────────────────────
    service_b = ApiService<AppB><Resource>(cfg__<app_b>)
    result = service_b.create_something(processed)
    _log.info("<task_name>: sent %d item(s) to <AppB>", len(processed))

    return f"Processed {len(processed)} item(s)"
```

**Decorator rules (apply only what the task actually needs):**

| Decorator | When to add |
|---|---|
| `@SPROUT.task()` | Always — every task |
| `@log_result()` | Always — ships result to Elasticsearch |
| `@feed()` | When the task pushes data to the desktop HUD |
| `@init_meter(...)` | When the task controls a Rainmeter widget |

Decorators are applied bottom-up — `@SPROUT.task()` must be innermost (closest to the function).

**For AI/Claude steps:** load the prompt from `workflows/<category>/prompts/` (see Step 6). Use `apps.antropic.references.web.base_api_service.BaseApiServiceAnthropic` for the API call. Follow the pattern in `workflows/finance/tasks/parse_transaction.py`.

---

## Step 6 — Generate AI prompts (if Claude / Anthropic is used)

If the workflow includes an AI reasoning, extraction, or generation step, create a prompt file:

```
workflows/<category>/prompts/<task_name>.md
```

The prompt must:
1. Define the role and goal in the first paragraph
2. Specify the exact output format (JSON schema, markdown, plain text)
3. Include 1–2 examples of good output
4. Be loadable via the existing `load_prompt` pattern:

```python
from workflows.<category>.prompts import load_prompt
system_prompt = load_prompt("<task_name>")
```

If `workflows/<category>/prompts/__init__.py` does not already define `load_prompt`, add:

```python
from pathlib import Path

def load_prompt(name: str) -> str:
    path = Path(__file__).parent / f"{name}.md"
    return path.read_text(encoding="utf-8")
```

---

## Step 7 — Add placeholder schedule to `tasks_config.py`

Read `workflows/<category>/tasks_config.py`. If it does not exist, create it from the template pattern.

Add the new task entry as a **commented-out block** so the user can activate it deliberately:

```python
from celery.schedules import crontab
from datetime import timedelta
from workflows.queues import WorkflowQueue

WORKFLOW_<CATEGORY> = {

    # ... existing entries ...

    # ── <task_name> ──────────────────────────────────────────────────────────
    # Inferred schedule: <explain why you chose this schedule>
    # Required kwargs: cfg_id__<app_a>='<APP_A>', cfg_id__<app_b>='<APP_B>'
    # Activate by uncommenting and importing in workflows/config.py
    #
    # 'run-job--<task_name>': {
    #     'task': 'workflows.<category>.tasks.<module>.<task_name>',
    #     'schedule': crontab(<inferred_schedule>),
    #     'kwargs': {
    #         'cfg_id__<app_a>': '<APP_A>',
    #         'cfg_id__<app_b>': '<APP_B>',
    #     },
    #     'options': {
    #         'queue': WorkflowQueue.<QUEUE>,
    #         'expires': 60 * <expiry_seconds>,
    #     },
    # },

}
```

Infer the schedule and queue:
- **timedelta** for sub-minute or short-interval tasks
- **crontab** for hourly/daily/weekly tasks
- Use `WorkflowQueue.HUD` for display tasks, `WorkflowQueue.TCG` for card/purchase tasks, `WorkflowQueue.DEFAULT` for everything else

If you cannot confidently infer the schedule, ask the user before writing the comment.

---

## Step 8 — Register in `workflows/config.py` (commented out)

Read `workflows/config.py`. Add a commented import and merge line so the user can activate with one edit:

```python
# from workflows.<category>.tasks_config import WORKFLOW_<CATEGORY>   # uncomment to activate
# CONFIG_DICTIONARY = CONFIG_DICTIONARY | WORKFLOW_<CATEGORY>          # add to existing merge line
```

If the category is already imported and registered, skip this step.

---

## Step 9 — Wire credentials and config

List every `CONFIG_MANAGER.get(...)` key the task uses. For each one:

1. Check if `apps_config.yaml` already has that section:
   ```bash
   grep -n "<APP_NAME>" apps_config.yaml
   ```
2. If missing, print the snippet the user needs to add to `apps_config.yaml`.
3. Check if `.env/apps.env` already declares the required env vars:
   ```bash
   grep -n "<ENV_VAR>" .env/apps.env 2>/dev/null || echo "not found"
   ```
4. If missing, print the env vars the user needs to add.

Do NOT write secrets to any file. Print them as instructions only.

---

## Step 10 — Write tests

Create `workflows/<category>/tests/test_<task_name>.py`. Do **not** run the tests.

```python
"""
Tests for workflows/<category>/tasks/<module>.<task_name>

These are live integration tests — requires valid credentials in .env/apps.env.
Run manually: pytest workflows/<category>/tests/test_<task_name>.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
from workflows.<category>.tasks.<module> import <task_name>


class TestTaskName:

    @pytest.mark.smoke
    def test_<task_name>_runs_without_error(self):
        """Happy path: task executes and returns a non-empty string."""
        result = <task_name>()
        assert result is not None
        assert isinstance(result, str)

    @pytest.mark.smoke
    def test_<task_name>_handles_empty_data(self):
        """Task returns gracefully when the source app returns no data."""
        with patch('apps.<app_a>.references.web.api.<resource>.ApiService<AppA><Resource>.get_something',
                   return_value=[]):
            result = <task_name>()
        assert "No data" in result or result is not None

    @pytest.mark.integration
    def test_<task_name>_live(self):
        """Live integration test — requires real credentials."""
        result = <task_name>()
        assert result is not None
```

If the user explicitly asks to run tests after writing them:
```bash
pytest workflows/<category>/tests/test_<task_name>.py -v -m "not integration"
```

---

## Step 11 — Update `workflows/<category>/README.md`

If `README.md` exists in the category, **append** a new section for the task. If it does not exist, create it from the template structure.

Section to add/create:

```markdown
### `<task_name>`

**Goal:** <one sentence>

**Apps chained:**
1. `apps/<app_a>` → <what it fetches/does>
2. `apps/<app_b>` → <what it receives/does>

**Schedule:** <crontab or timedelta description, or "manual / on-demand">

**Queue:** `WorkflowQueue.<QUEUE>`

**Required config keys:** `<APP_A>`, `<APP_B>`

**Required env vars:** `<ENV_VAR_1>`, `<ENV_VAR_2>`

**Data flow:**
```
<AppA data> → [filter/transform] → <AppB action> → result
```

**AI prompt:** `workflows/<category>/prompts/<task_name>.md` *(if applicable)*
```

---

## Step 12 — Print the activation checklist

Print this at the end, filled in with the actual values:

```
Workflow created. Manual steps to activate:

  Config & secrets:
  [ ] Add <APP_A> section to apps_config.yaml  (snippet printed above if missing)
  [ ] Add <APP_B> section to apps_config.yaml  (snippet printed above if missing)
  [ ] Add env vars to .env/apps.env:
        <ENV_VAR_1>=
        <ENV_VAR_2>=

  Schedule activation:
  [ ] Review and uncomment the schedule in workflows/<category>/tasks_config.py
  [ ] Uncomment the import + merge line in workflows/config.py
  [ ] Restart Celery Beat to pick up the new task

  Testing:
  [ ] pytest workflows/<category>/tests/test_<task_name>.py -v -m "not integration"
  [ ] pytest workflows/<category>/tests/test_<task_name>.py -v -m integration  (live, needs creds)
```

---

## Decision guide — new file vs merge

| Situation | Action |
|---|---|
| New category that doesn't exist yet | Create new task file |
| Task clearly belongs with existing tasks (same app group) | Merge into existing file |
| Task is a standalone pipeline unrelated to existing tasks | New file |
| User passed `--merge` | Always merge |
| User passed `--new-file` | Always new file |
| Ambiguous | Ask the user |

---

## RPA chaining patterns

Use these patterns when connecting apps. Pick the one that fits the data flow:

**Sequential (A → B → C):**
```python
data_a = service_a.get_something()
enriched = service_b.enrich(data_a)
service_c.send(enriched)
```

**Fan-out (A → B and A → C independently):**
```python
data = service_a.get_something()
service_b.send(data)
service_c.notify(data)
```

**Conditional branch:**
```python
data = service_a.get_something()
if <condition>:
    service_b.handle_case_one(data)
else:
    service_c.handle_case_two(data)
```

**Aggregation (A + B → C):**
```python
data_a = service_a.get_something()
data_b = service_b.get_something()
combined = merge(data_a, data_b)
service_c.send(combined)
```

**AI-in-the-loop (A → Claude → B):**
```python
raw = service_a.get_raw_data()
prompt = load_prompt("<task_name>")
structured = call_claude(prompt, raw)   # see finance/tasks/parse_transaction.py
service_b.save(structured)
```

---

## Available queues

| Queue | Use when |
|---|---|
| `WorkflowQueue.DEFAULT` | General background tasks, desktop operations |
| `WorkflowQueue.HUD` | Tasks that push data to the Rainmeter desktop display |
| `WorkflowQueue.TCG` | TCG card / purchase pipeline tasks |
| `WorkflowQueue.ADHOC` | On-demand / manually triggered tasks |
