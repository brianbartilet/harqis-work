# Entity merges

## Automatic matching

Successful model enrichment durably records a matching job alongside the extracted
mentions. A one-time historical job is available from **Automatic matching and review
suggestions → Scan existing entities once / resume**. Repeating that request resumes
a failed job or returns the existing job; it does not repeat a completed historical scan.
The historical scan examines existing entity metadata, not previously unenriched text.

Candidates must share a type and a name/alias token or contact/reference identifier.
Each entity contributes up to three strongest candidates; this is a bounded shortlist,
not an exhaustive comparison of every possible pair. Original aliases inside nested
merges remain searchable. Each model call reviews at most eight pairs with up to eight
supporting activity excerpts per entity. Related concepts are not sufficient evidence
of identity. Automatic approval requires two distinct, verbatim, substantial supporting
excerpts on both sides, no reported contradictions, and current evidence on revalidation.
Different explicit identifiers block automatic approval. These checks constrain model
judgment; they do not guarantee that an inferred identity is correct. Unmerge is available.

Manually curated names and notes are retained. Two independently curated identities
require review. Generated groups carry the provenance of curated profiles through later
automatic merges. Unmerge and **Keep separate** record durable exclusions across nested
member identities, preventing automatic remerging through another group. A subsequent
explicit manual merge remains possible.

Uncertain or insufficiently corroborated matches appear as review suggestions. **Review
suggested merge** opens the existing editable confirmation dialog; **Keep separate**
dismisses and blocks the pair. Status lists processed outcomes and pending comparisons.
Suggestions are shown in batches of 100; resolving them reveals the remaining suggestions.
Audit-source entries are excluded from enrichment and matching evidence to avoid feedback.

Runtime classification: **Celery**, with a bounded, schema-driven AI evaluator. The model
interprets evidence but does not execute mutations or choose external tools. Celery owns
dispatch, a per-store matching lock, retries, continuation, and transactional merges.
The initiators are existing enrichment or a manual historical-scan request. Existing HFL
outbox recovery redispatches interrupted jobs after ten minutes; no additional Beat schedule
is created. Four task retries precede a visible failed job. Resume the historical job using
the scan button. Durable operation receipts prevent a crash from repeating an applied merge.

Configuration: `HARQIS_ENTITY_AUTO_MATCH` defaults to `1` (set `0` to disable execution).
`HARQIS_ENTITY_MATCH_MODEL` overrides the existing configured answer model. Workers use
`HARQIS_ENTITIES_QUEUE` and must share `HARQIS_ENTITIES_DB` with the frontend/API. Matching
errors do not roll back extraction. Automatic merge audit events include the model,
policy version, input hash, evidence, reasoning, and protected-profile provenance.

Additional authenticated endpoints:

| Method and path | Behavior |
| --- | --- |
| `GET /api/hfl/entities/matching` | Job counts/states and uncertain suggestions. |
| `POST /api/hfl/entities/matching/scan` | Start or resume the one-time historical scan. |
| `POST /api/hfl/entities/matching/suggestions/{id}/dismiss` | Keep the identities separate and block future automatic matching. |

Suggestions can be accepted using the existing merge preview and submit endpoints with
their `data.entity_ids`. Stale IDs require refreshing the directory before proceeding.

The Activity Corpus Entities directory supports selecting entities across pages,
searches and filters. Select a single type (People, Companies, Tools, Topics or
Referenced objects), choose **Merge selected**, enter a name and optional evidence,
then **Review merge**, edit the combined categories, emails, phones, references or
notes as needed, and **Confirm merge**. Reviewing again preserves those edits.
**Select all matching** includes results
beyond the current 50-result page. With a selection already active, selection controls
include only its type. **Clear filters** preserves selection; **Clear selection** removes it.

The new identity combines unique supporting entries and deduplicates exact categories,
emails, phone numbers and references. Notes are grouped under their original entity
names. Original profiles and corpus evidence remain intact. Graph connections converge
on the new identity and its orb size reflects unique visible connections; graph filters
can still hide some of those connections.

Open the resulting entity to inspect **Entity audit history** or choose **Unmerge**.
Reversal restores the immediate members. For nested merges, unmerge the outer grouping
first. Edits made to a merged profile remain in audit snapshots and are not distributed
to its originals. Historical one-to-one decisions appear as **Unmerge previous alias**.

## Authentication and instance

All commands are available on the frontend server and standalone HFL API. Use
`Authorization: Bearer <HFL_CORPUS_API_TOKEN>` for agents, or the existing owner session
for browser operations. Point agents at the same instance/entity store as the UI.
Entity state is host-local (`HARQIS_ENTITIES_DB`); API requests do not synchronize
separate hosts' derived stores. Never expose tokens in logs or command output.

All paths below begin with `/api/hfl/entities`.

| Method and path | Behavior |
| --- | --- |
| `GET /?q=term&kind=people&offset=0&limit=50` | Search profiles and names. Returns `entities`, matching `total`, and full type `counts`. Omit `limit` or use zero to retrieve all matches. Source/date parameters remain available. |
| `POST /merge-preview` | Validate members and compute combined fields and unique-entry count. Returns a signed preview token valid for 15 minutes. |
| `POST /merges` | Atomically create the named identity, aliases, audit event and operation receipt. |
| `POST /merges/{entity_id}/unmerge` | Atomically restore immediate members of an active outer grouping. |
| `GET /operations/{request_id}` | Retrieve a committed receipt and audit-delivery state. 404 means no committed receipt is currently visible, including while work may still be in flight. |
| `GET /audit/{entity_id}` | Merge, unmerge and merged-profile edit history, with preserved profile snapshots. Works for retired group IDs too. |
| `POST /decisions/{decision_id}/undo` | Reverse a legacy one-to-one decision. Group decisions must use the group unmerge endpoint. |

Preview payload:

```json
{
  "entity_ids": ["entity-id-a", "entity-id-b"],
  "name": "Combined identity",
  "evidence": "Optional explanation"
}
```

Submit the same payload to `/merges` with the returned `preview_token` and a UUID
`request_id`. Optionally include a `profile` object containing edited `categories`,
`emails`, `phones`, `references` (arrays), and/or `notes` (string). Omitted fields retain
their proposed values; empty arrays/strings explicitly clear fields. Edits are validated
and saved atomically with the merge and audit. The token still verifies the original
source preview, so profile edits cannot bypass stale-source checks. The receipt includes
`entity_id`, `event_id`, `state: "complete"`, and
`action: "merged"`. Unmerge accepts `{"request_id":"<UUID>","evidence":"optional"}`
and also returns `restored_ids`.

Mutations run in a database transaction off the web event loop. Keep the exact request
body and request ID across transport retries. Reusing a request ID with different
content returns 409; replaying the original returns its receipt. A stale/expired
preview returns 409 with no partial merge. Re-preview after relevant entity changes.
The preview checks the entity-store revision and recomputes visible supporting data.
Mixed types, hidden/removed selections and nested reversals out of order are rejected.
Selections may contain up to 10,000 IDs per operation; duplicates do not add members.

## Audit delivery

Every successful merge/unmerge records the actor, UTC time, source IDs/names, resulting
identity, optional evidence and relevant profile snapshots locally. A pending audit
delivery is committed in the same transaction. The background response handler submits
an HFL entry with source **`entities-audit`**, using a deterministic event identity.
Existing five-minute HFL outbox recovery retries pending deliveries. Entries summarize
the operation; complete profile snapshots stay in the entity audit store. Profile edits
are preserved locally without creating a corpus entry for every edit.

Operation receipts distinguish a completed entity mutation from audit delivery:
`pending` means the entity audit outbox still owns it, `outbox` means the HFL outbox
owns retry, `forwarded` means it was queued for the canonical host, and `persisted`
means local corpus persistence returned successfully. Delivery failures never require
repeating the merge with a new request ID.
