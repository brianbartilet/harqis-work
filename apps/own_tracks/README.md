# OwnTracks — Location Tracking Integration

## Overview

[OwnTracks](https://owntracks.org/) is an open-source mobile app (iOS/Android) that publishes GPS location data over **MQTT**. This integration runs a local **Mosquitto MQTT broker** and an **OwnTracks Recorder** (HTTP REST API) via Docker Compose, enabling you to query the last known location of any registered device.

- **No cloud dependency** — all data stays local
- **Multi-device** — tracks multiple users/devices via topic namespacing
- **REST queryable** — the Recorder exposes an HTTP API for last-location lookups

---

## Architecture

```
[iPhone/Android]
  └─ OwnTracks App
       └─ MQTT publish → owntracks/<user>/<device>
                              │
                    [Docker: Mosquitto]  :1883
                              │
                    [Docker: OwnTracks Recorder]  :8083
                              │
                    REST API → GET /api/0/last
```

---

## Directory Structure

```
apps/own_tracks/
├── docker-compose.yml              # Mosquitto + Recorder containers
├── mosquitto/
│   └── config/
│       └── mosquitto.conf          # MQTT broker config (anonymous, port 1883)
├── references/
│   └── client.py                   # Python MQTT subscriber stub
└── recorder_store/                 # Auto-created: persisted location data (gitignored)
```

---

## Setup

### 1. Start the Docker stack

```bash
cd apps/own_tracks
docker compose up -d
```

This starts:
| Container | Port | Purpose |
|---|---|---|
| `mosquitto` | 1883 | MQTT broker |
| `owntracks-recorder` | 8083 | REST API + web UI |

### 2. Configure OwnTracks on your phone

Open the OwnTracks app → **Preferences → Connection**:

| Setting | Value |
|---|---|
| Mode | MQTT |
| Host | `<your PC's local IP>` (e.g. `192.168.1.x`) |
| Port | `1883` |
| Username | anything (e.g. `brian`) |
| Password | *(leave blank — broker is anonymous)* |
| Device ID | e.g. `iphone`, `android` |
| Topic | auto-set to `owntracks/<username>/<device>` |

> **Tip:** Find your PC IP with `ipconfig` → look for IPv4 under your active adapter.

### 3. Verify data is flowing

After the app publishes a location, check the Recorder web UI:

```
http://localhost:8083
```

Or query the REST API directly:

```bash
# Last known location of all devices
curl http://localhost:8083/api/0/last

# Filter by user
curl "http://localhost:8083/api/0/last?user=brian"

# Filter by user + device
curl "http://localhost:8083/api/0/last?user=brian&device=iphone"
```

---

## REST API Reference

Base URL: `http://localhost:8083`

| Endpoint | Method | Description |
|---|---|---|
| `/api/0/last` | GET | Last location of all tracked devices |
| `/api/0/last?user=X` | GET | Filter by username |
| `/api/0/last?user=X&device=Y` | GET | Filter by user + device |
| `/api/0/locations?user=X&device=Y&from=T&to=T` | GET | Location history |
| `/api/0/list` | GET | List all known users/devices |

### Sample response (`/api/0/last`)

```json
[
  {
    "username": "brian",
    "device": "iphone",
    "lat": 1.3521,
    "lon": 103.8198,
    "tst": 1775460000,
    "acc": 15,
    "tid": "bi",
    "topic": "owntracks/brian/iphone"
  }
]
```

---

## Python Client (references/client.py)

A blocking MQTT subscriber that prints location updates in real-time. Useful for debugging or piping into other workflows.

**Before running**, update the config at the top of the file:

```python
MQTT_HOST = "localhost"   # or your PC's IP
MQTT_PORT = 1883
MQTT_USER = ""            # leave blank if anonymous
MQTT_PASS = ""
TOPIC = "owntracks/#"     # subscribe to all devices
```

**Run:**

```bash
pip install paho-mqtt
python apps/own_tracks/references/client.py
```

---

## Integrating with HARQIS-CLAW

To query your device location via the agent, the Recorder REST API is the easiest path:

```python
import requests

def get_last_location(user="brian", device=None):
    params = {"user": user}
    if device:
        params["device"] = device
    r = requests.get("http://localhost:8083/api/0/last", params=params)
    return r.json()
```

Or just ask the agent: *"where is my phone?"* — once this is wired into a workflow or the agent knows the Recorder URL, it can query it directly.

---

## TODO / Improvements

- [ ] Move MQTT credentials to `apps_config.yaml` + `.env/apps.env`
- [ ] Add Celery task for periodic location polling
- [ ] Add `get_location` workflow task usable by HARQIS-CLAW
- [ ] Enable MQTT authentication (add username/password to `mosquitto.conf`)
- [ ] Expose Recorder behind nginx with auth for remote access

---

## Accessing Remotely (optional)

By default this only works on your local network. To access from anywhere:

1. **Tailscale** (easiest) — install on phone + PC, use Tailscale IP instead of local IP
2. **Port forward** port `1883` and `8083` on your router (not recommended without auth)
3. **Cloudflare Tunnel** — tunnel port `8083` for the REST API only

---

## Notes

- `recorder_store/` is auto-created by Docker and contains all persisted location data — add it to `.gitignore`
- The broker runs anonymously — fine for home use, add auth before exposing to internet
- OwnTracks publishes on move + on a configurable interval (set in app settings)
