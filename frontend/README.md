# HARQIS Frontend

The HARQIS frontend is an authenticated, module-based interface for operating
and inspecting the automation platform. It is built with FastAPI, Jinja2,
HTMX, Alpine.js, Tailwind CSS, and SortableJS. Production serves compiled,
content-versioned assets from `/static/`; the generated files are committed so
runtime deployment does not require Node.js.

The frontend currently exposes nine modules:

| Module | Route | Purpose |
|---|---|---|
| Home | `/home` | Introduces the platform modules. |
| Organize → Files | `/files` | Metadata catalog, storage discovery, file/category/entity graph, versioned Drive packages, and expiring guest pages. |
| Manifesto | `/manifesto` | Renders `docs/MANIFESTO.md` and the HARQIS guiding principles. |
| Workflows | `/workflows` | Displays Celery workflow categories, task triggers, schedules, status, and run history. |
| Apps | `/applications` | Inventories `apps/*`, renders documentation, and runs controlled pytest checks using host configuration. |
| Activity Corpus | `/hfl-corpus` | Browses and searches HARQIS activity logs, based on the Homework for Life reflection practice, and their references. |
| Social | `/sharing` | Builds reviewed, immutable Activity Corpus snapshots and temporary guest portals. |
| Git Forks | `/git-forks` | Maps fork drift and launches guarded synchronization, regression, and isolated deployment operations. |
| Second Brain | `/second-brain` | Shows a ranked context-aware advisory feed, manual mode overrides, and opt-in presentation settings. |

`/dashboard` remains as a compatibility redirect to `/home`.

Files deployment requires the catalog-host `files` queue, persistent SQLite
storage, configured source roots, and Drive/SFTP credentials as applicable.
Follow [Files deployment](../docs/info/FILES-DEPLOYMENT.md). Public package pages
use `/file-share/{token}` on the frontend host, separate from HFL sharing.

The reviewed manifest maps 115 canonical `/api/hfl` operations to the
`hfl_corpus` integration through the shared CLI/MCP adapter. See the [tool guide](../apps/hfl_corpus/README.md)
and [endpoint coverage report](../docs/info/FRONTEND_MCP_COVERAGE.md).
The reviewed [coverage manifest](mcp_coverage.json) includes browser aliases and
deferred administration/session protocols. Run
`python -m tools.frontend_coverage --check` when adding or changing routes; CI
requires each endpoint to have a tool mapping or an explicit coverage decision.

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

Tailwind 4 uses the separately pinned `@tailwindcss/cli` package. The CSS input
loads the JavaScript theme with `@config` and explicitly scans templates and Python
files using `@source`; source paths are relative to the CSS input. CI builds these
assets and checks that representative utilities were generated.

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
│   ├── second_brain/
│   │   ├── router.py              # Authenticated feed, SSE, commands, and settings
│   │   └── service.py             # Canonical-store projections
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

Build → Integrations groups user-scoped GitHub/Jira **Connectors** and the existing
**Workflows** application catalogue. Connector credentials are independent of
host workflow configuration. The catalogue includes search, README descriptions,
authentication hints, and Hermes-assisted integration development. See the
[connector operations and security guide](modules/integrations/README.md).

The workflow inventory supports browser-local drag-and-drop ordering through
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

The canonical host prewarms its in-memory index during frontend startup. The
index has a 30-second TTL; after expiry, requests keep using the last complete
snapshot while one daemon refresh scans for filesystem changes. Writes made
through the frontend force a synchronous refresh, so newly created or edited
entries remain immediately visible. Query-independent tag, source, and tree
projections are reused until the index publishes a new document snapshot.

Remote-reader requests run outside the FastAPI event loop and share a bounded
HTTP keep-alive pool. The pool is closed during application shutdown. This
keeps a slow or restarting canonical host from blocking unrelated frontend
requests and avoids reconnecting for every Activity Corpus page load.

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
Uploads accept any file type, with limits of 500 MB per file, 25,000 MB combined,
and 50 files per entry. Size limits use 1 MB = 1,048,576 bytes, matching the
existing upload convention. Files are staged before commit, existing files are
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

Quick tags are configured under **User > App Settings > Activity Corpus** as
an ordered comma-separated list. Optional leading `#` signs are accepted and
case-insensitive duplicates are removed. Favorites stay visible beside the Tags
accordion, including tags with no current matches. Clicking a pill toggles its
partial tag filter immediately; multiple selected tags use AND and retain the
other search filters. **Quick tags** opens the settings section and focuses the field, with a breadcrumb
back to the filtered corpus view. Agents and Activity Corpus settings start collapsed.

**View feed** (shortcut **V**, also closes the dialog) opens a reading feed for the applied search,
tags, sources, dates, and selected Space filters. It stays disabled without a
meaningful filter; pending filter edits or an explicit ORDER BY enable it.
Clicking it applies the current filters through Search, then opens the feed. Entries
are ordered by their recorded date, newest first, with an oldest-first option
and undated entries last. The dialog loads 50 entries at a time as you scroll,
offers retry/load-more controls, and links each card to its original document
entry. Cards use the shared-page layout with tag and source badges. Attached images
fit inside each card without cropping or a separate viewer; supported video and
audio use inline controls without autoplay. Images load lazily, players do not
preload media, and other files have authenticated download links. Closing the
dialog pauses playback. Secret entries retain the existing PIN rules. **Save as Space** carries
the filters into the Space editor, including combined rules shown under
**Saved timeline rules**; it does not copy or freeze the entries themselves.
The owner endpoint is `/hfl-corpus/curated-feed`; remote frontends require the
canonical host's authenticated `/api/hfl/curated-feed` endpoint from the same
version. Pagination cursors expire after one hour; reopen the dialog to refresh.

### Secret entries

**App Settings > Activity Corpus** manages a salted hash of a six-digit owner PIN and a
comma-separated protected-tag list. `#secrets` is always protected; configured
tags are normalized without their leading `#` and matched exactly and
case-insensitively. This is an authenticated-frontend privacy screen only:
Markdown, Elasticsearch, MCP, RAG, and direct filesystem consumers are not
encrypted or filtered.

Activity Corpus search and document views hide protected entries by default.
The document page's **Edit entry** button opens a structured editor for only the
selected entry, including date/time, narrative fields, tags, references, and file
uploads. Source, machine, and entry identity are preserved. Attachment removal
detaches its reference without deleting the stored file. Save checks the document
version, updates the selected Markdown block in place (even when its date changes),
refreshes the corpus index, and attempts an Elasticsearch upsert under the same ID.
Search synchronization failures are reported after saving. Cancel discards staged
changes. The separate document Edit control still edits the complete Markdown file.
Remote readers require the canonical API's `/api/hfl/entry-edit/{relative_path}`
endpoint; deploy the API and frontend together for this feature.

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

### Activity Graph views

Graph opens from Activity Corpus as a dedicated page at `/hfl-corpus/graph`.
It inherits the active workspace and corpus filters. The selected board is kept
in the URL and the graph retains its view state across refreshes. Back to corpus
returns to the inherited context. Entities opens all authorized entities without inherited workspace or graph filters.
The board sidebar keeps Explore Activity Graph, Add, and Board guide pinned while
scrolling, with Filters, Fit graph, and Reset layout grouped under Controls.

The Activity Kanban is a dedicated page at `/hfl-corpus/actions`. Its filters and
opened saved action/idea survive refresh through URL state. Existing action and
idea editors autosave after a short typing pause, serialize concurrent edits,
and display save errors without overwriting newer server versions. New objects
require Create. Closing with unsaved edits offers Save and close, Discard unsaved
changes, or Keep editing; already saved edits cannot be discarded.

Kanban and its Ideas drawer offer separate multiselect toggles and bulk menus
before Refresh. Select cards to move status, add a Space or board, or dismiss
them after confirmation. Add operations preserve existing memberships; adding
an action to a new board returns it to In Review, as with individual updates.
Updates use each card's version and report partial failures, retaining failed
cards for review and retry. Selection survives refresh for cards still present
and clears when selection mode is turned off or the Space changes. Setting an
idea to Has actions changes its status without creating an action and removes
it from the drawer.

Checklists support moving items between lists by dragging or the move icon,
reordering whole lists, and one-time A–Z/Z–A sorting. Card covers show completed
items last without changing editor order. New actions have an empty Agent
Instructions checklist; existing actions receive it on their next edited save.
Add to board links existing actions/ideas, or creates a board thought linked to
a checklist item's source. New manual corpus entries always include `#moments`.

The bottom-left bulb opens an overlay drawer containing manual and generated
ideas, excluding dismissed ideas. Click outside or press Escape to close it. Cards
show their origin and description, with Edit, Promote, and Dismiss controls. The board's
Create menu offers Entry, Action, and Idea. Actions and ideas can belong to several
saved workspaces through a checkbox dropdown below supporting files. Explicit
workspace selections are prefilled from the current view when creating an action
or idea, and can be changed or cleared before saving. Existing objects and drafts
with their own workspace selections retain those assignments. Explicit
workspace assignments include the object even when its source, tags, or
dates do not match that workspace's saved filters. Additional search filters and
protected-entry restrictions still apply. Removing an assignment restores the
usual source-based inclusion for that workspace. The board's
rightmost Spaces picker aggregates selected views, applies selections when
closed, and includes All activity; its adjacent caption names the selected views. Clone buttons open an
independent draft with supporting files and reset checklists. Dates, recurrence,
and previous relationships are omitted; a `copied-from` connection records its source.

The optional **Boards** checkbox dropdown follows **Spaces** in both editors.
It lists active boards by most recent update. Selections mirror board membership:
adding one attaches an orphan orb without connections to other objects; removing
one detaches the object without deleting it. Creating an object inside a board
automatically associates that board and preserves the creation flow's connections.
Idea-to-action conversion inherits active board selections. Board Settings has an
**Active** toggle (existing boards default to active); inactive associations remain
stored but are excluded from choices for new attachments.

Ideas and actions expose `board_ids` through the canonical and management APIs.
`GET /api/hfl/timeline/ideas/board-context` and `get_hfl_corpus_board_context` provide
active boards with permitted member objects and connections. Idea generation and
action processing use that context and can add relevant board associations while
retaining owner selections. Context never includes protected corpus objects.

Checklist text renders sanitized Markdown and switches to source text when clicked.
Each list has a copy button with recent, searchable action/idea destinations; list
copies preserve completion. Adding a whole list to a mindmap attaches a live List
entity with connected Thought items. Edit live list updates the source checklist
and its appearances on other boards. New list creates a standalone shared list.
Board list content refreshes every five seconds while the view is idle.

On boards, Shift/Ctrl/Command-click selects multiple nodes. Copy selected/Paste and
Ctrl/Command+C/V copy thoughts, lists, actions, and ideas with numbered names and
selected internal connections. Other shared entity types cannot be copied. Delete
selected or Delete removes board membership (or local thoughts), preserving shared
records. Text inputs retain their normal editing shortcuts. Action, idea, and entry
forms also accept media files through clipboard paste or drag/drop.

Action Plan supports completion-triggered daily, weekly, monthly, and yearly
recurrence with an interval, first planned date, and optional end date. Completion
creates one next future occurrence atomically, resets checklist completion, and
preserves the completed record. Month-end dates clamp without losing the original
anchor. Reopening and completing an occurrence again does not create a second successor.

`/hfl-corpus/graph` uses the shared Space picker, including All activity,
combined selections, and Dynamic mode. Corpus, Kanban, and Graph synchronize
workspace selection and applied corpus filters through the existing owner profile
and cross-tab updates. Graph-only filters and presets further narrow that scope.
The main graph uses an opt-in capacity guard: by default, more than 1,000 matching
nodes or 2,000 connections pauses the viewport before rendering. The overlay
reports counts and offers Refine search, Open filters, or Show limited preview.
Filters → Graph capacity accepts 1,000–10,000 nodes and 100–5,000 connections,
remembered per owner in this browser, with a Restore button. Limits
count all node types before local preset/type visibility filters. Preview results
are explicitly incomplete, keep valid connection endpoints, and use stable
recency order with connected neighbors. Animation Off is recommended for larger
previews. Blocked graphs stop automatic polling until the user takes action;
preview polling remains bounded. Changes to search, filters, or scope require a
new preview choice. Boards, embedded graphs, timeline previews, and shared graphs
retain their existing behavior; API consumers without `capacity_guard=true` are
unchanged. Overview, Expanded, Dense, and the separate All activity switch are removed.
The information helper reports matching/displayed nodes, locally hidden nodes,
and visible connections. Old browser detail settings are ignored.

In the main graph's Filters drawer, Shared connections only is a switch.
Graph capacity has an info button explaining performance and preview omissions
in a compact popover on hover, keyboard focus, or tap. Escape or moving away
dismisses the helper. Its arrow buttons adjust values by 100; typed whole numbers
and keyboard arrows remain supported. Restore sets 1,000 nodes
and 2,000 connections. Older saved node limits below 1,000 migrate to 1,000;
other valid saved preferences are preserved. **This week** selects Monday through
today, inclusive, in browser-local time: Monday selects only that day, Sunday
selects all seven days. The range is recalculated on each graph refresh, including
after a week boundary, and the From/To fields show the effective dates.

Boards use explicit workspace assignments, not matching member content. All
activity includes unassigned boards. New boards default to all currently selected
workspaces; under All activity they start unassigned. **Add → Existing board**
adds assignments without replacing previous ones. Settings can remove assignments
without deleting the board. Opening a board retains all authorized members;
members outside workspace filters are dimmed and identified in the inspector
and node list. Goals remain independent of workspace assignment. Switching
workspace flushes pending board saves and returns to exploration if the board
is outside the new selection; failed saves retain edits and offer Retry.

Recipient sharing of complete assigned boards (including drafts, local edges,
and attachments) is a future feature. Existing share recipes still describe
corpus filters and do not grant access to those board contents.

Views now contains five calculated **Presets**: Sources, Timeline (the initial default; oldest dates on the left; initial zoom and Fit frame the latest 30 available days), People, Tools, and Companies.
Sources surround activity; the entity presets bring highly connected target
orbs toward the center. Missing target types fall back to Sources with a notice.
Switching presets moves existing nodes into place over approximately one second
and fits once, without re-fetching graph data. Shared connections only starts
off. Existing saved-view records remain intact but the UI no longer reads or
writes saved positions, and the old Group by control has been removed.

The **Animation** dropdown offers Off (initial default), Breathing, Ripple, and Drift.
A colored pill shows the selected mode, which is remembered per owner in this browser
across modal openings and refreshes. Reset returns the preference to Off.
Motion stays bounded around the preset positions; Timeline date anchors stay
fixed. Node selection pauses motion until cleared. Touch gestures, dragging,
drawers, nested Entities, and hidden tabs also pause it. Reduced-motion users
get immediate preset changes and must explicitly enable ambient motion.
Motion updates are capped at 30 per second, or 15 above 1,000 nodes; actual frame
rates depend on graph size and device. Mobile uses a full-width animation menu.
Manual node positions last only until the next preset is applied.

Visible, idle graphs check the applied query approximately every three seconds
after the preceding request completes. The current corpus reader has no remote
push feed, so updates use adaptive polling, slowing to at most a 60-second gap
after expensive reads or failures. Hidden tabs and active interactions defer
updates. Returning to the tab checks again. New and removed nodes preserve the
surviving layout and viewport. Rolling windows
use the browser's local calendar dates. A stale indicator accompanies failures.
Full graphs can take several seconds to lay out; narrower workspace filters remain useful
for quick navigation. The neighbor list shows up to 200 items at a time.

Capacity measurements (2026-10-17, local headless Chromium, synthetic hub graphs,
Drift animation, 1440px / 390px viewports):

| Nodes | Connections | JSON size | Frame interval p95, desktop / narrow |
|---|---|---|---|
| 500 | 1,920 | 185 KiB | 16.8 / 50.4 ms |
| 1,000 | 3,920 | 378 KiB | 316.6 / 133.3 ms |
| 2,000 | 7,920 | 768 KiB | 566.7 / 66.6 ms |
| 3,000 | 11,920 | 1,159 KiB | 916.7 / 433.6 ms |
| 6,000 | 23,920 | 2,331 KiB | 1,949.9 / 666.7 ms |
| 1,000 | 11,760 | 930 KiB | 985.1 / 283.3 ms |

These measurements informed the original 500-node/2,000-connection default.
The current user-requested default is 1,000/2,000, with adjustable maxima of
10,000/5,000. These larger allowances are not guarantees of smooth performance;
10,000 nodes were not benchmarked. Narrow viewports used the same desktop CPU,
not phone hardware.
Frame measurements include initial animation settling and background refresh;
random layout and visibility explain non-monotonic results. Mocked page load
times were 1.2–2.2 seconds after the first cold load (4.2 seconds), including the
test client's asset routing, so these are not production API latency figures.
The guard bounds browser payload/rendering, but still assembles the canonical
server graph to count it. Server assembly cost and real-corpus latency remain
unmeasured; a future count-first projection could address that separately.
The reproducible opt-in test is `test_graph_capacity.py::test_capacity_measurements`
with `GRAPH_CAPACITY_BENCHMARK=1`; it writes raw results to
`results/graph-capacity-measurements.json`. Follow the repository test environment
bootstrap when running it.

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
- QR and a pasteable capability link, reopenable by the owner for newly generated
  active shares; PINs are displayed only in the generation response;
- owner previews for active, expired, and revoked shares, with inactive shares
  retaining their last saved snapshot; and
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
Newly generated shares also retain an encrypted capability link in `share_handoffs`,
using a key derived from the sharing secret. Existing links cannot be recovered
retroactively. It never stores a generated PIN or public capability token in plaintext.

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
| GET/POST | `/hfl-corpus/workspace-views` | List or create owner workspace filter profiles. Writes require the page CSRF token. |
| PUT/DELETE | `/hfl-corpus/workspace-views/{id}` | Update or remove a workspace with its current revision. |
| POST | `/hfl-corpus/workspace-views/{id}/select` | Remember the selected workspace. |
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

### Activity Corpus focus views

**Space**, on Corpus, Graph, and Kanban, opens the **Focus on** selector. A view combines sources,
tags/search text, date type and range, sort order, and page size to focus on a
particular aspect of your activity: work, learning, relationships, or a project.
Use the information button beside **Focus on** for in-page guidance.

Choose filters and click **Search** to review results. **Manage Spaces** carries
filters to **Organize → Spaces**. Choose an explicit new or existing destination,
review, and **Save Space**. The dedicated page manages names, colors, filters,
and weekly schedules; **Remove Space** confirms removal without deleting entries.
Sources use OR matching (`source=git,notes`), combined with the existing tag and
text matching rules. Fixed dates and rolling last 7/30/90 days are supported,
including today. Rolling dates are recalculated when the view is opened.

Views and the last selected view are stored in the server's owner profile
database. A plain visit to `/hfl-corpus` restores that view from page 1, including
after a new login or from another browser using the same server. Separate local
and remote servers do not automatically synchronize their view databases.
Explicit query parameters take precedence. **Reset** clears additional search
filters and restores the currently selected view or combination, retaining Dynamic
mode when enabled. With no selected views it shows All activity.
Removing the selected view clears that selection. **Save Space** in Organize → Spaces updates the named
view; applying a search shares its filters without changing that definition.
Unsubmitted typing is discarded on navigation. Secrets access is
never stored in a view. Graph profiles remain independent.

#### Combined views and Dynamic mode

Use the **Focus on** checkbox dropdown to choose up to 30 views. Closing the list applies the selection automatically. **All activity** clears saved-view filtering.
Each view retains its own source/tag/text/date rules. An entry matching any view
appears once in document results, matching-entry navigation, and Memory Signal
counts. Search controls show inherited sources and shared filter values; differing
values are marked as varying by view. Unchanged inherited values preserve each
view’s original rules. Inspect each Space’s rules in **Organize → Spaces**; the search
controls further narrow the union. A combined handoff carries only the additional
filters and requires an explicit destination; it cannot flatten the union into
a single saved Space. Removal requires confirmation.

In **Organize → Spaces → Assign schedules**, choose weekdays and add one or more time blocks.
End times are exclusive; an end before the start continues into the next day.
Overlapping blocks combine all active views. The shared schedule timezone is
configured in **Profile → Timezone**, initially `Asia/Singapore` (existing schedule settings are preserved); Views read it automatically. It follows
named-zone daylight-saving rules rather than the browser's local timezone.

**Dynamic mode** starts off. Add at least one time block before enabling it; the Views menu explains this requirement when no schedules exist. Its setting and manual selection persist in the
owner profile database. When enabled, active scheduled views replace the manual
selection; gaps show all entries (subject to normal secret-access restrictions). Turning it off restores the manual
selection. Choosing views manually turns it off. Explicit filter links retain
their own scope; ordinary landing-page visits restore persisted preferences.

Activity Corpus, Actions Kanban, and Activity Graph share selections, Dynamic mode, saved-view
edits, and applied search/source/tag/date filters in the owner profile database.
All three landing pages restore this state. Open tabs receive change notifications
and check for updates every 15 seconds and when focus returns, in either mode.
Generated navigation URLs carry a revision so stale refresh/back navigation can
restore the latest shared state. Explicit filter links retain their own scope.
No Celery task or external scheduler runs this feature. Updates wait while a
dialog or the Views menu is open, or filters contain unsubmitted edits. Apply
those edits to share them. A transition shows loading feedback, keeps the old results
on failure with Retry, preserves scroll position for automatic changes, and
fades the updated heatmap unless reduced motion is requested.

Planned date categories support optional multiple workspace assignments. Their
date blocks and heatmap markers appear when any assigned workspace is selected;
All activity includes unassigned categories too. The category picker offers Select
all, and new categories select every available workspace by default. Saving
assignments refreshes the visible pins.

The Memory Signal header identifies the current view(s), Dynamic ON/OFF, and
Saved/Modified state. The combined view names identify every applied view. Combined results use a shared sort and page size.

#### Weekly schedule visualizer

Choose **Visualize** beside Dynamic mode to preview all saved schedules for the
current Monday–Sunday week in the Profile timezone. Today and the current time
are highlighted. Shorter overlapping blocks sit above longer blocks; identical periods share equal columns. Overnight blocks span days.
The preview works with Dynamic mode OFF and does not change your active selection.
Unscheduled periods show all entries when Dynamic mode is ON.

Select a block to inspect its full period, sources, search/tags, and date filters,
or choose **Edit view**. Blocks are read-only. Mobile users can scroll the week
horizontally. There are no previous/next-week controls for these recurring schedules.
Choose a persistent view color under **Assign schedules** using the pinned-date
palette; existing views receive colors automatically. Status pill colors remain unchanged.

#### Example: reflect with four quadrants

The urgency-and-importance matrix in [Habit 3 of The 7 Habits of Highly Effective
People](https://www.franklincovey.com/courses/the-7-habits/habit-3/) can help frame
an activity review. The tags below are suggestions for your own entries:

| Quadrant | Activity review example | Suggested tag |
|---|---|---|
| Q1: urgent and important | Pressing deadlines or incidents | `#Q1` |
| Q2: important, not urgent | Planning, learning, relationships | `#Q2` |
| Q3: urgent, not important | Interruptions away from your priorities | `#Q3` |
| Q4: neither urgent nor important | Low-value distractions | `#Q4` |

Tag entries yourself, then combine a quadrant tag with sources and a date range
and save the result as a view. For example, filter `#Q2` with your notes source
and **Last 30 days** to review longer-term investments. These examples do not
create presets, classify entries automatically, or filter by action-matrix data.

#### Tailor a corpus for sharing

Saved views provide control over which activity you review, helping you decide
what is relevant to a particular audience. Below the view controls,
**Generate share recipe** opens Share Activity with an unsaved draft, and **Sharing preview**
opens the sharing preview in a responsive dialog without leaving Activity Corpus.

Both use the current controls, including unsaved changes: activity sources, tags,
dates, and date type. Search text, sort order, and page size are not transferred.
Single-view handoffs retain Sharing's existing exact-tag matching. Combined
view handoffs preserve the per-view tag matching rules and source/date pairing;
free-text search is omitted from every clause. Use the preview to check the
resulting scope. Created and Updated filter document timestamps; Entry date
filters entry headings. Existing recipes continue to use Entry date. Rolling
ranges become fixed dates; preview and its handoff reuse the resolved range.

The preview includes scope statistics, up to 250 listed entries, and reference
selection. Agent testing remains available on the Share Activity page. Reference exclusions
carry into the draft. Changing filter controls invalidates the earlier preview's
reference choices. Secrets are excluded by default, even if unlocked in Activity
Corpus. Broad-scope and size-limit warnings use the existing sharing rules.

The generated draft suggests a name and records provenance in **Background for
HARQIS**: “This was generated from Activity Corpus on [DATE]”, the timestamp and
timezone, view name if available, and transferred filters. This is recipe context,
not a separately saved corpus audit entry. Recipient remains blank, and access,
expiry, and other recipe fields use the normal new-recipe defaults. Review the
scope, enter the recipient, and explicitly save the recipe or generate a link.
The handoff itself neither saves a recipe nor grants anyone access.

For combined views, both **Sharing preview** and **Generate share recipe** retain
the union of the applied view scopes, plus additional tag/source/date filters.
Previewing does not flatten sources and tags into a broader cross-product.
The draft displays the combined rules and preserves them through editing,
saving, previewing, and link generation. The preview captures the current
resolved date ranges; changing schedule blocks cannot change an open preview
or an already generated recipe. References remain individually selectable.

Deploy the updated canonical API as well as the frontend for remote multisource
search and combined-view scopes. Older canonical hosts fail explicitly instead
of returning a broader scope.

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
| `SECOND_BRAIN_STORE_PATH` | `.harqis-data/second-brain.sqlite3` | Canonical context, mode, configuration, run, and feed state. |

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


#### Space context sharing

Personalized recipes combine multiple canonical entities of any available types. The separate
**Share with** accordion and owner-saved entity templates combine filtered entity activity
with optional workspace objects. The first selected name prefills an editable Recipient; overlapping content is deduplicated. The preview
explains supporting content. The accordion offers Review and a disposable QR with
a 24-hour redemption window followed by a full 24-hour session. Other
personalized Instant Share paths respect reference
settings. See the [personalized sharing walkthrough](../docs/info/WORKSPACE-SHARING-GUIDE.md#personalize-a-share-with-one-entity)
and [implementation boundaries](../docs/info/HFL-CORPUS-SHARING.md#personalized-recipes).
Relevant checks include `frontend/tests/test_share_personalization.py`, including
desktop/mobile browser coverage, alongside the existing sharing regressions.

For local review, start the frontend with the machine environment loaded as
described above, bind it to loopback on an unused port, and open `/sharing`.
Use a separate `HFL_SHARE_STORE_PATH` and local `HFL_SHARE_PUBLIC_URL` when creating
test grants. A localhost QR works only on the machine running that instance.

For step-by-step owner instructions, see the [Space sharing user guide](../docs/info/WORKSPACE-SHARING-GUIDE.md)
(QR generation, browser redemption limits, expiry, refresh, and context names).

Express > **Share Activity** now has Settings, Entries, Actions,
Boards, Plans, Graph, and Agent tabs. Generate share recipe from Corpus, Graph, or Kanban
preselects eligible workspace context in an unsaved draft. Saved recipes and
generated-share lists retain their existing controls.

Recipients start with chat and an Activity entries sidebar. The hamburger menu
offers Actions and ideas, Plans, Idea boards, and Activity graph only when enabled
and populated in the published snapshot. Actions precede ideas; plans group by
category and sort by descending end date (start date fallback). Boards and graphs
occupy the main area alongside the last selected desktop sidebar, with Back to
chat. Canvases resize to the available panel height; the board picker shares the
heading row, and board citations open node details directly. Switching views retains conversation and
draft text. Mobile source views use a full-height drawer. Close session exits preview or
ends the guest session. Graph exploration is temporary: reopening a view restores
the recipe's published layout and animation settings. Recipient activity graphs
hide the preset and animation selectors, fall back to Drift when unspecified, and respect
reduced-motion preferences. Recipe editors retain both selectors. On mobile, recipient
activity graph and idea board type pills sit in an initially collapsed **Entity orbs** section;
desktop keeps the pills visible. Use Update from saved recipe on an active generated
share to republish its linked recipe without replacing its QR/link. Save recipe
edits first; existing access settings and reference permissions are preserved.
Generating a share prompts for a separate recipient-visible share name, initially
filled with the recipe name. Republishing from the recipe preserves this name.

Entries are required when creating or saving a recipe. Legacy publications keep
their approved content, including older entries-excluded snapshots; applying the
new interface does not rebuild them. Explicit in-place publication can replace a
share's snapshot and captured live configuration while preserving its URL/QR,
expiry, access policy, and sessions. Such an update must use the owner-approved
recipe and preserve existing citation identities and reference permissions.

New standalone recipes default to no date restriction. **From days** offers None,
15, 30, or 90 days and fills Entry date plus the inclusive date range in the
owner's timezone. Saved presets roll forward for live shares; frozen snapshots
retain their resolved dates. Editing either date or the date type switches to a
custom range. None clears the range. Existing recipes and workspace handoffs keep
their filters. Oversized previews offer a last-15-days shortcut; large explicitly
workspace-linked objects may still need individual exclusions.

Entry filters preserve combined-view rules. Filters can edit those rules or
explicitly replace inherited workspace scope. Explicit workspace assignments
retain standalone actions/ideas even without matching entries. Defaults exclude
completed actions and dismissed ideas. Board members outside the workspace
require per-board opt-in; mapped goals never recursively include other boards.
Excluded objects remain excluded during live refresh. Source objects are never
modified by sharing.

Plans share active pinned date ranges grouped by category, including dates, title,
instructions as the description, and notes. They inherit category workspace membership
and support individual exclusions and automatic inclusion in live recipes.

New recipes include entries, actions, ideas, boards, plans and the activity graph by
default. Excluded items appear in an initially expanded sidebar accordion grouped
by tab, with a Restore button per item. The accordion hides when empty. Topic and
agent-background helper text stays visible, and the initial agent question uses
the profile nickname (with the profile display-name fallback).

Frozen shares capture all content together. Live recipes independently choose
approved-object updates or automatic matching for entries, actions, ideas, and
boards. New references stay disabled after generation. Secrets remain excluded
unless the owner enables Include secrets and unlocks the Activity Corpus PIN.
That switch applies across all object types. Public graphs and assistant citations
are projected from the same approved snapshot, and public routes expose no edits.

Automatic inclusion defaults on for all four object types in new recipes. Freeze
disables these controls while preserving their selections. The shared activity
graph reuses Activity Graph layouts and motion modes; presets, animation, type
visibility, zoom, pan and node positions are saved with the recipe and carried
into its snapshot. Dragged nodes retain their positions during animation;
choosing another preset creates a fresh arrangement. Type filters
only change the graph view. All types start visible, and node details remain
available by selecting an orb without an additional object directory.

See [sharing operations and compatibility](../docs/info/HFL-CORPUS-SHARING.md#workspace-context-sharing)
for canonical API requirements and local acceptance checks.

Sharing review uses bounded entry scroll loading (50 per batch, 150 mounted),
Kanban-style action/idea cards with per-item Connections, and read-only board/timeline
canvas graphs from approved snapshot data. Settings combines recipe details and filters, with filters immediately
after Description, and hides the preview region;
workspace-reset controls only appear for inherited scope. Graph assets are rebuilt
by `npm run build:knowledge-graph`, including `share-graphs.jsx`.


### Facets, Soul, and personal share context

**Organize → Facets** opens `/roles`: name/color, Markdown Soul,
attachments with extraction preview, Space/entity links, revision history, and a
private agent journal. Share recipes explicitly select personal excerpts, linked
entity activity, revision history, analysis summaries, and
optional original downloads; existing shares retain their publication-time persona
revision even when activity refreshes. Opportunity fields tailor presentation
without adding unsupported qualifications. Approved facet evidence informs chat
without a recipient-facing excerpt catalogue.

See [Facets and Spaces](../docs/info/ROLES-AND-SPACES.md) for selection, refresh,
archive/revocation, file limits, API ownership, and the weekly `persona-audit` job.

| Method | Route | Purpose |
|---|---|---|
| GET | `/roles` | Authenticated role editor. |
| GET/POST | `/roles/data` | List/create roles; writes require CSRF. |
| PUT | `/roles/data/{id}` | Version-checked edits, archive, and restore. |
| POST | `/roles/analyze` | Queue a manual persona audit. |
| GET/POST/PUT | `/api/hfl/roles[/{id}]` | Bearer-protected role operations. |
| GET | `/api/hfl/roles/{id}/history` | Bearer-protected full revision history for owner agents. |
| POST | `/api/hfl/roles/audit/run` | Idempotent worker-to-owner analysis command. |

The Spaces management route is `/spaces`; it reuses the existing authenticated
`/hfl-corpus/workspace-views` APIs and revision checks. The frontend Space editor
was moved out of the activity dropdowns. See [Spaces guide](../docs/info/SPACES-GUIDE.md).


### Advanced corpus filters

Activity Corpus offers **Query mode** under **Advanced**, **Media only** in the main filter row, and an **Exclude tags** popup beside Quick tags. The Space editor keeps these controls in its **Advanced Filters** panel. **Media only** matches entries with recognized image/video references or embedded media; audio alone does not qualify. **Exclude tags** accepts comma-separated whole tag names, ignores case and optional `#`, and never excludes similarly prefixed names.

Enable **Query mode** to generate a query from the current controls. Valid edits synchronize the controls; **Apply** searches the corpus (or applies a Space draft before Save Space). Invalid expressions retain the last valid filters. Suggestions support arrow keys and Enter/Tab; Escape dismisses them. Ctrl/Cmd+Enter applies.

Expressions support `AND`, `OR`, `NOT`, parentheses, `=`, `!=`, `~`, `!~`, `IN`, and `NOT IN` where appropriate. `~` matches partial text/tags; tag equality and lists use exact names. For example:

```text
hasMedia = true AND tags NOT IN ("hfl") AND (source = "instagram" OR tags = "travel")
```

Fields: `text`, `tags`, `source`, `hasMedia`, and `q` (the existing combined text/#tag search). `entryDate`, `created`, and `updated` accept quoted ISO dates and comparison operators. Global control settings `dateField`, `dateFrom`, `dateTo`, `rolling`, `sort`, and `pageSize` use top-level `AND` equality clauses. Nested conditions that cannot fit the ordinary controls remain in the expression and stay active when Query mode is disabled. Saved Space restrictions remain in force. Advanced filters travel with feeds, saved Spaces, and generated recipes; canonical remote hosts must also run the updated backend.


Expressions also accept a trailing, multi-field `ORDER BY`, for example:

```text
hasMedia = true AND tags NOT IN ("hfl") ORDER BY source ASC, entryDate DESC
```

Supported sort fields are `source`, `entryDate`, `created`, and `updated`. Directions default to `ASC`; fields are evaluated left to right. Source names ignore case, missing values sort last in either direction, and document paths/entry anchors break remaining ties. `ORDER BY` can appear on its own. Duplicate/unknown fields and conflicting legacy `sort` clauses are rejected. Sorting is independent of the date filter. The existing direction control reverses the first field and retains secondary fields.

Corpus results stay grouped by document: matching entries are sorted within each document, and each document is positioned by its first ordered entry. Feeds and recipe snapshots use the full entry-level order. The sort list is preserved in URLs, saved Spaces, feed cursors, and recipe scope. Queries without `ORDER BY` keep the existing default behavior.
