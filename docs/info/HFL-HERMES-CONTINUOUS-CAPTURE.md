# Continuous Hermes prompt capture

Express: retain substantive default-profile Hermes CLI/Telegram requests, including
unfinished requests, in the existing agent-session spool and HFL corpus/index.
The five-minute collector reads SQLite without modifying it and makes no model calls.
The existing retained-event ingester owns persistence.

## Contract

- Top-level CLI/Telegram in the default profile only. Cron/subagents, other profiles,
  internal controls, slash commands and trivial acknowledgements are excluded.
- Consecutive requirements before assistant activity are retained separately. A new
  request after unfinished assistant activity interrupts the previous request;
  its later answer must not be attributed to the earlier request. Approval-only
  messages preserve the pending request so later visible outcomes remain linked.
- A visible final answer means `finish_reason=stop`, no tool calls, and Codex items
  (when present) marked `final_answer`. It is not proof the logical task succeeded.
- Pending/interrupted records have an empty assistant outcome, an explicit capture
  status and `prompt-observation` tag. HFL renders an observation, not a fabricated
  answer, and never uses a model to distill these observations.
- Existing artifacts and acknowledged receipts are immutable. Later visible answers
  or state transitions use deterministic linked records (`related_event_id`).
  Malformed existing artifacts fail closed. Historical rollups are not refreshed.
- Recover archived compacted originals. Suppress replay copies only when a Hermes
  microsecond insertion batch matches an ordered sequence of archived records;
  never collapse ordinary repeated submissions merely because their text matches.
  Hermes does not persist copy-to-original IDs: this is an explicit format-dependent
  reconstruction rule, not a universal provenance guarantee.
- Read full available history of sessions touched inside a bounded one-day scan.
  This recovers late answers to older prompts while preserving original dates.
  Rewound/inactive noncompacted rows remain excluded.
- Default batch 100; maximum 500. Repeat bounded windows to drain larger backlogs.
  The retained ingester also checks unacknowledged historical Hermes artifacts,
  so original dates older than its normal two-day window do not strand late answers.
- Collector runs use a persistent POSIX advisory lock. Capture and ingestion share
  per-event FD-bound locks; writes publish complete temporary files atomically.
  No hard links or stale-lock deletion. All writer processes must run this revision.
- stdout is counts only. Failures exit nonzero and report exception type, not payloads.

## Activation and recovery

1. Review and publish; run collector, migration and ingestion tests. Include a real
   multi-process contention probe on the spool filesystem before changing writers.
2. Keep the collector paused. Update the canonical worker and collector checkouts to
   the reviewed revision, suppressing automatic Git restart hooks for that operation.
   Restart only the affected worker; verify its exact broker identity and HFL queue.
3. The wrapper must load the deployment environment and resolve `audit_root()` to
   the existing shared spool. Configure an aware `HFL_HERMES_CAPTURE_SINCE` boundary.
4. Preview with `collect_hermes_sessions.py --since ISO --until ISO --dry-run`.
   Each window must be aware and at most one day. Preserve original message IDs/dates.
5. Run reviewed bounded collection. Persist only new artifacts through
   `process_agent_session_event(payload, synthesize=False)` for no-model recovery.
   Check spool receipts, canonical Markdown IDs and Elasticsearch IDs independently.
6. Replay collection and persistence to prove idempotency. Hash pre-existing artifacts
   before and after. No old artifact, receipt, rollup or canonical entry is replaced.
7. Resume the single existing five-minute `no_agent=true` Hermes job, retaining its
   explicit Telegram delivery. Verify an actual job invocation and worker persistence.
   Collector success alone is not HFL persistence success.
8. Rollback: pause the exact job; retain data and receipts. Never restore old writers
   while new ones are active, as old versions do not participate in the shared lock.

The legacy `migrate_hermes_sessions.py` CLI is read-only: its old text-based
deduplication and extraction rules are not valid for current recovery. Live writes
through that entry point fail closed. Do not substitute its dry-run count for the
collector recovery manifest.

Collector outages beyond the lookback window need a bounded backfill. SQLite polling
cannot recover messages deleted before persistence or sources outside the stated scope.
This is eventual capture, not a synchronous prompt-submit hook. Existing background-control
captures are preserved for audit rather than silently deleted during repair.

## Tests

```sh
python -m pytest scripts/tests/test_collect_hermes_sessions.py \
  scripts/tests/test_hermes_capture_completeness.py \
  workflows/hfl/tests/test_migrate_hermes_sessions.py \
  workflows/hfl/tests/test_ingest_agent_sessions.py -q
python -m pytest workflows/hfl/tests -q
```
