"""
OwnTracks MQTT subscriber client.

Connects to a local Mosquitto broker and prints real-time location updates.
Used for debugging or as a base for custom location-driven workflows.

Usage:
    pip install paho-mqtt
    python apps/own_tracks/references/client.py
"""

import json
import requests
import paho.mqtt.client as mqtt

# ── Config ────────────────────────────────────────────────────────────────────
# Update these to match your setup. For anonymous brokers, leave USER/PASS blank.
MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_USER = ""
MQTT_PASS = ""
TOPIC = "owntracks/#"  # subscribe to all users/devices

# OwnTracks Recorder REST API base URL
RECORDER_URL = "http://localhost:8083"


# ── MQTT subscriber ───────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    print(f"[MQTT] Connected (rc={rc})")
    client.subscribe(TOPIC)
    print(f"[MQTT] Subscribed to: {TOPIC}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print(f"[MQTT] Failed to decode message: {e}")
        return

    # OwnTracks location message (_type: "location")
    if payload.get("_type") != "location":
        return

    lat = payload.get("lat")
    lon = payload.get("lon")
    tst = payload.get("tst")
    acc = payload.get("acc")
    tid = payload.get("tid")

    print(f"[{msg.topic}] lat={lat}, lon={lon}, acc={acc}m, tst={tst}, tid={tid}")


def run_subscriber():
    """Start blocking MQTT subscriber."""
    client = mqtt.Client()
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


# ── REST API helpers ──────────────────────────────────────────────────────────

def get_last_location(user: str = None, device: str = None) -> list[dict]:
    """
    Query the OwnTracks Recorder for the last known location(s).

    Args:
        user:   Filter by username (e.g. "brian")
        device: Filter by device ID (e.g. "iphone"). Requires user.

    Returns:
        List of location dicts with keys: username, device, lat, lon, tst, acc, tid
    """
    params = {}
    if user:
        params["user"] = user
    if device:
        params["device"] = device
    r = requests.get(f"{RECORDER_URL}/api/0/last", params=params, timeout=5)
    r.raise_for_status()
    return r.json()


def list_devices() -> list[dict]:
    """List all known users and devices tracked by the Recorder."""
    r = requests.get(f"{RECORDER_URL}/api/0/list", timeout=5)
    r.raise_for_status()
    return r.json()


def get_location_history(user: str, device: str, from_ts: int = None, to_ts: int = None) -> list[dict]:
    """
    Retrieve location history for a specific user/device.

    Args:
        user:     Username
        device:   Device ID
        from_ts:  Unix timestamp start (optional)
        to_ts:    Unix timestamp end (optional)

    Returns:
        List of historical location dicts
    """
    params = {"user": user, "device": device}
    if from_ts:
        params["from"] = from_ts
    if to_ts:
        params["to"] = to_ts
    r = requests.get(f"{RECORDER_URL}/api/0/locations", params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("data", [])


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_subscriber()
