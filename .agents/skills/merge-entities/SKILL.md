---
name: merge-entities
description: Search Activity Corpus entities, preview and perform same-type bulk merges, inspect merge audits, or reverse a merge through the authenticated entity API. Use when a user asks agents to consolidate or unmerge entity identities.
---

# Merge Activity Corpus entities

Use the running HARQIS API, not direct database writes. The directory, graph and agents
share the same merge service. Read [the API contract](../../../docs/info/ENTITY-MERGES.md)
for endpoint paths, payloads and reversal behavior.

## Connect and resolve

Use the user-specified instance. Otherwise resolve `HFL_CORPUS_API_URL` and
`HFL_CORPUS_API_TOKEN` from the existing machine configuration; do not print credentials.
When executing repository Python, load the machine environment before importing apps
or workflows, following the available `harqis-env-context` skill.

Search `GET /api/hfl/entities?q=...&kind=...`. A nonzero `limit` requires paging with
`offset` until `total` matching records are collected. `counts` are full type counts.
Resolve exact entity IDs and inspect supporting entries. A shared name alone does not
establish identity; ask one focused question if matches or the intended scope are ambiguous.
Never expand a request for specific entities to every search result silently.

## Merge

1. Require at least two distinct entities of one type, a resulting name, and optional
   user-provided evidence. Explicit instructions to perform the merge authorize it;
   a request to investigate duplicates authorizes a preview only.
2. Submit `/merge-preview`; inspect member IDs, unique supporting-entry count and
   combined fields. Do not truncate the preview or reconstruct its token.
3. Submit `/merges` with the same IDs, name and evidence, its `preview_token`, and a
   fresh UUID `request_id`. Keep the exact submitted payload until the result is known.
4. If the connection fails, query `/operations/{request_id}`. Retry the exact request
   with the same ID if necessary; never generate a new ID to resolve an uncertain result.
   Stop after two transport retries and report the request ID for later recovery.
5. A 409 means the preview or selection changed. Fetch a new preview and reassess the
   original authorized scope. Do not automatically substitute different entity IDs.

Report the new identity, number of members, unique supporting entries, operation ID,
and audit-delivery state. Corpus audit delivery may continue through the durable outbox.

## Unmerge and history

Read `/audit/{entity_id}` and confirm the target is the active outermost grouping.
An explicit unmerge instruction authorizes `POST /merges/{entity_id}/unmerge` with a
fresh UUID request ID and optional evidence. Use the same retry discipline as merging.

Unmerge restores immediate members; a previously merged member remains merged until
separately reversed. Do not recursively unmerge additional groups unless requested.
Later merged-profile edits remain in audit snapshots, not copied into every original.
Legacy one-to-one merges have `legacy_decisions`; their reversal endpoint is documented.

## Automatic matching and historical scan

When explicitly asked to scan existing entities, call `POST /api/hfl/entities/matching/scan`.
This starts/resumes the one-time job; do not manufacture fresh jobs to bypass completion
or retry limits. Check `GET /api/hfl/entities/matching` for pending work, errors and review
suggestions. Future enrichment automatically creates matching intent when enabled.
Report queued/running work accurately; a successful request is not a completed scan.

For a suggestion, inspect its reasoning and quotes. Use the ordinary merge preview and
submit workflow for an authorized acceptance. `POST /matching/suggestions/{id}/dismiss`
(beneath the entities API prefix) records a durable keep-separate decision when requested.
Do not bypass unmerge/dismissal exclusions or manually approve uncertain matches merely
to increase the number of automatic merges.

No new branch, deployment, corpus enrichment run, or unrelated merge is implied by
invoking this skill.
