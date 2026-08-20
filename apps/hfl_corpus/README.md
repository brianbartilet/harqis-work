# HFL Activity Corpus

## Description

This integration wraps the authenticated HARQIS Homework-for-Life (HFL) Activity
Corpus API. It creates canonical entries, reports their Markdown and best-effort
Elasticsearch persistence, searches the corpus, retrieves or replaces documents,
and downloads safe references.

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
│           └── entries.py
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

`create_entry` writes Markdown first and then attempts an idempotent Elasticsearch
upsert. Inspect `indexed` and `doc_id`; the request can succeed with
`indexed: false` when Elasticsearch is unavailable.

## MCP Tools

| Tool | Description |
|---|---|
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

## Tests

Read-only smoke tests require a reachable API and valid bearer token:

```bash
pytest apps/hfl_corpus/tests/ -m smoke
pytest frontend/tests/test_hfl_api_server.py
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
