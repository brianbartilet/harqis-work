---
name: check-activity-corpus-sources
description: Audit every Homework-for-Life activity-corpus source against its expected schedule and pipeline evidence, diagnose stale or missing ingestion, safely retry or backfill bounded gaps, repair code when authorized, and report failures and actions. Use for daily/weekly HFL source-health checks or investigations of missing corpus activity.
allowed-tools: Bash Read Glob Grep Edit Write
---

# Check Activity Corpus Sources

Audit HFL source reliability across the complete pipeline, not just the final
Elasticsearch index:

`upstream activity -> collector/hook -> spool/checkpoint -> Celery execution -> Markdown corpus -> Elasticsearch -> dependent rollup`

The Markdown corpus is canonical. Elasticsearch is a rebuildable projection.
Never infer that Elasticsearch failed merely because it received no documents.

## Runtime and schedules

This is a hybrid automation:

- Hermes owns the daily adaptive invocation, normally after nightly ingestion.
- Celery Beat separately owns the Monday 07:30 deterministic weekly snapshot:
  `workflows.hfl.tasks.check_activity_corpus_sources.check_activity_corpus_sources`.
- Celery owns durable retries, backfills, persistence, and task IDs. The agent
  owns diagnosis, recovery selection, code changes, and the final explanation.
- Do not create a second daily Beat schedule or a second weekly Hermes schedule.

## Start with the deterministic scan

Before investigating or mutating anything, run the checked-in scanner with the
repository virtual environment:

```powershell
$python = if (Test-Path .venv/Scripts/python.exe) { '.venv/Scripts/python.exe' } else { 'python' }
& $python .agents/skills/check-activity-corpus-sources/scripts/check_activity_corpus_sources.py scan --mode daily
```

Use `--mode weekly` for the deeper weekly audit. Exit code `2` means findings
exist; it is not a scanner crash. Use `--json` when structured evidence helps
the investigation. The CLI bootstraps `.env/apps.env` and machine context before
importing `apps.*` or `workflows.*`; do not bypass that bootstrap.

Read [references/sources.toml](references/sources.toml) for source schedules,
freshness grace, task paths, output source names, empty-success policy, and
recovery capability. Every active `WORKFLOW_HFL` task must have an entry. Manual,
hook-driven, Hermes-owned, and unscheduled producers remain inventoried even
when they have no freshness SLA.

## Diagnose each finding

For every failed or degraded source:

1. Establish the last evidence at every applicable pipeline stage. Include the
   expected schedule, last task heartbeat, last Markdown entry, last ES document,
   upstream activity, collector/spool evidence, and dependent rollup.
2. Inspect Celery Beat uptime, task expiry, queue routing, worker coverage, and
   the relevant `@log_result` record when the task heartbeat is missing or stale.
3. Treat a fresh successful task plus stale entries as a likely empty-input or
   upstream-capture problem. Confirm whether upstream activity actually existed.
4. Treat genuine inactivity as healthy only when a successful task heartbeat,
   collector marker, checkpoint, or other source-specific empty-success evidence
   exists.
5. Compare Markdown and ES independently. For parity findings, run
   `scripts/agents/hfl/reconcile_elasticsearch.py` read-only before considering
   `--apply`. Never delete ES or corpus records.
6. Follow dependent sources. A rollup cannot be repaired until its prerequisite
   source entries are present.

For `agent-session`, explicitly compare:

- recent CLI/Telegram activity in `HERMES_STATE_DB` or `~/.hermes/state.db`;
- event JSON under `HFL_SESSION_AUDIT_PATH/events`;
- `ingest_agent_session_events` heartbeats and pending-event results;
- latest `agent-session` Markdown/ES entries;
- `rollup_agent_sessions` executions and `agent-session-rollup` entries.

This must surface the important case where Hermes is active, the scheduled
ingester repeatedly succeeds with `no pending events`, and Elasticsearch is
healthy but receives nothing because no lifecycle collector feeds the spool.

## Remediate safely

Read [references/remediation-policy.md](references/remediation-policy.md) before
performing any retry, backfill, code change, Git push, or PR action.

- Prefer an existing idempotent task or checked-in recovery command. Do not
  reproduce app integration or persistence logic in ad-hoc code.
- Validate the source identity, exact missing window, task signature, stable
  deduplication key, queue, host affinity, and expected cost before dispatch.
- The maximum automatic backfill window is 15 days. Split work by source/day
  when needed, retain the correlation ID and every child task ID, and stop on an
  unexpected partial result.
- Retry retained spool/outbox data before reconstructing it from upstream.
- Repair ES from canonical Markdown only after a read-only reconciliation plan.
- Never rewrite/delete corpus documents, delete ES records, broaden a backfill,
  bypass a checkpoint, or remove skipped/manual test protections.
- After source entries recover, rerun only the affected dependent rollups.

## Code repair and publication

Code repair is allowed only when evidence identifies a repository defect.

1. Work on a feature branch, preserve unrelated changes, and make the smallest
   source-specific change.
2. Add a regression test reproducing the detected failure and run the targeted
   HFL tests through `$run-tests`.
3. Classify the change with the remediation policy.
4. A direct push to `main` requires an explicit approval reference supplied by
   the current invocation and must satisfy every low-risk gate. Skill installation
   or a recurring schedule is not standing authorization.
5. Without that current approval—or for any breaking/high-risk change—push a
   feature branch and publish a pull request instead. Record the branch, commit,
   tests, PR URL, and approval evidence in the report.

## Report and notify

Write a report only when a failure/degradation was found or a recovery/backfill
was performed. Store it under repository-root `results/hfl/`. Update the initial
deterministic report after remediation so each failed source includes:

- expected schedule and pipeline stage where progress stopped;
- last task, Markdown, ES, upstream, and rollup evidence;
- root cause and evidence, without secrets or private content;
- actions performed, correlation/child task IDs, tests, commit, push, or PR;
- recovered date range, remaining risk, and recommendations.

Also record the scanner correlation ID and the SHA-256 of the loaded `SKILL.md`
so the review artifact identifies both the data-plane run and agent policy.

Write one canonical HFL audit entry for the run. Notify Telegram when unresolved
failures remain or any backfill was performed. Do not create a report, HFL entry,
or notification for a wholly healthy scan.

End with a concise user summary: failed sources only, what was fixed/backfilled,
what remains unresolved, publication state, and the report path.
