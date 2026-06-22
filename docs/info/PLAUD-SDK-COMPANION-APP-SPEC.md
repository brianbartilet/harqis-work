# PLAUD SDK Companion App — Design Spec (Track B detail)

**Parent spec:** [PLAUD-CALENDAR-RECORDING-SPEC.md](PLAUD-CALENDAR-RECORDING-SPEC.md) (PR #39)
**Upstream:** [github.com/Plaud-AI/plaud-sdk-public](https://github.com/Plaud-AI/plaud-sdk-public)
**Status:** Proposed (spec only)
**Date:** 2026-06-22

---

This is the detailed design for **Track B** of the calendar-triggered recording
spec — a minimal companion app built on PLAUD's **official Embedded SDK** that
gives harqis-server a sanctioned, durable way to start/stop the Note Pro over
BLE. Component names, file paths, and API signatures below were **verified
against the live `plaud-sdk-public` repo on 2026-06-22**, not inferred.

## Table of Contents

1. [Why Track B over the ADB MVP](#1-why-track-b-over-the-adb-mvp)
2. [The SDK repo, component by component](#2-the-sdk-repo-component-by-component)
3. [Verified API surface](#3-verified-api-surface)
4. [Auth & platform requirements](#4-auth--platform-requirements)
5. [Companion app design](#5-companion-app-design)
6. [How harqis-server drives it](#6-how-harqis-server-drives-it)
7. [Bonus: this closes the device→cloud sync gap](#7-bonus-this-closes-the-devicecloud-sync-gap)
8. [iOS vs Android decision](#8-ios-vs-android-decision)
9. [Build & deploy](#9-build--deploy)
10. [Risks & mitigations](#10-risks--mitigations)
11. [Open questions](#11-open-questions)
12. [Implementation walkthrough](#12-implementation-walkthrough)

---

## 1. Why Track B over the ADB MVP

Track A (ADB UI-automation of the stock Plaud app) proves the calendar→record
loop fast but is brittle — it taps screen coordinates and breaks on app updates.
Track B replaces those taps with **first-class SDK calls** to the device. The
key fact, verified in
`plaud-template-app/ios/PlaudTemplateApp/Managers/RecordingManager.swift`:

```swift
func startRecord()  { PlaudDeviceAgent.shared.startRecord() }
func stopRecord()   { PlaudDeviceAgent.shared.stopRecord() }
func pauseRecord()  { PlaudDeviceAgent.shared.pauseRecord() }
func resumeRecord() { PlaudDeviceAgent.shared.resumeRecord() }
```

`RecordingManager` is a thin pass-through to `PlaudDeviceAgent` — the SDK
**does** command the physical device to start/stop recording over BLE. (The
repo README's "Key SDK Methods" list omits these and shows only
scan/connect/sync/export, which is what initially looked like recording control
might be missing — the source settles it: it's there.)

## 2. The SDK repo, component by component

Top level:

| Path | What it is |
|---|---|
| `sdk/` | Precompiled binaries — iOS `.framework`s + the Android `.aar` |
| `plaud-template-app/` | Complete **iOS** reference app (Swift, UIKit + MVVM + Combine) |
| `README.md`, `LICENSE`, `.gitignore` | — |

The shipped SDK frameworks (in `sdk/`):

| Framework | Role |
|---|---|
| **PlaudBleSDK.framework** | BLE transport — scan, connect, the record-control + file commands |
| **PlaudDeviceBasicSDK.framework** (+ `.bundle`) | Core device ops + `PlaudDeviceAgent` (the main entry point) |
| **PlaudWiFiSDK.framework** | WiFi fast transfer (~10× faster file export than BLE) |
| **Android `.aar`** | The same surface for Android (no template app yet — "coming soon") |

The iOS template app's manager layer
(`plaud-template-app/ios/PlaudTemplateApp/Managers/`) is the part we mirror —
each is a thin wrapper we can copy the shape of:

| Manager | Responsibility | Do we need it? |
|---|---|---|
| `DeviceManager` | SDK wrapper: scan / connect / OTA / multi-device; forwards device callbacks | **Yes** — connection lifecycle |
| `RecordingManager` | Recording state + start/stop/pause/resume + PCM waveform | **Yes** — the whole point |
| `SyncManager` | File sync (BLE + WiFi fast transfer); auto-runs after a recording stops | **Yes** — pulls audio off the device |
| `TranscriptionManager` | S3 upload + transcription polling (uses client API key) | Optional — we already Whisper |
| `PlaudAPIService` | HTTP client for the partner API | Indirect |

Other folders: `App/` (launch routing), `Common/` (UI/theme), `Models/`,
`Storage/` (local persistence), `UI/` (feature screens). For a headless trigger
we keep only `Managers/` + `Models/` and drop the UI.

## 3. Verified API surface

From the README + `RecordingManager.swift` (iOS names; the Android `.aar`
mirrors these):

```swift
// init / connect
PlaudDeviceAgent.shared.initSDK(userAccessToken:customDomain:)
PlaudDeviceAgent.shared.startScan()
PlaudDeviceAgent.shared.connectBleDevice(bleDevice:)

// recording control  ← what Track B uses
PlaudDeviceAgent.shared.startRecord()
PlaudDeviceAgent.shared.stopRecord()
PlaudDeviceAgent.shared.pauseRecord()
PlaudDeviceAgent.shared.resumeRecord()

// file ops / sync
PlaudDeviceAgent.shared.getFileList(startSessionId:)
PlaudDeviceAgent.shared.exportAudio(sessionId:outputDir:format:channels:callback:)
PlaudDeviceAgent.shared.deleteFile(sessionId:)
PlaudWiFiAgent.shared.exportAudioViaWiFi(...)

// firmware
PlaudDeviceAgent.shared.checkFirmwareUpdate(_:)
PlaudDeviceAgent.shared.startFirmwareUpdate(progress:completion:)
```

**State & callbacks** (from `RecordingManager`) — our verification signal:

- `statePublisher: AnyPublisher<RecordingState, Never>` — `.idle` /
  `.recording(sessionId, startedAt)` / `.paused(sessionId)`.
- Device-originated callbacks forwarded by `DeviceManager`:
  `handleRecordStart(sessionId:startTime:)`, `handleRecordStop(sessionId:)`,
  `handleRecordPause`, `handleRecordResume`. **These fire for a physical button
  press too**, so the companion always knows the true device state — no blind
  open-loop control.
- On stop, `handleRecordStop` calls `SyncManager.shared.startSync()` after 1s —
  audio is pulled off the device automatically.

## 4. Auth & platform requirements

**Credentials (partner program at `dev.plaud.ai`):**

1. `USER_ACCESS_TOKEN` — a JWT minted via a partner backend call
   (`POST /open/partner/users/access-token`), passed to `initSDK(...)`. This is
   the per-user SDK session token.
2. `PLAUD_CLIENT_ID` + `PLAUD_API_KEY` — created in the Developer Portal; sent
   as `X-Client-Id` / `X-Client-Api-Key` headers, used only for the
   transcription API (optional for us).

A **free tier** exists for prototyping. Production is usage-based.

**Platform:**

- iOS 14.0+, Xcode 16.0+, Swift 5.0+, **arm64 physical device only — no
  simulator** (no BLE radio in the simulator).
- Android: `.aar` available; min SDK per the AAR; **real device only** (same BLE
  constraint — and the emulator has no BLE, consistent with the parent spec).

## 5. Companion app design

A **minimal, headless-as-possible** app whose only job is: stay connected to the
Note Pro and expose a local trigger that calls `startRecord()` / `stopRecord()`.

```
┌───────────────────────────────────────────────────────────┐
│ Companion app (on the dedicated paired phone)              │
│                                                           │
│  initSDK(USER_ACCESS_TOKEN)                                │
│  startScan() → connectBleDevice() → auto-reconnect loop    │
│        │                                                  │
│  ┌─────┴──────────────┐     ┌──────────────────────────┐  │
│  │ Trigger listener    │────▶│ RecordingManager         │  │
│  │ (broadcast / HTTP)  │     │  start/stop/pause/resume │  │
│  └─────────────────────┘     └────────────┬─────────────┘  │
│                                            │ statePublisher │
│  ┌─────────────────────────────────────────▼────────────┐  │
│  │ State reporter → ADB logcat tag / HTTP 200 / file     │  │
│  │  so harqis-server can VERIFY the toggle took          │  │
│  └───────────────────────────────────────────────────────┘  │
│  SyncManager auto-runs on stop → audio pulled off device   │
└───────────────────────────────────────────────────────────┘
```

Responsibilities:

1. **Init + connect on launch**, with an auto-reconnect watchdog (the SDK
   supports auto-reconnect) so the link survives the phone sleeping/roaming.
2. **Foreground/keep-alive service** (Android foreground service / iOS
   background-BLE entitlement) so the OS doesn't kill the BLE connection.
3. **Trigger listener** — the only "API" harqis-server needs:
   - *Android (preferred):* a `BroadcastReceiver` for
     `com.harqis.plaud.RECORD` with `--es action start|stop|pause|resume`, **or**
     a tiny localhost HTTP listener on the LAN.
   - *iOS:* a localhost HTTP listener or a URL-scheme handler.
4. **State reporter** — subscribe to `statePublisher`; emit the current state to
   a place harqis-server can read (logcat tag, HTTP response, or a synced file)
   so the task can confirm `start` actually reached `.recording`.

What we deliberately **don't** build: any UI beyond a status line. No
account/login screens, no transcription UI — those template folders are dropped.

## 6. How harqis-server drives it

This is the `controller="sdk"` branch of the `plaud_calendar_recorder` task from
the parent spec (§8). Two transport options:

```bash
# Android broadcast over ADB (USB or `adb connect host:port` over LAN —
# repo already has device_tcpip / device_connect MCP tools)
adb -s $PLAUD_REC_ADB_SERIAL shell am broadcast \
    -a com.harqis.plaud.RECORD --es action start

# or HTTP over the LAN
curl -s http://<phone-ip>:<port>/record/start
```

Then read back state for verification:

```bash
adb -s $SERIAL shell "logcat -d -s HARQIS_PLAUD:I | tail -1"   # expect: state=recording
# or: curl http://<phone-ip>:<port>/state   → {"state":"recording","sessionId":...}
```

The task's idempotent reconcile loop (parent spec §8) compares desired
(calendar) vs actual (reported) state and only acts on a mismatch — so a missed
beat self-heals on the next tick. New config keys reuse the parent spec's block;
`PLAUD_REC_CONTROLLER=sdk` selects this path.

## 7. Bonus: this closes the device→cloud sync gap

A separate problem surfaced during the integration review (parent spec risk +
open question #5): **only factory-sample recordings are in the Plaud cloud
today** — the nightly ingest has nothing real to pull because the device→cloud
upload isn't happening.

The SDK companion app helps here independently of recording control:

- `SyncManager.startSync()` (auto-fired on stop, or callable on a schedule)
  pulls audio off the device over BLE/WiFi — no reliance on the stock app
  syncing.
- `exportAudio(sessionId:outputDir:format:channels:)` writes the audio to a
  local dir on the phone, which harqis-server can then pull via ADB and feed
  **straight into the existing `ingest_plaud` pipeline** — bypassing the Plaud
  cloud entirely if it stays unreliable. This effectively becomes a **third
  acquisition backend** behind the existing `PlaudBackend` interface
  (`apps/plaud/references/adapter.py`), alongside cloud and folder.
- Optionally, `TranscriptionManager` could transcribe via Plaud's own service
  (client API key) — but we already have Whisper, so this stays optional.

So Track B is worth doing even if calendar-triggering is deferred: it gives a
reliable acquisition path that doesn't depend on the unofficial `api.plaud.ai`
surface or the stock app's sync.

## 8. iOS vs Android decision

| | iOS companion | Android companion |
|---|---|---|
| Template | ✅ Complete reference app | ⚠️ `.aar` only, template "coming soon" |
| Headless trigger from harqis-server | ❌ No ADB; needs HTTP/URL-scheme + a Mac to build | ✅ ADB `am broadcast` — fits existing `device_*` tooling |
| Background BLE | Stricter iOS background limits | Foreground service is reliable |
| Build toolchain | Xcode 16 + Xcodegen (needs a Mac — we have the mini) | Gradle + `.aar` (cross-platform) |

**Recommendation: Android companion.** It's driven by the ADB tooling
harqis-work already has, runs a reliable foreground service, and the trigger is
a one-line `am broadcast`. Cost: we wire the `.aar` ourselves without a template
(more upfront work than copying the iOS sample). If that proves slow, the iOS
template + a localhost HTTP listener is the fallback (the Mac mini can build it).

## 9. Build & deploy

1. **Get partner access** at `dev.plaud.ai` → `PLAUD_CLIENT_ID`,
   `PLAUD_API_KEY`, and the backend call to mint `USER_ACCESS_TOKEN`. Use the
   free tier for prototyping.
2. **Android:** new Gradle module, add the `.aar` from `sdk/`, implement the
   `Managers/` shapes (Device/Recording/Sync) against the AAR API, add the
   `BroadcastReceiver` + foreground service + state logger. (iOS fallback:
   `cd plaud-template-app/ios`, set `PartnerConfig.xcconfig` creds + bundle-id
   prefix in `project.yml`, `xcodegen`, build to a device.)
3. **Provision the controller phone** (parent spec phase 1): install the app,
   pair to the Note Pro, keep awake/charged/in range, enable ADB over LAN.
4. **Wire `controller="sdk"`** in `plaud_calendar_recorder` and flip the config.

## 10. Risks & mitigations

- **Partner approval lead time** — start the `dev.plaud.ai` request early; ship
  Track A (ADB) meanwhile so the calendar loop isn't blocked on it.
- **Android template not published** — we integrate the `.aar` by hand against
  the documented API; the iOS template is the reference for the manager shapes.
- **OS kills the BLE link** — foreground service (Android) / background-BLE
  entitlement (iOS); auto-reconnect watchdog; state reporter alerts on
  disconnect (Discord/Telegram, already integrated).
- **SDK API drift between iOS names and the `.aar`** — confirm the Android
  method names against the AAR on first integration; keep the wrapper thin.
- **USER_ACCESS_TOKEN expiry** — mint/refresh it server-side (harqis-server
  already does token lifecycles for other apps) and hand it to the app on launch.

## 11. Open questions

1. **Android-by-hand vs iOS-from-template** for v1 of the companion?
2. **Partner tier** — does the free tier cover a single always-connected device
   + our usage, or do we need the paid tier from day one?
3. **Acquisition strategy** — if §7 works, do we make the SDK export the primary
   acquisition backend and demote the unofficial cloud API to a fallback?
4. **Token minting** — confirm the exact `USER_ACCESS_TOKEN` mint call and
   whether it can be fully server-side (no interactive step).
5. Still unresolved from the parent spec: **why are only factory samples in the
   cloud today** — does provisioning the SDK sync path make this moot?

## 12. Implementation walkthrough

This splits into **two codebases**: a small **Android app** built on Plaud's SDK
(lives *outside* this repo) and the **harqis-work workflow** that drives it. The
harqis side is mapped to files that already exist.

### Critical path & the one real blocker

**Partner access at `dev.plaud.ai`** is the gating item (lead time + it unlocks
the SDK token). Everything else builds in parallel, but nothing *runs* without it.

```
[Partner access]──┐
                  ├─▶ Android companion app ──┐
[Controller phone]┘                           ├─▶ wire + test ─▶ schedule
[harqis workflow task] ────────────────────────┘
```

> **Pragmatic recommendation:** stand up **Track A** (ADB UI-automation of the
> *stock* Plaud app — parent spec §6) FIRST. It needs no partner signup and proves
> the calendar→record loop end-to-end while the SDK access request is in flight.
> Then swap the controller from `adb-taps` to `sdk` — the harqis-side task (Phase
> 2) is identical for both tracks.

### Phase 0 — Prerequisites

1. **Request partner access** → `dev.plaud.ai`. You receive `PLAUD_CLIENT_ID` +
   `PLAUD_API_KEY` and the backend call to mint a `USER_ACCESS_TOKEN`
   (`initSDK`). Free tier covers prototyping.
2. **Dedicate an Android phone**: install the companion app (Phase 1), BLE-pair
   it to the Note Pro, keep it charged + awake (sleep disabled) + in BLE range.
3. **Make it reachable from harqis-server over ADB** — the repo already supports
   this: `apps/android_emulator/devices.py` → `enable_tcpip(serial)` then
   `connect_wireless("host:5555")` (the `device_tcpip` / `device_connect` MCP
   tools).

### Phase 1 — Android companion app (the bulk of the work)

A **separate Android Studio project** (Kotlin), not part of harqis-work. The iOS
template in `plaud-sdk-public/plaud-template-app/` is the reference for the
manager shapes; you re-implement them against the `.aar`.

**1.1 Project + SDK wiring**
- New Android project, min SDK per the AAR.
- Copy the Android `.aar` from the SDK repo's `sdk/` into `app/libs/`:
  ```gradle
  implementation files('libs/plaud-sdk.aar')
  ```
- Manifest permissions: `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT`,
  `FOREGROUND_SERVICE`, `INTERNET`, location (BLE scan on older Android).

**1.2 Mirror the three managers** (from the verified iOS source, §2):
- `DeviceManager` → `initSDK(userAccessToken)`, `startScan()`,
  `connectBleDevice()`, plus an **auto-reconnect watchdog**.
- `RecordingManager` → thin pass-through to the agent's
  `startRecord()/stopRecord()/pauseRecord()/resumeRecord()`, and subscribe to the
  **recording-state stream** (Android equivalent of `statePublisher`).
- `SyncManager` → `startSync()` / `exportAudio(...)` (optional — Phase 3).

**1.3 Keep BLE alive** — a **foreground service** holding the connection so the
OS doesn't kill it.

**1.4 The trigger surface** (the only "API" harqis-server needs) — a
`BroadcastReceiver`:

```kotlin
// Manifest: <receiver android:name=".RecordReceiver" android:exported="true">
//   <intent-filter><action android:name="com.harqis.plaud.RECORD"/></intent-filter>
class RecordReceiver : BroadcastReceiver() {
  override fun onReceive(ctx: Context, intent: Intent) {
    when (intent.getStringExtra("action")) {
      "start"  -> RecordingManager.startRecord()
      "stop"   -> RecordingManager.stopRecord()
      "pause"  -> RecordingManager.pauseRecord()
      "resume" -> RecordingManager.resumeRecord()
    }
  }
}
```

**1.5 State reporter** (so harqis can verify a toggle took) — emit a logcat line
on every state change:

```kotlin
Log.i("HARQIS_PLAUD", "state=recording sessionId=$id")   // or =idle / =paused
```

### Phase 2 — harqis-work workflow task (grounded in the repo)

The `controller="sdk"` task from the parent spec. Home:
`workflows/mobile/android/tasks/plaud_calendar_recorder.py` (next to the existing
android capture task). Scaffold with `/create-new-workflow`.

**2.1 Read the calendar** via `apps/google_apps/references/web/api/calendar.py`
(`get_google_calendar_events_today`); filter events whose title/desc contains the
tag (e.g. `#record`).

**2.2 Drive the phone over ADB** using the existing wrapper
`apps/android_emulator/devices.py` (`_adb(...)`):

```python
from apps.android_emulator import devices

def _send(serial, action):
    return devices._adb(["-s", serial, "shell", "am", "broadcast",
                         "-a", "com.harqis.plaud.RECORD", "--es", "action", action])

def _read_state(serial):
    r = devices._adb(["-s", serial, "shell", "logcat", "-d", "-s", "HARQIS_PLAUD:I"])
    # parse the last "state=..." line
```

**2.3 Idempotent reconcile loop** (the never-break-the-beat pattern from
`workflows/hfl/tasks/ingest_plaud.py`):

```python
@SPROUT.task()
@log_result()
def plaud_calendar_recorder(*, calendar_filter="#record", serial=None,
                            dry_run=False) -> dict:
    serial = serial or os.environ["PLAUD_REC_ADB_SERIAL"]
    desired = "recording" if _event_active_now(calendar_filter) else "idle"
    actual  = _read_state(serial)                 # from logcat
    if desired == actual:
        return {"action": "none", "state": actual}
    if dry_run:
        return {"action": f"would->{desired}", "state": actual}
    _send(serial, "start" if desired == "recording" else "stop")
    return {"action": desired, "verified": _read_state(serial) == desired}
```

Poll mode (run every N minutes, reconcile desired-vs-actual) beats
event-boundary scheduling — a missed beat self-heals on the next tick.

**2.4 Schedule** in `workflows/mobile/.../tasks_config.py`: a
`crontab(minute='*/5')` entry on a queue the controller-adjacent host consumes;
start with `dry_run=True`.

**2.5 Config** in `.env/apps.env`: `PLAUD_REC_ADB_SERIAL`, `PLAUD_REC_EVENT_TAG`,
`PLAUD_REC_MAX_SESSION_MIN`, `PLAUD_REC_QUIET_HOURS`.

### Phase 3 — Acquisition bonus (optional, high value)

Once `SyncManager.exportAudio` writes audio to a folder on the phone, add a
**third `PlaudBackend`** in `apps/plaud/references/adapter.py` (alongside cloud +
folder) that pulls those files via `adb pull` — so `ingest_plaud_activity`
ingests **straight from the device**, bypassing the unreliable
phone→cloud→`api.plaud.ai` path. This is the part that actually fixes "recordings
aren't reaching the server."

### Phase 4 — Test & roll out (maps to parent spec phases 2→5)

1. Companion app: `am broadcast … start` flips the device to recording (watch
   logcat).
2. harqis task in `dry_run`: confirm it resolves the right calendar events.
3. Flip live; verify a real event auto-records and the audio lands.
4. Guardrails (max-session auto-stop, quiet hours) + Discord/Telegram alert on a
   failed toggle (both already integrated).

### Realistic effort

- **Android app** — the real work (~days), since the Android template isn't
  published; integrate the `.aar` by hand using the iOS managers as the spec.
- **harqis task** — ~half a day; mostly reusing `devices._adb` + the calendar API
  + the `ingest_plaud` patterns.
- **Blocker** — partner access lead time (start it early; ship Track A meanwhile).
