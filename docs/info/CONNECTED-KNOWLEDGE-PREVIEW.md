# Activity Corpus entities — local review

This branch replaces the standalone Connected Knowledge product with Graph and Entities inside Activity Corpus.

## Open locally

- Activity Corpus: http://127.0.0.1:8092/hfl-corpus
- Graph: http://127.0.0.1:8092/hfl-corpus/graph
- Entity timelines and processing: http://127.0.0.1:8092/hfl-corpus/entities
- Fictional library example: http://127.0.0.1:8092/hfl-corpus/graph?example=1

Use the existing HARQIS login. Old /knowledge and /knowledge/graph links redirect.

## What changed

The duplicate capture, chat, search and contextual-memory UI/API were removed. Existing Activity Corpus ingestion and manual entry creation remain the entry points; Share Corpus retains scoped chat. The old preview SQLite/content copy is not used by the new feature and is retained on disk for recovery, rather than deleted.

The new metadata-only SQLite store tracks hashes, extraction versions, mentions, evidence, reversible identity decisions and durable work intent. Graphs join that metadata to current permitted corpus entries. Source/date filters run before graph construction; source and month grouping use the same current metadata. Entity timelines show source, date and supporting excerpts. Generic tags and acronyms are no longer blindly promoted to topics.

Canonical persistence and document edits notify the Celery enrichment task. Work intent survives broker failure and is retried by existing HFL outbox recovery. Each model request processes at most eight entries. Historical backfill continues in bounded child tasks and reports progress in the Entities page. There is no new polling schedule and no second corpus ingestion pipeline.

Explicit object references join automatically. Ambiguous person/company names remain separate. Exception review records same-type identity merges with reasons and supports undo. Obsidian export is optional and retains conflict handling.

## Start and rebuild

From this feature worktree, using the configured repository environment:

```powershell
C:/Users/brian/GIT/harqis-work/.venv/Scripts/python.exe scripts/knowledge_preview.py frontend --port 8092
C:/Users/brian/GIT/harqis-work/.venv/Scripts/python.exe scripts/knowledge_preview.py worker
npm ci
npm run build:knowledge-graph
```

The launcher loads machine configuration, then uses loopback 8092 and the isolated connected-preview.adhoc queue. Derived state is .harqis-data/connected-preview/corpus-entities.sqlite3. Source reads use the existing canonical corpus URL/token; secrets are not stored in tracked files. It does not launch Beat or deploy the canonical hooks remotely.

Host settings: HARQIS_ENTITIES_DB identifies a local SQLite path; HARQIS_ENTITIES_QUEUE is the full queue name, normally hfl on the canonical host. HARQIS_OBSIDIAN_VAULT is optional. Existing HFL_CORPUS_API_URL/TOKEN control remote reads. Backfill is explicitly started through the Entities page.

## Review steps

1. Open Graph, filter a source/date range, change grouping, select a node and inspect the evidence beside its connections.
2. Open Entities, search a person/tool/object, and expand its dated source entries.
3. Use Processing to start a historical backfill and inspect its current job state.
4. Review ambiguous same-name identities only when the evidence supports a merge; undo the decision to separate them again.
5. Optionally export Obsidian; local edited notes remain protected by export conflict handling.

## Validation and limits

Regression coverage includes authentication, removal of duplicate APIs, source/date filters, edge evidence, stale/removed entry suppression, source failure without pruning, ambiguous-name separation, explicit-ID linking, reversible merges, model revalidation, and broker failure retention. Optional export conflict/path tests remain.

Semantic similarity and inferred relationship assertions are intentionally deferred. The 100/500/1,000 node display budgets and grouping are navigation tools, not completeness or community-discovery claims. Enrichment is not deployed to the remote source host by launching this local preview. The graph can show explicit references immediately; model-derived entities depend on completed enrichment.

See the approved architecture and runtime record in ../thesis/CONNECTED-HFL-KNOWLEDGE.md.

## Verified local outcome

- 4,889 current permitted canonical entries were read during verification.
- 142 earlier extraction records were reused only after checking their stored hash, current source text and literal evidence; a live Celery/model smoke job enriched one additional previously uncached entry.
- The broader regression run passed 125 tests, including Share Corpus, persistence and editing. The final focused rerun passed 24 tests, including two additional source-adapter cases.
- Browser verification passed for the live graph, source grouping, selected-link evidence, example mode, entity timelines, authenticated entry navigation and mobile width. No JavaScript errors were observed.
- Full historical model enrichment was not launched automatically. Use Enrich corpus history when ready; explicit references and validated existing extraction are already visible.
- Canonical hooks are implemented in this branch but have not been deployed to the remote source host. Local worker and frontend use the isolated preview queue and store.


## Editable entity directory

Entities now support durable curated profiles: display name, multiple email addresses and phone numbers, free-form categories, and notes. Expand an entity and choose **Edit profile**. These owner-only records live in the `profiles` table alongside derived metadata, but are not deleted by enrichment/pruning. Back up the SQLite database: it now contains original user-maintained data as well as rebuildable metadata. A saved profile remains in the directory without supporting entries; source-filtered results require current supporting activity. Graph labels use curated names.

URLs, web domains and email addresses are excluded as entity names from both existing cached mentions and new extraction. Links remain in corpus text. Repository-qualified references such as `org/repo#123` remain legitimate referenced objects. Extraction does not automatically fill or overwrite contact fields, and a shared contact value does not automatically merge identities.

The directory offers type, category, activity-source and profile/contact filters, combined search across names/contact details/categories/notes, name/activity/recency sorting, and 25-item pagination. Existing type classifications organize entries immediately; custom categories are user-maintained, with an Uncategorized filter for unfinished records. Search is literal and runs locally over the loaded portion of the permitted index. The directory initially loads 100 entities; Load more entities adds another 100.

Identity merges retain the canonical profile; an alias profile is preserved separately for undo rather than silently combining potentially conflicting contact details. Curated profile/contact data is not included in the optional Obsidian export, which remains a corpus-derived export.

Directory follow-up validation: 17 focused tests passed. Live desktop/mobile browser checks covered filters, pagination and profile editing; an isolated browser fixture verified profile saving and combined contact/category search without modifying live contacts. The permitted live directory contained 283 entities after URL exclusion (42 people) at verification time.

## Bounded graph responses

The graph API accepts `limit` (1–1,000, default 100), `query`, `shared`, `source` (or repeated `sources`), `since`, and `until`. It filters before selection, favors recent matching entries and their connected neighbors, and returns at most `limit` nodes and `4 * limit` links. Metadata includes `total_nodes`, `matching_entries`, and `truncated`. The UI sends search/detail/shared changes to the server and discards superseded responses. Type toggles and focus operate within the returned view. Source reads still scan the current permitted corpus; this bounds graph construction and transfer, not ingestion/source-reading cost. No stale-result cache is introduced.

## Browser layout saving

The graph automatically saves node positions and pan/zoom in localStorage, scoped to the signed-in user. It retains the latest ten views keyed by search, detail, sources, dates, shared-only, grouping, types and focus. Returning to the same view restores its coordinates; newly appearing nodes still receive a layout. Reset removes the current view layout before resetting display controls. Saved layouts are local to this browser/origin, are not synchronized to the server, and contain node IDs/coordinates plus filter values rather than entry text. Storage failure is shown in the view status.

Graph detail limits are now Overview 100, Expanded 500 and Dense 1,000 (API default 100, maximum 1,000). The latest selected detail, search, applied source/date filters, shared-only setting and grouping are remembered per user/browser and restored before the initial graph request.

Saved graph coordinates restore starting positions. Manually dragged nodes also retain their drop constraints; dragging a connected node releases its neighbors so they can follow. Earlier snapshots without constraint flags remain compatible.


## Production rollout

See [Activity Graph deployment and propagation](ACTIVITY-GRAPH-DEPLOYMENT.md) for required server settings, initial historical enrichment, verification, and persistence boundaries. The local preview launcher is not the production deployment command.
