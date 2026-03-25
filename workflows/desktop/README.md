# Desktop Workflow

## Description

- Automates Windows desktop maintenance tasks: git pulls, window management, file sync, and activity logging.
- Captures desktop activity (screenshots + OCR) and generates daily/weekly AI-powered summaries.
- Runs n8n automation sequences on a schedule.

## Queue

Tasks run on the `default` queue.

## Scheduled Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `git_pull_on_paths` | Every 10 min | Pull latest commits on configured git repos |
| `set_desktop_hud_to_back` | Every 30 min | Send desktop HUD windows to background |
| `copy_files_targeted` | Every 30 min | Sync dev files to run directory |
| `run_n8n_sequence` | Daily at midnight | Execute n8n automation workflow |
| `run_capture_logging` | Every 15 min | Capture screenshot + log foreground app |
| `generate_daily_desktop_summary` | Daily at 23:55 | AI summary of today's desktop activity |
| `generate_weekly_desktop_summary` | Sundays at 23:58 | AI summary of the week's activity |

## Task Files

| File | Tasks |
|------|-------|
| `tasks/commands.py` | `git_pull_on_paths`, `set_desktop_hud_to_back`, `copy_files_targeted`, `run_n8n_sequence` |
| `tasks/capture.py` | `run_capture_logging`, `generate_daily_desktop_summary`, `generate_weekly_desktop_summary` |

## App Dependencies

| App | Used For |
|-----|---------|
| `desktop` | Window management, git automation, file sync helpers |
| `rainmeter` | HUD window z-order management |
| `open_ai` / `antropic` | Generating activity summaries from log data |

## Prompt Templates

AI summary tasks use markdown prompts from `workflows/prompts/`:
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

The `run_capture_logging` task:
1. Takes a screenshot of the active window.
2. Reads the foreground application name.
3. Writes a timestamped log entry to `ACTIONS_LOG_PATH`.
4. Archives logs by month pattern (`YYYY-MM`).

Log filenames use the format: `YYYY-MM-DD-HH-MM`.

## Notes

- `generate_daily_desktop_summary` and `generate_weekly_desktop_summary` were moved out of the `hud` workflow into `desktop` to keep concerns separated.
- `run_n8n_sequence` requires n8n to be running locally (default: `http://localhost:5678`).
- The `set_desktop_hud_to_back` task prevents the Rainmeter HUD from overlapping active windows.
