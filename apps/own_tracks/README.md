# OwnTracks

## Description

- [OwnTracks](https://owntracks.org/) is an open-source location tracking app (iOS/Android) that publishes GPS data via MQTT.
- This integration runs a local MQTT broker (Mosquitto via Docker) and subscribes to location updates.
- **No Python API integration** — the Python client stub exists but is not connected to any workflow.
- Runtime dependency is Docker Compose only.

## Supported Automations

- [ ] webservices
- [ ] browser
- [ ] desktop
- [ ] mobile
- [X] internet of things

## Directory Structure

```
apps/own_tracks/
├── docker-compose.yml          # Mosquitto MQTT broker container
├── mosquitto/
│   └── config/
│       └── mosquitto.conf      # MQTT broker configuration
├── references/
│   └── client.py               # MQTT subscriber stub (not connected to workflows)
└── __init__.py
```

## Running the MQTT Broker

```sh
cd apps/own_tracks
docker compose up -d
```

This starts a Mosquitto MQTT broker. Configure the OwnTracks mobile app to publish to:

```
Host: <your-local-ip>
Port: 1883
Topic: owntracks/<username>/<device>
```

## MQTT Client Stub (`references/client.py`)

Subscribes to `owntracks/#` and extracts location fields from incoming JSON payloads:

| Field | Description |
|-------|-------------|
| `lat` | Latitude |
| `lon` | Longitude |
| `tst` | Unix timestamp |
| `acc` | Accuracy (meters) |

```python
# Configuration (hardcoded in client.py — update before use)
MQTT_HOST = "your.server.ip"
MQTT_PORT = 1883
MQTT_USER = "youruser"
MQTT_PASS = "yourpass"
TOPIC = "owntracks/#"
```

## Notes

- The Python client uses `paho-mqtt` and runs `client.loop_forever()` — it is a blocking subscriber, not a Celery task.
- MQTT credentials in `client.py` are hardcoded and should be moved to `apps_config.yaml` / env vars before use.
- No workflow tasks consume this app. Location data is not currently fed into the HUD or any other workflow.
- Docker must be running for the Mosquitto broker to be available.
