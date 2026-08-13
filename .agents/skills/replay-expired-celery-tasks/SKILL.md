---
name: replay-expired-celery-tasks
description: >
  Reconstruct, review, and safely replay HARQIS Celery Beat executions that likely
  expired before a worker consumed them. Use only when the user asks for a
  retrospective or backfill execution of expired/missed Celery tasks.
user-invocable: true
allowed-tools: Bash Read Glob Grep
---

# Replay Expired Celery Tasks

## Overview

Use this skill to reconstruct and execute missed HARQIS Celery task occurrences after their broker messages expired or disappeared while no eligible worker was available.

The Express output is a verified replay report: which intended occurrences were reconstructed, which were skipped, which were dispatched, their new task IDs, and their terminal outcomes or explicit unresolved state.

This is **reconstruction**, not RabbitMQ recovery. RabbitMQ normally removes expired messages and does not preserve their original body for later retrieval unless dead-lettering or publish-event capture was already configured. Never claim to have recovered an original message unless an actual retained payload or dead-letter record proves it.

## When to Use

Use when the user asks to:

- replay expired Celery messages;
- retrospectively execute tasks missed while a worker or machine was offline;
- backfill scheduled Celery runs from a specific outage window;
- rerun a named task occurrence known to have expired before consumption.

Do not use for:

- currently queued messages that have not expired;
- failed tasks that were received and executed — diagnose the failure first;
- changing Beat schedules or queue topology — use `manage-queues`;
- automatically replaying every suspected miss without a bounded time window and review;
- periodic catch-up automation. This skill is deliberately user-invoked and fail-closed.

## Source of Truth

Inspect current state every time:

| Evidence | Source |
|---|---|
| Beat entries, scheduled kwargs, queue, expiry | `workflows/*/tasks_config.py` and `workflows/config.py::CONFIG_DICTIONARY` |
| Direct/fanout queue semantics | `workflows/queues.py`, `workflows/config.py::task_queues` |
| Expected machine coverage | `machines.toml` plus `machines.local.toml` |
| Live queue consumers and backlog | `docker exec rabbitmq rabbitmqctl list_queues ...` |
| Actual task receipts/outcomes | Flower API/events, `logs/worker.log`, result backend where available |
| Beat dispatch evidence | `logs/scheduler.log` |
| Manual replay overrides | Beat entry `manual_kwargs`, task source/docstring, workflow README |
| Express verification | Task-specific artifact, feed/ES log, file, email/API record, and Celery outcome |

The current runtime checkout is `/Users/harqis-one/GIT/harqis-work`. Execute from it so broker/app configuration matches the deployed HARQIS runtime.

## Required Input

Resolve these before dispatching:

1. **Time window** — explicit start/end in Asia/Singapore unless the user supplied another timezone.
2. **Scope** — named task(s), workflow(s), queue(s), or the bounded set affected by a documented outage.
3. **Replay policy** — scheduled arguments from each historical occurrence or a justified retrospective override.

If the request supplies an obvious bounded scope such as “replay yesterday’s expired HUD tasks,” inspect and produce a dry-run manifest without asking first. Ask only when the time window or target set cannot be recovered from context/evidence.

## PAER Workflow

### 1. Plan — bound the replay

State one sentence naming the replay window, target scope, and Express report. Work in Asia/Singapore by default.

Reject or narrow unbounded requests such as “replay everything ever missed.” Large backfills can duplicate purchases, emails, posts, API mutations, file moves, AI spend, or periodic summaries whose meaning changes with time.

Completion criterion: start/end, timezone, and target selector are explicit.

### 2. Analyze — reconstruct candidate occurrences

Read in parallel:

- `workflows/config.py`;
- `workflows/queues.py`;
- `machines.toml` and `machines.local.toml` when present;
- affected `workflows/<area>/tasks_config.py`;
- affected task function bodies and workflow README;
- scheduler/worker logs covering the requested window.

For each affected Beat entry:

1. Expand its `crontab(...)` or `timedelta(...)` into expected occurrence timestamps inside the bounded window.
2. Record task path, scheduled args, scheduled kwargs, `manual_kwargs`, queue, OS hint, expiry seconds, and expected expiry timestamp.
3. Search scheduler evidence for publication near that occurrence.
4. Search worker/Flower/result evidence for receipt or terminal execution.
5. Classify the occurrence:

| Status | Meaning | Replay default |
|---|---|---|
| `CONFIRMED_EXPIRED` | Retained dead-letter/publish evidence proves publication and expiry without receipt | Candidate |
| `LIKELY_EXPIRED` | Beat publication is evidenced, no receipt/outcome exists, queue had no consumer, and expiry elapsed | Candidate, clearly labelled inferred |
| `MISSED_NOT_PUBLISHED` | Expected occurrence exists but Beat publication is not evidenced | Candidate only if user asked for missed-run backfill |
| `ALREADY_EXECUTED` | Worker/Flower/artifact proves execution | Skip |
| `STILL_QUEUED` | RabbitMQ shows the original work may remain pending | Do not replay; restore a consumer |
| `AMBIGUOUS` | Evidence is incomplete or contradictory | Block pending review |

Absence from Flower alone is not proof of expiry; Flower history can be incomplete. Correlate at least schedule + scheduler/worker evidence, and inspect task-specific Express artifacts when duplicate side effects matter.

Completion criterion: every expected occurrence in scope has exactly one classification and cited evidence.

### 3. Analyze — side-effect and temporal-safety gate

Open the task function body and immediate callees. Classify each candidate:

- **Safe/idempotent refresh** — replaces current HUD/cache/feed state, guarded upsert, deterministic sync.
- **Window-sensitive** — “today,” “yesterday,” “last month,” current inventory, or implicit `now()` means replaying scheduled kwargs today may produce the wrong historical output.
- **Duplicate-sensitive** — email, Telegram/social post, purchase/order mutation, task creation, append-only ingest, AI billing, file move/delete, git push, backup/restore, external API write.
- **Dependency-sensitive** — must run after another missed occurrence or requires an artifact from the historical time.
- **Broadcast** — fanout queue would execute once per subscribed worker and must not be replayed casually.

Rules:

1. Prefer explicit historical parameters when the task supports them.
2. `manual_kwargs` are not automatically historical truth. They are dashboard overrides and may intentionally use a recent window. Compare them with scheduled kwargs and task semantics.
3. Never invent unsupported date/ID parameters.
4. Never invoke the Python task function directly as a substitute for Celery unless the user explicitly asks for local debugging. Replay through Celery so routing, signals, observability, and worker environment remain intact.
5. Treat external writes, duplicate-sensitive tasks, broadcast tasks, deletes, financial/order operations, public posts, emails, and paid AI generation as **approval-required** even though the user asked for a retrospective generally.
6. A clearly named single safe/idempotent task replay requested by the user may proceed after the manifest is shown; the request itself is sufficient dispatch authorization. Multi-task, duplicate-sensitive, broadcast, destructive, financial, public, or paid sets require approval of the exact manifest.

Completion criterion: every candidate has risk class, replay args/kwargs, ordering, and approval status.

### 4. Plan artifact — print the dry-run manifest

Before dispatch, print a compact manifest:

```text
Replay window: <start> → <end> <timezone>
Evidence level: retained | inferred

[1] <historical occurrence>
    task: <dotted path>
    classification: CONFIRMED_EXPIRED | LIKELY_EXPIRED | MISSED_NOT_PUBLISHED
    queue: <queue> — live consumers: <N>
    original expiry: <timestamp>
    args: <redacted compact JSON>
    kwargs: <redacted compact JSON>
    risk: safe | window-sensitive | duplicate-sensitive | dependency-sensitive | broadcast
    evidence: <paths/API records/timestamps>
    action: replay | skip | blocked
```

Redact secrets, tokens, private payload bodies, and personal identifiers. For a large candidate set, save the full manifest under `.harqis-data/replay-manifests/` and show counts plus blocked/high-risk rows.

Do not dispatch if:

- the target queue has zero live consumers;
- the worker OS does not match the task requirement;
- the occurrence is `STILL_QUEUED`, `ALREADY_EXECUTED`, or `AMBIGUOUS`;
- required historical parameters cannot be represented safely;
- required approval has not been given.

Completion criterion: the exact dispatch set and all blocked/skipped rows are visible and reviewable.

### 5. Execute — dispatch one controlled occurrence at a time

Use HARQIS's configured Celery app from the runtime checkout. Generate a **new** task ID; never reuse the historical ID.

Preferred dispatch shape:

```bash
python - <<'PY'
from core.apps.sprout.app.celery import SPROUT

result = SPROUT.send_task(
    "<task.path>",
    args=<args>,
    kwargs=<kwargs>,
    queue="<direct-queue>",
)
print(result.id)
PY
```

Do not copy the old `expires` value onto a retrospective replay by default: its historical deadline has already passed. If a replay expiry is useful, choose a fresh bounded value based on current worker availability and state it in the manifest.

Dispatch discipline:

1. Recheck live consumers immediately before each send.
2. Follow dependency order.
3. For duplicate-sensitive work, dispatch one occurrence and verify it before the next.
4. Record historical occurrence → new task ID → dispatch timestamp.
5. Stop the batch on unexpected failure, wrong routing, duplicate signal, or missing prerequisite.
6. Never route a direct task to a broadcast queue as a workaround for missing workers.

Completion criterion: every approved candidate is either dispatched with a new task ID or reported blocked with the precise reason.

### 6. Review — verify real execution and Express output

For each new task ID:

1. Confirm worker receipt in Flower/events or `logs/worker.log`.
2. Wait for `SUCCESS`, `FAILURE`, or `REVOKED` within a task-appropriate bound. `PENDING` is not success.
3. Inspect the task-specific Express artifact named by its `manifesto.express_target`, workflow README, decorator/feed, or function behavior.
4. Check for duplicate external effects when relevant.
5. Report terminal state, elapsed time, worker/queue when observable, and artifact evidence.

Final report:

```text
Reconstructed: N
Dispatched: N
Succeeded + Express verified: N
Failed: N
Skipped already executed/still queued: N
Blocked ambiguous/high-risk: N

<historical occurrence> → <new task id> → <state> → <artifact evidence>
```

Do not report “replayed successfully” based only on `send_task()` returning an ID.

## Hard Rules

- User invocation is required; never auto-replay from the RabbitMQ watchdog or a scheduled job.
- Never claim an expired RabbitMQ payload was recovered without retained payload evidence.
- Never consume queue messages with `basic.get`, management `get`, or destructive inspection to discover candidates.
- Never replay an unbounded time range.
- Never replay already executed or still-queued work.
- Never silently substitute current-time semantics for a historical occurrence.
- Never dispatch to a queue with zero consumers or an OS mismatch.
- Never bulk replay duplicate-sensitive, broadcast, financial, destructive, public, email, or paid-AI tasks without exact-manifest approval.
- Never treat task ID creation, scheduler status, or Flower `PENDING` as completion.
- Never expose secrets or raw private task payloads in the manifest or report.

## Common Pitfalls

1. **Equating “missing from Flower” with expired.** Flower retention is not an immutable audit log. Correlate scheduler, worker, broker, and artifact evidence.
2. **Replaying the current function defaults.** A task using `now()` can produce today’s result rather than the missed day’s result. Require supported historical parameters or block it.
3. **Using `manual_kwargs` blindly.** Dashboard semantics may intentionally differ from Beat semantics.
4. **Replaying into a dead queue.** Check live RabbitMQ consumers, not only `machines.toml` intent.
5. **Creating duplicates after delayed recovery.** Verify the original is not still queued and inspect the Express artifact before dispatch.
6. **Fanout multiplication.** A broadcast replay runs once per bound worker queue; quantify recipients and require approval.
7. **Ignoring downstream ordering.** Reports, pulls, summaries, or notifications may depend on an earlier generation/sync occurrence.
8. **Calling task functions locally.** This bypasses Celery routing/signals and may run under the wrong machine environment.
9. **Reusing historical expiry.** A past absolute deadline or stale relative TTL can make the replay expire immediately or before pickup.
10. **Stopping at dispatch.** Verification requires terminal state plus the real Express artifact.

## Verification Checklist

- [ ] Replay window, timezone, and scope are bounded.
- [ ] Current task config, source, routing, topology, and logs were inspected.
- [ ] Every expected occurrence has one evidence-backed classification.
- [ ] Already-executed and still-queued occurrences are excluded.
- [ ] Args/kwargs represent the intended historical occurrence without invented parameters.
- [ ] Side effects, temporal semantics, dependencies, and broadcast behavior were reviewed.
- [ ] Exact-manifest approval was obtained where required.
- [ ] Live eligible consumers were confirmed immediately before dispatch.
- [ ] Each replay received a new task ID.
- [ ] Worker receipt and terminal state were observed.
- [ ] Task-specific Express output was verified.
- [ ] Final report maps each historical occurrence to its new execution and evidence.
