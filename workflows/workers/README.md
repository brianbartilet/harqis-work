# Workers Workflow

Cluster telemetry for HARQIS worker nodes. The workflow broadcasts one task to
every worker subscribed to `workers_broadcast`; each node resolves its own
location and updates its latest Elasticsearch document.

## `broadcast_report_location`

**Task:** `workflows.workers.tasks.broadcast_report_location`

**Schedule:** Every 15 minutes, with a 15-minute expiry.

**Queue:** `workers_broadcast` fanout. A new worker must include that queue in
its queue list, for example:

```powershell
python scripts/deploy.py --role node -q default,workers_broadcast
```

**Location cascade:**

1. Static `WORKER_LAT` and `WORKER_LON` environment values.
2. Public-IP geolocation through `ip-api.com`, unless
   `WORKER_SKIP_IP_GEO=true`.
3. Latest fix from the configured OwnTracks Recorder block, default `OWN_TRACKS`.
4. A document with `source="unavailable"` when no coordinates can be resolved.

**Output:** The task overwrites `<machine_name>_latest` in
`harqis-worker-locations`, configurable with `WORKER_LOCATIONS_INDEX`. The
document includes host/platform identity, current and prior fixes, OwnTracks
identity, timestamps, and the Elasticsearch write result.

Elasticsearch failures are logged and returned as `es_indexed: false`; they do
not crash the broadcast task. Fanout work must remain idempotent because all
subscribed workers execute concurrently.

## Tests

```powershell
pytest workflows/workers/tests
```

Tests mock location sources and persistence; do not depend on public IP
geolocation for deterministic assertions.
