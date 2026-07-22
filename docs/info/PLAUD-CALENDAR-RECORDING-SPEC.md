# PLAUD Calendar-Triggered Recording — Design Spec

**Related:** [apps/plaud/README.md](../../apps/plaud/README.md), [workflows/hfl/tasks/ingest_plaud.py](../../workflows/hfl/tasks/ingest_plaud.py)
**Status:** Proposed (spec only — no implementation yet)
**Date:** 2026-06-22

---

## Table of Contents

1. [Goal](#1-goal)
2. [Key Constraint (read this first)](#2-key-constraint-read-this-first)
3. [Where this fits in the existing pipeline](#3-where-this-fits-in-the-existing-pipeline)
4. [Feasibility summary](#4-feasibility-summary)
   - [4.1 Evaluated: official Plaud MCP CLI (retrieval only)](#41-evaluated-official-plaud-mcp-cli-retrieval-only)
5. [Architecture](#5-architecture)
6. [Track A — ADB UI-automation MVP](#6-track-a--adb-ui-automation-mvp)
7. [Track B — Official Embedded SDK (durable)](#7-track-b--official-embedded-sdk-durable)
8. [Workflow design](#8-workflow-design)
9. [Configuration](#9-configuration)
10. [Phased rollout](#10-phased-rollout)
11. [Risks & mitigations](#11-risks--mitigations)
12. [Open questions](#12-open-questions)

---

## 1. Goal

Start and stop a **PLAUD Note Pro** voice recorder hands-free, on a schedule
driven by the calendar — e.g. auto-record every event tagged `#record` (or all
events in a chosen calendar), without anyone pressing the physical button. The
captured audio then flows through the **existing** Plaud → HFL pipeline
(`workflows/hfl/tasks/ingest_plaud.py`) unchanged: cloud pull → Whisper →
Haiku distil → HFL corpus + ES.

This spec covers only the **trigger** (turning the device on/off on a schedule).
Acquisition, transcription, distillation, and archival already exist and are
verified working.

## 2. Key Constraint (read this first)

**There is no headless control surface for the device.** Confirmed by research
(2026-06-22):

- The unofficial cloud API (`api.plaud.ai`) is **sync/retrieval only** — there
  is no "start recording" endpoint. (Our own `apps/plaud/references/adapter.py`
  documents this.)
- **Zapier / IFTTT are trigger-only** — they fire *after* a transcript/summary
  exists; they cannot start a recording.
- The Android **emulator has no BLE radio**, and PLAUD's SDK frameworks are
  arm64 real-device only — so an emulator can never reach the device.

What *is* true and useful:

- **Remote start/stop is firmware-supported.** PLAUD's own app can start a
  recording over BLE ("Record through the Plaud App"), and PLAUD's official
  Embedded SDK exposes `startRecord()` / `stopRecord()` / `pauseRecord()` /
  `resumeRecord()` over BLE.

> **Therefore every viable control path requires one always-on phone with a live
> Bluetooth radio, paired to the recorder, acting as the controller.** This is
> the irreducible piece of new hardware/infra this feature needs.

## 3. Where this fits in the existing pipeline

```
                    NEW (this spec)                      EXISTING (unchanged)
   ┌──────────────────────────────────────┐   ┌─────────────────────────────────┐
   │ Google Calendar (apps/google)        │   │                                 │
   │   event @ HH:MM tagged #record       │   │                                 │
   │            │                         │   │                                 │
   │            ▼                         │   │                                 │
   │ harqis-server (Celery beat)          │   │                                 │
   │   plaud_calendar_recorder task       │   │                                 │
   │            │ start / stop command    │   │                                 │
   │            ▼ (ADB or SDK push)       │   │                                 │
   │ Controller phone (BLE-paired) ───────┼───┼─▶ Plaud device records          │
   └──────────────────────────────────────┘   │        │ BLE pull + upload      │
                                               │        ▼                        │
                                               │   Plaud cloud (api.plaud.ai)    │
                                               │        │ nightly 23:15          │
                                               │        ▼                        │
                                               │   ingest_plaud_activity →       │
                                               │   Whisper → Haiku → HFL+ES      │
                                               └─────────────────────────────────┘
```

The new component is a Celery task that reads the calendar and pokes the
controller phone at event boundaries. Everything downstream of "device records"
already works.

## 4. Feasibility summary

| Approach | Verdict | Notes |
|---|---|---|
| Official Embedded SDK on a paired phone | ✅ Durable, sanctioned | `startRecord()/stopRecord()`; B2B partner signup, free prototyping tier; must build a small app |
| Real phone + Plaud app + ADB UI automation | ⚠️ Fast MVP | UI-coordinate fragile; breaks on app updates; no signup needed |
| BLE GATT reverse-engineering (Pi + `bleak`) | ⚠️ High effort | No public protocol; must self-sniff; fragile |
| Zapier / IFTTT / cloud API | ❌ Impossible | Trigger/retrieval only |
| Official Plaud MCP CLI (`@plaud-ai/mcp`) | ❌ Impossible (for trigger) | OAuth, no signup, but **read-only** — no `startRecord`. Useful for *acquisition*, not control — see [§4.1](#41-evaluated-official-plaud-mcp-cli-retrieval-only) |
| Android emulator + ADB | ❌ Impossible | No BLE radio in emulator |
| Servo/solenoid long-press rig | ⚠️ Last resort | Phone-free but open-loop; timed long-press (start 1 vibration, stop 2) |
| Native scheduled recording in app | ❌ Not available | Note Pro hardware has no built-in schedule; Desktop "Automatic Recording" records the *computer*, not the device |

**Recommended:** ship **Track A (ADB)** as the MVP to prove the calendar→record
loop end-to-end this week, then migrate to **Track B (SDK)** for durability once
the value is confirmed and partner access is granted.

### 4.1 Evaluated: official Plaud MCP CLI (retrieval only)

PLAUD ships an official, OAuth-authenticated MCP server
([`@plaud-ai/mcp`](https://docs.plaud.ai/plaud-mcp-cli/mcp), `npx -y
@plaud-ai/mcp@latest install`; or the remote `https://mcp.plaud.ai/mcp`). It was
evaluated as a possible implementation surface for this feature (2026-06-23)
because, unlike the SDK partner program, it needs **no signup** — just a browser
OAuth login with an ordinary Plaud account.

**Verdict: it does not unblock the recording trigger.** Its entire tool surface
is read-only — `list_files`, `get_file` (with a 24h `presigned_url`),
`get_transcript`, `get_note`, `get_current_user`, `login`/`logout`. There is
**no `startRecord`/`stopRecord`**, so it shares the exact ceiling of the
unofficial cloud API and Zapier (§2): it talks to the Plaud *cloud*, not the
device, and cannot tell the recorder to begin. The always-on BLE controller
phone (Track A/B) remains the irreducible requirement for the trigger.

It also does **not** resolve open question #5 (only factory samples in the
cloud). The MCP reads the same cloud the unofficial API does — if the device
isn't uploading, the MCP sees nothing new either. Only the SDK's `SyncManager`
([companion spec §7](PLAUD-SDK-COMPANION-APP-SPEC.md#7-bonus-this-closes-the-devicecloud-sync-gap))
or the stock app actually syncing closes that gap.

**Where it *is* worth adopting (acquisition, not control):** it is the official
OAuth equivalent of the **unofficial** `api.plaud.ai` surface our
`PlaudCloudBackend` currently reverse-engineers
([apps/plaud/references/adapter.py](../../apps/plaud/references/adapter.py)) —
`list_files` ≈ `/file/simple/web`, `get_file.presigned_url` ≈
`/file/temp-url/{id}`, and `get_transcript`/`get_note` ≈ Plaud's own
transcript/summary. It is therefore a strong candidate as a **sanctioned
acquisition backend** behind the existing `PlaudBackend` interface, more durable
than the scraped surface, and relevant to companion-spec open question #3
(acquisition strategy). Caveat: it is an *MCP server* (stdio/npx or remote
HTTP), not a REST API the Python adapter can call with `requests` — wiring it
into `ingest_plaud` means driving it as an MCP client or shelling the CLI, more
plumbing than the current cloud backend. **Recommend tracking this as a separate
read-side spike, independent of the recording trigger.**

## 5. Architecture

Three actors:

1. **harqis-server (orchestrator)** — runs the Celery beat schedule and the new
   `plaud_calendar_recorder` task. Reads Google Calendar via the existing
   `apps/google` integration.
2. **Controller phone** — a dedicated Android device, always on, awake, charged,
   BLE-paired to the Note Pro, reachable from harqis-server over ADB (USB or
   `adb tcpip` over LAN — the repo already has `device_tcpip` / `device_connect`
   MCP tools). Runs either the stock Plaud app (Track A) or a tiny custom app
   built on the SDK (Track B).
3. **Plaud Note Pro** — the recorder, within BLE range of the controller phone.

Trigger model (two options, choose in config):

- **Event-boundary (preferred):** for each calendar event matching the filter,
  schedule a `start` at `event.start` and a `stop` at `event.end`.
- **Poll:** the task runs every N minutes, checks "is an eligible event active
  right now?", and toggles recording to match (idempotent — only acts on state
  change). More robust to missed beats; simpler to reason about.

## 6. Track A — ADB UI-automation MVP

Drive the **stock Plaud Android app** over ADB from harqis-server.

- **Reuse existing repo tooling:** `apps/android` already wraps ADB (see the
  `device_*` / `android_activity` MCP tools and `workflows/mobile/android`).
- **Start recording:** bring the Plaud app to foreground (`adb shell monkey -p
  <plaud.pkg> 1` or an explicit `am start`), then tap the record control. Two
  ways to locate the control, in order of robustness:
  1. `uiautomator dump` → parse the XML → tap the record button's bounds by
     resource-id/content-desc (survives minor layout shifts).
  2. Fixed `input tap X Y` fallback (fast but coordinate-fragile).
- **Stop recording:** same, tapping the stop control.
- **Verification:** after a start, re-dump the UI and assert the "recording"
  state (timer visible / stop button present); log + alert (Discord/Telegram —
  both already integrated) if the expected state isn't reached.

**Pros:** no partner signup, uses radios + tooling we already have, working
loop in days. **Cons:** brittle to Plaud app updates; phone must stay unlocked
and on the right screen; no formal API contract.

## 7. Track B — Official Embedded SDK (durable)

> **Detailed design:** see the companion spec
> [PLAUD-SDK-COMPANION-APP-SPEC.md](PLAUD-SDK-COMPANION-APP-SPEC.md) — component
> map, verified API surface, app design, and how it also closes the device→cloud
> sync gap. Recording control (`startRecord()`/`stopRecord()`) is **verified
> present** in the SDK (`RecordingManager.swift` passes through to
> `PlaudDeviceAgent.shared`).

Build a minimal companion app on PLAUD's Embedded SDK
(`github.com/Plaud-AI/plaud-sdk`, Android `.aar`):

- App connects/pairs to the Note Pro over BLE on launch, auto-reconnects, and
  exposes a thin local trigger — e.g. an Android broadcast `Intent` or a tiny
  on-device HTTP listener — that calls `PlaudDeviceAgent.startRecord()` /
  `.stopRecord()`.
- harqis-server fires the trigger via ADB (`am broadcast …`) or an HTTP call
  over the LAN.
- **Access:** request B2B partner access at `dev.plaud.ai` (Client ID/Secret +
  per-user access token via `POST /open/partner/users/access-token`); free tier
  covers prototyping.

**Pros:** sanctioned, stable contract, survives app updates, exposes pause/resume
and connection state. **Cons:** partner signup lead time; requires building +
maintaining a small Android app; still needs the always-on paired phone.

## 8. Workflow design

New task: `workflows/<area>/tasks/plaud_calendar_recorder.py` (area TBD —
likely a new `workflows/mobile` task or a small `workflows/plaud` package),
scheduled on `harqis-server` (the box that already runs `ingest_plaud_activity`
and the Plaud archive).

```python
@SPROUT.task()
@log_result()
def plaud_calendar_recorder(*, calendar_filter="#record", mode="poll",
                            controller="adb", dry_run=False) -> dict:
    """Toggle Plaud recording to match the active calendar event.

    mode="poll": check the current minute against eligible events; start when
    an event begins, stop when it ends. Idempotent — acts only on state change
    (tracked in a small state file / ES doc so a missed beat self-heals).
    controller="adb"  -> Track A (UI automation of the stock app)
    controller="sdk"  -> Track B (broadcast/HTTP into the companion app)
    """
```

Design rules (mirroring the existing HFL ingest tasks):

- **Never break the beat:** every external failure (calendar, ADB, BLE) is
  caught, logged, and surfaced in the result dict — never raises.
- **Idempotent state machine:** persist last-known recording state; on each
  tick reconcile actual vs. desired. A missed start/stop self-corrects next tick.
- **Dry-run mode:** resolve the calendar + intended action and log it without
  touching the device — for safe scheduling validation.
- **Guardrails:** max session length (auto-stop after N hours so a stuck
  "recording" can't run the battery flat), and a quiet-hours window.
- **Consent:** recording people is legally sensitive. The task must respect an
  allow-list of calendars/tags and default to off.

## 9. Configuration

New env (in `.env/apps.env`, resolved per-machine like the rest):

```env
PLAUD_REC_CALENDAR_ID=        # which Google Calendar to watch (default: primary)
PLAUD_REC_EVENT_TAG=#record   # only events whose title/desc contains this tag
PLAUD_REC_CONTROLLER=adb      # adb | sdk
PLAUD_REC_ADB_SERIAL=         # controller phone's adb serial (USB or host:port)
PLAUD_REC_PACKAGE=            # Plaud app package id (Track A)
PLAUD_REC_MAX_SESSION_MIN=180 # auto-stop guardrail
PLAUD_REC_QUIET_HOURS=        # e.g. "22:00-07:00" — never auto-record in window
```

Beat schedule entry alongside `ingest_plaud_activity` in
`workflows/hfl/tasks_config.py` (or the new area's `tasks_config.py`), on the
`hfl`/`host` queue so it runs only on harqis-server.

## 10. Phased rollout

| Phase | Deliverable | Exit criteria |
|---|---|---|
| 0 | This spec approved | Direction + track chosen |
| 1 | Controller phone provisioned | Phone BLE-paired to Note Pro, reachable via ADB from harqis-server, stays awake/charged |
| 2 | Track A task (poll mode, dry-run) | Calendar filter resolves correct events; intended start/stop logged |
| 3 | Track A live + verification | Real start/stop confirmed; audio reaches Plaud cloud and flows through nightly ingest |
| 4 | Guardrails + alerting | Max-session auto-stop, quiet hours, Discord/Telegram alert on failed toggle |
| 5 | (optional) Track B migration | Companion SDK app; switch `controller=sdk`; retire UI taps |

## 11. Risks & mitigations

- **Plaud app UI changes (Track A):** prefer `uiautomator` resource-id lookup
  over fixed coordinates; alert on verification failure; Track B removes this risk.
- **Phone sleeps / unpairs / out of range:** keep it plugged in, disable sleep,
  pin it physically near the recorder; verification tick catches silent failure.
- **Device→cloud upload lag:** recordings appear in the cloud only after the
  phone syncs them; the nightly ingest already tolerates this (window-based).
  *(Note: as of 2026-06-22 only factory sample recordings are in the cloud —
  confirm real recordings actually upload before relying on the loop.)*
- **Battery drain:** max-session guardrail + don't auto-record overlapping/all-day
  events.
- **Privacy/legal:** opt-in allow-list only; default off; consider a spoken/visible
  recording notice for in-person events.

## 12. Open questions

1. **Track choice for v1** — ADB MVP first (recommended) or wait for SDK partner access?
2. **Controller phone** — is a spare Android device available to dedicate, kept near where recordings happen?
3. **Trigger granularity** — all events on a calendar, or only `#record`-tagged? Per-calendar or per-event?
4. **Where the recorder physically lives** — does the controller phone stay in BLE range of it during target events (desk vs. mobile)?
5. **Confirm the upstream sync gap** — why are only factory samples in the Plaud cloud today? This must be resolved for the loop to deliver value.
