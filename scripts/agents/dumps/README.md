# Android seven-day summary supervisor

`harqis_dumps_summary_android_7d.py` is the canonical copy of the standalone
Hermes no-agent wrapper installed at `~/.hermes/scripts/` on the macOS hub.
It runs the existing runtime checkout's `run_dumps_summary_retro.py --days 7
--device nothing-phone --result-json`, using that checkout's Python (`-u` for
unbuffered progress). Deploy the wrapper and runtime CLI together: the wrapper
requires the versioned result record and fails if it is missing or invalid.

- Child deadline: 3000 seconds, below the existing 3600-second cron deadline.
- Cleanup: dedicated POSIX process group, SIGTERM followed by SIGKILL after a
  five-second grace period, bounded reap and a bounded group-disappearance check.
  A surviving group (including unreaped zombies) is reported as incomplete cleanup;
  delivery of SIGKILL alone is not proof of exit. SIGTERM/SIGINT to the supervisor also
  clean up the group. SIGKILL to the supervisor itself cannot be handled.
- Exit status: original child status (signals normalized to 128+signal), 124 on
  deadline, 1 on launch/diagnostics/supervisor/cleanup failure.
- Diagnostics: unique `~/.hermes/logs/android-dumps-summary/*.jsonl` files, mode
  0600, flushed/fsynced by a daemon writer at start, every 30 seconds, and completion. Only lifecycle,
  elapsed time, PID, byte counters and exception *types* are recorded. Heartbeats
  show liveness/output activity, not which internal analyzer stage is blocked.
  A bounded 128-record queue keeps filesystem I/O off the supervision thread.
  Failed logging stops supervision with cleanup; stalled logging cannot prevent
  the child deadline or cleanup. Final logging gets one second to drain, then
  returns failure if incomplete. A blocked writer cannot delay process exit, but
  diagnostics may be incomplete. Process creation and OS scheduling are not hard
  real-time guarantees; retain the independent scheduler deadline as a backstop.
- Child output is drained continuously with bounded memory, not saved. Only
  allowlisted numeric fields from `DUMPS_RESULT` JSON contribute to the production
  success report; raw errors and paths from child output are never included.
  Version 1 reports status (`success`, `no_data`, `error`, `skipped`), file/byte
  totals, requested days, days with dumps, and number of appended log sinks.
  The default CLI still prints Markdown; `--result-json` changes output only.
  Best-effort publisher/sink failures not surfaced by the task cannot be inferred
  from this record; success does not certify every external destination.
  Legacy text parsing remains available for synthetic/older callers that do not
  require structured results. Nonzero child exits always override parsed output.

The analyzer change filters exact parsed device names before stat/recursive walks.
It retains the unfiltered behavior for callers without a machine filter and does
not change notification, Markdown, HUD, ES, gap, or count semantics.

## Safe verification

Run `python -m pytest scripts/agents/dumps/tests -q` using the repository's Python.
Tests use synthetic child processes and extract actual pure scanner/task functions
without importing publisher decorators. They do not load live task configuration,
read private dumps, append summary logs, or publish HUD/ES/Telegram messages.

Do **not** execute the real summary entry point as a smoke test: it publishes and
appends logs even with `--no-md` (which disables only the Markdown append). For a
live check, call only `_scan_day` with the exact device filter; output aggregate
counts rather than paths or dump contents.

Installing the standalone wrapper does not deploy the analyzer. Keep the runtime
checkout read-only until the PR is reviewed and a separate deployment is authorized.
