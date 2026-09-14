# Activity Corpus entities and relationships

## Feature Spec — Corpus-derived entities and graph

**Goal:** Explain how canonical HFL activities connect across sources and time, with inspectable evidence.

**Trigger:** Successful canonical HFL writes and corpus document edits; manual historical backfill.

**Automation runtime:**
- Classification: celery. Bounded schema-driven extraction does not require an adaptive agent.
- Execution owner: Celery for extraction, retries, continuation and metadata persistence.
- Schedule owner: existing Celery Beat HFL outbox recovery; no new periodic schedule.
- Decision record: canonical change events create durable intent; the existing outbox recovery retries undispatched/stale intent. Manual backfill uses the same worker.

**Primary files changed:**
- frontend/modules/hfl_corpus/entities.py, entity_source.py, entities_api.py — current corpus projections, owner routes, evidence and timelines.
- workflows/hfl/entity_store.py, entity_events.py — metadata only, reversible identity decisions, durable work intent.
- workflows/hfl/persistence.py and frontend/modules/hfl_corpus/document_edit.py — post-write notification.
- workflows/knowledge/tasks/connected_hfl.py — bounded Celery enrichment.
- frontend/src/knowledge-graph.jsx and corpus templates — graph, source/date filters, grouping and entity review.

**Files / components NOT touched:**
- HFL narrative schema and producer-specific automated ingestion — remain canonical.
- Share Corpus retrieval and chat — retained; no second chat implementation.
- Existing generic Knowledge/RAG tools — retained independently of this corpus feature.

**Inputs:** Current permitted corpus entries, stable IDs or the existing deterministic legacy locator; references, source, dates, tags and content.

**Outputs / side-effects:** Derived mentions with source hashes and extractor version; explicit object identities; reversible merge decisions; source/date graph links and entity timelines; optional explicit Obsidian export.

**Error handling:** Incomplete reads do not prune; inaccessible sources fail closed. Changed hashes suppress stale extraction immediately. Provider failures retain work for bounded retries. Canonical writes do not wait for enrichment. Broker failures retain intent in SQLite.

**New dependencies:**
- Apps: none; existing Anthropic integration.
- Packages: React Force Graph and its existing pinned build dependencies are retained.
- Env vars: HARQIS_ENTITIES_DB and HARQIS_ENTITIES_QUEUE. Existing corpus URL/token settings provide source access.

**Edge cases addressed:** Duplicate/conflicting source identities; changed or removed entries; protected entries; ambiguous same-name people; alias cycles and undo; partial model responses; explicit-only indexing versus completed extraction; old URLs redirected to the graph.

**Acceptance criteria:**
- [x] Activity Corpus owns Graph and Entities navigation.
- [x] No duplicate knowledge capture/chat API or second HFL content store.
- [x] Every graph edge has a relation, method and evidence.
- [x] Source/date filtering and source/month grouping are available.
- [x] Entity timelines link to permitted source entries.
- [x] Explicit object identities join automatically; ambiguous people/companies remain separate.
- [x] Review decisions are reversible and reject cycles.
- [x] Source changes trigger asynchronous bounded enrichment; a manual backfill is available.
- [x] Obsidian is an optional one-way export.

**Open questions / assumptions:** The user's five affirmative answers and explicit implementation request authorize this scope. Obsidian stays optional. Semantic similarity and inferred relationship assertions are deferred. No autonomous name-only person merge is enabled.

## Architecture

HFL remains the source of truth. The derived store contains entry hashes, evidence excerpts, extraction versions, identity decisions and work intent. It contains no authoritative full-text entry copy and no embeddings. Source text is read through the existing corpus adapter.

The graph is a projection of current permitted entries. Cached extraction must match the current hash. Source and date are explicit dimensions; tags are preserved as entry metadata, not automatically promoted to topics. Generic acronym matches are no longer graph entities. Model-extracted people/companies use entry-scoped provisional IDs until an accepted identity decision connects them. Object URLs and qualified repository references carry explicit IDs.

Visual grouping is a navigation aid, not a relationship assertion. Edges distinguish mentions, source membership and occurrence dates. This release does not assert employment, causation, or semantic similarity.

## Identity policy

Exact explicit object identifiers resolve deterministically across entries. Formatting whitespace is normalized for labels; ambiguous names are not case-folded into one person. Accepted aliases apply across projections and have a reason, timestamp and undo record. A human or future agent may submit a supported merge through the same authenticated API. This release does not introduce an independent adaptive agent scheduler.

## Privacy and lifecycle

Every projection re-reads the permitted corpus scope. Withdrawn or protected entries cannot remain visible just because extraction was cached. Remote retrieval requests a complete entry-bearing manifest; older servers support the compatible whitespace query. Where entries are unavailable in the manifest, bounded parallel document reads use a manifest-validated in-memory cache, never a stale fallback on source failure.

Model batches are revalidated against the source before saving. Source hashes and extractor versions determine whether work is current. Full reconciliation prunes metadata for missing entries. Extracted evidence remains local derived data; public Share Corpus does not traverse it.

## Delivery boundary

Canonical hooks run on hosts carrying this branch and configured entity settings. The localhost preview does not deploy hooks to the remote canonical server. Historical backfill is manual. Existing corpus recovery owns recurring retries; the preview worker has no Beat process.


## Editable entity directory

Entities now support durable curated profiles: display name, multiple email addresses and phone numbers, free-form categories, and notes. Expand an entity and choose **Edit profile**. These owner-only records live in the `profiles` table alongside derived metadata, but are not deleted by enrichment/pruning. Back up the SQLite database: it now contains original user-maintained data as well as rebuildable metadata. A saved profile remains in the directory without supporting entries; source-filtered results require current supporting activity. Graph labels use curated names.

URLs, web domains and email addresses are excluded as entity names from both existing cached mentions and new extraction. Links remain in corpus text. Repository-qualified references such as `org/repo#123` remain legitimate referenced objects. Extraction does not automatically fill or overwrite contact fields, and a shared contact value does not automatically merge identities.

The directory offers type, category, activity-source and profile/contact filters, combined search across names/contact details/categories/notes, name/activity/recency sorting, and 25-item pagination. Existing type classifications organize entries immediately; custom categories are user-maintained, with an Uncategorized filter for unfinished records. Search is literal and runs locally over the permitted index.

Identity merges retain the canonical profile; an alias profile is preserved separately for undo rather than silently combining potentially conflicting contact details. Curated profile/contact data is not included in the optional Obsidian export, which remains a corpus-derived export.
