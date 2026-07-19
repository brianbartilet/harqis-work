# Looki L1

Read-only integration with the approval-controlled Looki developer API. It is the
Capture adapter for the metadata-first HFL path described in
[`docs/thesis/LOOKI-L1-HARQIS-INGESTION.md`](../../docs/thesis/LOOKI-L1-HARQIS-INGESTION.md).

## Express output

Looki moments become source-linked HFL entries in the existing Markdown corpus
and `harqis-hfl-entries` Elasticsearch index. Looki-generated descriptions are
stored as **unverified recall indexes**, not facts.

## Configure

1. Apply for developer access at <https://web.looki.tech/api-keys>.
2. Create a key after approval and add it to `.env/apps.env`:

   ```sh
   LOOKI_API_KEY=
   ```

3. Restart the MCP server/worker so `apps_config.yaml` is reloaded.
4. Validate access without writing HFL:

   ```sh
   MCP_ENABLED_APPS=Looki python mcp/server.py
   ```

   Then call `looki_status` and `list_looki_moments` through an MCP client for a
   known date.

The key is sent in `X-API-Key` to `https://open.looki.tech/api/v1`. Never commit
or log the key.

## MCP tools

- `looki_status` — local readiness only; no API call.
- `list_looki_moments` — bounded date-window metadata.
- `search_looki_moments` — coarse search over Looki-generated labels.
- `get_looki_moment` — one normalized moment.
- `list_looki_moment_files` — verification metadata; signed URLs are removed by
  default. `include_temporary_urls=true` is explicit, immediate-use only.

## HFL ingestion

Callable task:

```python
from workflows.hfl.tasks.ingest_looki import ingest_looki_activity

ingest_looki_activity.delay(window_days=2, max_moments=200)
```

The example Beat entry in `workflows/hfl/tasks_config.py` is intentionally
commented out until a live one-day schema smoke test succeeds. After validation,
uncomment it to poll daily at 23:25 local.

### Persistence contract

- One HFL entry per Looki moment.
- Stable reference: `looki:<moment-id>`.
- Stable ES ID: `looki-<first 128 bits / 32 hex chars of SHA-256(moment-id)>`
  (independent of corrected dates).
- Atomic claim/done files under the HFL corpus prevent overlapping workers from
  appending the same source ID; global exact-reference checks cover legacy state.
- Bounded overlapping poll window; corpus-reference check prevents duplicates.
- Metadata only: no video download, precise coordinates, or expiring signed URL.
- No LLM call: Looki text remains clearly labeled `unverified-ai`.
- Missing key, no moments, or API outage is a clean no-op.

## API-confidence boundary

The live API host and `X-API-Key` requirement are vendor-operated. The endpoint
list and response-shape handling are based on community-observed behavior because
Looki does not expose a public OpenAPI document. The adapter accepts conservative
envelope variants and drops unknown shapes rather than guessing them into HFL.
Live schema validation remains the activation gate.

## Tests

Offline contract tests require no key or network:

```sh
WORKFLOW_CONFIG=workflows.config \
PATH_APP_CONFIG="$PWD" APP_CONFIG_FILE=apps_config.yaml PYTHONPATH=. \
pytest -q -o addopts='' \
  apps/looki/tests \
  workflows/hfl/tests/test_ingest_looki.py
```
