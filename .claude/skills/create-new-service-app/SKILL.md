Scaffold a complete app integration under `apps/` — either from an OpenAPI spec / docs URL (full generation) or as a named stub (skeleton only).

## Arguments

`$ARGUMENTS` format (parse left to right):

```
<app_name> [<spec_or_url>] [--workflow <workflow_name>]
```

| Token | Required | Description |
|---|---|---|
| `app_name` | Yes | snake_case name, e.g. `stripe`, `openweather` |
| `spec_or_url` | No | OpenAPI JSON/YAML URL, local spec file path, or docs page URL. Omit for skeleton-only mode. |
| `--workflow <name>` | No | After finishing, also scaffold a Celery workflow that uses this app. |

**Mode A — skeleton only:** `app_name` is the only argument. Create the directory structure with stub implementations and TODO comments. User fills in service logic manually.

**Mode B — from spec/URL:** `app_name` + `spec_or_url`. Fetch and parse the spec, then generate real implementations for all discovered endpoints.

---

## Step 1 — Fetch and analyse the API spec (Mode B only; skip for Mode A)

**If `spec_or_url` ends in `.json`, `.yaml`, `.yml`, or contains `openapi` / `swagger`:**
Fetch with `WebFetch` (or `Read` if a local path). Parse the OpenAPI object:
- `info.title`, `info.description` → app description
- `servers[0].url` → `base_url`
- `components.securitySchemes` → auth type (Bearer, API key, OAuth2, Basic, query param)
- `paths` → group endpoints by first path segment into service files
- `components.schemas` → DTO field names and types

**If `spec_or_url` is a documentation web page:**
Fetch with `WebFetch`. Extract:
- API base URL (look for `https://api.` patterns or explicit base URL statements)
- Auth method (look for "Authorization", "Bearer", "API key", "OAuth" headings)
- Endpoint list (HTTP method + path + description)
- Response field descriptions for DTOs

Summarise findings before writing any file:
- Base URL
- Auth method
- Endpoint groups → planned service files
- DTO fields per resource

For **Mode A**, set `base_url = "https://api.example.com/v1/"` as a placeholder and auth as Bearer. All service methods will be stubs.

---

## Step 2 — Create directory structure

```
apps/APP_NAME/
├── __init__.py
├── config.py
├── mcp.py
├── references/
│   ├── __init__.py
│   ├── dto/
│   │   ├── __init__.py
│   │   └── <resource>.py        # one DTO file per resource group
│   └── web/
│       ├── __init__.py
│       ├── base_api_service.py
│       └── api/
│           ├── __init__.py
│           └── <resource>.py    # one service file per endpoint group
└── tests/
    ├── __init__.py
    └── test_<resource>.py       # one test file per service class
```

Create all `__init__.py` as empty files.

For **Mode A**, create one placeholder resource file (`resource.py`) with TODO stubs.
For **Mode B**, create one file per discovered endpoint group.

---

## Step 3 — Write `apps/APP_NAME/config.py`

Always the same pattern — do not deviate. Mirrors `apps/.template/config.py`:

```python
from apps.config_loader import app_name_for, get_ws_config

APP_NAME = app_name_for(__file__)
CONFIG = get_ws_config(__file__)
```

Do **not** instantiate `ConfigLoaderService` directly here. The centralized helper routes through `apps.apps_config.CONFIG_SERVICE`, which honours the `CONFIG_SOURCE` env var (local / redis / http) and is built once with an explicit `base_path=ENV_APP_CONFIG`. A direct `ConfigLoaderService(file_name=...)` call falls back to `os.getcwd()` and walks upward, which can pick up a stale `apps_config.yaml` from a sibling repo (e.g. `harqis-core`) and silently hand the worker the wrong config.

---

## Step 4 — Write `apps/APP_NAME/references/web/base_api_service.py`

Choose the auth pattern from the table below. For **Mode A** default to Bearer and add a TODO.
Reference apps: `apps/trello/references/web/base_api_service.py` (query-param), `apps/jira/references/web/base_api_service.py` (Bearer), `apps/telegram/references/web/base_api_service.py` (token in URL path).

**Bearer token (Authorization header):**
```python
from core.web.services.fixtures.rest import BaseFixtureServiceRest
from core.web.services.core.constants.http_headers import HttpHeaders

class BaseApiServiceAPP_NAME(BaseFixtureServiceRest):
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.client.session.headers.update({
            HttpHeaders.AUTHORIZATION: f'Bearer {config.app_data["api_key"]}',
            HttpHeaders.CONTENT_TYPE: 'application/json',
        })
```

**API key as query param (e.g. Trello / Gemini style):**
```python
class BaseApiServiceAPP_NAME(BaseFixtureServiceRest):
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.request \
            .add_header(HttpHeaders.CONTENT_TYPE, 'application/json') \
            .add_query_string('key', config.app_data['api_key'])
```

Note: always use `self.request.add_query_string()` in `__init__` — **never** `self.client.session.params` (session is not initialized at construction time in this framework).

**Token in URL path (e.g. Telegram style):**
```python
class BaseApiServiceAPP_NAME(BaseFixtureServiceRest):
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        token = config.app_data['api_key']
        self.client.base_url = f"{self.client.base_url}/{token}"
```

**Basic auth (username + password):**
```python
class BaseApiServiceAPP_NAME(BaseFixtureServiceRest):
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        import base64
        creds = base64.b64encode(
            f"{config.app_data['username']}:{config.app_data['password']}".encode()
        ).decode()
        self.client.session.headers.update({
            HttpHeaders.AUTHORIZATION: f'Basic {creds}',
        })
```

Replace `APP_NAME` with the PascalCase form of the app name throughout.

---

## Step 5 — Write DTOs in `apps/APP_NAME/references/dto/<resource>.py`

One file per resource group. Use `@dataclass` with all fields `Optional` and defaulting to `None`.

```python
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class DtoAPP_NAMEResource:
    id: Optional[str] = None
    name: Optional[str] = None
    created_at: Optional[str] = None
    # Mode B: add every field from the API schema
    # Mode A: add a TODO comment: # TODO: add response fields
```

For **Mode B**, include every field found in the API schema.
For **Mode A**, add two or three representative stub fields and a TODO.

---

## Step 6 — Write API service classes in `apps/APP_NAME/references/web/api/<resource>.py`

One class per endpoint group. Inherit from `BaseApiService{APP_NAME}`. Use `@deserialized` for typed return values. Name methods: `list_*`, `get_*`, `create_*`, `update_*`, `delete_*`, `search_*`.

```python
from typing import List
from core.web.services.core.decorators.deserializer import deserialized
from apps.APP_NAME.references.web.base_api_service import BaseApiServiceAPP_NAME
from apps.APP_NAME.references.dto.resource import DtoAPP_NAMEResource

class ApiServiceAPP_NAMEResources(BaseApiServiceAPP_NAME):

    def __init__(self, config, **kwargs):
        super().__init__(config, **kwargs)

    @deserialized(List[DtoAPP_NAMEResource])
    def list_resources(self) -> List[DtoAPP_NAMEResource]:
        """Return all resources."""
        self.request.get().add_uri_parameter('resources')
        return self.client.execute_request(self.request.build())

    @deserialized(DtoAPP_NAMEResource)
    def get_resource(self, resource_id: str) -> DtoAPP_NAMEResource:
        """Return a single resource by ID."""
        self.request.get().add_uri_parameter(f'resources/{resource_id}')
        return self.client.execute_request(self.request.build())

    def create_resource(self, name: str, **kwargs) -> dict:
        """Create a new resource."""
        payload = {'name': name, **kwargs}
        self.request.post().add_uri_parameter('resources').set_body(payload)
        return self.client.execute_request(self.request.build())
```

For **Mode B**, map every endpoint from Step 1. For **Mode A**, write one stub `list_resources` method with a `# TODO: implement` body and `raise NotImplementedError`.

---

## Step 7 — Write `apps/APP_NAME/mcp.py`

Expose every useful operation as an MCP tool. Every `@mcp.tool()` must have:
- A descriptive docstring
- An `Args:` section for every non-trivial parameter
- `logger.info(...)` at entry and on result
- Defensive `isinstance` check on the return value

```python
import logging
from mcp.server.fastmcp import FastMCP
from apps.APP_NAME.config import CONFIG
from apps.APP_NAME.references.web.api.resource import ApiServiceAPP_NAMEResources

logger = logging.getLogger("harqis-mcp.APP_NAME")


def register_APP_NAME_tools(mcp: FastMCP):

    @mcp.tool()
    def list_APP_NAME_resources() -> list[dict]:
        """List all APP_NAME resources."""
        logger.info("Tool called: list_APP_NAME_resources")
        service = ApiServiceAPP_NAMEResources(CONFIG)
        result = service.list_resources()
        result = result if isinstance(result, list) else []
        logger.info("list_APP_NAME_resources returned %d item(s)", len(result))
        return [r.__dict__ if hasattr(r, '__dict__') else r for r in result]

    @mcp.tool()
    def get_APP_NAME_resource(resource_id: str) -> dict:
        """Get a specific APP_NAME resource by ID.

        Args:
            resource_id: The unique identifier of the resource.
        """
        logger.info("Tool called: get_APP_NAME_resource id=%s", resource_id)
        service = ApiServiceAPP_NAMEResources(CONFIG)
        result = service.get_resource(resource_id)
        return result.__dict__ if hasattr(result, '__dict__') else (result if isinstance(result, dict) else {})
```

For **Mode A**, write stub tools that return `{"status": "not implemented"}` and a TODO comment.

---

## Step 8 — Register in `mcp/server.py`

Read `mcp/server.py`. Find the last `register_*_tools(mcp)` block. Add immediately after it:

```python
from apps.APP_NAME.mcp import register_APP_NAME_tools
# ...
logger.info("Registering APP_NAME tools...")
register_APP_NAME_tools(mcp)
```

---

## Step 9 — Register in `agents/projects/agent/tools/mcp_bridge.py`

Read `agents/projects/agent/tools/mcp_bridge.py`. Find the `_APP_LOADERS` dict. Add a new entry in alphabetical order by key:

```python
"app_name":    "apps.app_name.mcp.register_app_name_tools",
```

Where `app_name` is the snake_case app name and `register_app_name_tools` is the function defined in `apps/APP_NAME/mcp.py`. Preserve the column-alignment style of the existing entries.

---

## Step 9b — Update Kanban dependency detector  ← **MANDATORY if the new app has any env var**

Read `agents/projects/dependencies/detector.py`. Add a new entry to the `_SERVICE_SECRETS` list so the orchestrator can short-circuit cards that mention this service when its credentials are missing.

```python
# In _SERVICE_SECRETS, add — alphabetised within the existing category comment block:
(r"\bAPP_NAME_UPPER\b",   "APP_NAME_UPPER_API_KEY"),
```

Rules:
- The **regex** matches what humans write on Kanban cards. Use `\b` word boundaries. If the app has common aliases (e.g. `OpenAI` ↔ `GPT`, `Grok` ↔ `xAI`, `Perplexity` ↔ `Sonar`, `Moo` ↔ `Futu`), include them with `|` alternation. Use `\s*` between words for products with optional whitespace (e.g. `OWN\s*TRACKS` matches both "OwnTracks" and "Own Tracks").
- The **env var name** must match the key in `.env/apps.env` and the `${VAR}` reference in `apps_config.yaml` **exactly**. If they don't match, the agent will be blocked even when the credential is configured (just under a different name).
- For OAuth services that store tokens in files (e.g. `credentials.json` + `storage-*.json`), use the **shared API key** as a coarse readiness signal rather than naming a non-existent token env var.
- For services with multiple required vars (e.g. OAuth client_id + secret + access_token), pick the **most specific** one — typically the access/bearer token. The agent's actual app config will fail loudly on any other missing var, so naming all of them isn't worth the noise.
- Apps with **no** env var at all (filesystem, browser, playwright, scryfall, etc.) get **no entry** here — there's nothing to detect.

After editing, run a quick sanity check:
```python
from agents.projects.dependencies.detector import DependencyDetector
mapping = dict(DependencyDetector._SERVICE_SECRETS)
assert "APP_NAME_UPPER_API_KEY" in mapping.values()
```

### Optional — update agent profiles

If the new app should be available to existing agent profiles (`agents/projects/profiles/examples/agent_*.yaml`), add the env var to each profile's `secrets.required` list. Keep alphabetical order within each profile. Do **not** add it to `base.yaml` (that's the minimum core set — orchestrator deps only).

Decide based on the agent type:
- `agent_code.yaml` — tools that read/write code, run shell commands, use most APIs
- `agent_write.yaml` — tools that produce content (docs, social posts) — likely needs comms apps
- `agent_full.yaml` — superset; almost always include

If unsure, leave profile updates to the user — they know which agents are meant to call this app.

---

## Step 10 — Update `apps_config.yaml`

Read `apps_config.yaml`. Append the new app block at the end of the file. Match the exact YAML formatting style used by other entries (2-space indent, single-quoted strings for app_id and client, `True`/`False` for booleans).

Derive the env var names from the auth type determined in Steps 1/4:

| Auth type | `app_data` fields |
|---|---|
| Bearer / API key (header or query) | `api_key: ${APP_NAME_UPPER_API_KEY}` |
| Basic auth | `username: ${APP_NAME_UPPER_USERNAME}` · `password: ${APP_NAME_UPPER_PASSWORD}` |
| OAuth2 | `client_id: ${APP_NAME_UPPER_CLIENT_ID}` · `client_secret: ${APP_NAME_UPPER_CLIENT_SECRET}` · `access_token: ${APP_NAME_UPPER_ACCESS_TOKEN}` |

`APP_NAME_UPPER` = `app_name` converted to SCREAMING_SNAKE_CASE (e.g. `my_app` → `MY_APP`).

Standard block template:
```yaml


APP_NAME_UPPER:
  app_id: 'app_name'
  client: 'rest'
  parameters:
    base_url: '<BASE_URL_FROM_STEP_1>'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    api_key: ${APP_NAME_UPPER_API_KEY}
  return_data_only: True
```

Adjust `app_data` fields to match the actual auth type. Set `stream: True` if the API supports streaming.

---

## Step 11 — Update `.env/apps.env`

Read `.env/apps.env`. Check whether the app's env var(s) are already present (grep for `APP_NAME_UPPER`). If **not** present, append a new section at the end of the file:

```
# APP_NAME_UPPER
APP_NAME_UPPER_API_KEY=
```

Add one line per env var identified in Step 9 (all set to empty — the user fills in the real value). Do **not** add a section if any of the app's env vars already exist in the file.

---

## Step 12 — Write tests in `apps/APP_NAME/tests/test_<resource>.py`

One test file per service class. All tests are live integration tests — no mocking.
Use `@pytest.mark.smoke` for fast read-only checks, `@pytest.mark.sanity` for broader coverage.

```python
import pytest
from hamcrest import assert_that, not_none, instance_of

from apps.APP_NAME.references.web.api.resource import ApiServiceAPP_NAMEResources
from apps.APP_NAME.config import CONFIG


@pytest.fixture()
def given():
    return ApiServiceAPP_NAMEResources(CONFIG)


@pytest.mark.smoke
def test_list_resources(given):
    when = given.list_resources()
    assert_that(when, instance_of(list))


@pytest.mark.smoke
def test_get_resource(given):
    items = given.list_resources()
    assert_that(items, not_none())
    if items:
        when = given.get_resource(items[0].id)
        assert_that(when.id, not_none())
```

For **Mode A**, mark tests with `@pytest.mark.skip(reason="not implemented")`.

---

## Step 13 — Write `apps/APP_NAME/README.md`

Follow `apps/.template/README.md` structure exactly. Required sections:

1. **Description** — what the service is, API docs link, auth method used
2. **Supported Automations** — tick the applicable boxes (`webservices`, `browser`, `desktop`, `mobile`, `iot`)
3. **Directory Structure** — the actual file tree for this app
4. **Configuration** — ready-to-paste `apps_config.yaml` snippet and all required env vars
5. **Available Services** — table: service class → methods → what each does
6. **MCP Tools** — table: tool name → args → description (must match `mcp.py` exactly)
7. **Tests** — run commands, what credentials are needed
8. **Notes** — rate limits, OAuth flows, pagination, quirks, known issues

---

## Step 14 — Update root `README.md`  ← **MANDATORY — never skip**

Read `README.md`. Make **three** targeted edits. These edits are **required** regardless of whether a spec was provided, the app is a skeleton, or the app has no external API. If this step is skipped the App Inventory and Configuration docs go out of sync with the codebase.

1. **App Inventory table** (under `## App Inventory`) — add a row in **alphabetical order by app name**:
   ```
   | `APP_NAME` | <one-line description> | REST API | Yes | [API Docs](<url>) · [Site](<url>) |
   ```
   - For local/no-config apps (git, filesystem, playwright, browser) use `Local` for Type and `No` for Tests and `—` for Links.
   - For stub/skeleton apps use `Stub` for Type and `No` for Tests.

2. **Directory Structure `apps/` block** — add in **alphabetical order**:
   ```
   │   ├── APP_NAME/                   # <short description>
   ```

3. **Environment Variables block** (under `## Configuration` → `### Environment Variables (.env/apps.env)`) — append the new app's env var(s) under the matching category section (or add a new `# ── <Category> ──` section if none fits):
   ```env
   # ── My category ──...
   APP_NAME_UPPER_API_KEY=
   ```
   - All values **must be blank** — never paste real keys into README.md.
   - Match the env var names you added to `.env/apps.env` in Step 11 exactly.
   - For local/no-config apps (no env vars), skip this edit.

---

## Step 15 — Update `mcp/README.md`

Read `mcp/README.md`. Add a new `### APP_NAME` section (alphabetical position) with:
- Heading linking to the API docs
- `"Requires valid APP_NAME section in apps_config.yaml."`
- Tool table: `| tool_name | args | returns |`
- 2–3 example prompts in italics

---

## Step 16 — Remind the user

Print this checklist verbatim at the end:

```
Next steps:
  [ ] Fill in APP_NAME_UPPER_API_KEY (and any other vars) in .env/apps.env
  [ ] Run: pytest apps/APP_NAME/tests/ -m smoke
  [ ] Restart the MCP server / Claude Desktop to load the new tools
  (apps_config.yaml updated ✓ — Kanban bridge registered ✓)
```

---

## Chaining to a new workflow (--workflow flag)

If `--workflow <workflow_name>` was passed, after completing all steps above run `/create-new-workflow <workflow_name>` and in that workflow:
- Import the new app's service classes in the task files
- Propose 1–3 useful scheduled tasks based on what the API provides (e.g. daily summary, alert on new items, periodic sync)
- Name tasks clearly after the app and the action (e.g. `fetch_APP_NAME_daily_report`)

---

## Quality checklist (verify before finishing)

- [ ] All `__init__.py` files created
- [ ] `config.py` uses the exact standard pattern — no deviations
- [ ] Base service class name is `BaseApiService{PascalCase}`
- [ ] All service classes inherit from the base service
- [ ] All DTO fields are `Optional` with `None` defaults
- [ ] Every MCP tool has a docstring, `Args:` section, entry log, and defensive return check
- [ ] `mcp/server.py` registration added
- [ ] Kanban bridge `_APP_LOADERS` entry added in `agents/projects/agent/tools/mcp_bridge.py`
- [ ] **Kanban dependency detector** entry added in `agents/projects/dependencies/detector.py:_SERVICE_SECRETS` (skip only if the app has zero env vars) — env var name matches `.env/apps.env` exactly
- [ ] `apps_config.yaml` updated with APP_NAME_UPPER section
- [ ] `.env/apps.env` updated with env var placeholder(s)
- [ ] Tests use `hamcrest` and `@pytest.mark.smoke`; Mode A tests are `@pytest.mark.skip`
- [ ] `apps/APP_NAME/README.md` covers config snippet, env vars, and tool table
- [ ] **Root `README.md` App Inventory row added** (alphabetical, under `## App Inventory`) ← easy to forget
- [ ] **Root `README.md` Directory Structure `apps/` line added** (alphabetical) ← easy to forget
- [ ] **Root `README.md` Configuration block updated** with the new env var(s), values blank ← easy to forget
- [ ] `mcp/README.md` section added
