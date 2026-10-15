# HFL Activity Corpus

## Description

This integration wraps the authenticated HARQIS Homework-for-Life (HFL) Activity
Corpus API. It creates canonical entries, reports their Markdown and best-effort
Elasticsearch persistence, searches the corpus, retrieves or replaces documents,
and downloads safe references. It also manages actions, Memory Signal categories,
and date pins through bearer-authenticated endpoints, plus entities, graph views,
timeline, ideas, mind maps, goals, connections and idea attachments.

- API contract: [`openapi.yaml`](openapi.yaml)
- Runtime Swagger UI: `http://<canonical-host>:8082/docs`
- Authentication: `Authorization: Bearer <HFL_CORPUS_API_TOKEN>`

## Supported Automations

- [x] webservices — REST API calls
- [ ] browser — browser automation
- [ ] desktop — local desktop automation
- [ ] mobile — Android/iOS automation
- [ ] internet of things — MQTT / hardware integration

## Directory Structure

```text
apps/hfl_corpus/
├── config.py
├── mcp.py
├── openapi.yaml
├── references/
│   ├── dto/
│   │   ├── documents.py
│   │   └── entries.py
│   └── web/
│       ├── base_api_service.py
│       └── api/
│           ├── documents.py
│           ├── entries.py
│           ├── management.py
│           ├── extended.py
│           ├── calendar.py
│           ├── entities.py
│           ├── graph_views.py
│           ├── timeline.py
│           └── ideas.py
└── tests/
    ├── test_documents.py
    └── test_entries.py
```

The standalone server reuses the canonical router in `frontend/hfl_api.py`; it
does not duplicate the Markdown or Elasticsearch persistence implementation.

## Configuration

`apps_config.yaml`:

```yaml
HFL_CORPUS:
  app_id: 'hfl_corpus'
  client: 'rest'
  parameters:
    base_url: 'http://127.0.0.1:8082/api/hfl/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    api_url: ${HFL_CORPUS_API_URL}
    api_key: ${HFL_CORPUS_API_TOKEN}
  return_data_only: True
```

`.env/apps.env`:

```env
HFL_CORPUS_API_URL=http://harqis-server:8082
HFL_CORPUS_API_TOKEN=
HFL_API_HOST=0.0.0.0
HFL_API_PORT=8082
```

The host/port overrides are optional. Keep the bearer token on trusted hosts;
expose plain HTTP only over a private network such as Tailscale, or add TLS.

## Available Services

| Service class | Methods | Purpose |
|---|---|---|
| `ApiServiceHflCorpusEntries` | `create_entry`, `preview_entry`, `create_entry_with_uploads` | Write or preview canonical entries and attachments |
| `ApiServiceHflCorpusDocuments` | `list_documents`, `get_tree`, `list_matches`, `get_document`, `update_document` | Search, retrieve, and update corpus documents |
| `ApiServiceHflCorpusDocuments` | `get_reference_preview`, `download_reference`, `download_reference_media`, `download_reference_thumbnail` | Preview or download tokenized references |
| `ApiServiceHflCorpusManagement` | `create_action`, `list_actions`, `get_action`, `update_action`, `get_action_history` | Versioned actions and completion/dismissal |
| `ApiServiceHflCorpusManagement` | `create_category`, `list_categories`, `get_category`, `update_category`, `archive_category` | Memory Signal categories |
| `ApiServiceHflCorpusManagement` | `create_pin`, `list_pins`, `get_pin`, `update_pin`, `delete_pin` | Annotated dates and date ranges |
| `ApiServiceHflCorpusManagement` | `upload_attachments`, `list_attachments`, `download_attachment`, `delete_attachment` | Multiple supporting input files for actions and pins |
| `ApiServiceHflCorpusCalendar` | `list_day_matches` | Canonical calendar operations |
| `ApiServiceHflCorpusEntities` | `list_entities`, `get_entity_graph`, `get_entity_entry`, `get_entity_status`, `update_entity_profile`, `create_entity_backfill`, `create_entity_legacy_merge`, `update_entity_legacy_undo`, `create_entity_export`, `analyze_entity_selection`, `create_entity_merge`, `update_entity_unmerge`, `get_entity_operation`, `get_entity_audit`, `get_entity_matching`, `create_entity_matching_scan`, `update_entity_matching_dismiss`, `create_entity_consolidation`, `get_entity_consolidation`, `update_entity_consolidation_decision`, `update_entity_consolidation_decisions`, `update_entity_consolidation_finish`, `create_entity_consolidation_claim`, `update_entity_consolidation_claim`, `update_entity_consolidation_checkpoint`, `update_entity_consolidation_evidence`, `create_entity_consolidation_group` | Canonical entities operations |
| `ApiServiceHflCorpusGraphViews` | `list_graph_views`, `create_graph_view`, `update_graph_view`, `update_graph_view_selection`, `delete_graph_view` | Canonical graph views operations |
| `ApiServiceHflCorpusTimeline` | `get_timeline_source`, `get_timeline_evidence`, `list_timeline_items`, `update_timeline_order`, `create_timeline_item`, `update_timeline_item`, `get_timeline_item`, `get_timeline_history`, `get_timeline_markers`, `get_timeline_period`, `update_timeline_suggestion_dismiss`, `create_timeline_exploration` | Canonical timeline operations |
| `ApiServiceHflCorpusIdeas` | `get_ideas_snapshot`, `get_connection_availability`, `get_action_connections`, `get_date_connections`, `get_idea_connections`, `list_reuse_options`, `list_board_ideas`, `get_clone_draft`, `create_clone`, `create_list_copy`, `create_map_paste`, `get_list`, `create_list`, `update_list`, `list_boards`, `update_board_order`, `update_goal_order`, `get_goal_options`, `get_map`, `get_map_graph`, `list_map_attach_options`, `get_rendered_markdown`, `get_idea`, `create_idea`, `update_idea`, `create_topic`, `create_link`, `delete_link`, `create_map`, `update_map`, `delete_map`, `create_map_promotion`, `get_goal`, `create_map_link_promotion`, `update_map_connection`, `create_goal`, `update_goal`, `get_idea_conversion`, `create_idea_conversion`, `list_idea_attachments`, `download_idea_attachment`, `upload_idea_attachments`, `delete_idea_attachment`, `create_map_proposal` | Canonical ideas operations |

`create_entry` writes Markdown first and then attempts an idempotent Elasticsearch
upsert. Inspect `indexed` and `doc_id`; the request can succeed with
`indexed: false` when Elasticsearch is unavailable.

## MCP Tools

| Tool | Description |
| --- | --- |
| `get_hfl_corpus_role_history` | Read private facet revision history. |
| `list_hfl_corpus_item_connection_options` | Search visible ideas/actions available for manual linking, with query and offset pagination. |
| `update_hfl_corpus_item_connection` | Create, update or remove a shared manual link; update/remove require the current revision (destructive remote write). |

The existing `hfl_corpus` catalog entry covers every
canonical `/api/hfl` method/path in the frontend. CLI, standalone MCP and the
Kanban bridge consume the same adapter; existing tool names remain compatible.
No new credential is required. Configure the canonical host in
`HFL_CORPUS_API_URL` and its owner bearer token in `HFL_CORPUS_API_TOKEN`.

Use `python -m tools commands hfl_corpus` for discovery and
`python -m tools schema hfl_corpus <tool_name>` for the input schema. CLI writes
require `--confirm-write`; MCP users must review each tool's documented effects.
Requests retain server validation, versions/revisions and idempotency IDs. No
write retries are automatic. For entity merges, preview with
`analyze_hfl_corpus_entity_selection`, then pass the reviewed token and a UUID to
`create_hfl_corpus_entity_merge`; query `get_hfl_corpus_entity_operation` after
an uncertain response before retrying with the same UUID and payload.

Document search accepts `include_entries`, `activity_year`, `activity_from_year`
and combined-view `scope`; match/day queries also accept `scope`. Document
updates accept `expected_updated_at` for a 409 on stale edits. Omitting it retains
legacy unconditional replacement behavior.

`create/update_hfl_corpus_action` remain the intent-only management tools.
Advanced `create/update_hfl_corpus_timeline_item` expose the canonical agenda
payload, which can change agent scheduling; request those changes explicitly.
Entity backfill/matching scans, exploration and exports have side effects even
when their result looks like a status response. File destinations are on the MCP
host; downloads stream to a temporary file and atomically replace the destination
only on success. Redirects are not followed by the extended client.

Browser aliases, session administration, sharing and worker lease protocols are
tracked separately in the [frontend coverage report](../../docs/info/FRONTEND_MCP_COVERAGE.md).
The [machine-readable manifest](../../frontend/mcp_coverage.json) and
`python -m tools.frontend_coverage --check` prevent unreviewed endpoint drift.
The standalone HFL API includes graph views and exactly one copy of entity merge
routes; deploy that API revision before using newly exposed graph-view tools.

| Tool | Description |
| --- | --- |
| `upload_hfl_corpus_attachments` | Attach multiple supporting files to an action or pin (remote write). |
| `list_hfl_corpus_attachments` | List supporting files attached to a task. |
| `download_hfl_corpus_attachment` | Download an input attachment (writes a local file). |
| `delete_hfl_corpus_attachment` | Detach an input from future runs (remote write). Prior run files are retained. |
| `create_hfl_corpus_action` | Create an action (writes remote state), with scheduled agent execution disabled. |
| `list_hfl_corpus_actions` | List actions, up to 500 per page. |
| `get_hfl_corpus_action` | Read an action and its current version. |
| `update_hfl_corpus_action` | Edit, complete, or dismiss an action (writes remote state). |
| `get_hfl_corpus_action_history` | Read immutable action revisions. |
| `create_hfl_corpus_category` | Create a Memory Signal category (writes remote state). |
| `list_hfl_corpus_categories` | List active and archived Memory Signal categories and the color palette. |
| `get_hfl_corpus_category` | Read a Memory Signal category, including an archived category. |
| `update_hfl_corpus_category` | Edit a category (writes remote state). |
| `archive_hfl_corpus_category` | Archive a category and hide its pins, retaining history (writes remote state). |
| `create_hfl_corpus_pin` | Pin dates (writes remote state). A prompt does not enable agent execution. |
| `list_hfl_corpus_pins` | List date pins in active categories. |
| `get_hfl_corpus_pin` | Read a date pin in an active category. |
| `update_hfl_corpus_pin` | Edit a date pin (writes remote state); preserves its agent setting. |
| `delete_hfl_corpus_pin` | Delete a date pin (destructive remote write). |
| `create_hfl_corpus_entry` | Create a durable HFL entry. This writes Markdown and attempts an ES upsert. |
| `preview_hfl_corpus_entry` | Preview a rendered HFL entry without saving it. |
| `upload_hfl_corpus_entry` | Create a durable HFL entry and upload attachments. This writes remote state. |
| `list_hfl_corpus_documents` | Search and paginate canonical HFL documents. |
| `get_hfl_corpus_tree` | Get a shallow directory tree from the canonical corpus. |
| `list_hfl_corpus_matches` | List matching entries within one HFL Markdown document. |
| `get_hfl_corpus_document` | Get one HFL document with parsed entries and safe references. |
| `update_hfl_corpus_document` | Replace an HFL document. Destructive: overwrites canonical Markdown text. |
| `update_hfl_corpus_entry` | Update one entry with its anchor and last-read revision, optionally uploading attachments (destructive remote write). |
| `get_hfl_corpus_reference_preview` | Get a safe HTML preview for a text or Markdown reference. |
| `download_hfl_corpus_reference` | Download a reference to a local path. This writes a local file. |
| `download_hfl_corpus_reference_media` | Download reference image/video content. This writes a local file. |
| `download_hfl_corpus_reference_thumbnail` | Download a reference thumbnail. This writes a local file. |
| `list_hfl_corpus_entities` | Search the entity directory with explicit pagination (limit 1–10000). |
| `get_hfl_corpus_entity_graph` | Read the entity graph; limit is 0–1000, with 0 requesting all nodes. |
| `get_hfl_corpus_entity_entry` | Read an entity-linked entry preview and its safe references. |
| `get_hfl_corpus_entity_status` | Read entity enrichment state and legacy merge decisions. |
| `update_hfl_corpus_entity_profile` | Replace entity profile fields; omitted lists are cleared. Destructive: writes remote state. |
| `create_hfl_corpus_entity_backfill` | Request entity enrichment/backfill on the canonical host. Destructive: writes remote state. |
| `create_hfl_corpus_entity_legacy_merge` | Legacy pair merge; prefer the preview-token bulk merge flow. Destructive: writes remote state. |
| `update_hfl_corpus_entity_legacy_undo` | Undo a legacy pair-merge decision. Destructive: writes remote state. |
| `create_hfl_corpus_entity_export` | Write the canonical host’s configured Obsidian export; requires HARQIS_OBSIDIAN_VAULT. Destructive: writes remote state. |
| `analyze_hfl_corpus_entity_selection` | Preview a same-type entity merge and obtain a short-lived preview token. Read-only. |
| `create_hfl_corpus_entity_merge` | Commit a reviewed entity merge; reuse the UUID and identical payload on retry. Destructive: writes remote state. |
| `update_hfl_corpus_entity_unmerge` | Reverse a bulk merge, preserving audit history; UUID is required for idempotency. Destructive: writes remote state. |
| `get_hfl_corpus_entity_operation` | Read a committed merge/unmerge result and audit delivery state. |
| `get_hfl_corpus_entity_audit` | Read immutable entity merge/unmerge audit events. |
| `get_hfl_corpus_entity_matching` | Read matching scan status and candidate suggestions. |
| `create_hfl_corpus_entity_matching_scan` | Request a matching scan; this may schedule background work. Destructive: writes remote state. |
| `update_hfl_corpus_entity_matching_dismiss` | Dismiss a matching suggestion. Destructive: writes remote state. |
| `list_hfl_corpus_graph_views` | List saved graph views and the selected view. |
| `create_hfl_corpus_graph_view` | Create and select a named graph view. Destructive: writes remote state. |
| `update_hfl_corpus_graph_view` | Replace a saved graph view using its latest revision. Destructive: writes remote state. |
| `update_hfl_corpus_graph_view_selection` | Select an existing saved graph view. Destructive: writes remote state. |
| `delete_hfl_corpus_graph_view` | Delete a graph view with an optimistic revision check. Destructive: writes remote state. |
| `get_hfl_corpus_timeline_source` | Validate and read the title/date of unprotected entry evidence. |
| `get_hfl_corpus_timeline_evidence` | Return the validated evidence navigation link without following its redirect. |
| `list_hfl_corpus_timeline_items` | List up to 500 scoped agenda items with board positions and due-state grouping. |
| `update_hfl_corpus_timeline_order` | Reorder a status column with item version checks. Destructive: writes remote state. |
| `create_hfl_corpus_timeline_item` | Create/adopt an agenda item. May configure agent execution if explicitly requested. Destructive: writes remote state. |
| `create_hfl_corpus_checklist_action` | Create an action and tick the source checklist item atomically, with version checks and retry-safe creation. Agent execution stays disabled. Destructive: writes remote state. |
| `update_hfl_corpus_timeline_item` | Update an agenda item using its latest version. Can alter scheduling; completion writes a receipt. Destructive: writes remote state. |
| `get_hfl_corpus_timeline_item` | Read the current agenda item and version. |
| `get_hfl_corpus_timeline_history` | Read immutable agenda revisions and rendered completion notes. |
| `get_hfl_corpus_timeline_markers` | Read scoped action date markers and aggregate statuses. |
| `get_hfl_corpus_timeline_period` | Read agenda items, suggestions, receipts and exploration state for 1–31 inclusive days. |
| `update_hfl_corpus_timeline_suggestion_dismiss` | Dismiss an idea/suggestion. Destructive: writes remote state. |
| `create_hfl_corpus_timeline_exploration` | Schedule AI exploration for 1–31 days ending today or earlier; may incur model usage. Destructive: writes remote state. |
| `get_hfl_corpus_ideas_snapshot` | Read ideas, maps, links, goals and visible graph context. |
| `get_hfl_corpus_connection_availability` | Read available object connection choices. |
| `get_hfl_corpus_action_connections` | Read an action’s graph connections. |
| `get_hfl_corpus_date_connections` | Read a date pin’s graph connections. |
| `get_hfl_corpus_idea_connections` | Read an idea’s graph connections. |
| `list_hfl_corpus_boards` | Read board metadata, goals and the color palette without scanning the corpus. |
| `update_hfl_corpus_board_order` | Persist board ordering. Destructive: writes remote state. |
| `update_hfl_corpus_goal_order` | Persist goal ordering. Destructive: writes remote state. |
| `get_hfl_corpus_goal_options` | List visible ideas/actions that can be linked to goals. |
| `get_hfl_corpus_map` | Read a mind map and current version. |
| `get_hfl_corpus_map_graph` | Read the visible graph projection for map members. |
| `list_hfl_corpus_map_attach_options` | Search attachable objects; returns 50 per page. |
| `get_hfl_corpus_rendered_markdown` | Render up to 60000 characters of Markdown using the frontend renderer. Read-only. |
| `get_hfl_corpus_idea` | Read an idea, version and rendered content. |
| `create_hfl_corpus_idea` | Create an idea; reuse the request UUID for stable identity. Destructive: writes remote state. |
| `update_hfl_corpus_idea` | Edit/dismiss/restore an idea using the latest version. Destructive: writes remote state. |
| `create_hfl_corpus_topic` | Create a named graph topic and initial entity profile; URLs are not topic names. Destructive: writes remote state. |
| `create_hfl_corpus_link` | Create a durable relation between visible graph nodes. Destructive: writes remote state. |
| `delete_hfl_corpus_link` | Delete a durable relation between visible graph nodes. Destructive: writes remote state. |
| `create_hfl_corpus_map` | Create a versioned mind map; UUID determines its stable identity. Destructive: writes remote state. |
| `update_hfl_corpus_map` | Update map membership/content/layout with an optimistic version check. Destructive: writes remote state. |
| `delete_hfl_corpus_map` | Delete a map using its latest version; shared objects remain independently owned. Destructive: writes remote state. |
| `create_hfl_corpus_map_promotion` | Promote a map draft into a durable idea. Destructive: writes remote state. |
| `get_hfl_corpus_goal` | Read a goal with its current version. |
| `create_hfl_corpus_map_link_promotion` | Promote a map connection to a durable graph relation. Destructive: writes remote state. |
| `update_hfl_corpus_map_connection` | Edit a board connection using its current board/edge revision. Destructive: writes remote state. |
| `create_hfl_corpus_goal` | Create a durable goal with validated idea/action links. Destructive: writes remote state. |
| `update_hfl_corpus_goal` | Update a goal with optimistic concurrency and validated milestone links. Destructive: writes remote state. |
| `get_hfl_corpus_idea_conversion` | Preview conversion of an idea or checklist item into an action. |
| `create_hfl_corpus_idea_conversion` | Convert an idea to an action, clone selected attachments, and mark it adopted. Agent execution remains disabled. Destructive: writes remote state. |
| `list_hfl_corpus_idea_attachments` | List an idea’s supporting files. |
| `download_hfl_corpus_idea_attachment` | Download a supporting file to a local path; replaces an existing destination. Destructive: writes a local file. |
| `upload_hfl_corpus_idea_attachments` | Attach supporting files to an idea; at most 50 files of 500 MB each. Destructive: writes remote state. |
| `delete_hfl_corpus_idea_attachment` | Detach a supporting file from an idea. Destructive: writes remote state. |
| `create_hfl_corpus_map_proposal` | Accept a proposed thought into a map with at most five existing parents. Destructive: writes remote state. |
| `list_hfl_corpus_day_matches` | Read matching entries across documents for one YYYY-MM-DD activity date; maximum 20 per page. |
| `create_hfl_corpus_entity_consolidation` | Begin or resume an entity consolidation run. Destructive: writes remote state. |
| `get_hfl_corpus_entity_consolidation` | Read a consolidation run and its candidate decisions. |
| `update_hfl_corpus_entity_consolidation_decision` | Record a decision and apply an eligible merge. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_decisions` | Submit up to 20 pair decisions; results report each success or error. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_finish` | Finish a decided run and dispatch its reports. Destructive: writes remote state. |
| `create_hfl_corpus_entity_consolidation_claim` | Claim a disjoint anchor packet. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_claim` | Renew or release a review lease. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_checkpoint` | Checkpoint partial progress and discover changed inputs. Destructive: writes remote state. |
| `update_hfl_corpus_entity_consolidation_evidence` | Cache bounded original-entry context across pending pairs. Destructive: writes remote state. |
| `create_hfl_corpus_entity_consolidation_group` | Commit independently corroborated anchor pairs atomically. Destructive: writes remote state. |
| `get_hfl_corpus_board_context` | Read active boards and permitted member objects and connections. |

## Deployment

The `hfl-api` daemon is opt-in through `machines.toml` and enabled for the
canonical `harqis-server` profile only. This prevents multiple writable corpus
authorities.

```bash
python scripts/launch.py hfl-api
python scripts/deploy.py --machine harqis-server --restart hfl-api
python scripts/deploy.py --machine harqis-server --register
```

Health and documentation endpoints:

```text
GET http://harqis-server:8082/health
GET http://harqis-server:8082/openapi.json
GET http://harqis-server:8082/docs
```

## External actions, categories, and date pins

All routes below use `Authorization: Bearer <HFL_CORPUS_API_TOKEN>` and are
available in the standalone server's `/docs` Swagger UI and `/openapi.json`.

| Resource | Routes |
|---|---|
| Actions | `GET/POST /api/hfl/actions`, `GET/PATCH /api/hfl/actions/{action_id}`, `GET /api/hfl/actions/{action_id}/history` |
| Categories | `GET/POST /api/hfl/categories`, `GET/PATCH /api/hfl/categories/{category_id}`, `POST /api/hfl/categories/{category_id}/archive` |
| Date pins | `GET/POST /api/hfl/pins`, `GET/PATCH/DELETE /api/hfl/pins/{pin_id}` |

Create an action with this JSON body:

```json
{
  "request_id": "442c6b17-e106-4d91-8d7f-fc7ce50679e3",
  "title": "Review the capture pipeline",
  "expected_outcome": "Record missing sources and a proposed fix",
  "review_date": "2026-09-15",
  "due_date": "2026-09-18",
  "prompt": "Compare the captured sources with the expected schedule.",
  "notes": "Check the Android source first"
}
```

Generate a new UUID for each logical action; keep the same `request_id` and
body when retrying. Creation returns `201` and `{item, duplicate: false}`;
an unchanged retry returns `200` with the existing item and `duplicate: true`.
Reusing the ID with different content returns `409`. Add an optional
`source: {"path": "2026/Sep/2026-09-14.md", "entry_id": "hfl-..."}` to link
an existing unprotected entry. The API validates the evidence and fills its
title/date; an HTML anchor cannot replace the stable entry ID.

Action lists accept `closed` (default false) and `offset` (default zero), with
up to 500 `items` per page and a `total`. Read an action's latest `version`
before PATCH, for example `{"version": 1, "status": "done", "completion_note": "Reviewed"}`.
Use `status: "dismissed"` to dismiss, or edit `title`, `expected_outcome`,
`review_date`, `due_date`, `prompt`, and `notes`. Omitted fields are preserved;
empty strings clear optional text/dates. Stale versions return `409`.
Completion retains the existing HFL completion receipt and retry behavior.

Create a category with `name`, a `color` from the GET categories `palette`,
and optional `instructions`. Category names are case-insensitively unique.
Responses use `{category}`; lists return `categories`, `archived_categories`,
and `palette`. Archiving hides its pins while retaining history.

Create a pin with `category_id`, `title`, `start_date`, `end_date`, and optional
`note` and `prompt`. Dates use `YYYY-MM-DD`; identical dates pin one day, and
reversed endpoints are normalized. Bounds follow the dashboard: no earlier
than the profile birthdate and no later than five years ahead. Lists return
`{pins}` and accept `category_id`; other reads/writes return `{pin}`. PATCH
preserves omitted fields. Pins in archived categories are absent from these
pin routes. Category and pin creation do not provide idempotency keys: reconcile
with their list endpoints before retrying an uncertain write.

New actions and pins created through these management endpoints have
`agent_enabled: false`, including when a prompt is supplied. Updates preserve
the existing agent setting; these endpoints cannot enable execution. Existing
UI and legacy timeline behavior is preserved, and explicit owner agent-run
controls remain separate. The API uses the same timeline and profile stores
as the dashboard **on that host**. Deploy the API and dashboard against the
same configured store paths to share records; these routes do not synchronize
independent hosts' profile databases.

Invalid inputs return `422`, missing records/evidence return `404`, and absent
or invalid bearer credentials return `401` (`503` if no token is configured).
The existing evidence validator returns `400` for malformed source paths/IDs.

Use the repository [`create-action` skill](../../.agents/skills/create-action/SKILL.md)
to save actions conversationally. The same tools are available through
`python -m tools commands hfl_corpus`; writes use `--confirm-write`.

## Supporting files and authenticated links

Actions and pins accept multiple attachments through these bearer-authenticated
routes (`resource` is `actions` or `pins`):

```text
GET    /api/hfl/{resource}/{source_id}/attachments
POST   /api/hfl/{resource}/{source_id}/attachments
GET    /api/hfl/{resource}/{source_id}/attachments/{attachment_id}
DELETE /api/hfl/{resource}/{source_id}/attachments/{attachment_id}
```

POST uses multipart form data with repeated `files` parts. The task limit is
50 attached files, 500 MB each, and 25,000 MB combined. Uploads are atomic as a batch;
oversized batches return `413`. Identical filename/content retries return the
existing attachment instead of duplicating it. List, upload, and detach return
`{attachments: [...]}` with `id`, original `name`, worker-local `filename`,
SHA-256 `digest`, and byte `size`. Downloads are authenticated binary attachments
with `nosniff`; uploaded HTML is never served inline.

Create the action or pin first, then attach files using its returned ID. New
management API records remain opted out of scheduling. For existing scheduled
records, finish uploads before requesting execution. Both dashboard editors stage
file additions/removals until Save, keep the prompt empty during the file-save
phase, and restore it after success. An upload failure leaves the editor open
for retry; an already-created record is reused. Schedule preferences are preserved.

Each agent run snapshots its attachment manifest. The worker fetches only those
files using its active execution lease and checks hashes and sizes before running.
Detaching an input excludes it from future runs; the immutable file remains
downloadable for history and existing runs. Input blobs live in the `.inputs`
directory beside the owning timeline/profile database. Back up both together;
no automatic garbage collection is provided in this version.

Agents read relevant attachments and supplied web links using available tools.
For protected links they try configured service integrations first, then an
available signed-in browser on the executing host. Trusted/restricted execution
rules still apply; a remote worker does not inherit a desktop browser session.
Missing permissions, login/MFA, sessions, and unsupported file formats are reported
as limitations rather than claimed as successfully read. Credentials remain on
the host and are not included in snapshots or results.

## Tests

Read-only smoke tests require a reachable API and valid bearer token:

```bash
pytest apps/hfl_corpus/tests/ -m smoke
pytest frontend/tests/test_hfl_api_server.py
pytest frontend/tests/test_hfl_management_api.py
pytest frontend/tests/test_mcp_coverage.py
python -m tools.frontend_coverage --check
```

Entry creation and document replacement tests are skipped by default because
they mutate the canonical corpus.

## Notes

- FastAPI generates the live schema at `/openapi.json`; `openapi.yaml` is the
  checked-in portable contract.
- `HFL_CORPUS_API_URL` is the server root, without `/api/hfl`.
- Uploads allow at most 50 files and have server-enforced size limits.
- Markdown remains authoritative; Elasticsearch is an additive, best-effort
  projection that can be reconciled later.
- Reference download tools write caller-selected local paths.

### Intent reuse tools

- `list_hfl_corpus_reuse_options`: Search actions and ideas available for independent copying.
- `list_hfl_corpus_board_ideas`: List visible ideas available to boards, optionally including dismissed ideas.
- `get_hfl_corpus_clone_draft`: Preview an independent action or idea copy without saving it.
- `create_hfl_corpus_clone`: Create a copy using a caller UUID and the source revision. Writes remote state.
- `create_hfl_corpus_list_copy`: Copy a checklist into an action or idea at the expected revision. Writes remote state.
- `create_hfl_corpus_map_paste`: Paste selected objects between versioned boards. Writes remote state.
- `get_hfl_corpus_list`: Read a standalone or owner-linked checklist entity.
- `create_hfl_corpus_list`: Create a standalone checklist with a caller-generated UUID. Writes remote state.
- `update_hfl_corpus_list`: Update a standalone or owner-linked checklist at its expected revision. Writes remote state.


### Workspace sharing service context

`GET /api/hfl/timeline/ideas/share-context` returns canonical object input to the
sharing service under the existing bearer authentication. Browser owner routes
cannot proxy this endpoint. The sharing service must apply its PIN-authorized
secrets policy, workspace selection, explicit exclusions and safe public projection
before persisting or returning recipient data. See
[workspace sharing](../../docs/info/HFL-CORPUS-SHARING.md#workspace-context-sharing).
Older canonical servers support ordinary sharing through the existing filtered
snapshot; mixed secret-backed sharing requires the updated service endpoint.
