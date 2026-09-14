# HFL Activity Corpus

## Description

This integration wraps the authenticated HARQIS Homework-for-Life (HFL) Activity
Corpus API. It creates canonical entries, reports their Markdown and best-effort
Elasticsearch persistence, searches the corpus, retrieves or replaces documents,
and downloads safe references. It also manages actions, Memory Signal categories,
and date pins through bearer-authenticated endpoints.

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
│           └── management.py
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

`create_entry` writes Markdown first and then attempts an idempotent Elasticsearch
upsert. Inspect `indexed` and `doc_id`; the request can succeed with
`indexed: false` when Elasticsearch is unavailable.

## MCP Tools

| Tool | Description |
|---|---|
| `upload_hfl_corpus_attachments` | Upload multiple task input files (write) |
| `list_hfl_corpus_attachments` | List attached files for an action or pin |
| `download_hfl_corpus_attachment` | Download a supporting input (local write) |
| `delete_hfl_corpus_attachment` | Detach a file from future runs; retain past run files (write) |
| `create_hfl_corpus_action` | Create standalone or entry-linked intent with scheduled agents disabled (write) |
| `list_hfl_corpus_actions` | List open or closed actions, 500 per page |
| `get_hfl_corpus_action` | Read an action and its version |
| `update_hfl_corpus_action` | Edit, complete, or dismiss using the latest version (write) |
| `get_hfl_corpus_action_history` | Read immutable action revisions |
| `create_hfl_corpus_category` | Create a Memory Signal category (write) |
| `list_hfl_corpus_categories` | List active/archived categories and valid colors |
| `get_hfl_corpus_category` | Read a category |
| `update_hfl_corpus_category` | Edit category fields (write) |
| `archive_hfl_corpus_category` | Archive a category and hide its pins without deleting history (write) |
| `create_hfl_corpus_pin` | Pin a date or date range with scheduled agents disabled (write) |
| `list_hfl_corpus_pins` | List active pins, optionally by category |
| `get_hfl_corpus_pin` | Read an active pin |
| `update_hfl_corpus_pin` | Edit pin fields, preserving its agent setting (write) |
| `delete_hfl_corpus_pin` | Remove a pin (destructive write) |
| `create_hfl_corpus_entry` | Create durable Markdown and attempt its ES projection (write) |
| `preview_hfl_corpus_entry` | Render an entry without saving it |
| `upload_hfl_corpus_entry` | Create an entry with local attachments (write) |
| `list_hfl_corpus_documents` | Search and paginate corpus documents |
| `get_hfl_corpus_tree` | Browse the shallow corpus directory tree |
| `list_hfl_corpus_matches` | Find matching entries within one document |
| `get_hfl_corpus_document` | Retrieve a document, entries, and safe references |
| `update_hfl_corpus_document` | Replace canonical Markdown text (destructive) |
| `get_hfl_corpus_reference_preview` | Preview a tokenized text/Markdown reference |
| `download_hfl_corpus_reference` | Download a reference to a local path (write) |
| `download_hfl_corpus_reference_media` | Download tokenized image/video content (write) |
| `download_hfl_corpus_reference_thumbnail` | Download a generated thumbnail (write) |

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
10 attached files, 50 MB each, and 200 MB combined. Uploads are atomic as a batch;
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
```

Entry creation and document replacement tests are skipped by default because
they mutate the canonical corpus.

## Notes

- FastAPI generates the live schema at `/openapi.json`; `openapi.yaml` is the
  checked-in portable contract.
- `HFL_CORPUS_API_URL` is the server root, without `/api/hfl`.
- Uploads allow at most 10 files and have server-enforced size limits.
- Markdown remains authoritative; Elasticsearch is an additive, best-effort
  projection that can be reconciled later.
- Reference download tools write caller-selected local paths.
