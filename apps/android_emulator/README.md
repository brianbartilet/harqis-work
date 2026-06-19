# Android Emulator + Device App

Local-CLI integration that controls Android targets — **emulators (AVDs) and
physical/wireless handsets** — by shelling out to the Android SDK tools
(`emulator`, `adb`, `avdmanager`, `sdkmanager`) plus `scrcpy` for screen
mirroring. Like `apps/filesystem`, it is **not** a REST app — it resolves the
SDK per-host and reads its own `ANDROID_EMULATOR` block from `apps_config.yaml`.

adb is device-agnostic, so install / screenshot / shell / logcat work the same
on an AVD or a real phone. The physical-device pieces an emulator doesn't need
(scrcpy mirroring, wireless adb) live in `devices.py` / `scrcpy.py`.

## Layers

| File | Responsibility |
|---|---|
| `config.py` | Per-host SDK discovery, tool-path resolution, named-profile loading, `merge_profile()`. |
| `client.py` | Subprocess wrapper (`CmdResult`/dicts, never raises). Emulator lifecycle, AVD mgmt, persistent `config.ini` props, parallel `spawn`/`clone_avd`, device ops, snapshots. |
| `devices.py` | Device-agnostic: `list_devices()` (emulator/physical/wireless), `device_info()`, wireless adb (`pair_wireless`/`connect_wireless`/`enable_tcpip`/`disconnect`). |
| `scrcpy.py` | Screen mirror+control via scrcpy: `resolve_scrcpy()`, `start_mirror()`, `stop_mirror()`. |
| `mcp.py` | `register_android_emulator_tools(mcp)` — the `emulator_*` and `device_*` MCP tools. |
| `tests/` | Unit tests, subprocess fully mocked (no SDK/emulator needed). |

## Requirements

The SDK must be on the host (`%LOCALAPPDATA%\Android\Sdk`, `ANDROID_SDK_ROOT`
set): JDK 17, `cmdline-tools;latest`, `platform-tools`, `emulator`, and a
`system-images;android-XX;google_apis(_playstore);x86_64`. Windows acceleration
uses WHPX — confirm with `emulator -accel-check`.

**Mirroring** needs scrcpy (optional): `winget install Genymobile.scrcpy`
(Windows), `brew install scrcpy` (macOS), `apt install scrcpy` (Linux).
`resolve_scrcpy()` finds it on PATH, via `scrcpy_path` config, or the winget
install dir.

## Configuration (`apps_config.yaml`)

```yaml
ANDROID_EMULATOR:
  sdk_root: ${ANDROID_SDK_ROOT}     # optional; env/OS-default used if unset
  scrcpy_path: ""                   # optional override; auto-resolved otherwise
  default_profile: pixel7-test
  profiles:
    pixel7-test:
      device: pixel_7
      image: system-images;android-34;google_apis_playstore;x86_64
      ram_mb: 8192
      cores: 6
      headless: false               # show the UI window
      no_audio: true
      gpu: angle_indirect           # HW (D3D11); renders Chrome/WebView correctly
      no_snapshot: false            # quick-boot persistence
      hw_keyboard: true             # host keyboard passthrough (config.ini)
      play_store: true              # certified Play Store (needs *_playstore image)
      nav_mode: threebutton         # on-screen Back/Home/Recents (applied post-boot)
      port: 5560                    # console port (adb = port+1)
```

`ram_mb`/`cores` apply via `-memory`/`-cores` at launch. `-partition-size` is
**not** used — the emulator caps it at 2047 MB; the data partition is sized by
the AVD's `config.ini`. `hw_keyboard`/`play_store` are written to `config.ini`
pre-boot; `nav_mode` is applied in-guest post-boot.

## MCP tools

Emulator: `emulator_sdk_info` · `emulator_start` · `emulator_spawn` (parallel) ·
`emulator_stop` · `emulator_status` · `emulator_list_running` ·
`emulator_list_avds` · `emulator_list_system_images` · `emulator_create_avd` ·
`emulator_clone_avd` · `emulator_delete_avd` · `emulator_install_apk` ·
`emulator_adb_shell` (whitelisted verbs) · `emulator_screenshot` ·
`emulator_snapshot_save` / `_load` / `_list`.

Devices + mirroring: `device_list` · `device_mirror` / `device_mirror_stop` ·
`device_connect` · `device_pair` · `device_tcpip`.

## Physical devices & mirroring

Real handsets are the way to test apps with RASP/anti-tamper that refuse to run
on emulators — scrcpy only mirrors the display and forwards input through adb,
so it doesn't root/hook/debug/instrument/modify the app, and the device passes
its integrity checks.

```bash
# USB: enable Developer options → USB debugging, plug in, accept the prompt
python scripts/agents/emulator/run_emulator.py devices --info
python scripts/agents/emulator/run_emulator.py mirror --serial <serial> --title "QA"

# Go wireless (then unplug):
python scripts/agents/emulator/run_emulator.py tcpip <serial>      # prints <ip>:5555
python scripts/agents/emulator/run_emulator.py connect <ip>:5555
# Android 11+ pure-wireless (Wireless debugging → Pair with code):
python scripts/agents/emulator/run_emulator.py pair <ip>:<pairPort> <code>
python scripts/agents/emulator/run_emulator.py connect <ip>:<connPort>

# One-shot auto-connect (USB → wireless fallback) + mirror:
python scripts/agents/emulator/run_emulator.py device-up --wireless <ip>:5555

# Daemon: connect + mirror, then AUTO-RECONNECT on drop (leave/return Wi-Fi range):
python scripts/agents/emulator/run_emulator.py device-watch --wireless <ip>:5555 --interval 10
```

### Auto-connect on deploy (`[<machine>.device]`)

`scripts/deploy.py` fires the connect+mirror+reconnect flow when a machine
declares a `[<machine>.device]` table (see `machines.toml`): it tries USB first,
falls back to a wireless target, mirrors via scrcpy, and leaves a tracked
**watchdog daemon** (`device-watch`) that re-connects + re-mirrors whenever the
device drops — no need to re-run deploy. If nothing is reachable it prints a
message and skips gracefully. Composes with the flags: `deploy.py --restart
device` / `--stop device` / `--status` / `--down`. Real `serial`/`wireless`
values belong in `machines.local.toml` (gitignored — the repo is public).

## See also

- Workflow + CLI: [`workflows/mobile/emulator`](../../workflows/mobile/emulator/README.md)
- CLI: `scripts/agents/emulator/run_emulator.py`
