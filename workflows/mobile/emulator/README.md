# Mobile / Emulator Workflow

On-demand Celery tasks for starting and managing local Android emulators. Thin
wrappers over [`apps/android_emulator`](../../../apps/android_emulator/README.md)
so the MCP tools, the CLI, and these tasks share one implementation.

## Tasks (`tasks/manage.py`)

| Task | Purpose |
|---|---|
| `start_emulator` | Boot an AVD from a named profile (+ per-call overrides); optionally wait for boot. |
| `ensure_emulator` | Idempotent — start the profile's AVD only if it isn't already running. Safe to schedule. |
| `stop_emulator` | Gracefully stop a running emulator by serial (`adb emu kill`). |
| `list_emulators` | Running emulators + installed AVDs on this host. |
| `create_avd` | Create an AVD from a profile and/or explicit image/device. |

All tasks self-guard: on a worker without the Android SDK they return
`{"skipped": True, ...}` instead of failing (the "any host with the SDK" model —
a competing-consumers pickup on a non-SDK box no-ops). Each is `@log_result`-ed
to Elasticsearch.

## Schedule

**None.** These are on-demand (`tasks_config.py` exports an empty
`WORKFLOW_MOBILE_EMULATOR`). Tasks are still registered with Celery via
`autodiscover_tasks(['workflows'])`, so they're callable directly. To keep a
profile warm on a timer, add a beat entry calling the idempotent
`ensure_emulator` and union the dict into `workflows/config.py`.

## How to run

```bash
# CLI (synchronous, self-guards, exit 2 if no SDK)
python scripts/agents/emulator/run_emulator.py start --profile pixel7-test
python scripts/agents/emulator/run_emulator.py list
python scripts/agents/emulator/run_emulator.py stop emulator-5554
python scripts/agents/emulator/run_emulator.py create --profile pixel7-test

# Celery (queue-routed to whichever SDK-equipped worker picks it up)
from workflows.mobile.emulator.tasks.manage import start_emulator
start_emulator.delay(profile="pixel7-test")
```

## Setup

See the app README for SDK install/config. On this repo's primary Windows box
the SDK is at `%LOCALAPPDATA%\Android\Sdk` (`ANDROID_SDK_ROOT` set), with the
`android-34;google_apis;x86_64` image and WHPX acceleration.

## Relation to `workflows/mobile/android`

`workflows/mobile/android` is the on-device Termux screen logger (runs on a
physical phone). This `emulator/` sibling runs on the **desktop** and drives
SDK-managed virtual devices — unrelated code paths, grouped under `mobile/`.
