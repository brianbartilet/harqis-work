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
