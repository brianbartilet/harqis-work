# PLAUD Embedded companion for HARQIS

Status: experimental, personal-device beta integration. The Android APK builds
successfully, but end-to-end BLE control still requires PLAUD developer
credentials and a supported physical recorder.

## What this adds

HARQIS previously interacted with PLAUD only after a recording existed:

| Surface | Existing behavior | New behavior |
|---|---|---|
| `apps/plaud` adapter | Read recordings and transcripts from the unofficial cloud API or an export folder | Unchanged |
| HARQIS MCP | List recordings, fetch transcripts, report acquisition status | Adds companion status and start/stop/pause/resume/connect |
| HFL workflow | Ingest completed PLAUD recordings daily | Adds a two-minute Google Calendar recording reconciler |
| Android | None | Dedicated BLE companion built around PLAUD's public beta AAR |
| Location | HFL location history ingest only | On-device geofence can request recording on entry and release it on exit |

The control path is:

```text
Google Calendar
      |
      v
Celery Beat -> HFL reconciler -> authenticated ADB broadcast
                                      |
                                      v
                         HARQIS PLAUD Android companion
                                      |
                         PLAUD Embedded SDK over BLE
                                      |
                                      v
                            Note Pro / NotePin S

Android geofence ----------------------^
```

Calendar and location are independent recording claims. The companion records
while either claim is active. Releasing the calendar claim cannot stop a
recording still required by the location claim, and vice versa. A manually
started recording is not stopped merely because an inactive trigger is
reconciled.

## Feasibility and beta constraints

Both requested triggers are technically possible with the Embedded SDK:

- **Calendar on/off:** yes. HARQIS reads explicitly tagged events and sends
  authenticated commands to the companion phone. It starts while at least one
  eligible event is active and releases the calendar claim after the last
  overlapping event ends.
- **Location trigger:** yes. Google Play Services geofencing runs on the
  companion phone; BLE control remains local to the phone and recorder.

Important limitations as of 2026-07-31:

1. The [PLAUD Android SDK documentation](https://docs.plaud.ai/plaud-embedded/android-sdk)
   still says Android is “coming very soon.” However, PLAUD's
   [public SDK repository](https://github.com/Plaud-AI/plaud-sdk-public)
   contains `sdk/android/plaud-sdk.aar`. This project pins that binary to
   commit `359efc913672a73de8edde0ab088e5684e2be611` and verifies SHA-256
   `7900F462744DB7EFC6A36C549925E2E3B5072818F3E793AE4AA90BFFD5B67F21`.
   The AAR is compiled but not committed.
2. There is no official Android starter app or published Android API reference
   yet. One internal AAR accessor is therefore isolated behind reflection in
   `PlaudSdkBridge.kt`. Re-test whenever the AAR changes.
3. The current Embedded overview names **PLAUD Note Pro** and
   **PLAUD NotePin S**. Do not assume older Note or NotePin models work.
4. A recorder can be bound to only one partner app. Binding it to this companion
   may require unbinding it from the standard PLAUD app and may change the normal
   PLAUD experience.
5. The [Embedded quickstart](https://docs.plaud.ai/plaud-embedded/quickstart)
   currently marks US and Japan endpoints available; Europe and Singapore are
   “coming soon.” A Singapore PLAUD account may need a US/Japan developer
   application or PLAUD approval.
6. The beta AAR initializer currently accepts app credentials and an SDK token.
   This prototype stores them in private Android `SharedPreferences`; it is
   suitable for a dedicated personal controller, not a distributed production
   app. A production version must mint short-lived user tokens on a backend and
   must not ship a client secret.
7. A physical Android phone with BLE is required. An emulator can compile and
   render the app but cannot validate a real PLAUD BLE session.

## Source layout

```text
apps/plaud/
├── companion/android/                 # Native Kotlin companion app
│   ├── app/src/main/...               # UI, service, BLE bridge, geofence
│   ├── scripts/fetch-plaud-sdk.ps1    # Pinned AAR download + checksum
│   └── gradlew(.bat)                  # Reproducible Gradle 8.9 wrapper
├── references/companion.py            # Authenticated ADB controller
└── mcp.py                              # HARQIS MCP control tools

workflows/hfl/tasks/plaud_companion.py  # Calendar reconciler
```

## Prerequisites

### PLAUD

- A PLAUD Developer Portal account and Embedded application.
- Client/app key, client secret, and the SDK partner/user token expected by the
  pinned beta AAR. Confirm the token type with PLAUD because the Android
  reference is not yet published.
- A device serial and device token/stable user identifier for a supported
  recorder.
- A supported region and permission to bind the recorder to the partner app.

Use the [PLAUD Developer Portal](https://portal.plaud.ai/) and follow the
Embedded quickstart. Do not reuse the unofficial `PLAUD_TOKEN` used by the
existing cloud acquisition adapter unless PLAUD confirms it is the token
expected by the Embedded SDK; these are separate integrations.

### Build workstation

- JDK 17.
- Android SDK Platform 34 and Build Tools 34.0.0.
- PowerShell 7 or Windows PowerShell for the pinned AAR fetch script.
- Android Platform Tools (`adb`) for installation and HARQIS control.
- Internet access for the initial Gradle and AAR downloads.

Android Studio users can install Platform 34 and Build Tools 34.0.0 from SDK
Manager. Command-line Windows setup is:

```powershell
$sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
& "$sdk\cmdline-tools\latest\bin\sdkmanager.bat" `
  "platforms;android-34" "build-tools;34.0.0" "platform-tools"
$env:ANDROID_HOME = $sdk
```

## Compile the Android app

From the repository root:

```powershell
Set-Location apps/plaud/companion/android
.\scripts\fetch-plaud-sdk.ps1
$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
.\gradlew.bat :app:assembleDebug
```

The debug APK is written to:

```text
apps/plaud/companion/android/app/build/outputs/apk/debug/app-debug.apk
```

The fetch script refuses a modified AAR and deletes a checksum-mismatched
download. To test a newer official SDK, update the pinned commit and checksum
deliberately, inspect the AAR API changes, compile, and exercise a real device
before committing the pin.

For a release build, create a normal Android signing configuration outside the
repository and run `.\gradlew.bat :app:assembleRelease`. Never commit a
keystore, passwords, PLAUD credentials, or a built APK.

## Install on the companion phone

1. On the Android phone, enable Developer options and USB debugging.
2. Connect USB, accept the computer's RSA prompt, and verify:

   ```powershell
   adb devices -l
   ```

3. Install or upgrade:

   ```powershell
   adb install -r apps/plaud/companion/android/app/build/outputs/apk/debug/app-debug.apk
   ```

4. Launch the setup screen:

   ```powershell
   adb shell am start -n com.harqis.plaudcompanion/.MainActivity
   ```

5. In Android Settings, set the app's battery usage to **Unrestricted**. Grant
   Nearby devices, notifications, precise location, and—if using a
   geofence—Location **Allow all the time**. Android requires the background
   location choice to be granted separately in Settings.

The app starts a visible foreground service and restores it after boot once SDK
configuration exists. Keep the persistent notification enabled; it is the
operating-system signal that BLE control is allowed to continue in the
background.

## Configure and bind the companion

Open **HARQIS PLAUD** and enter:

| Field | Value |
|---|---|
| ADB control token | A new high-entropy random secret shared only with HARQIS |
| PLAUD SDK partner/user token | Token required by the pinned Embedded beta AAR |
| App key / client ID | Embedded application identifier |
| App secret | Embedded beta credential; personal dedicated-phone use only |
| Custom domain | Regional hostname, without path; default `platform-us.plaud.ai` |
| Device serial | PLAUD recorder serial |
| Device token / stable user ID | Device-binding token expected by the SDK |
| BLE name or MAC | Optional scan filter; strongly recommended near multiple devices |

Generate the ADB control token locally, for example:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToHexString($bytes)
```

Save the form and tap **Connect device**. Keep the phone near the recorder,
Bluetooth enabled, and the recorder awake. Confirm the UI reads `BLE LINKED`,
then test **Start recording** and **Stop recording** before enabling automation.

The exported receiver requires Android's privileged `DUMP` permission (held by
the ADB shell), is addressed by explicit component, and rejects blank or
mismatched control tokens. Ordinary third-party apps therefore cannot call it.
Treat any workstation authorized for phone debugging as capable of controlling
the recorder.

## Verify ADB control

Replace the serial and token; do not paste real values into shell history on a
shared machine.

```powershell
$serial = "PHONE_ADB_SERIAL"
$token = "HIGH_ENTROPY_CONTROL_TOKEN"
$component = "com.harqis.plaudcompanion/com.harqis.plaudcompanion.control.RecordCommandReceiver"
$action = "com.harqis.plaudcompanion.RECORD_COMMAND"

adb -s $serial shell am broadcast -n $component -a $action `
  --es action status --es token $token
```

The ordered-broadcast result contains JSON like:

```json
{
  "success": true,
  "state": "idle",
  "connected": true,
  "active_triggers": []
}
```

Valid actions are `connect`, `status`, `start`, `stop`, `pause`, and `resume`.
`start` and `stop` acquire/release the `calendar` claim. HARQIS polls status
after a command; process exit code zero alone is not considered confirmation.

For wireless ADB on a trusted private network:

```powershell
adb pair PHONE_IP:PAIR_PORT
adb connect PHONE_IP:DEBUG_PORT
adb devices -l
```

Use the exact `IP:DEBUG_PORT` value shown by `adb devices` as
`PLAUD_COMPANION_ADB_SERIAL`. Wireless debugging pairing can expire after a
phone reboot or network change. Do not expose an ADB port to the public
internet; use USB, a trusted LAN, Tailscale, or an attached HARQIS worker.

## Enable Google Calendar recording

The existing Google Calendar integration and credentials must already work on
the Beat/HFL worker. Add these values to the worker's git-ignored
`.env/apps.env`:

```env
PLAUD_COMPANION_ENABLED=true
PLAUD_COMPANION_DRY_RUN=true
PLAUD_COMPANION_ADB_SERIAL=PHONE_ADB_SERIAL_OR_IP_PORT
PLAUD_COMPANION_TOKEN=HIGH_ENTROPY_CONTROL_TOKEN
PLAUD_COMPANION_CALENDAR_ID=primary
PLAUD_COMPANION_EVENT_TAG=#record
```

Restart Beat and the HFL worker after changing environment variables. The
registered task runs every two minutes:

```text
workflows.hfl.tasks.plaud_companion.reconcile_plaud_companion
```

Create a timed calendar event whose title or description contains `#record`.
All-day, cancelled, declined, untagged, malformed, and already-ended events are
ignored. Overlapping tagged events form one continuous calendar claim.

Roll out safely:

1. Leave `PLAUD_COMPANION_DRY_RUN=true`.
2. Start a tagged test event and inspect the task result. It should report
   `desired_state=recording`, `action=start`, and `dry_run=true`.
3. Confirm status through MCP or the ADB command above.
4. Change `PLAUD_COMPANION_DRY_RUN=false`, restart worker/Beat, and repeat with
   a short test event.
5. Confirm the recorder starts within the scheduler interval and releases the
   calendar claim after the event. Expect up to about two minutes of boundary
   delay.

The task is fail-closed: when `PLAUD_COMPANION_ENABLED` is not true, or the ADB
serial/token is missing, it performs no Calendar or recorder call.

## Enable the location trigger

In the Android setup screen:

1. Grant precise location and **Allow all the time** in Android Settings.
2. Enter decimal latitude and longitude, such as `1.3521` and `103.8198`.
3. Enter a radius. Values below 100 metres are raised to 100 metres because
   smaller geofences are unreliable on typical Android devices.
4. Enable **Record inside geofence**, save, and wait for “Location trigger
   armed.”

Entering the region acquires the `location` claim; exiting releases it. Android
geofences are intentionally power-efficient, so transitions are not
instantaneous and can be delayed by device idle, weak location signals, or
vendor battery management. Test outdoors or with a realistically separated
route rather than walking a few metres around a desk.

The current trigger means “record while inside this zone.” Useful variants for
later work include:

- record on arrival at a customer site, clinic, studio, or vehicle;
- invert the policy to record after departure for a voice debrief;
- use a dwell transition to require several minutes inside a location;
- maintain several named zones with per-zone calendar tags;
- require both calendar and location for sensitive environments instead of the
  current safer availability-oriented OR policy.

## HARQIS MCP tools

This repository's Python MCP server now exposes:

| Tool | Purpose |
|---|---|
| `plaud_companion_status` | Read BLE, recording, battery, and trigger-claim state |
| `control_plaud_recording` | `start`, `stop`, `pause`, `resume`, `connect`, or `status` |

Example prompts:

- “Is my PLAUD companion connected and recording?”
- “Start PLAUD recording.”
- “Release the calendar PLAUD recording trigger.”

These tools use the existing HARQIS MCP runtime and require no Node.js.

PLAUD's official MCP is also useful, but for a different layer. It offers
OAuth-backed `list_files`, `get_file`, `get_note`, and `get_transcript` tools;
it does **not** expose hardware recording controls. Its local installer requires
Node.js 20+ and `npx -y @plaud-ai/mcp@latest install`. Because HARQIS already has
Python recording/transcript tools and the user prefers not to add npm, this
solution does not install or wrap it. Reconsider it when:

- the official MCP becomes remotely hostable without a Node sidecar;
- OAuth reliability is preferred over the existing unofficial cloud adapter;
- its official file/note schema is worth replacing the current acquisition
  backend.

If adopted, run it as an optional isolated sidecar pinned to an explicit
version, not `@latest` in production, and bridge only its read tools into
HARQIS. Keep device start/stop in the Android companion.

## Troubleshooting

| Symptom | Checks and fix |
|---|---|
| `plaud-sdk.aar` missing | Run `.\scripts\fetch-plaud-sdk.ps1` from the Android project. The AAR is intentionally git-ignored. |
| AAR checksum mismatch | Do not bypass it. Confirm the official repository and deliberately review/update the commit and checksum. |
| Gradle cannot find Android SDK | Set `ANDROID_HOME`; install Platform 34 and Build Tools 34.0.0. |
| Java/Gradle version failure | Use JDK 17 and the checked-in Gradle 8.9 wrapper. |
| APK compiles but no device appears | Use a supported physical Note Pro/NotePin S, enable Bluetooth/Nearby devices, wake the recorder, set a BLE name/MAC filter, and move away from other PLAUD devices. |
| SDK initialization fails | Re-check region hostname, app key/secret, SDK token type, and PLAUD beta entitlement. The standard cloud `PLAUD_TOKEN` is not automatically interchangeable. |
| Device already bound | Unbind it from the existing app/account only after understanding the data and UX impact; each recorder can bind to one partner app. |
| Singapore endpoint fails | PLAUD currently marks Singapore Embedded service “coming soon.” Use a provisioned available region or contact PLAUD. |
| `adb devices` says `unauthorized` | Unlock the phone, accept the RSA prompt, then `adb kill-server` / `adb start-server` if needed. |
| No device at the configured serial | Copy the exact value from `adb devices`; wireless ADB usually includes `:port`. Re-pair after reboot/network changes. |
| Broadcast says `unauthorized` | The app's ADB control token and `PLAUD_COMPANION_TOKEN` differ, or the app token is blank. |
| Broadcast returns no JSON | Use the explicit component/action shown above and ensure the installed package is `com.harqis.plaudcompanion`. |
| Command accepted but state never changes | Inspect BLE link, recorder battery, SDK credentials, and `adb logcat -s HARQIS_PLAUD:I`. HARQIS correctly treats this as unverified failure. |
| Calendar task always skips | Set `PLAUD_COMPANION_ENABLED=true`, restart worker/Beat, verify HFL workflow registration, and confirm serial/token exist in that process. |
| Calendar says no active events | Use a timed event, include the exact case-insensitive tag in title/description, accept the invitation, and check event/calendar timezone. |
| Calendar dry run never controls | Set `PLAUD_COMPANION_DRY_RUN=false` only after inspecting a correct dry-run result, then restart the worker. |
| Recorder stays active after calendar event | Check `active_triggers`; a location claim intentionally keeps it recording. If `calendar` remains, inspect task results and Calendar access. |
| Geofence never fires | Grant Location “Allow all the time,” enable precise location and Google Play Services, disable battery optimization, use a radius ≥100 m, then save again. |
| Geofence stops/restarts around the boundary | Increase the radius and avoid placing the boundary where the phone normally rests. GPS/Wi-Fi position can oscillate. |
| Service dies in background | Keep its notification enabled, set battery use to Unrestricted, allow autostart on vendor Android builds, and reopen the app once. |
| App rebooted while a claim was active | The boot receiver reconnects. Calendar repairs its claim within two minutes; save the geofence again if Google Play Services did not restore it. |

Useful diagnostics:

```powershell
adb -s PHONE_SERIAL logcat -s HARQIS_PLAUD:I
adb -s PHONE_SERIAL shell dumpsys package com.harqis.plaudcompanion
adb -s PHONE_SERIAL shell dumpsys location
```

On the HARQIS worker, call `plaud_companion_status` before testing the scheduled
task. Never print or attach `.env/apps.env`, the Android preference database,
PLAUD secrets, device tokens, or the ADB control token to an issue.

## Consent, privacy, and operational safety

- Record only where lawful and with the required participant notice or consent.
- Use the explicit `#record` opt-in tag; do not make every calendar event record
  by default.
- Keep dry-run enabled during rollout.
- Use a dedicated Android controller, a high-entropy control token, and a
  trusted ADB transport.
- The device retains audio locally after stop. Existing PLAUD/HFL acquisition
  and retention policies still apply after recording.
- The companion does not upload or transcribe audio. That remains a separate
  step through the existing adapter/HFL pipeline or PLAUD Embedded upload and
  transcription APIs.

## Validation performed

- Pinned official AAR checksum verified.
- `:app:assembleDebug` completed with JDK 17, Android Platform/Build Tools 34,
  Gradle 8.9, and the beta AAR.
- HARQIS ADB parsing, fail-closed configuration, authenticated explicit
  commands, trigger arbitration, and calendar event filtering are covered by
  unit tests.

Physical BLE connection, binding, geofence transitions, and live calendar
control cannot be certified without the user's supported PLAUD recorder,
developer application, token, and companion phone. Treat the first device test
as a beta acceptance test and retain the standard PLAUD app path until it
passes.
