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
