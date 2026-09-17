# Capture backlog recovery and September 15–16 follow-up

## Scope and release boundary

This change prepares a pull request, not a deployment. It changes desktop
analysis from 40 files / one day to 200 pending files / seven days, adds a daily
06:30 pending-capture monitor, and fixes retained agent-session budget starvation.
The dated recovery below is an operator plan, **not a registered or executed job**.
Do not add a recurring historical backfill to Beat or silently run it on merge.

## Checkpoint review

- `collect_agent_session_events(..., pending_only=True)` filters acknowledged
  artifacts before its budget. Previously the first 500 files could all be
  completed, permanently hiding pending files later in the same scan window.
- `process_agent_session_event` writes a retryable artifact without inherited
  `ingest` acknowledgement before submitting to canonical persistence, then
  records the returned checkpoint. Failed persistence can be retried using the
  same event identity; the caller's original payload is not mutated.
- Canonical persistence, stable event IDs, and its existing outbox remain the
  authority for delivery. A forwarded task ID is not proof of canonical storage.
- Retry scans remain window-bounded (two days by default). They cannot recover
  missing capture hooks, absent audit files, or older artifacts automatically.
  Worker-local spools require the existing broadcast retry routing; inspect
  capture production and outbox delivery separately from retry task success.
- A crash after successful canonical submission but before checkpointing can
  replay the same ID. Do not generate a new event ID to bypass an uncertain write.
  Concurrent event writers and remote forwarding acknowledgement are not
  redesigned by this patch.

## Monitor behavior and limitations

The monitor uses the analyzer's provenance, extension, reference and claim
filters. Desktop and Android pending counts are separate; warning >=25 and
critical >=100 are inclusive. Its 14-day window is not an all-history inventory.
Active claims and completed semantic skips are not pending. A missing inbox or
corpus raises. Failed Telegram sends raise; valid message IDs mean API acceptance,
not read/delivery confirmation. Elevated counts can alert again the next day.
There is no notification deduplication ledger in this monitor; an uncertain
notification must be reconciled before manually retrying the task.

A backlog above 200/day can still grow. Check oldest pending time and run an
explicit date-scoped recovery before captures age out. Do not confuse a successful
Celery result with complete source coverage. The source-health registry monitors
the monitor's task heartbeat; it does not replace exact-date coverage checks.

## Proposed one-time recovery window

Target event dates: **2026-09-15 and 2026-09-16, Asia/Singapore**. Run once after
review/activation, during an operator-attended maintenance window. No execution
time or scheduler receipt is claimed by this PR. Use a durable identity such as
`hfl-recovery-2026-09-15-16` and reconcile previous receipts before rescheduling.
Keep each source independent so an unavailable browser host does not repeat
already completed Hermes or Trello writes.

1. Inventory the two dates by source before mutation. Retain a private manifest
   of eligible source IDs, existing canonical Markdown IDs, ES IDs, checkpoint
   state, and terminal semantic skips. Exclude AppleDouble files. The incident's
   reported 57 recovered desktop entries are prior work, not permission to
   regenerate them. Do not assume a sparse day proves every source has gaps.
2. **Desktop:** inventory dated dump artifacts; compare shared media state and
   canonical references. Use `analyze_desktop_capture(media_path=...)` only for
   exact missing eligible paths in the approved inbox. Start with one canary,
   replay it to verify no model call, then process bounded batches and retain
   per-path outcomes. Do not clear completed media-state records globally.
3. **Hermes:** inspect the relevant host's read-only `state.db` and retained audit
   spool. Use `scripts/agents/hfl/migrate_hermes_sessions.py` with `--dry-run`,
   explicit `--since`/`--until`, and `--manifest` after standard environment
   bootstrap (`PATH_APP_CONFIG`, `APP_CONFIG_FILE`, `WORKFLOW_CONFIG`). Verify
   actual boundary inclusion and approved closed user-facing surfaces from the
   manifest. Use `--start` / `--limit` for a canary and bounded apply; preserve
   source timestamps and stable pair IDs. Exclude open/automation sessions,
   reasoning, tools, and internal controls. Audit the capture hook separately;
   successful catch-up does not fix absent production.
4. **Trello:** use the native `collect_trello_activity` and
   `resolve_trello_window` preview first; ensure pagination is complete below
   `max_actions`. The existing `ingest_trello_activity` accepts explicit `since`
   and `until` dates. Inspect its resolved end boundary before dispatch. Compare
   stable Trello action IDs with canonical entries and persist only verified
   gaps. Keep synthesis settings unchanged across retries; Markdown deduplication
   alone does not guarantee an unchanged ES projection.
5. **Browser host:** collect Chrome/Edge history on the actual source host or
   from an authorized consistent SQLite copy. Verify exact half-open local-day
   bounds and database availability. `ingest_browsing_activity(window_days=...)`
   is **not a date-safe historical backfill**: it selects a current rolling window
   and writes at current time. Use an explicitly reviewed dated adapter through
   canonical persistence before any historical browser write. Missing DB/session
   or host access is a blocked source, never evidence of zero browsing.
6. Require canonical Markdown/ES ID-set parity for recovered entries and a
   duplicate replay with no additional entries. Record meaningful skips and
   unavailable sources separately. Regenerate dependent rollups only after
   confirming replacement-safe persistence; otherwise report them stale.

## Activation and rollback

Before an explicitly authorized deployment, record deployed commit, effective
Celery timezone, old desktop kwargs (40/1), and active schedule entries. Activate
only the reviewed worker/Beat changes. Verify natural dispatch, task registration,
source-health registry coverage, returned counts and accepted Telegram receipt.
The new monitor is daily at 06:30; desktop remains daily at 22:00.

Rollback: restore the prior deployed commit/schedule under the same deployment
procedure, removing the new monitor and restoring desktop kwargs. Do not delete
media-state, audit checkpoints, canonical entries or outbox records. A historical
backfill requires its own private preimage/ID manifest and conditional rollback;
reverting code does not undo corpus writes.
