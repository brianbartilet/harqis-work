# Activity Graph deployment and propagation

## Before deploying

Merge the feature PR into the runtime branch (`main` on harqis-mac-mini) before invoking `$deploy-harqis --remote harqis-mac-mini`. The deployment skill pulls the currently checked-out branch; publishing a PR alone does not install it. No deployment, remote configuration update, or historical model backfill was performed while preparing this PR.

Configure the following through the server's existing private environment/machine settings, loaded consistently by the frontend, canonical HFL writer/API, and enrichment worker. Git does not distribute these private settings.

| Setting | Requirement |
| --- | --- |
| `HARQIS_ENTITIES_DB` | Required absolute, writable, persistent **host-local** SQLite file path. The frontend, canonical writer/API and entity worker must use the same file. For example `/Users/harqis-one/.harqis-data/corpus-entities.sqlite3`. Use your actual persistent data directory. |
| `HARQIS_ENTITIES_QUEUE` | Full Celery queue name; defaults to `hfl`. Must be consumed by the worker on the host holding that SQLite file. A queue prefix is not automatically added. Do not reuse the Windows preview queue. |
| `HFL_CORPUS_API_URL` / `HFL_CORPUS_API_TOKEN` | Keep the existing canonical corpus connection if remote reads are configured. Otherwise the configured local corpus root must be accessible to the frontend and worker. |
| Existing `ANTHROPIC` integration credentials | Required on the enrichment worker for extracting people, companies, tools and topics. These use the existing apps configuration. |
| `HARQIS_CONNECTED_ANSWER_MODEL` | Optional model override; the implemented default is `claude-haiku-4-5-20251001`. Ensure the configured provider account can use the chosen model. |
| `HARQIS_OBSIDIAN_VAULT` | Optional writable vault path, only if using export. |

Keep the existing canonical HFL API, one Beat scheduler, HFL worker and five-minute `flush_hfl_outbox` broadcast schedule enabled. The enrichment task is registered as `workflows.knowledge.tasks.connected_hfl.refresh_corpus_entities`. Workers on other machines must not consume the entity queue using a separate SQLite database: this feature does not replicate entity stores between hosts. For a split frontend/worker deployment, colocate the entity frontend and worker with the store before enabling this feature.

The schema is created automatically on first use; existing stores gain missing tables/columns automatically. Back up an existing SQLite store using SQLite's backup facility or while its writers are stopped. It contains curated profiles, contacts, notes and identity decisions that cannot be reconstructed solely from the corpus.

Compiled graph assets are tracked in the PR. A normal checkout does not require a Node runtime to serve them. If rebuilding assets, use `npm ci` and `npm run build:knowledge-graph`. Do not use `scripts/knowledge_preview.py` for the server: it substitutes isolated paths, queue names, and loopback preview settings. Do not set `HARQIS_CONNECTED_PREVIEW` in production.

## What propagates

1. **Entries, sources and dates:** Graph requests read all currently permitted canonical corpus documents. Each selected entry gets source-membership and occurrence-date edges. Activity Graph requests all matching nodes (`limit=0`) within the shared Corpus/Kanban workspace selection. Additional graph filters and presets can hide nodes; the information helper shows matching and displayed counts. Search and source/date filters run before selection. Missing occurrence dates are excluded. The open graph checks for updates approximately every three seconds and when returning to the tab. Checks pause while the tab is hidden, during interaction, or while a dialog is open. Changed responses preserve positions, zoom, selection and orb filters; unchanged responses do not redraw. Manual Refresh remains available. There is no live push feed.
2. **Entities and evidence:** Qualified object references are available immediately. People, companies, tools and substantive topics appear after model enrichment. Only literal supported mentions with matching current entry hashes are displayed. This is explicit evidence, not inferred social relationships. Ambiguous people/company names remain separate until reviewed.
3. **New/edited activity:** Canonical persistence records durable enrichment intent for that entry. Document edits request a rescan. The worker processes at most eight entries per model call, checks current source permissions/content again, and schedules bounded continuation tasks until complete. Existing matching hashes avoid re-extraction.
4. **Failures and recovery:** Failed broker sends leave pending SQLite work. Existing HFL outbox recovery retries dispatch every five minutes; queued work becomes eligible for redispatch after ten minutes. Tasks use bounded retries, revision checks and a host-local lock. A provider error or an incomplete source read does not erase existing metadata. Monitor the processing status if progress stalls.
5. **Changed/deleted/protected content:** Each graph/index joins metadata to the current permitted source. Stale mentions disappear immediately from the projection; enrichment prunes removed entries after a successful source read. User-curated profiles survive pruning. A signed entry locator fetches just its current document and rechecks access, avoiding a full corpus scan for the entry dialog.
6. **Browser state:** Layouts, dropped positions, pan/zoom and view preferences live in browser localStorage, scoped by origin and user. They do not migrate from `127.0.0.1:8092` to the server. They are not server entity data.

The initial entity directory loads 100 entities with Load more entities for additional records. Its text/profile filters apply to loaded entities. Source/date graph queries still read the complete permitted source before constructing a bounded response; the entry-dialog optimization does not eliminate that graph startup cost.

## First run after your manual deployment

1. Confirm the deployment skill reports `REMOTE HOST RESTART VERIFIED` and the frontend, canonical HFL API and Celery worker are healthy. Confirm the worker registers `workflows.knowledge.tasks.connected_hfl.refresh_corpus_entities` and consumes the configured entity queue.
2. Sign in and open `/hfl-corpus/graph` and `/hfl-corpus/entities`. Source/date nodes and explicit object references should work before model backfill. APIs require the existing owner session: `GET /api/hfl/entities/graph`, `GET /api/hfl/entities`, and `GET /api/hfl/entities/status`.
3. In Entities, open **Processing and optional export**, choose **Enrich corpus history** once, then **Check progress**. This starts model-backed historical processing across current permitted entries and incurs provider usage. It is not automatically started by deploying. `job.state` should eventually become `complete`; `enrichment.pending` should reach zero. Large histories require multiple batches.
4. Verify a known entry: its graph links should include its source, occurrence date and enriched entity mentions. Use search or a narrower date range if it falls outside the visible node budget. Select the entry and open its dialog to check metadata and reference access.
5. Create an ordinary entry through the existing corpus UI, wait for enrichment, and refresh. Check the new source/date/mention edges. Edit its content and verify obsolete mentions disappear and new supported mentions arrive. Use the existing permission controls to confirm protected content is excluded.
6. If status remains `retrying` or `failed`, check worker logs, provider credentials, canonical source connectivity, matching DB paths and queue consumption. A fresh empty store on another host does not contain the preview's enrichment or curated profiles. Rebuild enrichment via backfill; migrate curated profiles/decisions only through an explicit, backed-up store migration.

## Validation included with this PR

Regression tests cover owner access, secret/deleted/stale entry suppression, occurrence/source filters, bounded responses, profile preservation, signed direct document loading, durable broker-failure recovery, two-batch continuation, and new/edited entry propagation into entity/source/date edges. Model and broker behavior in propagation tests are mocked; production credentials, queue consumption and historical completion must be verified after deployment.
