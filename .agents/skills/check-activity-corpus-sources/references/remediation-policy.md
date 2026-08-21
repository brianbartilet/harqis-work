# Activity corpus remediation policy

Use this policy only after the deterministic scan identifies a failed or
degraded source. The registry's `auto_retry = true` means the existing task is
eligible for consideration; it does not remove the validation and authorization
requirements below.

## Recovery gates

Before dispatching a retry or backfill, record:

- source and failed pipeline stage;
- inclusive missing dates, capped at 15 days;
- canonical task/command and validated arguments;
- source-specific deduplication or checkpoint behavior;
- target queue and required host;
- correlation ID and resulting Celery child task IDs;
- expected external calls/model usage;
- rollback or safe-stop behavior.

Abort automatic recovery when the source window cannot be bounded, a task is
not idempotent, credentials or upstream evidence are unavailable, the canonical
host/queue is unknown, or the prior attempt produced an unexpected partial
result.

## Change risk

A change is low-risk only when all of these are true:

- it does not modify schemas, canonical persistence, deduplication identities,
  checkpoints, schedules, queues, routing, credentials, privacy filtering,
  deletion behavior, or migrations;
- it is confined to the failing source or its tests/documented registry entry;
- targeted regression tests and relevant HFL tests pass;
- the working tree contains no unrelated staged changes;
- the branch is current with its target and the resulting commit is reviewable;
- the current invocation supplies a durable approval reference authorizing a
  low-risk direct push.

Anything else is breaking/high-risk and must use a feature branch plus pull
request. A failed push does not authorize force-push, history rewriting, or
weaker tests.

## Recovery preference

Use the least invasive option that restores the missing stage:

1. retry retained spool or outbox delivery;
2. rerun an idempotent source task for the exact missing window;
3. reconcile missing/stale ES documents from canonical Markdown;
4. regenerate affected derived rollups;
5. patch and test a verified repository defect;
6. publish through the authorized Git path.

Never delete or rewrite corpus entries as an automated repair.

## Required report evidence

For each failing source, retain the schedule, last stage timestamps, suspected
and confirmed cause, commands/tasks used, task IDs, recovered window, counts,
tests, commit/PR, approval reference, remaining risk, and next recommendation.
Redact tokens, credentials, prompts, message bodies, and private activity
content. Counts, timestamps, source names, task names, and entry IDs are enough.
