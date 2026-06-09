# Plaud

Adapter integration for the [Plaud](https://www.plaud.ai/) AI voice recorder
(Plaud Note / NotePin + desktop/mobile apps + cloud). Acquires recordings and,
when available, Plaud's own transcripts/summaries — normalized so downstream
code never branches on where the data came from.

Unlike most `apps/` integrations this is **not** a stock `BaseFixtureServiceRest`
client. Plaud exposes no general-purpose public REST API for retrieving *your*
recordings (the official OAuth API is waitlist-only beta; USB mass-storage is
disabled on firmware ≥ V2.1). So acquisition runs through a two-backend adapter:

| Backend | Role | Mechanism |
|---|---|---|
| **Cloud** (`PlaudCloudBackend`) | Primary | Unofficial [`plaud-api`](https://github.com/arbuzmell/plaud-api) client against `api.plaud.ai`, bearer-token auth |
| **Folder** (`PlaudFolderBackend`) | Fallback | Watches a local folder you export to from the Plaud desktop app |

`PlaudAdapter` tries the cloud first and transparently falls back to the folder.
The unofficial cloud surface is isolated in `PlaudCloudBackend` so it can be
swapped for Plaud's official OAuth API later without touching callers.

Consumed by the daily HFL ingest task
`workflows/hfl/tasks/ingest_plaud.py`.

## Supported Automations

- [x] webservices (cloud API)
- [ ] browser
- [x] desktop (export-folder fallback)
- [ ] mobile
- [ ] iot

## Directory Structure

```
apps/plaud/
├── __init__.py
├── config.py                       # standard get_ws_config pattern
├── mcp.py                          # MCP tools
├── references/
│   ├── adapter.py                  # cloud + folder backends, PlaudAdapter facade
│   └── dto/
│       └── recording.py            # DtoPlaudRecording (normalized)
└── tests/
    └── test_adapter.py
```

## Configuration

`apps_config.yaml`:

```yaml
PLAUD:
  app_id: 'plaud'
  client: 'rest'
  parameters:
    base_url: 'https://api.plaud.ai/'
    response_encoding: 'utf-8'
    verify: True
    timeout: 60
    stream: False
  app_data:
    token: ${PLAUD_TOKEN}
    export_dir: ${PLAUD_EXPORT_DIR}
  return_data_only: True
```

Environment variables (`.env/apps.env`):

```env
PLAUD_TOKEN=          # bearer token lifted from web.plaud.ai localStorage ("tokenstr")
PLAUD_EXPORT_DIR=     # local folder you export Plaud recordings into (fallback)
```

Either is sufficient on its own: set `PLAUD_TOKEN` for cloud, `PLAUD_EXPORT_DIR`
for the manual-export fallback, or both (cloud preferred).

## Available Services

| Class | Methods | Purpose |
|---|---|---|
| `PlaudAdapter` | `list_recordings(since, until)`, `ensure_audio_local(rec, dest_dir)`, `status` | Acquisition facade (cloud → folder) |
| `PlaudCloudBackend` | `available`, `list_recordings`, `ensure_audio_local` | Unofficial `plaud-api` wrapper (isolated) |
| `PlaudFolderBackend` | `available`, `list_recordings`, `ensure_audio_local` | Export-folder reader; pairs sidecar transcript/summary files |

## MCP Tools

| Tool | Args | Description |
|---|---|---|
| `list_plaud_recordings` | `since?`, `until?` (ISO-8601) | List recordings in a date window (cloud → folder) |
| `get_plaud_transcript` | `recording_id` | Plaud transcript + summary for one recording, if present |
| `plaud_status` | — | Which backend is active (cloud/folder readiness) |

Example prompts:
- *"List my Plaud recordings from yesterday."*
- *"Is the Plaud cloud connection working or are we on the export folder?"*

## Tests

```bash
pytest apps/plaud/tests/ -m smoke          # folder backend, no credentials needed
pytest apps/plaud/tests/ -m sanity         # live cloud check (needs PLAUD_TOKEN + plaud-api)
```

## Notes

- **`plaud-api` is unofficial and may break.** Its exact method names are flagged
  in `adapter.py` — verify against the installed version when wiring real
  credentials. The package is an optional/lazy import: if it is absent or errors,
  the adapter falls back to the export folder rather than crashing.
- **Folder pairing:** an audio file `Foo.mp3` pairs with `Foo.txt`/`Foo.md`
  (transcript) and `Foo-summary.md` / `Foo_summary.txt` (summary) in the same
  directory. Recording id is derived deterministically from the file date + stem,
  so re-runs upsert in Elasticsearch instead of duplicating.
- **Transcription:** when neither backend yields a transcript, the HFL ingest
  task transcribes the audio itself (OpenAI Whisper) — see
  `workflows/hfl/tasks/ingest_plaud.py`.
- **Future:** when Plaud's official OAuth API leaves beta, implement a third
  backend behind the same `PlaudBackend` interface and make it primary.
