# Desktop Workflow

## Description

- Automates Windows desktop maintenance tasks: git pulls, window management, file sync, and activity logging.
- Captures desktop activity (screenshots + OCR) and generates daily/weekly AI-powered summaries.
- Runs n8n automation sequences on a schedule.

## Queues

Tasks are routed per-entry in `tasks_config.py`. See the `Queue` column below.

## Scheduled Tasks

| Task | Schedule | Queue | OS | Description |
|------|----------|-------|----|-------------|
| `git_pull_on_paths` | 00:00 and 12:00 daily | `default_broadcast` (fanout) | any | Fast-forward the repo root (`REPO_ROOT`) with Git hooks disabled for this invocation only; no deployment or restart. Every subscribed worker refreshes its own working tree. |
| `git_auto_push_paths` | Daily at 02:00 | `default_broadcast` (fanout) | any | Generic Git backup for repositories listed under that machine's `git_autopush.paths`; clean and non-Git paths are no-ops, and rejected pushes retry through rebase/autostash with conflict abort. Notes repositories use the separate `workflows/notes` chain and must not be duplicated here. |
| `run_n8n_sequence` | Daily at midnight | `n8n` | windows / macos / linux | Backup → restore via `.bat` (Windows) or `.sh` (macOS / Linux) in `workflows/n8n/deploy/` |
| `set_desktop_hud_to_back` | Every 30 min | `hud` | windows | Send desktop HUD windows to background (Rainmeter) |
| `copy_files_targeted` | Every 30 min | `peon` | any | Sync dev files to run dir; file list sourced from `machines.local.toml` `[sync] items` |
| `run_capture_logging` | Every 5 min | `capture` | windows | Supervise one lock/idle-aware desktop activity reader |
| `generate_daily_desktop_summary` | Daily at 23:55 | `peon` | any | AI summary of today's desktop activity |
| `generate_weekly_desktop_summary` | Sundays at 23:58 | `peon` | any | AI summary of the week's activity |

## Repository refresh is not deployment

`git_pull_on_paths` runs `git -c core.hooksPath=/dev/null pull --ff-only`
against its existing upstream. The command-scoped override suppresses hooks
(including `post-merge`) without deleting them or changing persistent Git
configuration. A post-merge hook that restarts services can otherwise stop the
very Celery worker executing the pull and interrupt its own recovery.

Divergent branches are refused instead of merged or rebased. Git errors still
use the existing stderr logging path; the task retains its repository-path
return value, so task success alone is **not** proof that the pull succeeded.
Inspect the Git output. This does not change `git_auto_push_paths` or other Git
callers, and it is not a deployment lock or an atomic code/dependency rollout.

Dependency synchronization, service reloads and readiness checks belong to an
operator or the existing externally supervised maintenance process, outside the
worker process tree. Hosts previously relying on post-merge deployment need
that external owner; do not replace the hook with a background restart spawned
by this task or introduce another competing scheduler.

**Rollout:** publishing or pulling this patch does not change code already
imported by a running worker, and it does not alter any installed local hook.
Use a separately authorized external deployment with hook-suppressed Git
refresh, then supervised worker reload and readiness verification. Until the
worker loads the fixed task, its existing scheduled invocation can still take
the unsafe path. This code change alone does not repair an unloaded service.

Offline safety regressions are in
`scripts/tests/test_desktop_git_pull_safety.py` (outside the auto-importing
`workflows.desktop` package). They use isolated local repositories and inert
marker hooks, never live service restarts.

## Task Files

| File | Tasks |
|------|-------|
| `tasks/commands.py` | `git_pull_on_paths`, `git_auto_push_paths`, `set_desktop_hud_to_back`, `copy_files_targeted`, `run_n8n_sequence` |
| `tasks/capture.py` | `run_capture_logging`, `generate_daily_desktop_summary`, `generate_weekly_desktop_summary` |

## App Dependencies

| App | Used For |
|-----|---------|
| `desktop` | Window management, git automation, file sync helpers |
| `rainmeter` | HUD window z-order management |
| `open_ai` / `antropic` | Generating activity summaries from log data |

## Prompt Templates

AI summary tasks use markdown prompts from `workflows/desktop/prompts/`:
- `daily_summary.md` — Prompt for daily activity summarization
- `weekly_summary.md` — Prompt for weekly activity summarization

## Configuration (`apps_config.yaml`)

```yaml
DESKTOP:
  capture:
    strf_time: "%Y-%m-%d-%H-%M"
    actions_log_path: ${ACTIONS_LOG_PATH}
    archive_path: ${ACTIONS_ARCHIVE_PATH}
    screenshots_path: ${ACTIONS_SCREENSHOT_PATH}
    show_console: False
    idle_pause_seconds: 300
    focus_interval_seconds: 1.0
    max_memory_mb: 768
  copy_files:
    path_dev_files: ${DESKTOP_PATH_DEV}
    path_run_files: ${DESKTOP_PATH_RUN}
  corsair:
    path_profiles: ${DESKTOP_PATH_I_CUE_PROFILES}
  feed:
    path_to_feed: ${DESKTOP_PATH_FEED}
```

`.env/apps.env`:

```env
ACTIONS_LOG_PATH=/path/to/activity/logs
ACTIONS_ARCHIVE_PATH=/path/to/archive
ACTIONS_SCREENSHOT_PATH=/path/to/screenshots
DESKTOP_PATH_DEV=/path/to/dev/files
DESKTOP_PATH_RUN=/path/to/run/files
DESKTOP_PATH_I_CUE_PROFILES=/path/to/icue/profiles
DESKTOP_PATH_FEED=/path/to/hud/feed
```

## Activity Capture Format

The `run_capture_logging` task supervises one long-lived activity reader. A healthy
reader is left in place; duplicate/orphan process trees are replaced. The reader
pauses UI Automation while Windows is locked or the user has been idle for the
configured threshold, polls focus no more than once per second, and exits if its
private memory reaches the configured cap. `actions_health.json` records its PID,
memory, session state, idle time, last operation, and last focus poll.

Log filenames use the format: `YYYY-MM-DD-HH-MM`.

## Notes

- `generate_daily_desktop_summary` and `generate_weekly_desktop_summary` were moved out of the `hud` workflow into `desktop` to keep concerns separated.
- `run_n8n_sequence` requires n8n to be running locally (default: `http://localhost:5678`). It auto-picks `.bat` on Windows and `.sh` on macOS / Linux from `workflows/n8n/deploy/`, and is routed to the dedicated `n8n` queue (consumed by `harqis-server` only).
- `copy_files_targeted` reads its file list from `machines.local.toml` `[sync] items` — same source of truth as `scripts/sync-to-host.ps1`. No hardcoded paths in source.
- `git_pull_on_paths` uses `REPO_ROOT` (resolved from this module's location) instead of a hard-coded path, so it works on Windows and macOS without per-host edits.
- `git_auto_push_paths` reads per-machine repository paths from the gitignored `machines.local.toml`; it does not embed local paths or credentials in source. This list is for generic unattended Git backup. Checkouts managed by `workflows/notes` belong only under `[<machine>.notes.repositories]`, because that workflow has different push safety rules and continues through a canonical host pull and Activity Corpus ingest.
- The `set_desktop_hud_to_back` task prevents the Rainmeter HUD from overlapping active windows.

## Manifesto alignment

See [`docs/MANIFESTO.md`](../../docs/MANIFESTO.md) and [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](../../docs/thesis/MANIFESTO-REPO-UPDATES.md). The same metadata is persisted on each beat entry's `'manifesto'` key in `tasks_config.py`; `scripts/agents/repo-quality/manifesto_audit.py` validates it.

| Task | code_role | para_bucket | express_target | review_artifact | hfl_signal |
| --- | --- | --- | --- | --- | --- |
| `git_pull_on_paths` | organize | area | `es_log` | `es_log` | `False` |
| `git_auto_push_paths` | organize | area | `git_remote+es_log` | `es_log` | `False` |
| `run_n8n_sequence` | organize | area | `hud_feed` | `es_log+hud_feed` | `False` |
| `set_desktop_hud_to_back` | organize | area | `hud_feed` | `es_log+hud_feed` | `False` |
| `copy_files_targeted` | organize | area | `hud_feed` | `es_log+hud_feed` | `False` |
| `run_capture_logging` | capture | area | `hud_feed+file:screenshots` | `es_log+hud_feed` | `True` |
| `generate_daily_desktop_summary` | distill+express | area | `rainmeter:DESKTOP_LOGS+file:daily` | `es_log+hud_widget+file` | `True` |
| `generate_weekly_desktop_summary` | distill+express | area | `rainmeter:DESKTOP_LOGS+file:weekly` | `es_log+hud_widget+file` | `True` |
