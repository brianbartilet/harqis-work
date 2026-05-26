# Edge Sensor Telemetry — ESP32 → Elasticsearch + HUD + Discord

**Related:** [EDGE-TAILSCALE-NODE.md](EDGE-TAILSCALE-NODE.md) · [WORKER-CONFIG-DISTRIBUTION.md](WORKER-CONFIG-DISTRIBUTION.md)
**Date:** 2026-05-26

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Components](#3-components)
4. [Data model](#4-data-model)
5. [Thresholds & alerting](#5-thresholds--alerting)
6. [Running it](#6-running-it)
7. [Activation (opt-in)](#7-activation-opt-in)
8. [Use cases solved](#8-use-cases-solved)

---

## 1. Overview

Cheap ESP32 sensors report environmental readings (temperature, humidity, CO₂,
air quality, power draw, …) into harqis-work, where they are:

- **indexed** to the `harqis-sensor-telemetry` Elasticsearch index (time series),
- **surfaced** on a Rainmeter HUD widget next to the existing HUDs, and
- **alerted** to Discord when a reading breaches a configured threshold.

The transport is a thin **HTTP webhook** (chosen over MQTT for the smallest moving
surface — no broker to run). The ESP32 POSTs JSON; a FastAPI receiver validates it
and hands it to a Celery task that does the index/threshold/alert work.

This PR is **opt-in**: the ingest task and HUD widget ship registered but
unscheduled, and nothing runs until the receiver is started and devices point at it.

## 2. Architecture

```
   ┌────────────┐   Wi-Fi / LAN        ┌──────────────────────────────┐
   │  ESP32 +   │  POST /telemetry     │  Receiver (FastAPI)          │
   │  DHT22     │ ───────────────────▶ │  workflows/workers/receiver  │
   │  (leaf)    │   JSON reading       │  validate → .delay(...)      │
   └────────────┘                      └──────────────┬───────────────┘
                                                       │ Celery (default queue)
                                                       ▼
                                   ┌───────────────────────────────────────┐
                                   │ ingest_sensor_reading                  │
                                   │   1. DtoSensorReading.build(...)       │
                                   │   2. evaluate_threshold(value, rule)   │
                                   │   3. ES append (harqis-sensor-telemetry)│
                                   │   4. Discord alert embed on breach     │
                                   └───────────────┬─────────────┬──────────┘
                                                   ▼             ▼
                                       Kibana / hud_sensors   Discord webhook
```

The ESP32 is a **leaf**: it can't run Tailscale, so it reaches the receiver over the
local LAN. Run the receiver on the host or on a Raspberry Pi gateway (which *is* on
the tailnet — see [EDGE-TAILSCALE-NODE.md](EDGE-TAILSCALE-NODE.md)); the Pi can act as
a Tailscale subnet router to expose the sensor subnet to the mesh.

## 3. Components

| Component | Path | Role |
|---|---|---|
| Receiver | `workflows/workers/receiver/app.py` | FastAPI; validates payload, dispatches the task. Optional bearer auth (`SENSOR_RECEIVER_TOKEN`). |
| Ingest task | `workflows/workers/tasks/ingest_sensor_reading.py` | `@SPROUT.task` — ES write + threshold eval + Discord alert. Log-and-continue on any downstream outage. |
| DTO | `workflows/workers/dto/sensor_reading.py` | `DtoSensorReading` ES doc shape + `evaluate_threshold()`. |
| HUD widget | `workflows/hud/tasks/hud_sensors.py` | Rainmeter `SENSORS` skin — latest reading per metric, ⚠ on breach. |
| Firmware | `edge/esp32_sensor/` | MicroPython (DHT22 reference) that POSTs readings. |

The ingest task is a **normal direct task** (not a `broadcast_*` fanout), so it runs
once on whichever `default`-queue worker picks it up — unlike
`broadcast_report_location`, which fans out to every worker.

## 4. Data model

One ES document **per reading** (append-only time series), keyed
`<device_id>_<metric>_<device_ts>` so readings accumulate rather than overwrite:

| Field | Example | Notes |
|---|---|---|
| `device_id` | `esp32-garage` | stable per-device id |
| `metric` | `temperature` | what was measured |
| `value` | `21.5` | numeric |
| `unit` | `C` | unit of measure |
| `location` | `garage` | free-text placement |
| `device_ts` / `date` | `2026-05-26T08:00:00+00:00` | capture time (ingest time if device omits) |
| `ingested_by` | `harqis-server` | host that received it |
| `breached` | `true` | threshold violated |
| `threshold` | `{"min":2,"max":35,"unit":"C"}` | rule that was evaluated |
| `extra` | `{"battery":87}` | arbitrary device context |

Index name overridable via `SENSOR_TELEMETRY_INDEX`.

## 5. Thresholds & alerting

A rule is `{"min": <float|None>, "max": <float|None>, "unit": "<str>"}`; a breach is
`value < min` or `value > max`. Rules are resolved as: task `thresholds` kwarg →
`SENSOR_THRESHOLDS` env JSON → none.

```bash
export SENSOR_THRESHOLDS='{"temperature":{"min":2,"max":35,"unit":"C"},"co2":{"max":1200,"unit":"ppm"}}'
```

On breach the document carries `breached: true` **and** — when a Discord webhook is
configured — an alert embed is posted via `ApiServiceDiscordWebhooks.execute_webhook`.
Webhook credentials resolve from env `DISCORD_ALERT_WEBHOOK_ID`/`_TOKEN`, else the
`DISCORD` config block's `app_data.alert_webhook_id`/`alert_webhook_token`. If neither
is set the alert is skipped but the breach is still recorded in ES.

## 6. Running it

```bash
# Receiver (host or Pi gateway, both on the tailnet)
export SENSOR_RECEIVER_TOKEN="$(openssl rand -hex 16)"   # optional auth
export SENSOR_THRESHOLDS='{"temperature":{"min":2,"max":35}}'
uvicorn workflows.workers.receiver.app:app --host 0.0.0.0 --port 8770

# A default-queue worker must be running to consume the ingest task
python scripts/launch.py worker --queues default
```

Smoke-test without hardware:

```bash
curl -X POST http://localhost:8770/telemetry -H "Content-Type: application/json" \
  -d '{"device_id":"esp32-test","metric":"temperature","value":40,"unit":"C","location":"desk"}'
```

The device side is in [`edge/esp32_sensor/`](../../edge/esp32_sensor/).

## 7. Activation (opt-in)

Nothing runs automatically. To wire it into the cluster:

1. Start the receiver (above) and point devices at it.
2. Ensure a `default`-queue worker is running.
3. *(optional)* Schedule the HUD refresh by adding a `show_sensors` entry to
   `workflows/hud/tasks_config.py`, mirroring the other HUD tasks. Until then the
   widget is triggerable manually / via `launch.py trigger-hud-tasks`.

## 8. Use cases solved

| # | Use case | How |
|---|----------|-----|
| UC-1 | **Home/lab environmental monitoring** | ESP32 temp/humidity/CO₂ sensors stream into Kibana for trend charts and onto the `SENSORS` HUD for an at-a-glance read. |
| UC-2 | **Threshold alerting to chat** | Freezer over-temp, server-room heat, CO₂ spike → instant Discord embed via the existing `apps/discord` webhook path. |
| UC-3 | **Cheap many-sensor fan-in without a broker** | HTTP webhook means each ESP32 is ~30 lines and needs no MQTT broker to run/maintain; the receiver scales to many devices. |
| UC-4 | **Time-series retention independent of logs** | Dedicated `harqis-sensor-telemetry` index keeps sensor history queryable/retainable separately from operational logs. |
| UC-5 | **Remote-site sensing over LTE** | Pair with a Pi gateway on LTE ([EDGE-TAILSCALE-NODE.md §7](EDGE-TAILSCALE-NODE.md#7-connectivity-wi-fi-vs-lte5g)) to monitor a second property / cabin / storage unit with no reliable Wi-Fi. |
| UC-6 | **Sensor-agnostic ingest** | The DTO/receiver/task are metric-agnostic; new sensors (power clamp, water-leak, door) need only a new firmware `_read_sensor()` — no server-side change. |
