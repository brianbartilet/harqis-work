# Continuous Hermes prompt/outcome capture

Express: retain completed default-profile Hermes CLI/Telegram turns in the existing
agent-session spool, then let the existing ten-minute HFL ingester persist them.
The collector is deterministic, read-only against Hermes SQLite, and makes no model calls.

## Contract

- Require a user prompt followed by a persisted final assistant answer (`stop`, no
  tool calls; Codex items must be `final_answer`). An open session may contain a
  completed turn; session closure is not required.
- Exclude cron/subagents, other profiles, inactive/compacted rows, internal controls,
  slash commands and trivial acknowledgements using the existing migration filters.
- Reuse the existing sanitizer and event IDs. Never rewrite an existing event or
  clear its ingestion receipt. Malformed existing events fail closed.
- Read a bounded overlapping SQLite snapshot: last 24 hours, no earlier than an
  operator-approved launch boundary. Default batch 100; maximum 500. No moving
  timestamp cursor that could skip a late final answer inside the window.
- The existing two-day retained ingester has retry headroom beyond the collector's
  one-day window. Do not widen the producer without coordinating consumer retention.
- A POSIX advisory lock prevents overlapping collector runs. stdout is counts only;
  failures exit nonzero and report only exception type, never private payloads.

## Activation

Use a reviewed/published checkout and its configured repository interpreter. Set
`HFL_HERMES_CAPTURE_SINCE` to an aware ISO timestamp approved for new collection.
Repository `scripts.launch.setup_env()` loads `.env/apps.env` and machine overrides.
Preview first:

```sh
HFL_HERMES_CAPTURE_SINCE='<launch timestamp with offset>' \
  /absolute/runtime/.venv/bin/python \
  /absolute/reviewed-checkout/scripts/agents/hfl/collect_hermes_sessions.py --dry-run
```

Create a small local `.sh` wrapper with that same environment and command (without
`--dry-run`). Schedule it through Hermes `cronjob`: `no_agent=true`, every five
minutes, `script=<wrapper filename relative to ~/.hermes/scripts/>`, with an explicit configured Telegram delivery
for each count-only receipt. Never rely on CLI-origin delivery for notifications.
No Hermes or existing worker restart is required. Only one collector job is needed.

When the main runtime has unrelated undeployed changes, deploy the reviewed commit
as a separate detached Git worktree. Reuse the canonical runtime's `.venv`, `.env`
and ignored `machines.local.toml` via local symlinks, not copied secrets. Verify
`audit_root()` resolves to the existing spool before enabling the schedule.

Verify a real, clearly labelled test conversation: completed turn -> new retained
artifact -> existing HFL worker -> exactly one Markdown and Elasticsearch record.
Replay collection to prove the artifact's ingestion checkpoint is unchanged.
Rollback: pause the exact collector job; retain all spool artifacts and receipts.

## Limits and recovery

A collector outage or single unfinished turn lasting beyond 24 hours can require
an explicitly approved bounded historical migration. Compacted/deactivated history
is deliberately not reconstructed. The collector does not regenerate old rollups
or change existing Celery schedules. Collection success is not persistence success;
verify both corpus and index, allowing bounded search-refresh latency.

## Tests

```sh
python -m pytest scripts/tests/test_collect_hermes_sessions.py \
  workflows/hfl/tests/test_migrate_hermes_sessions.py \
  workflows/hfl/tests/test_ingest_agent_sessions.py -q
```
