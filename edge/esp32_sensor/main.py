# edge/esp32_sensor/main.py
#
# MicroPython firmware for an ESP32 + DHT22 (AM2302) that reports temperature
# and humidity to the harqis-work sensor telemetry receiver.
#
#   ESP32 ──Wi-Fi──▶ POST /telemetry ──▶ ingest_sensor_reading (Celery)
#                                          ├─ Elasticsearch (harqis-sensor-telemetry)
#                                          ├─ Rainmeter HUD (hud_sensors)
#                                          └─ Discord alert on threshold breach
#
# DHT22 is the reference sensor; swap _read_sensor() for any sensor you wire.
# One POST carries one metric (matches the one-doc-per-reading DTO), so a cycle
# sends two POSTs: temperature then humidity.
#
# Flashing: copy config.py (from config.example.py) + this file to the device
# with `mpremote` / Thonny / ampy. Full guide: README.md.

import time

import network
import urequests
import dht
from machine import Pin

import config


def connect_wifi():
    """Bring up Wi-Fi, blocking until connected (with a bounded retry)."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print("wifi: connecting to", config.WIFI_SSID)
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        for _ in range(40):  # ~20s
            if wlan.isconnected():
                break
            time.sleep(0.5)
    if not wlan.isconnected():
        raise OSError("wifi: failed to connect")
    print("wifi: connected", wlan.ifconfig()[0])
    return wlan


def _read_sensor(sensor):
    """Return (temperature_c, humidity_pct). Replace for a different sensor."""
    sensor.measure()
    return sensor.temperature(), sensor.humidity()


def post_reading(metric, value, unit):
    """POST a single reading to the receiver. Returns the HTTP status (or -1)."""
    payload = {
        "device_id": config.DEVICE_ID,
        "metric": metric,
        "value": value,
        "unit": unit,
        "location": config.LOCATION,
    }
    headers = {"Content-Type": "application/json"}
    token = getattr(config, "RECEIVER_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        resp = urequests.post(config.RECEIVER_URL, json=payload, headers=headers)
        status = resp.status_code
        resp.close()
        print("post:", metric, "=", value, unit, "->", status)
        return status
    except Exception as exc:  # network blip — skip this reading, try next cycle
        print("post: error", exc)
        return -1


def main():
    connect_wifi()
    sensor = dht.DHT22(Pin(config.DHT_PIN))
    interval = getattr(config, "INTERVAL_SECONDS", 60)

    while True:
        try:
            temperature_c, humidity_pct = _read_sensor(sensor)
            post_reading("temperature", temperature_c, "C")
            post_reading("humidity", humidity_pct, "%")
        except OSError as exc:
            # DHT read failures are common (timing); just wait for the next cycle.
            print("sensor: read error", exc)
        time.sleep(interval)


if __name__ == "__main__":
    main()
