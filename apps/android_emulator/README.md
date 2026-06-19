# Android Emulator App

Local-CLI integration that controls Android Virtual Devices (AVDs) by shelling
out to the Android SDK command-line tools (`emulator`, `adb`, `avdmanager`,
`sdkmanager`). Like `apps/filesystem`, it is **not** a REST app — it does not use
`apps.config_loader.get_ws_config`; it resolves the SDK per-host and reads its
own `ANDROID_EMULATOR` block from `apps_config.yaml`.

## Layers

| File | Responsibility |
|---|---|
| `config.py` | Per-host SDK discovery (`ANDROID_SDK_ROOT`/`ANDROID_HOME` → config `sdk_root` → OS default), tool-path resolution, named-profile loading, `merge_profile()` (profile + overrides). |
| `client.py` | Thin, testable subprocess wrapper. Returns `CmdResult`/dicts, never raises for operational failure. Lifecycle, AVD mgmt, device ops, snapshots. `start_emulator` launches detached. |
| `mcp.py` | `register_android_emulator_tools(mcp)` — the `emulator_*` MCP tools. |
| `tests/` | Unit tests, subprocess fully mocked (no SDK/emulator needed). |

## Requirements

The SDK must be installed on the host that runs the tools/tasks. On this machine
it lives at `%LOCALAPPDATA%\Android\Sdk` with `ANDROID_SDK_ROOT` set. Components:
JDK 17, `cmdline-tools;latest`, `platform-tools`, `emulator`, and at least one
`system-images;android-XX;google_apis;x86_64`. Windows acceleration uses WHPX
(Hyper-V); confirm with `emulator -accel-check`.

## Configuration (`apps_config.yaml`)

```yaml
ANDROID_EMULATOR:
  sdk_root: ${ANDROID_SDK_ROOT}     # optional; env/OS-default used if unset
  default_profile: pixel7-test
  profiles:
    pixel7-test:
      device: pixel_7
      image: system-images;android-34;google_apis;x86_64
      ram_mb: 4096
      cores: 4
      partition_mb: 6144
      headless: true
      no_audio: true
      gpu: auto
      port: 5554
```

`ram_mb`/`cores`/`partition_mb` are applied at launch via the emulator's
`-memory`/`-cores`/`-partition-size` flags (no `config.ini` edits).

## MCP tools

`emulator_sdk_info` · `emulator_start` · `emulator_stop` · `emulator_status` ·
`emulator_list_running` · `emulator_list_avds` · `emulator_list_system_images` ·
`emulator_create_avd` · `emulator_delete_avd` · `emulator_install_apk` ·
`emulator_adb_shell` (whitelisted verbs) · `emulator_screenshot` ·
`emulator_snapshot_save` / `_load` / `_list`.

For unrestricted `adb`, use the Celery task / CLI path instead — the MCP
`emulator_adb_shell` only allows read-mostly verbs (getprop, dumpsys, pm, am,
input, settings, ls, cat, df, ps, logcat, …).

## See also

- Workflow + CLI: [`workflows/mobile/emulator`](../../workflows/mobile/emulator/README.md)
- CLI: `scripts/agents/emulator/run_emulator.py`
