# Granola

## Description

Read-only integration with Granola's official meeting-notes API using a Bearer
API key. Supports note metadata, note details, folders, and transcript pages.
[API reference](https://docs.granola.ai/introduction).
API access requires a Business or Enterprise plan. No private API or local cache
scraping is used. Webhook management and audit endpoints are outside this adapter.

## Supported Automations

- [x] webservices — official REST API
- [ ] browser
- [ ] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```text
apps/granola/
├── __init__.py
├── config.py
├── mcp.py
├── references/
│   ├── __init__.py
│   ├── dto/
│   │   ├── __init__.py
│   │   └── note.py
│   └── web/
│       ├── __init__.py
│       ├── base_api_service.py
│       └── api/
│           ├── __init__.py
│           └── notes.py
└── tests/
    ├── __init__.py
    └── test_notes.py
```

## Configuration

The checked-in `apps_config.yaml` includes:

```yaml
GRANOLA:
  app_id: 'granola'
  client: 'rest'
  parameters:
    base_url: 'https://public-api.granola.ai/v1/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 30
    stream: False
  app_data:
    api_key: ${GRANOLA_API_KEY}
  return_data_only: True
```

Set these in the executing host's ignored `.env/apps.env`:

```env
GRANOLA_API_KEY=
GRANOLA_FOLDER_ID=
```

Create the API key in Granola Settings → Connectors → API keys. Choose only the
note access scopes needed. Use `list_granola_folders` to select the HFL import
folder; ingestion requires a folder, while service tools can read anything the
key permits. Folder filtering includes child folders and is not a security scope.

For copyable environment-loading, folder-discovery, preview, and first-import
commands, follow [first-time HFL setup](../../workflows/hfl/README.md#first-time-setup-and-import).
That guide also covers scheduled activation, delivery verification, and
troubleshooting. The checked-in schedule is disabled by default.

`config.py` uses `app_name_for` and `get_ws_config`. The transport inherits
`BaseFixtureServiceRest`, uses the configured timeout, enforces TLS and the
official origin, rejects redirects, and preserves explicit HTTP errors.
The shared `@deserialized` adapter returns `DtoGranolaNote` for `get_note`;
page primitives retain the wire `hasMore`/`cursor` keys.

## Available Services

| Class | Method | Result |
| --- | --- | --- |
| `ApiServiceGranolaNotes` | `list_notes` | One metadata page; creation/update/folder filters |
| `ApiServiceGranolaNotes` | `get_note` | Typed note; transcript optional |
| `ApiServiceGranolaNotes` | `get_transcript` | One transcript page, including oversized transcripts |
| `ApiServiceGranolaNotes` | `list_folders` | One folder page |

All methods are read-only. Note/folder pages permit 1–30 items; transcript pages
permit 1–100. Callers own pagination and retry budgets. Invalid resource IDs are
rejected before any request.

## MCP Tools

| Tool | Arguments | Description |
| --- | --- | --- |
| `list_granola_notes` | `created_after`, `created_before`, `updated_after`, `folder_id`, `cursor`, `page_size` | Metadata page |
| `get_granola_note` | `note_id`, `include_transcript` | Full note including private notes accessible to the key |
| `get_granola_transcript` | `note_id`, `cursor`, `page_size` | Transcript page |
| `list_granola_folders` | `cursor`, `page_size` | Folder page |

The shared catalog exposes these via CLI and MCP:

```powershell
python -m tools commands granola
python -m tools schema granola list_granola_notes
```

The separate Memory tool `granola_activity` previews folder-scoped summaries,
optionally distilled with Haiku, without corpus writes. See the
[HFL activation guide](../../workflows/hfl/README.md#granola-activation).

## Tests

Use the repository virtual environment and machine environment bootstrap.
Fixture-based coverage is in `workflows/hfl/tests/test_ingest_granola.py`.
Live smoke tests require explicit `GRANOLA_LIVE_TESTS=1` and configured credentials;
otherwise they are skipped. They read meeting data but never write notes or HFL.

```powershell
.venv/Scripts/python.exe -m pytest -o addopts= workflows/hfl/tests/test_ingest_granola.py -v
.venv/Scripts/python.exe -m pytest apps/granola/tests/ -m smoke -v
```

## Notes

- API results contain only processed notes. A missing result can mean processing
  is incomplete; it is not proof no meeting occurred.
- Granola documents 5 requests/second sustained and a 25-request burst capacity.
  This adapter does not retry automatically. Callers must respect HTTP 429.
- Oversized inline transcripts return HTTP 413; explicitly use transcript pages.
- Ingestion uses only enhanced summaries and does not request transcripts or
  include private notes in the HFL entry/model payload.
- Read-only tools can expose private notes/transcripts within the key's scope.
  Never share their outputs beyond that scope.
- Initial HFL capture is not a synchronization service: source edits, deletions,
  and access revocation do not automatically propagate to imported entries.
  Select material appropriate for independent retention and manage HFL deletion
  separately. No automatic task execution, Soul edit, or external write is added.
