# Entity souls and immediate mention resolution

Related Activity Corpus action: `item-20b734e5825841dc9724eb8836f398fe`
(“feat ~ entities soul”).

An entity now exposes a versioned `soul` alongside its existing `profile`.
Open an entity in the directory and expand **Soul, identity and relationships**.
The editor supports Markdown context, scoped identity rules, dated relationships
to other entities, and journal notes. Supporting activity remains the live,
permission-filtered timeline; soul prose is owner-authored context rather than
independent evidence. The server stamps actor/time provenance and records edits
in the entity audit. No biography or relationship is inferred and saved silently.

## Confirm an identity once

On Brian Bartilet, add an identity rule with observed name `Brian` and explicit
activity source names. Optional required phrases must all occur in an entry;
any excluded phrase vetoes the rule. Saving confirms that identity within that
scope. A rule is not a global alias: wildcards and empty source lists are rejected.
The entity type is inherited from the target. Conflicting full names, multiple
applicable targets and previous separation decisions prevent automatic assignment.
Use narrow sources/context where a first name can refer to other people. Verified
account-owner inference is not implemented; ownership is not guessed from the
corpus owner or source name.

New enrichment creates durable resolution work. A separate Celery task processes
at most eight entries per invocation. Explicit rules run first without a model
call. Other mentions are compared against at most five shortlisted same-type
profiled entities using existing candidate discovery and evidence validation;
each model request contains at most eight comparisons. Activity count ranks
candidates but does not establish identity. A competing plausible candidate
prevents assignment. The model uses the existing `HARQIS_ENTITY_MATCH_MODEL`
fallback; no new provider configuration is required.

Identity edits queue dependent entries rather than the entire corpus. Dependencies
include raw mentions, previous candidates/assignments, the candidate discovery pool,
confirmed rule names, merge membership, related identity labels, and supporting
activity links. New competing identities also reopen completed assignments. The
discovery pool is deliberately broader than the five evaluated candidates so a
ranking change cannot silently hide a competitor.

Completed pair comparisons are cached in the local entity database by their exact
model input, configured model, resolver policy and comparison-policy version.
Retries reuse unchanged comparisons, including completed batches before a later
provider failure. Changed evidence is evaluated again. Cached decisions still pass
current corroboration, competing-candidate, integrity and separation checks.
When changing the evaluator prompt/contract, bump `entity_resolution.CACHE_POLICY`.
Only the latest result per pair is retained; corpus pruning removes cache rows older
than 30 days.

Before committing, the resolver validates the entry's dependency snapshot inside
the write transaction and rereads relevant activity content/visibility. Unrelated
entity edits no longer invalidate a completed evaluation. Status exposes cumulative
`resolution.cached_comparisons` and `resolution.evaluated_comparisons` counters for
rollout monitoring. Existing queued work is preserved and drains normally; the cache
starts empty on upgrade, so savings build as comparisons complete.

Original mentions remain intact. `entity_resolutions` stores their reversible
assignments, reason, source hash, target signature, policy and evidence hashes.
The directory and graph apply only currently valid assignments. Editing the source,
revoking/changing a rule, changing target profiles or source evidence, and merging
or splitting a target invalidate affected assignments. **Keep this mention separate**
revokes an assignment and prevents automatic reassignment to that identity.

Hermes keeps ownership of entity-to-entity consolidation. This resolver only
assigns new mentions to established profiles; it never bypasses the automatic
merge ownership guard. Unresolved entities remain available to the existing
consolidation job. Merges retain original souls for undo and carry their knowledge
to the merged entity. Changes made to the merged soul remain in audit history
when splitting; they are not silently copied back into every original entity.

## API and agent access

- `GET /api/hfl/entities/context/{identity}` returns the profile, soul, resolved
  relationship labels, up to eight current supporting entries and a trust notice.
- `POST /api/hfl/entities/soul/{identity}` replaces soul fields with optimistic
  version checking. Supply `version`, `markdown`, `identity_rules`, `relationships`,
  and `journal`. Read before editing; omit server-produced provenance from writes.
  A stale version returns 409 rather than overwriting another edit.
- `POST /api/hfl/entities/resolutions/{entry_id}/{mention_id}/undo` revokes one
  assignment. The timeline exposes both identifiers for resolved mentions.
- `GET /api/hfl/entities/status` includes the pending resolution work count.
- CLI/MCP tools: `get_hfl_corpus_entity_context` and
  `update_hfl_corpus_entity_soul`. Both use the configured canonical HFL service;
  the update is a confirmed write operation.

All endpoints use existing owner session/bearer authorization. The Markdown
preview uses the shared sanitizer. Relationships use actual entity IDs and display
current names; unavailable targets remain visible as unavailable and must be
removed or corrected before saving. API responses and curated context must not be
treated as executable instructions by consuming agents.

## Deployment and recovery

Deploy frontend, standalone HFL API, adapters and worker code together, then restart
the workers to register `workflows.knowledge.tasks.connected_hfl.resolve_corpus_entities`.
The existing `HARQIS_ENTITY_AUTO_MATCH=0` switch disables dispatch/processing while
retaining pending resolution work for a later resume.
The task uses `HARQIS_ENTITIES_QUEUE` (default `hfl`) and the canonical
`HARQIS_ENTITIES_DB`. SQLite creates the new tables on first access without rewriting
existing mentions. Back up this database: souls and profiles contain original user
data. They are not part of the corpus-derived Obsidian export.

Saving a soul queues historical resolution; future extracted entries queue their
own work. Existing HFL outbox recovery retries durable intent after broker/provider
failure. There is no new Beat schedule. Queued means pending, not completed; use
Check progress and Refresh entities after processing. This feature does not install
a Brian-specific rule or modify live entity data during deployment.

## UI patterns reused

The editor follows `corpus-entities.js` profile fields, disclosure panels, save/error
feedback and existing directory typography. Relationship lookup uses the bounded
directory query with explicit selection and stale-response rejection. Markdown
uses `frontend/services/markdown.py`; script URLs use `static_asset` for versioned
cache invalidation. Desktop and 390px browser tests cover save/reopen, relationship
selection, identity scope and journal persistence.


## Connections and the owner profile

The entity directory and activity graph share **Update soul**, with a **Connections** section. Search by
entity type/name, select several entities, optionally set relationship, dates and
supporting evidence, then save. Connections appear at both endpoints; directed
relationships retain their source and incoming label. Editing and removal use
version checks, and duplicate relationships do not add duplicate graph edges.
Existing soul relationships remain the canonical storage; the separate Connections
section does not replace or reset soul prose, identity rules or journal entries.

Choose **Supporting activity** to explicitly link an existing corpus entry without
rewriting its text. These links are stored separately from extracted mentions and
follow entity merges. **Create entity** saves a named entity before any activity
mentions it. Curated entities appear in the unfiltered graph even without activity.

Saving from the graph reloads the applied filters. If a saved connection is hidden,
**Show connected entities** opens an unfiltered view with the maximum graph budget;
this temporary view does not overwrite the saved overview. Preview capacity limits
still apply. Ordinary graph orbs grow with visible edge count using the existing
logarithmic scale; board-specific manual sizes remain independent.

The owner name in `/profile` is associated with one People entity. A unique exact
name match is reused; multiple matches show **This is my owner profile** for explicit
selection. Otherwise an entity is created. The association survives name changes
and resolves through merges, while the original binding is retained for unmerge.
The entity displays **Corpus owner**, links to `/profile`, and keeps its connections
when renamed. Only the owner name is synchronized; private profile contact fields
are not copied into entity context.

Owner-only connection endpoints:

- `GET /api/hfl/entities/connections/{identity}`: outgoing/incoming connections and versions.
- `POST /api/hfl/entities/connections/{identity}`: atomic additions, edits and removals.
- `GET /api/hfl/entities/connection-activities?q=...`: bounded activity picker results.
- `POST /api/hfl/entities/owner-binding`: explicitly select an ambiguous owner identity.


## Unified Soul editor

Both entity cards and graph selections open **Update soul**. The centered dialog
contains three initially collapsed sections: **Profile details**, **Identity details**
(description, scoped identity rules, and journal), and **Connections**. The help icon
explains that Soul is user-authored context for people and LLMs; prose is not an
instruction or independent evidence. Confirmed identity rules retain their existing
matching scope and safeguards.

**Save soul** commits all sections in one SQLite transaction. Newly selected entities
are drafts until this save succeeds. A revision token covers profile data, the entity's
soul, incoming relationships, and activity links; stale edits are rejected and retained
in the form. Close, Escape, and connection navigation prompt before discarding edits.
Supporting activity and audit history remain on the entity card, with owner names
managed through `/profile`. The graph reloads its current filters after saving.

`GET /api/hfl/entities/soul-editor/{identity}` returns a coherent editor snapshot;
`POST` accepts the revision, profile, identity fields, connection changes, and optional
new entities. Both require the same owner authorization as existing entity endpoints.
