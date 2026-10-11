# Android seven-day summary supervisor

`harqis_dumps_summary_android_7d.py` is the canonical copy of the standalone
Hermes no-agent wrapper installed at `~/.hermes/scripts/` on the macOS hub.
It runs the existing runtime checkout's `run_dumps_summary_retro.py --days 7
--device nothing-phone`, using that checkout's Python (`-u` for unbuffered
progress). It does not depend on the scanner changes being deployed.

- Child deadline: 3000 seconds, below the existing 3600-second cron deadline.
- Cleanup: dedicated POSIX process group, SIGTERM followed by SIGKILL after a
  five-second grace period, bounded reap. SIGTERM/SIGINT to the supervisor also
  clean up the group. SIGKILL to the supervisor itself cannot be handled.
- Exit status: original child status (signals normalized to 128+signal), 124 on
  deadline, 1 on launch/diagnostics/supervisor/cleanup failure.
- Diagnostics: unique `~/.hermes/logs/android-dumps-summary/*.jsonl` files, mode
  0600, flushed/fsynced at start, every 30 seconds, and completion. Only lifecycle,
  elapsed time, PID, byte counters and exception *types* are recorded. Heartbeats
  show liveness/output activity, not which internal analyzer stage is blocked.
- Child output is drained continuously with bounded memory, not saved. Only
  numeric aggregate `TOTAL:` and legacy `Wrote N summary files` lines contribute
  to the concise success report; raw errors and paths from child output are never
  included. Current runtime Markdown output still yields `complete`, as before.

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
