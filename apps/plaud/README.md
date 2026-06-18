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
| **Cloud** (`PlaudCloudBackend`) | Primary | Direct HTTP against the unofficial `api.plaud.ai` surface; mints its own bearer token from account credentials (or uses a manual one) |
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
    email: ${PLAUD_EMAIL}
    password: ${PLAUD_PASSWORD}
    token: ${PLAUD_TOKEN}
    export_dir: ${PLAUD_EXPORT_DIR}
  return_data_only: True
```

Environment variables (`.env/apps.env`):

```env
PLAUD_EMAIL=          # web.plaud.ai login — enables automatic token minting (preferred)
PLAUD_PASSWORD=       #   "
PLAUD_TOKEN=          # manual bearer from web.plaud.ai localStorage ("tokenstr") — expires
PLAUD_EXPORT_DIR=     # local folder you export Plaud recordings into (fallback)
```

Any one is sufficient. Auth precedence inside the cloud backend:

1. **Credentials** (`PLAUD_EMAIL` + `PLAUD_PASSWORD`) — the backend mints its
   own ~300-day JWT via `POST /auth/access-token` (the web app's login call),
   caches it in the git-ignored `logs/plaud_token.json`, re-mints within 30
   days of expiry, and transparently re-mints + retries once when the API
   answers `-419 token expired`. Set-and-forget.
2. **Manual token** (`PLAUD_TOKEN`) — used when no credentials are set, and as
   a fallback if a mint attempt fails. Expires periodically (re-paste by hand).

The regional redirect (`-302` → e.g. `api-apse1.plaud.ai`) is followed
automatically for both the auth and data calls; `PLAUD_API_BASE` can pin it.

Verify any of this with `python scripts/agents/check_plaud_token.py` — it prints the
active backend, auth mode, and token expiry, and lists a window of recordings
without writing anything.

## Available Services

| Class | Methods | Purpose |
|---|---|---|
| `PlaudAdapter` | `list_recordings(since, until)`, `ensure_audio_local(rec, dest_dir)`, `status` | Acquisition facade (cloud → folder) |
| `PlaudCloudBackend` | `available`, `list_recordings`, `ensure_audio_local`, `token_info` | Unofficial `api.plaud.ai` client with token mint/refresh (isolated) |
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
pytest apps/plaud/tests/ -m smoke          # folder backend + mocked token lifecycle, no credentials
pytest apps/plaud/tests/ -m sanity         # live cloud check (needs PLAUD_TOKEN)
```

## Notes

- **The cloud surface is unofficial and may break.** Endpoints and field names
  were reverse-engineered from the web app (per the openplaud / plaud-toolkit
  projects) — everything is wrapped defensively, and a changed surface degrades
  to the export-folder backend rather than crashing the pipeline.
- **Folder pairing:** an audio file `Foo.mp3` pairs with `Foo.txt`/`Foo.md`
  (transcript) and `Foo-summary.md` / `Foo_summary.txt` (summary) in the same
  directory. Recording id is derived deterministically from the file date + stem,
  so re-runs upsert in Elasticsearch instead of duplicating.
- **Transcription:** when neither backend yields a transcript, the HFL ingest
  task transcribes the audio itself (OpenAI Whisper) — see
  `workflows/hfl/tasks/ingest_plaud.py`.
- **Future:** when Plaud's official OAuth API leaves beta, implement a third
  backend behind the same `PlaudBackend` interface and make it primary.
