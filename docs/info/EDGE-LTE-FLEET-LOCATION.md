# LTE Fleet & Location — GPS-HAT resolver + ESP32-over-LTE OwnTracks client

**Related:** [EDGE-TAILSCALE-NODE.md](EDGE-TAILSCALE-NODE.md) · [EDGE-SENSOR-TELEMETRY.md](EDGE-SENSOR-TELEMETRY.md)
**Date:** 2026-05-26

---

## Table of Contents

1. [Overview](#1-overview)
2. [Part A — GPS-serial resolver in the location broadcast](#2-part-a--gps-serial-resolver-in-the-location-broadcast)
3. [Part B — ESP32-over-LTE OwnTracks client](#3-part-b--esp32-over-lte-owntracks-client)
4. [How both feed the location timeline](#4-how-both-feed-the-location-timeline)
5. [Configuration](#5-configuration)
6. [Activation (opt-in)](#6-activation-opt-in)
7. [Use cases solved](#7-use-cases-solved)

---

## 1. Overview

Two complementary ways to put a *moving* device on the map, both feeding existing
harqis-work location plumbing:

- **Part A** adds a **GPS-HAT (serial/NMEA) resolver** to the cluster-wide
  `broadcast_report_location` task. A Raspberry Pi fleet node with a GPS HAT now
  reports a precise live fix to the `harqis-worker-locations` index — no
  downstream changes.
- **Part B** ships an **ESP32-over-LTE** firmware that emulates the OwnTracks
  app's HTTP payload, publishing fixes to an OwnTracks Recorder over cellular.
  `apps/own_tracks` then reads them back like any phone tracker.

Both are **opt-in**: Part A activates only where a GPS port is configured; Part B
is device-side firmware that touches no server schedule.

## 2. Part A — GPS-serial resolver in the location broadcast

`broadcast_report_location` already cascades through resolvers and returns the
first valid fix. This PR inserts a **fourth** resolver, `_resolve_via_gps_serial()`,
right after the operator-pinned env coordinate:

```
env  →  gps_serial  →  ip_geo  →  owntracks   →  unavailable
 │          │            │            │
 │          │            │            └─ remote phone fix (existing)
 │          │            └─ coarse city-level fallback (existing)
 │          └─ NEW: precise live NMEA fix from a serial GPS HAT
 └─ static operator override (existing)
```

Key properties:

- **Opt-in / zero-impact when absent.** Gated on `WORKER_GPS_SERIAL_PORT`. Unset →
  the resolver returns `None` immediately, so machines without a HAT behave
  exactly as before. The relative order of the existing env / IP / OwnTracks
  resolvers is unchanged.
- **Graceful dependency.** `pyserial` + `pynmea2` are imported lazily inside a
  `try/except` (matching the OwnTracks-import fallback). If they are missing the
  resolver skips — the dependency is only meaningful on GPS-HAT nodes. They are
  in `requirements.txt` (small, pure-Python) but never exercised without the port.
- **Fix detail.** Latitude/longitude from any GGA/RMC sentence; altitude from
  GGA, ground speed (km/h) from RMC when present. Emits `GeoPoint(source="gps_serial")`
  into the existing ES document — `GeoPoint` already carries `altitude`/`speed_kmh`.

A Pi on **LTE** (a USB cellular modem) with a GPS HAT becomes a live, moving
fleet node: Tailscale keeps it reachable for management (see
[EDGE-TAILSCALE-NODE.md §7](EDGE-TAILSCALE-NODE.md#7-connectivity-wi-fi-vs-lte5g))
while the broadcast reports its position every cadence.

## 3. Part B — ESP32-over-LTE OwnTracks client

For a device too small to run Celery (or where you don't want a Pi), the firmware
in [`edge/esp32_owntracks_lte/`](../../edge/esp32_owntracks_lte/) reads a GPS fix
from a SIMCom modem's GNSS and POSTs an OwnTracks `_type:location` payload to the
Recorder's `/pub` endpoint over LTE:

```
ESP32 + SIM7000 ──LTE──▶ POST /pub?u=<user>&d=<device>   (OwnTracks JSON)
```

Because the payload is byte-for-byte what the OwnTracks app sends, the Recorder and
`apps/own_tracks` need **no changes** — the device just looks like another tracker.
Carrier CGNAT is a non-issue: the device dials *out*; it never needs inbound
reachability.

## 4. How both feed the location timeline

```
   Part A (Pi GPS HAT)                 Part B (ESP32 over LTE)
        │ serial NMEA                       │ OwnTracks JSON over LTE
        ▼                                   ▼
  _resolve_via_gps_serial            OwnTracks Recorder
        │                                   │  get_last(user, device)
        │                          _resolve_via_owntracks (apps/own_tracks)
        └───────────────┬───────────────────┘
                        ▼
          broadcast_report_location
                        │
        ┌───────────────┴────────────────┐
        ▼                                 ▼
  harqis-worker-locations          HFL location timeline
  (Kibana fleet map)               (workflows/hfl/tasks/ingest_location.py)
```

The HFL location-timeline ingest (`workflows/hfl/`) already consumes OwnTracks
data, so Part B fixes enrich the Homework-for-Life timeline ("drove to X today")
the same way the phone does — extending the location-timeline roadmap.

## 5. Configuration

**Part A (Pi GPS-HAT node):**

| Env var | Default | Purpose |
|---|---|---|
| `WORKER_GPS_SERIAL_PORT` | *(unset → resolver skipped)* | Serial device, e.g. `/dev/serial0`, `/dev/ttyUSB0`, `COM3` |
| `WORKER_GPS_BAUD` | `9600` | NMEA baud rate |
| `WORKER_GPS_MAX_LINES` | `60` | Max NMEA lines read before giving up on a fix |

The node must subscribe to `workers_broadcast` to receive the broadcast:
`python scripts/launch.py worker --queues default,workers_broadcast`.

**Part B (ESP32 firmware):** see [`edge/esp32_owntracks_lte/config.example.py`](../../edge/esp32_owntracks_lte/config.example.py) — APN, modem UART pins, Recorder URL, user/device.

## 6. Activation (opt-in)

- **Part A** changes an existing task but adds a *gated* resolver — on machines
  without `WORKER_GPS_SERIAL_PORT` the broadcast behaves identically to before.
  No beat-schedule change (the broadcast already runs every 15 min where it's
  enabled).
- **Part B** is device-side firmware; nothing runs on the cluster until a device
  is flashed and pointed at a Recorder.

## 7. Use cases solved

| # | Use case | How |
|---|----------|-----|
| UC-1 | **Live vehicle / fleet tracking on the Kibana map** | A Pi (GPS HAT, on LTE) reports a precise fix every cadence into `harqis-worker-locations` — the existing fleet dashboard lights up with no new code. |
| UC-2 | **Track an asset too small for a Pi** | A ~$20 ESP32 + SIM7000 publishes OwnTracks fixes over LTE; `apps/own_tracks` ingests them like a phone. |
| UC-3 | **Precise fix beats coarse fallbacks** | The GPS-HAT resolver sits above IP-geo (city-level) and remote OwnTracks, so a node with real GPS reports real GPS — while nodes without it are unaffected. |
| UC-4 | **Enrich the HFL location timeline from a vehicle** | Part B fixes flow through the Recorder into the HFL location ingest, adding "where I was" signal to Homework-for-Life without carrying a phone. |
| UC-5 | **Works behind carrier CGNAT** | Both paths dial out (broadcast → ES; ESP32 → Recorder), so cellular's lack of a public IP is a non-issue. |
| UC-6 | **No server changes to onboard a tracker** | Part B emulates the OwnTracks payload exactly; the Recorder + `apps/own_tracks` treat it as just another device. |
