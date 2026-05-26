# `edge/esp32_sensor/` — ESP32 sensor → harqis-work telemetry

MicroPython firmware for an ESP32 that reads a sensor and POSTs readings to the
harqis-work telemetry receiver, which indexes them to Elasticsearch, shows them
on a Rainmeter HUD, and fires a Discord alert on threshold breach.

**Full design + use cases:** [docs/info/EDGE-SENSOR-TELEMETRY.md](../../docs/info/EDGE-SENSOR-TELEMETRY.md)

## Pipeline

```
ESP32 + DHT22 ──Wi-Fi──▶ POST /telemetry ──▶ ingest_sensor_reading (Celery)
                                               ├─ Elasticsearch  harqis-sensor-telemetry
                                               ├─ Rainmeter HUD  (hud_sensors)
                                               └─ Discord alert  (on threshold breach)
```

The ESP32 cannot run Tailscale, so it reaches the receiver over the **local LAN**
(or via the Pi/host gateway that is on the tailnet). See EDGE-SENSOR-TELEMETRY.md
for the gateway topology.

## Hardware (reference)

- Any ESP32 dev board (running MicroPython).
- DHT22 / AM2302 temperature + humidity sensor.
- Wiring: DHT22 data → GPIO 4 (configurable via `DHT_PIN`), VCC → 3V3, GND → GND.

DHT22 is just the reference sensor — replace `_read_sensor()` in `main.py` for
any sensor you wire (BME280, CO₂, current clamp, …); the receiver and ingest task
are sensor-agnostic.

## Flash it

1. Flash MicroPython to the ESP32 (esptool).
2. Copy `config.example.py` → `config.py` and fill in Wi-Fi + receiver URL +
   device id. (`config.py` is per-device; don't commit it.)
3. Upload both files to the device:
   ```bash
   mpremote connect /dev/ttyUSB0 fs cp config.py :config.py
   mpremote connect /dev/ttyUSB0 fs cp main.py :main.py
   ```
4. Reset the board — `main.py` runs on boot, connecting to Wi-Fi and posting a
   reading every `INTERVAL_SECONDS`.

## Receiver side

Run the receiver on the host or a Pi bridge (both on the tailnet):

```bash
# optional: require a bearer token (must match RECEIVER_TOKEN on the device)
export SENSOR_RECEIVER_TOKEN="$(openssl rand -hex 16)"
uvicorn workflows.workers.receiver.app:app --host 0.0.0.0 --port 8770
```

Smoke-test without hardware:

```bash
curl -X POST http://localhost:8770/telemetry \
  -H "Content-Type: application/json" \
  -d '{"device_id":"esp32-test","metric":"temperature","value":21.5,"unit":"C","location":"desk"}'
# → 202 {"status":"accepted",...}
```

## Thresholds & alerts

Threshold rules are supplied to the ingest task (env `SENSOR_THRESHOLDS` JSON or
the task `thresholds` kwarg), e.g.:

```bash
export SENSOR_THRESHOLDS='{"temperature":{"min":2,"max":35,"unit":"C"},"co2":{"max":1200,"unit":"ppm"}}'
```

A breach is recorded in ES (`breached: true`) and, when a Discord webhook is
configured (`DISCORD_ALERT_WEBHOOK_ID`/`_TOKEN` or the `DISCORD` config block's
`alert_webhook_id`/`alert_webhook_token`), posted as an alert embed.
