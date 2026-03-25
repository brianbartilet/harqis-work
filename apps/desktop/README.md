# Desktop

## Description

- Windows desktop automation helpers for the `desktop` workflow.
- Provides utilities for window management, Git operations, file synchronization, and HUD feed data writing.
- Not a third-party API integration — wraps Windows-native operations via `pywin32`, `subprocess`, and file I/O.

## Supported Automations

- [ ] webservices
- [ ] browser
- [X] desktop
- [ ] mobile
- [ ] internet of things

## Directory Structure

```
apps/desktop/
├── config.py
├── references/
│   └── helpers/
│       └── feed.py             # Atomic file writer for HUD feed data
├── corsair/                    # iCUE profile helpers (Corsair keyboard lighting)
└── tests/
```

## Helpers

### `helpers/feed.py`

Provides `_atomic_write_text(path, content)` — writes content to a file atomically (write to temp → rename) to prevent Rainmeter from reading partial writes.

Used by the `@feed()` decorator in workflow tasks to push data to the HUD feed directory.

## Configuration (`apps_config.yaml`)

```yaml
DESKTOP:
  app_id: 'desktop'
  app_data:
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
ACTIONS_LOG_PATH=           # Where activity log files are written
ACTIONS_ARCHIVE_PATH=       # Where logs are archived by month
ACTIONS_SCREENSHOT_PATH=    # Where screenshots are saved
DESKTOP_PATH_DEV=           # Source folder for file sync
DESKTOP_PATH_RUN=           # Destination folder for file sync
DESKTOP_PATH_I_CUE_PROFILES= # Path to iCUE profile files
DESKTOP_PATH_FEED=          # Path read by Rainmeter for HUD feed
```

## Workflow Integration

Tasks in `workflows/desktop/tasks/` use this app's config and helpers:

| Task | What it uses |
|------|-------------|
| `git_pull_on_paths` | `subprocess` git commands on configured repo paths |
| `set_desktop_hud_to_back` | `pywin32` window z-order management |
| `copy_files_targeted` | `shutil` file copy from `path_dev_files` → `path_run_files` |
| `run_capture_logging` | Screenshot + foreground window detection, writes to `actions_log_path` |

## Notes

- Windows-only — uses `pywin32` for window management and `ctypes` for process interaction.
- The HUD feed uses atomic writes to avoid Rainmeter rendering partial data.
- `corsair/` contains helpers for switching iCUE keyboard lighting profiles to match the active application.
