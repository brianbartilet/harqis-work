# HARQIS Frontend

The HARQIS frontend is an authenticated, module-based interface for operating
and inspecting the automation platform. It is built with FastAPI, Jinja2,
HTMX, Alpine.js, Tailwind CSS, and SortableJS. Production serves compiled,
content-versioned assets from `/static/`; the generated files are committed so
runtime deployment does not require Node.js.

The frontend currently exposes seven modules:

| Module | Route | Purpose |
|---|---|---|
| Home | `/home` | Introduces the platform modules. |
| Manifesto | `/manifesto` | Renders `docs/MANIFESTO.md` and the HARQIS guiding principles. |
| Workflows | `/workflows` | Displays Celery workflow categories, task triggers, schedules, status, and run history. |
| Apps | `/applications` | Inventories `apps/*`, renders documentation, and runs controlled pytest checks using host configuration. |
| Activity Corpus | `/hfl-corpus` | Browses and searches HARQIS activity logs, based on the Homework for Life reflection practice, and their references. |
| Social | `/sharing` | Builds reviewed, immutable Activity Corpus snapshots and temporary guest portals. |
| Git Forks | `/git-forks` | Maps fork drift and launches guarded synchronization, regression, and isolated deployment operations. |

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

## Frontend assets

The owner UI does not load Tailwind, HTMX, Alpine.js, or SortableJS from public
CDNs. Pinned npm packages build the committed files under `frontend/static/`:

```bash
npm ci
npm run build:frontend-assets
```

Run the build whenever template utility classes or pinned dependency versions
change. The runtime does not need Node.js because generated assets are tracked.
Rendered URLs include a content digest query, static responses are cacheable for
one year with `immutable`, and authenticated/dynamic responses use
`Cache-Control: no-store`.

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
│   ├── git_forks/
│   │   └── router.py
│   ├── hfl_corpus/
│   │   ├── router.py
│   │   └── corpus.py
│   └── hfl_shares/
│       ├── router.py              # Owner workspace + isolated guest routes
│       ├── scope.py               # Source-first snapshot construction
│       ├── store.py               # SQLite recipes, grants, and sessions
│       ├── security.py            # Capability, PIN, CSRF, and cookie signing
│       ├── agent.py               # Snapshot-only Q&A
│       └── audit.py               # sharing-audit HFL persistence
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
│   │   ├── git_forks/
│   │   ├── hfl_corpus/
│   │   └── hfl_shares/
│   └── share_base.html            # Dependency-free guest portal shell
│   └── partials/status_panel.html
├── assets/tailwind.css             # Tailwind build input
├── static/                         # Committed compiled CSS and pinned vendor JS
├── scripts/vendor-assets.mjs       # Copies pinned npm browser assets
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
- Activity Corpus is the searchable HARQIS activity-log layer, based on the Homework for Life reflection practice.

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

## Activity Corpus Module

The user-facing name is **Activity Corpus**. Internal route, package, API, and
environment names retain `hfl` / `HFL_*` for compatibility with the underlying
Homework for Life ingestion and persistence workflow.

### Corpus resolution

The frontend has two explicit modes:

- **Canonical-host mode:** when `HFL_CORPUS_API_URL` is empty, read local disk
  and persist manually created entries through the canonical HFL writer.
- **Remote mode:** when `HFL_CORPUS_API_URL` is set, read and create entries
  through the authenticated canonical API. A missing token, rejected request,
  or unreachable server is shown as a visible error; the UI does not silently
  fall back to a stale local corpus.

Local path precedence:

1. `apps_config.yaml` → `HFL.corpus.path`, when fully resolved
2. `HFL_CORPUS_PATH`
3. `<repo>/logs/hfl`

Every `.md` file below the resolved root is indexed recursively except files
inside dot-directories such as `.migrations` and `.media-ingest-state`. This
includes daily entries, the visible `time-capsule/` directory, `YYYY/Mon/`
archives, and miscellaneous Markdown logs. The frontend only writes corpus
content through **Create entry**; it never moves or deletes corpus content.

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

The canonical host exposes bearer-authenticated read endpoints and a manual
entry write endpoint under `/api/hfl`. A remote frontend performs those calls
server-to-server, so the API token never appears in browser links or
JavaScript. Set the shared secret in gitignored `.env/apps.env`; set the
remote frontend's non-secret URL in `machines.local.toml`.

### Create entry

Authenticated users can create a canonical HFL entry from the corpus index.
The browser supplies local date/time defaults and shows a rendered review
before saving. The canonical writer updates or creates the selected
`YYYY-MM-DD.md`, keeps its entries ordered by timestamp descending, applies
canonical source/machine/entry-ID metadata, and upserts the Elasticsearch
projection. Remote mode sends the same payload to the canonical host.

The form also accepts up to ten attachments from desktop or mobile browsers.
Selected files appear in the rendered review as their future canonical
references, but no bytes are transferred until the user confirms the save.
Confirmation shows byte-level upload progress, followed by a server-processing
state. Remote frontends stream the multipart request to the canonical host;
they never retain a local copy.

The canonical host stores attachments under the configured dumps inbox:

```text
<harqis_server_inbox>/uploads/YYYY-MM-DD/<entry-id>/<sanitized-original-filename>
```

The resulting absolute paths are appended to manually entered references.
Uploads accept any file type, with limits of 50 MB per file, 200 MB combined,
and ten files per entry. Files are staged before commit, existing files are
never overwritten, and a failed save removes newly committed attachments.
Re-uploading files for a duplicate manual entry merges the new paths into the
existing entry rather than adding another entry block.

### Search

The main page supports:

- Case-insensitive text substring search
- Partial tags beginning with `#`
- An entry-aware Source dropdown populated from distinct corpus `Source:` values
- A frequency-ranked cloud of the 20 most common tags
- One compact date mode selector (`Created` or `Updated`)
- One native date-picker field each for `From` and `To`

Filter classes combine with AND. Multiple tags must all match, and tag matching
is partial: `#debug` matches both `#debug` and `#debugging`. When Source is
selected, each result must contain an entry where that source and the current
text/tag query match together; inline matching-entry counts use the same rule.
Results are newest first, display excerpts, and link to the complete rendered
document. The UI shows at most 200 results while reporting the full match count.

Tag chips on both search results and document pages are links. Selecting one
opens a tag-only corpus search and returns every indexed document with a
matching tag, using the same case-insensitive partial-match behavior.

### Secret entries

Profile Settings stores a salted hash of a six-digit owner PIN and a
comma-separated protected-tag list. `#secrets` is always protected; configured
tags are normalized without their leading `#` and matched exactly and
case-insensitively. This is an authenticated-frontend privacy screen only:
Markdown, Elasticsearch, MCP, RAG, and direct filesystem consumers are not
encrypted or filtered.

Activity Corpus search and document views hide protected entries by default.
Protected tags remain in the tag cloud, but locked searches return no protected
entry content. An owner can unlock for the current browser session, then enable
**Show secrets** on a page or reveal one blurred document entry. Mixed documents
retain their ordinary entries; opening or saving the raw editor requires the
same active unlock. Remote-reader mode passes the configured classification to
the canonical API so filtering occurs before entry text crosses the network.

Social recipes persist an **Include secrets** intent, but preview, agent tests,
instant share, and generation require an active owner unlock. Generated guest
snapshots use their existing share access controls and never expose the owner
PIN.

Opened entries are still rendered from their source Markdown. For presentation
only, canonical HFL fields (`Source`, `Machine`, `Entry ID`, `Moment`, `What
happened`, `Why it stayed`, `Possible use`, `Tags`, and `References`) are separated into readable
paragraphs with bold labels. Indented reference items are normalized into a
Markdown list; source corpus files are never rewritten.

### References and downloads

HTTPS references open directly in the browser and are never proxied. Plain
`http://` references are omitted from rendered documents and rejected by new
HFL persistence. Local reference paths are converted to signed, one-day
download tokens only when the resolved file is inside an allowed root. The
same signed links appear in each entry's `References:` list and in the compact
document-level References summary.

Always-allowed roots:

- Resolved HFL corpus root
- Repository `logs/` directory
- `<harqis_server_inbox>/uploads` when the dumps target is configured

Additional non-secret roots can be supplied using the host OS path separator:

```powershell
$env:HFL_REFERENCE_ALLOWED_ROOTS = "D:\HFL Media;D:\Archive"
```

```bash
export HFL_REFERENCE_ALLOWED_ROOTS="/srv/hfl-media:/srv/archive"
```

Downloads revalidate existence, file type, containment, symlinks, and token
signature. Missing, directory, expired, tampered, and out-of-root references
are silently omitted. Canonical host paths are visible as requested link
labels, but are not placed directly in download URLs.

In remote mode, reference classification and token validation happen on the
Mac. Download links point to an authenticated Windows frontend proxy, which
adds the bearer token server-side and streams the response back to the signed-in
browser. A path that does not exist under an allowed Mac root is omitted.
Reference files are not uploaded or mirrored.

Historical HTTP cleanup is available through a dry-run-first migration:

```bash
python scripts/agents/hfl/migrate_references.py
python scripts/agents/hfl/migrate_references.py --apply
```

Apply mode backs up affected Markdown files and Elasticsearch documents under
the gitignored `.harqis-data/hfl-reference-migrations/` directory before
updating either store. Reports contain only counts and entry IDs.

## Social Module

Social exposes an authenticated owner workspace at `/sharing` and a separate,
navigation-free guest portal below `/share`. On a remote frontend it reads the
source catalogue and source-scoped entry text through the authenticated
canonical corpus API; local-file references remain unavailable there. A saved configuration is a
reusable recipe, not a permission grant or a stored result. Its source, tag,
date, topic, and entry-ID filters are recalculated whenever the owner previews
or generates. Generation then freezes the current matches into an immutable
snapshot; later recipe edits, corpus changes, or recipe deletion cannot alter
an existing share.

When `HFL_CORPUS_API_URL` enables remote-reader mode, Social uses only the
canonical API and fails closed if that host is unavailable. It never falls
back to the remote frontend's local filesystem.

The owner workflow supports:

- one or more required corpus sources as the primary scope boundary;
- optional tag, date, natural-language topic, and explicit entry-ID filters;
- reusable owner-only test prompts and snapshot-constrained preview chat;
- PIN, Cloudflare email OTP, manual approval, and QR-possession access modes;
- configurable expiry, device/session count, and single-use redemption;
- reference sharing disabled by default, with individual files enabled only
  after preview;
- QR, a pasteable capability link, and a PIN displayed only in the generation
  response; and
- immediate revocation of the share and every active guest session.

Guests can browse/search only the frozen entries and ask the configured model
questions against that snapshot. They receive `[S1]`-style citations and
cannot access owner navigation, corpus creation, workflows, tools, raw corpus
files, or canonical filesystem paths. Guest lifecycle events and successful
Q&A are submitted as HFL entries with source `sharing-audit`. Owner preview
chat is diagnostic and is not audited as guest activity.

Storage defaults to `.harqis-data/hfl-shares.sqlite3`. The database contains
recipes, immutable snapshots, HMAC hashes of capability tokens, scrypt PIN
hashes, signed-cookie session hashes, approval requests, and revocation state.
It never stores a generated PIN or public capability token in plaintext.

Detailed deployment, Cloudflare routing, lifecycle, recovery, and threat-model
guidance is in
[`docs/info/HFL-CORPUS-SHARING.md`](../docs/info/HFL-CORPUS-SHARING.md).

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
| GET | `/git-forks` | Latest fork fleet topology and drift report. |
| POST | `/git-forks/scan` | Run hybrid fleet discovery and optionally write per-fork HFL entries. |
| POST | `/git-forks/sync` | Cherry-pick, test, push, and optionally publish a fork PR from an isolated worktree. |
| POST | `/git-forks/test` | Run a fork regression suite in an isolated worktree. |
| POST | `/git-forks/deploy` | Deploy a fork branch locally from an isolated worktree. |
| GET | `/hfl-corpus` | Corpus tree and filtered search. |
| POST | `/hfl-corpus/entries/preview` | Validate and render a manual entry preview. |
| POST | `/hfl-corpus/entries` | Persist a manual entry locally or through the canonical host. |
| POST | `/hfl-corpus/entries/upload` | Persist a multipart manual entry and its attachments. |
| GET | `/hfl-corpus/document/{path}` | Render one corpus Markdown document. |
| GET | `/hfl-corpus/references/{token}/download` | Download an allowed signed reference. |
| GET | `/hfl-corpus/remote-references/{token}/download` | Proxy an allowed canonical-host reference. |
| GET | `/api/hfl/documents` | Bearer-authenticated canonical index and search. |
| POST | `/api/hfl/entries` | Bearer-authenticated canonical manual-entry write. |
| POST | `/api/hfl/entries/preview` | Bearer-authenticated attachment-reference preview. |
| POST | `/api/hfl/entries/upload` | Bearer-authenticated canonical multipart entry write. |
| GET | `/api/hfl/document/{path}` | Bearer-authenticated canonical Markdown document. |
| GET | `/api/hfl/reference/{token}` | Bearer-authenticated canonical reference download. |
| GET/POST | `/sharing[...]` | Owner-only recipe, preview, generation, approval, and revocation operations. |
| GET/POST | `/share/access/{token}` | Public capability redemption for PIN, manual, and QR modes. |
| GET/POST | `/share/email/{token}` | Cloudflare Access-protected email OTP redemption. |
| GET/POST | `/share/session[...]` | Signed guest-session browsing, Q&A, logout, and enabled references. |
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
| `HFL_SHARE_PUBLIC_URL` | empty | Public HTTPS tunnel origin used in generated links. Required for proxied production sharing. |
| `HFL_SHARE_SECRET_KEY` | `APP_SECRET_KEY` | Separate signing/HMAC key for share capabilities and guest cookies. |
| `HFL_SHARE_STORE_PATH` | `.harqis-data/hfl-shares.sqlite3` | Durable recipe, snapshot, grant, and session store. |
| `HFL_SHARE_DEFAULT_TTL_SECONDS` | `3600` | New-recipe expiry default. |
| `HFL_SHARE_DEFAULT_DEVICE_LIMIT` | `1` | New-recipe device/session default. |
| `HFL_SHARE_PIN_MAX_ATTEMPTS` | `5` | Failed PIN attempts allowed per grant. |
| `HFL_SHARE_PROVIDER` | `hermes` | Share Q&A backend. Only locked-down loopback `hermes` is accepted. |
| `HFL_SHARE_HERMES_BASE_URL` | `http://127.0.0.1:8643/v1` | Dedicated Hermes OpenAI-compatible API; non-loopback URLs are rejected. |
| `HFL_SHARE_HERMES_API_KEY` | empty | Server-side bearer for the isolated Hermes profile; never expose it to browsers. |
| `HFL_SHARE_HERMES_MODEL` | `share-corpus` | Model alias advertised by the dedicated Hermes API profile. |
| `HFL_SHARE_AGENT_TIMEOUT_SECONDS` | `90` | Provider request timeout. |
| `HFL_SHARE_MAX_OUTPUT_TOKENS` | `1200` | Maximum provider response tokens before citation validation. |
| `HFL_SHARE_MAX_CONTEXT_CHARS` | `120000` | Maximum ranked, sanitized snapshot characters sent per question. |
| `HFL_SHARE_MAX_SNAPSHOT_CHARS` | `10000000` | Hard sanitized-text size limit for a generated snapshot. |
| `HFL_SHARE_CHAT_LIMIT_PER_HOUR` | `30` | Durable per-share guest model-query limit. |
| `HFL_SHARE_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | FastEmbed model used locally for immutable-snapshot retrieval. |
| `HFL_SHARE_EMBEDDING_CACHE_DIR` | `.harqis-data/models/fastembed` | Local model cache. The first use may download model files; corpus text is never sent to an embedding API. |
| `HFL_SHARE_RETRIEVAL_K` | `8` | Maximum snapshot entries supplied to Hermes per question (clamped to 1–20). |
| `HFL_SHARE_SEMANTIC_WEIGHT` | `0.75` | Semantic share of hybrid semantic/lexical ranking, clamped to 0–1. |
| `HFL_SHARE_TRUST_PROXY_IDENTITY` | `false` | Trust Cloudflare Access identity headers for email OTP mode; enable only with a locked-down origin. |

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
API bearer authentication, signed reference containment, immutable share
snapshots, hashed capabilities and PINs, single-use sessions, revocation, and
route rendering. Browser-level validation
should additionally cover drag ordering, HTMX polling, confirmation dialogs,
responsive navigation, corpus filtering, and reference downloads.

## Operational Notes

- Start through `scripts/launch.py frontend` in deployed environments; a bare
  `uvicorn` invocation does not perform machine-context loading.
- Flower is optional for dispatch but required for useful task-state polling.
- Application pytest jobs execute on the frontend host, not a Celery worker.
- The Applications module is read-only. HFL source writes are limited to the
  authenticated **Create entry** flow and canonical persistence layer.
- Deploy/restart the Mac frontend before enabling/restarting a remote Windows
  frontend; otherwise Windows correctly reports the canonical corpus as
  unavailable.
- Never expose the origin directly to the public internet. Social requires an
  HTTPS tunnel or reverse proxy, `BEHIND_PROXY=true`, owner protection for all
  non-guest routes, and explicit public policy only for the intended
  `/share/access/*` and guest-session paths.
