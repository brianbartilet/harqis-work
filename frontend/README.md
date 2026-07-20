# HARQIS Frontend

The HARQIS frontend is an authenticated, module-based interface for operating
and inspecting the automation platform. It is built with FastAPI, Jinja2,
HTMX, Alpine.js, Tailwind CSS, and SortableJS, with no JavaScript build step.

The frontend currently exposes five modules:

| Module | Route | Purpose |
|---|---|---|
| Home | `/home` | Introduces the platform modules. |
| Manifesto | `/manifesto` | Renders `docs/MANIFESTO.md` and the HARQIS guiding principles. |
| Workflows | `/workflows` | Displays Celery workflow categories, task triggers, schedules, status, and run history. |
| Apps | `/applications` | Inventories `apps/*`, renders documentation, and runs controlled pytest checks using host configuration. |
| HFL Corpus | `/hfl-corpus` | Browses and searches the recursive Homework-for-Life Markdown corpus and its references. |

`/dashboard` remains as a compatibility redirect to `/home`.

## Requirements

- Python 3.12+
- The repository `.venv` installed from root `requirements.txt`
- RabbitMQ and a reachable Celery worker for workflow task execution
- Flower for task status polling
- A configured `.env/apps.env` and machine profile for host-backed app tests
- `HFL_CORPUS_PATH` when the corpus is not stored in `logs/hfl`

Markdown rendering additionally uses:

- `Markdown` with fenced-code, table, list, and heading support
- `bleach` to remove unsafe HTML, attributes, and URL protocols

## Running

Production-style startup uses the platform launcher so `.env/apps.env` and the
current machine's `env_vars` are applied before FastAPI imports configuration:

```powershell
# Windows
.venv\Scripts\python.exe scripts\launch.py frontend
```

```bash
# macOS / Linux
.venv/bin/python scripts/launch.py frontend
```

For isolated local branch testing, use a non-production port:

```powershell
$env:PORT = "8081"
.venv\Scripts\python.exe scripts\launch.py frontend
```

Open `http://127.0.0.1:8081`.

The detached/deployed frontend runs without Uvicorn file watching. For
foreground template or Python development, opt into reload explicitly; the
watch scope is limited to `frontend/` so repository log writes cannot trigger
a reload loop:

```powershell
$env:FRONTEND_RELOAD = "true"
.venv\Scripts\python.exe scripts\launch.py frontend
```

## Architecture

```text
frontend/
├── main.py                       # FastAPI composition, auth, middleware, legacy routes
├── web.py                        # Shared templates, page context, auth redirects
├── auth.py                       # Signed session cookies and login rate limiting
├── config.py                     # Pydantic settings from host environment
├── celery_client.py              # Celery dispatch and Flower polling
├── generate_registry.py          # workflows/*/tasks_config.py -> registry.json
├── registry.py                   # Workflow registry compatibility layer
├── modules/
│   ├── registry.py               # Fixed top-level ModuleDefinition registry
│   ├── home/
│   │   └── router.py
│   ├── manifesto/
│   │   ├── router.py
│   │   └── service.py
│   ├── workflows/
│   │   ├── router.py
│   │   └── service.py
│   ├── applications/
│   │   ├── router.py
│   │   ├── inventory.py
│   │   ├── test_runner.py
│   │   └── test_policy.toml
│   └── hfl_corpus/
│       ├── router.py
│       └── corpus.py
├── services/
│   ├── markdown.py               # Shared Markdown render + sanitization
│   └── safe_paths.py             # Root containment and signed references
├── templates/
│   ├── base.html                 # Global module navigation
│   ├── dashboard.html            # Workflow dashboard compatibility template
│   ├── modules/
│   │   ├── home/
│   │   ├── manifesto/
│   │   ├── workflows/
│   │   ├── applications/
│   │   └── hfl_corpus/
│   └── partials/status_panel.html
└── tests/
```

`main.py` does not contain module-specific business logic. It mounts each
module router and owns only shared application concerns. This keeps future
modules independent and testable.

## Adding a Frontend Module

1. Create `frontend/modules/<key>/` with `router.py` and module services.
2. Create templates below `frontend/templates/modules/<key>/`.
3. Add one `ModuleDefinition` to `frontend/modules/registry.py`.
4. Include the router in `frontend/main.py`.
5. Build every template context with `web.page_context()` so authentication,
   navigation, Flower, and active-module state remain consistent.
6. Add route and service tests under `frontend/tests/`.

A module definition supplies:

- `key`: stable internal identifier
- `label`: navigation label
- `route`: top-level authenticated route
- `description`: concise Home-card summary
- `detail`: documentation-grounded explanation of the module

Top-level module order is intentionally fixed. Modules can implement their own
customization below that level.

## Authentication and Shared Security

All module routes use the existing signed session cookie. Unauthenticated HTML
requests redirect to `/login`.

The existing protections remain active:

- Constant-time credential comparison
- Five failed logins per IP per 15-minute window
- HTTP-only, same-site session cookies
- Secure cookies when `BEHIND_PROXY=true`
- `X-Frame-Options`, MIME-sniffing, referrer, and permissions headers
- Startup refusal when password or secret-key defaults remain configured

Markdown is treated as untrusted presentation input. Raw scripts, event
handlers, unsafe attributes, and protocols such as `javascript:` are removed.
External HTTP/HTTPS links open in a normal browser tab with
`noopener noreferrer`.

## Home Module

Home reads and safely renders `docs/MANIFESTO.md` on request. The module cards
summarize existing repository responsibilities:

- Workflows are the Celery orchestration and scheduling layer.
- Applications are reusable integrations with external systems.
- HFL Corpus is the searchable personal and operational knowledge layer.

The displayed descriptions are maintained in the module registry and grounded
in the root README and manifesto; no AI call is made at render time.

## Workflows Module

The Workflows module preserves the original dashboard behavior:

- Workflow categories are sub-tabs within the Workflows parent module.
- Task cards dispatch via `POST /tasks/{workflow}/{task_key}/trigger`.
- Status panels poll `GET /tasks/status/{task_id}` through Flower.
- Polling stops on `SUCCESS`, `FAILURE`, or `REVOKED`.
- The last 20 browser-visible runs per task remain in `localStorage`.
- Workflow sub-tab and task-card ordering remains in the existing
  `harqis_tab_order` and `harqis_card_order_<workflow>` keys.

### Registry generation

At page load the workflow service regenerates `frontend/registry.json` from
`workflows/*/tasks_config.py` and reloads the in-memory registry. Run it
manually after workflow changes when you want to review the generated file:

```powershell
.venv\Scripts\python.exe frontend\generate_registry.py
```

The generator treats task path, queue, and kwargs as authoritative. Existing
labels, descriptions, schedules, manual-only flags, and custom workflow colors
are preserved.

## Applications Module

### Discovery

Application inventory is generated from direct directories below `apps/`.
Hidden directories, `.template`, and caches are excluded. `apps/aaa` is a
normal visible application.

For every application the frontend discovers:

- Every Markdown document recursively, with root `README.md` first
- Pytest files beginning with `test_` or `unit_tests`
- Tests explicitly listed in the safe policy
- Recent persisted test results

Apps without documentation or tests remain visible and show an explicit empty
state.

The Apps inventory supports browser-local drag-and-drop ordering through
**Edit Layout**. Card order is persisted in the `harqis_app_order`
`localStorage` key and can be reset without changing repository data.

### Safe and live tests

`frontend/modules/applications/test_policy.toml` is the only source for tests
that may run without a warning. Paths are repository-relative:

```toml
[safe]
aaa = [
  "apps/aaa/tests/test_dto.py",
]
```

Never infer safety from a filename. If a test has not been audited, leave it
out of the policy.

The UI offers:

- **Run safe tests** — fixed allowlisted paths only
- **Run full suite** — `pytest apps/<app>` after a live-service warning
- **Run individual file** — confirmation unless that path is allowlisted

The browser never supplies arbitrary pytest arguments. App keys and file paths
must match the server-generated inventory.

### Test execution model

Tests run through the active frontend interpreter with the frontend process's
inherited environment. When started through `scripts/launch.py`, that means
`.env/apps.env` plus the current machine's settings are already loaded.

Controls:

- Maximum two active test subprocesses globally
- Maximum one active subprocess per application
- Ten-minute timeout
- Cross-platform process-tree termination for timeout and cancellation
- Output capped at 500,000 characters
- Exact loaded credential values and common token/password patterns redacted
- Results persisted to `logs/frontend/test-runs/<app>/<run-id>.json`

Pytest failures are successful frontend jobs with a `failed` state, not HTTP
500 errors. Spawn errors, timeout, and cancellation have distinct states.

These tests may mutate live external services. The safe policy and warning
dialogs are operational boundaries, not proof that an upstream test is
non-destructive.

## HFL Corpus Module

### Corpus resolution

The frontend has two explicit modes:

- **Canonical-host mode:** when `HFL_CORPUS_API_URL` is empty, read local disk
  using the same path precedence as HFL persistence.
- **Remote mode:** when `HFL_CORPUS_API_URL` is set, read only the authenticated
  canonical API. A missing token, rejected request, or unreachable server is
  shown as a visible error; the UI does not silently fall back to a stale local
  corpus.

Local path precedence:

1. `apps_config.yaml` → `HFL.corpus.path`, when fully resolved
2. `HFL_CORPUS_PATH`
3. `<repo>/logs/hfl`

Every `.md` file below the resolved root is indexed recursively. This includes
daily entries, time capsules, nested directories, and miscellaneous Markdown
logs. The frontend never edits, moves, or deletes corpus content.

### Metadata

For each document:

- Created time is the earliest valid HFL entry header.
- A date-like filename is the second fallback.
- Filesystem birth/creation time, or ctime where unavailable, is the final
  fallback.
- Updated time is filesystem mtime.
- Tags and references are parsed from the canonical `HflEntry` Markdown shape
  without importing the Celery workflow package into the web process.

The canonical host's in-memory index has a 30-second TTL. A page refresh after that interval
observes filesystem changes without a separate database or Elasticsearch.

The Mac host exposes read-only bearer-authenticated endpoints under
`/api/hfl`. The Windows frontend performs those calls server-to-server, so the
API token never appears in browser links or JavaScript. Set the shared secret
in gitignored `.env/apps.env`; set the Windows-specific non-secret URL in
`machines.local.toml`.

### Search

The main page supports:

- Case-insensitive text substring search
- Partial tags beginning with `#`
- A frequency-ranked cloud of the 20 most common tags
- One compact date mode selector (`Created` or `Updated`)
- One native date-picker field each for `From` and `To`

Filter classes combine with AND. Multiple tags must all match, and tag matching
is partial: `#debug` matches both `#debug` and `#debugging`. Results are newest
first, display excerpts, and link to the complete rendered document. The UI
shows at most 200 results while reporting the full match count.

Tag chips on both search results and document pages are links. Selecting one
opens a tag-only corpus search and returns every indexed document with a
matching tag, using the same case-insensitive partial-match behavior.

Opened entries are still rendered from their source Markdown. For presentation
only, canonical HFL fields (`Source`, `Machine`, `Entry ID`, `Moment`, `What
happened`, `Why it stayed`, `Possible use`, `Tags`, and `References`) are separated into readable
paragraphs with bold labels. Indented reference items are normalized into a
Markdown list; source corpus files are never rewritten.

### References and downloads

HTTP and HTTPS references open directly in the browser and are never proxied.
Local reference paths are converted to signed, one-day download tokens only
when the resolved file is inside an allowed root.

Always-allowed roots:

- Resolved HFL corpus root
- Repository root

Additional non-secret roots can be supplied using the host OS path separator:

```powershell
$env:HFL_REFERENCE_ALLOWED_ROOTS = "D:\HFL Media;D:\Archive"
```

```bash
export HFL_REFERENCE_ALLOWED_ROOTS="/srv/hfl-media:/srv/archive"
```

Downloads revalidate existence, file type, containment, symlinks, and token
signature. Missing, directory, expired, tampered, and out-of-root references
are unavailable. Raw host paths are not placed in download URLs.

In remote mode, reference classification and token validation happen on the
Mac. Download links point to an authenticated Windows frontend proxy, which
adds the bearer token server-side and streams the response back to the signed-in
browser. A Windows-only path recorded by an older entry remains visible in the
Markdown but is marked unavailable when it does not exist under an allowed Mac
root. Reference files are not uploaded or mirrored.

## Routes

| Method | Route | Description |
|---|---|---|
| GET | `/` | Redirect to Home or login. |
| GET | `/home` | Module overview. |
| GET | `/manifesto` | Manifesto and guiding principles. |
| GET | `/workflows` | Workflow sub-tabs and task cards. |
| POST | `/tasks/{workflow}/{task}/trigger` | Dispatch a registry task. |
| GET | `/tasks/status/{task_id}` | Poll Flower task state. |
| GET | `/applications` | Application inventory. |
| GET | `/applications/{app}` | App docs, tests, and recent runs. |
| GET | `/applications/{app}/docs/{path}` | Render one app Markdown document. |
| POST | `/applications/{app}/tests` | Start a safe, full, or file test run. |
| GET | `/applications/test-runs/{id}` | Poll persisted/current test status. |
| POST | `/applications/test-runs/{id}/cancel` | Cancel a queued/running test. |
| GET | `/hfl-corpus` | Corpus tree and filtered search. |
| GET | `/hfl-corpus/document/{path}` | Render one corpus Markdown document. |
| GET | `/hfl-corpus/references/{token}/download` | Download an allowed signed reference. |
| GET | `/hfl-corpus/remote-references/{token}/download` | Proxy an allowed canonical-host reference. |
| GET | `/api/hfl/documents` | Bearer-authenticated canonical index and search. |
| GET | `/api/hfl/document/{path}` | Bearer-authenticated canonical Markdown document. |
| GET | `/api/hfl/reference/{token}` | Bearer-authenticated canonical reference download. |
| GET | `/health` | Process health response. |

## Configuration

| Variable | Default | Description |
|---|---|---|
| `APP_USERNAME` | `admin` | Login username. |
| `APP_PASSWORD` | insecure default rejected | Login password. |
| `APP_SECRET_KEY` | insecure default rejected | Session and reference-token signing key. |
| `CELERY_BROKER` | local RabbitMQ | Celery broker used for workflow dispatch. |
| `FLOWER_URL` | `http://localhost:5555` | Flower status API and header link. |
| `FLOWER_USER` / `FLOWER_PASSWORD` | empty | Flower Basic authentication. |
| `HOST` | `0.0.0.0` | Uvicorn bind host. |
| `PORT` | `8080` | Uvicorn bind port. |
| `SESSION_MAX_AGE` | `28800` | Session lifetime in seconds. |
| `BEHIND_PROXY` | `false` | Enables secure cookies behind HTTPS. |
| `FRONTEND_RELOAD` | `false` | Enables frontend-scoped Uvicorn reload for foreground development. |
| `HFL_CORPUS_PATH` | `logs/hfl` | Corpus root when not supplied through app config. |
| `HFL_REFERENCE_ALLOWED_ROOTS` | empty | Additional local reference-download roots. |
| `HFL_CORPUS_API_URL` | empty | Canonical frontend origin; enables exclusive remote mode when set. |
| `HFL_CORPUS_API_TOKEN` | empty | Shared bearer secret for canonical corpus API requests. |

## Testing

Frontend tests must run after loading the machine-scoped environment. The
canonical local command is:

```powershell
@'
import os
from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
load_env_into_os()
os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
os.environ.update(machine_env_vars(load_machine_config(None)))
import pytest
raise SystemExit(pytest.main(["-q", "frontend/tests"]))
'@ | .venv\Scripts\python.exe -
```

Coverage includes module authentication, navigation, inventory discovery,
Markdown sanitization, test redaction, HFL parsing/search/tree construction,
API bearer authentication, signed reference containment, and route rendering. Browser-level validation
should additionally cover drag ordering, HTMX polling, confirmation dialogs,
responsive navigation, corpus filtering, and reference downloads.

## Operational Notes

- Start through `scripts/launch.py frontend` in deployed environments; a bare
  `uvicorn` invocation does not perform machine-context loading.
- Flower is optional for dispatch but required for useful task-state polling.
- Application pytest jobs execute on the frontend host, not a Celery worker.
- The Applications and HFL modules are read-only with respect to source files.
- Deploy/restart the Mac frontend before enabling/restarting a remote Windows
  frontend; otherwise Windows correctly reports the canonical corpus as
  unavailable.
- Do not expose the frontend directly to the public internet. Use a VPN or an
  authenticated HTTPS reverse proxy and set `BEHIND_PROXY=true`.
