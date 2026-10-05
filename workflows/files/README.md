# Files workflow

Deterministic file indexing and Drive package delivery for **Organize → Files**.
See the [deployment guide](../../docs/info/FILES-DEPLOYMENT.md) and
[runtime decision](../../docs/info/FILES-IMPLEMENTATION.md).

**Runtime:** `celery`; no autonomous agent steps.
**Schedule owner:** one Celery Beat.
**Queue:** `WorkflowQueue.FILES` (`files`, or configured `FILES_QUEUE`), on the catalog server.
**OS:** cross-platform; configured local paths belong to one host.
**Apps:** `apps/file_index` → local/SFTP/HTTP or `apps/google_apps` Drive service.
**Config:** `GOOGLE_DRIVE` by default; all `FILES_*` settings documented in the app/runbook.

| Entry point in `tasks/index.py` | Trigger | Behavior |
|---|---|---|
| `scan_source(source_id)` | Manual UI or maintenance | Stream source metadata, upsert stable locations, reconcile missing files only after a complete scan |
| `publish_package(revision_id)` | Explicit owner publication | Retrieve selected files, persist preallocated Drive IDs, upload private copies, then grant public read access |
| `maintain_files()` | Every minute when `FILES_ENABLED=1` | Revoke expired public grants and queue sources due for their configured scan interval |

`__init__.py` imports the task module. `tasks_config.py` is opt-in and is merged
into `workflows/config.py`. Installing the code with the flag unset does not
activate recurring work. `scan_source` and `publish_package` remain callable
on demand. The default source recurrence is 24 hours, editable through the API
and selected when adding a source. Restart Beat after changing the enable flag.

## Data flow and failure handling

```text
configured source → metadata catalog → owner selection → immutable revision
                  → bounded retrieval → private Drive copies → public grant
                  → deadline → guest denial + Drive permission revocation
```

Source/file/package audit records are the durable Review artifact. They replace
Elasticsearch-only task logging for these operations. Scan tasks retry transient
OS/runtime failures up to three times; publication retries failures with backoff.
Lease contention is retryable. Incomplete discovery never marks unseen files
missing. A failed upload remains unpublished and its IDs survive retries.
Public permission response loss is recoverable using the saved folder ID and
deadline. Expiry failures remain audited and retry on the next maintenance tick.

The worker task limit is one hour; leases last 65 minutes after a process crash.
Maintenance has a two-minute limit and three-minute lease. Source interval
dispatch and maintenance have their own audit/task identifiers. Keep enough
worker capacity for expiry independently of large transfers.

## Generated outputs

`output_signals.py` listens to successful Celery results for explicit path fields.
It only registers existing files inside enabled local roots on the catalog host.
It is best-effort and cannot fail the producer. Recurring scans recover missed
registration, including older generated files already present in selected roots.
Remote producers should use a configured remote source; this workflow does not
share a SQLite catalog over the network.

## Validation

`tests/test_index.py` executes a real local scan task against temporary files and
checks task registration, opt-in Beat configuration, dispatch deduplication, and
bounded output-path extraction. Override the root pytest workflow ignore using
`-o addopts=` and load the normal host environment before importing tasks.
