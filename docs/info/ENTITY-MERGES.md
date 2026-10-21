# Entity merges

## Entity types

**Manage types and add entities** creates types with a name, color and extraction
description, or creates a named entity manually. Defaults include People, Organizations,
Tools, Topics, Referenced objects and Pets. Open an entity to change its type or edit its
profile. Custom types and Pets keep same-name mentions separate until identity matching
or a reviewed merge establishes that they are the same entity.

New types participate in future enrichment. Creating a type does not reprocess history.
**Backfill history with current types** explicitly queues the existing bounded Celery
extraction workflow with the current vocabulary. Existing evidence remains visible while
backfill runs, and saved profiles are preserved. Repeating a completed backfill with the
same vocabulary does not reprocess unchanged entries.

Authenticated endpoints include `POST /api/hfl/entities/types` (`name`, `color`,
`description`), `POST /api/hfl/entities/create` (`name`, `kind`, optional profile fields),
`POST /api/hfl/entities/type/{id}` (`kind`), and
`POST /api/hfl/entities/backfill?include_new_types=true`. The directory response includes
its `types` registry. Types are stored with the local entity database shared by the API
and workers; no new schedule or credential is required.

## Daily Hermes consolidation

The `auto-merge-entities` skill provides daily autonomous cleanup at 03:00
Asia/Singapore. Reconcile `scripts/agents/hfl/entity_consolidation_schedule.json`
using `setup_entity_consolidation.py --apply` on the canonical Hermes host.
Hermes owns the schedule and contextual decisions; the API owns validated,
transactional merges and Celery owns grouped report delivery. No extra Beat job.

Profiles expose `aliases` (exact strings), `partial_aliases` (substring hints of
at least three characters), and `preferred_name`. The directory editor and profile
API support these fields. `alias_sources` is server-maintained provenance (`user`,
`llm`, `merged-name`). Merged names are retained. Generated hints cannot supply
independent corroboration. Names with more unique current related activities rank
higher, after explicit preferred names and curated profiles.

Same-type token/trigram discovery includes fuzzy OCR variants. Partial hints only
shortlist candidates. The agent checks activity context: two independently supported
facts normally, or one substantial specific shared fact for a strong name/identifier
match with sparse activity. Similar spelling, popularity and model confidence alone
never establish identity. Conflicting curated identities, explicit identifiers,
keep-separate decisions and unmerges constrain automatic approval.

The first `POST /api/hfl/entities/consolidation/begin` durably transfers automatic
matching ownership to Hermes and includes historical entities and suggestions.
Previously queued Celery matching tasks stop applying decisions. Later daily runs
compare entity snapshots; unchanged deferred cases are not repeatedly evaluated.
Interrupted runs resume before new runs. Exact name/alias/contact buckets produce
highest-activity anchor stars, independently of the fuzzy shortlist (five neighbors
initially; up to 20 during claimed discovery). Buckets never authorize merging by
name alone. Fuzzy search uses a 50-candidate pool. Large homogeneous name buckets
reuse their exact stars instead of repeatedly scanning identical fuzzy postings.
This is not exhaustive all-pairs matching, particularly among ambiguous
leaves of a same-name bucket. Newly merged groups participate in fresh discovery.

Priority is People → Organizations → Tools → Pets → Apps → Games → remaining types;
every fifth fresh claim selects the oldest comparison to prevent starvation.
Search features persist by versioned name/profile inputs; counts and postings are
shared within a snapshot. Run metadata, comparison rows and content-addressed evidence
are stored separately. Unchanged rows are not rewritten. Legacy JSON runs migrate
transactionally on their next write; deploy API and report workers together because
older code cannot read the new storage format. No entity identities are changed by
this migration. Full snapshot reads and run serialization still have linear costs.

Run `.venv/Scripts/python.exe scripts/agents/testing/check_entity_scale.py --size 8400`
for a synthetic scale check, or add `--live` for a paged, read-only API snapshot.
Only temporary storage is written. The output reports aggregate candidate coverage,
timings and payload sizes, not confirmed duplicates or model execution time.

Validation on 2026-10-17 used a read-only snapshot of 8,382 entities (6,479 with one
supporting activity). It contained 334 repeated-name buckets, the largest with 24
members. Comparing discovery with local revision `e90a1f3f` preserved all 2,893
candidates: 14.776 seconds versus 27.102 seconds in the final same-process check.
Serialized benchmark run payloads decreased from 18,533,314 to 6,852,901 bytes;
one changed comparison wrote two rows (comparison plus metadata). These are local
discovery/storage measurements, not production merge latency or model cost estimates.
Reproduce with `check_entity_scale.py --live --baseline-ref e90a1f3f` using the full
script path above. Only use trusted local revisions for the optional baseline code.
Regression coverage also includes 8,400 identical-name entities producing 8,399
review edges, transactional rollback, interrupted-run migration, concurrent snapshot
reads, claim recovery, and fair scheduling. Identity evidence requirements remain intact.

Agent endpoints under `/api/hfl/entities/consolidation`:

| Method/path | Behavior |
| --- | --- |
| `POST /begin` | Start today's run or resume unfinished work. |
| `GET /{run_id}` | Counts, delivery state and the next 20 pending pairs. |
| `POST /{run_id}/decisions/{pair_id}` | Record an evidence-grounded merge, review or separate decision. |
| `POST /{run_id}/decisions` | Up to 20 decisions keyed by pair ID; independent results. |
| `POST /{run_id}/finish` | Checkpoint resolved work and enqueue grouped report delivery. Safe to repeat. |
| `POST /{run_id}/executions` | Start/recover a bounded selection using `execution_id`, `max_pairs` (1–200, default 40), and `seconds` (30–3600, default 900). |
| `POST /{run_id}/executions/{execution_id}/close` | Persist a receipt-reconciled execution report and dispatch its canonical delivery, even with global work pending. |

The helper `.agents/skills/auto-merge-entities/scripts/consolidate.py` handles
machine configuration and authentication without exposing credentials. Exact decision
replays recover receipts; changed replays conflict. Snapshots are revalidated before
commit. Review outcomes defer future reconsideration until evidence changes.
Consolidation `separate`, explicit Keep separate and unmerge create shared durable
exclusions respected by incoming resolution and future automatic consolidation.
An owner can reverse only a consolidation separation through
`POST /api/hfl/entities/separations/reverse` with `left_id`, `right_id`, and an
evidence-backed `reason`. This leaves unmerge/dismissal vetoes intact and records
an audit event before reopening work.

Servers advertising `bounded-executions-v1` keep the backlog open across executions.
Checkpoint before starting a new execution; claims and commits are restricted to
its fixed selection and deadline. Newly discovered candidates wait for a subsequent
execution. Close with `reason` equal to `budget`, `exhausted`, `provider-failure`, or
`integrity-concern`, plus optional sanitized `errors`. Reuse the execution ID and
identical close payload after a lost response. The returned `report_id` is a normal
consolidation status resource, including canonical HFL/Telegram delivery state.
Safe deferrals are successful work accounting, not merged duplicates. Reports
include actual operation and audit event IDs, verification, stop reason, remaining
eligible work, discoveries, and integrity exceptions. Merge receipts are recovered
from the audit if committing succeeded before the run was saved. A later global
finish does not notify operations already owned by an execution report.

### Resolver health and identity review

`GET /api/hfl/entities/resolution` exposes last success/error, dispatch error,
oldest pending age, pending/failed work, received/completed job counters and persisted
mention outcomes. Counters start at migration and received includes requeued jobs;
legacy pending ages begin at first observation because original arrival times were
not stored. Outcomes describe the latest assessment, not proof of resolved identity.
Unchanged unresolved work stays out of the queue; relevant target/source changes
reopen it. The worker processes up to eight entries independently, backs failures
off for 30 seconds up to one hour, and parks each after five attempts.
`POST /api/hfl/entities/resolution/{entry_id}/retry` explicitly requeues failed work.
Existing queued jobs preserve retry state when merges or profile edits enqueue work.

Matcher responses must finish normally and contain exactly one valid decision for
each requested pair. Truncated, malformed, or incomplete responses are rejected
before applying their decisions. Failure diagnostics include the stop reason,
token counts and JSON location when available, never model output or source text.
The resolution status includes these diagnostics per failed entry and a
`last_result` summary. A batch with any entry errors marks its Celery task failed;
successful entries remain committed and only failed entries retain retry work.

Producers and workers share one durable wakeup reservation under the resolver
lock. Contending and superseded deliveries exit without creating retry chains.
New ready work can replace a delayed wakeup; its old token becomes inert. The
dispatcher can replace a lost reservation ten minutes after its scheduled time.
Unexpected batch-level exceptions impose a one-minute dispatch cooldown. Deploy
the updated producers and workers together so every consumer honors these tokens.
Review failed-entry diagnostics before using the explicit retry endpoint; deployment
does not automatically reopen entries parked after five failed attempts.

Enrichment deliveries backed by a pending revision also exit on worker-lock
contention without scheduling duplicates or overwriting the owner's job status.
Their pending rows remain recoverable by the existing outbox dispatcher after the
ten-minute visibility timeout. Legacy direct calls without a revision retain their
handoff behavior because they have no durable pending row to recover.

`POST /api/hfl/entities/integrity/{identity}` accepts `required`, an evidence-backed
`reason`, and optional originating `operation_ids`. This is an audited owner action.
Flagged identities are excluded from automatic merge/assignment targets, with
transactional revision checks preventing an in-flight evaluation from committing
after a flag changes. Existing assignments remain recorded but are withheld from
projection while flagged; clearing the flag does not undo merges. Investigate the
outer identity and use separately authorized targeted reversals for confirmed errors.
Automatic alias and stable-ID projections are likewise isolated per entry while
their target is flagged, preventing new source mentions from bypassing the resolver.
Explicitly user-linked activity remains visible. Original merge and assignment
records remain intact.

`POST /api/hfl/entities/possible-existing` provides bounded same-type suggestions
for manual creation. `/create` returns `state: possible-existing` when suggestions
exist unless `confirm_distinct: true` is supplied. The directory and Soul connection
editor offer existing-identity reuse and an explicit distinct-identity choice.
Directory `identity_status` explains queued work, ambiguity, integrity review,
failed work and intentional separation. No health notification channel is added.

Each completed run produces one HFL report grouped by type. A concise Telegram
summary linking to it is sent only when at least one actual outcome is `merged`.
Empty and deferred-only runs persist HFL without a Telegram notification. Internal per-operation audit and
undo remain intact. **Automatic merges do not publish individual HFL audit entries**;
manual operations retain individual delivery. This applies prospectively, without
removing existing audit posts. Delivery state distinguishes HFL persistence, Telegram
completion and uncertain sends. With HFL persisted, `delivery.telegram_state` of
`sent` or `suppressed` is successful terminal delivery; suppression means no actual
merges and must not trigger retries or recovery dispatch. Queued delivery is not
completion. `sending` is uncertain and requires reconciliation before retrying.
Retry failed reporting without repeating merges.

## Legacy enrichment matching

Before Hermes takes ownership, successful model enrichment durably records a matching job alongside the extracted
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
Pending counts are **candidate pairs**, not unique entities or corpus entries. An entity
can occur in several pairs, so this count can exceed the entity count. New jobs reuse
outstanding pairs instead of queueing the same unresolved pair again.

The directory filters also apply to suggestions: either member must satisfy all active
filters. Filtering covers the full review queue; **Show more suggestions** reveals another
100 matching rows. Each row shows its colored entity-type pill. Polling retains expanded
suggestions, job history, selections and directory profile drafts.

Use the right-side checkboxes to stage reviewed suggestions, **Select visible** to select
the displayed rows, and **Review selected merges** to open confirmation. Hidden selections
are counted and included. Overlapping pairs become a single connected group in the modal;
review the resulting names and editable combined profiles before **Confirm merges**.
Independent groups can succeed or fail separately. Failed groups remain selected for retry;
transport retries retain their request IDs and payloads to avoid duplicate merges.
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
| `GET /api/hfl/entities/matching` | Job counts/states and up to 100 uncertain suggestions; `?all=true` includes the full review queue and current member entities. |
| `POST /api/hfl/entities/matching/scan` | Start or resume the one-time historical scan. |
| `POST /api/hfl/entities/matching/suggestions/{id}/dismiss` | Keep the identities separate and block future automatic matching. |

Suggestions can be accepted using the existing merge preview and submit endpoints with
their `data.entity_ids`. Suggestions resolve merged aliases to current IDs. Unavailable or
retyped selections receive an actionable error instead of silently failing.

The Activity Corpus Entities directory supports selecting entities across pages,
searches and filters. Select a single built-in or custom type, choose **Merge selected**, enter a name and optional evidence,
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
| `POST /merges/batch` | Submit up to 100 disjoint groups, each with the normal merge payload, signed preview and request ID. Returns a result or error per group. |
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
The preview verifies the selected entities and their supporting data; unrelated store
changes do not invalidate a review. The final commit still checks its transactional revision.
Mixed types, hidden/removed selections and nested reversals out of order are rejected.
Selections may contain up to 10,000 IDs per operation; duplicates do not add members.

## Audit delivery

Every successful merge/unmerge records the actor, UTC time, source IDs/names, resulting
identity, optional evidence and relevant profile snapshots locally. For manual operations, pending audit
delivery is committed in the same transaction. Automatic merges retain internal
audit with delivery `not-required`; their daily run provides grouped reporting. The background response handler submits
an HFL entry with source **`entities-audit`**, using a deterministic event identity.
Existing five-minute HFL outbox recovery retries pending deliveries. Entries summarize
the operation; complete profile snapshots stay in the entity audit store. Profile edits
are preserved locally without creating a corpus entry for every edit.

Operation receipts distinguish a completed entity mutation from audit delivery:
`pending` means the entity audit outbox still owns it, `outbox` means the HFL outbox
owns retry, `forwarded` means it was queued for the canonical host, and `persisted`
means local corpus persistence returned successfully. Delivery failures never require
repeating the merge with a new request ID.
