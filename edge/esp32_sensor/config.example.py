# edge/esp32_sensor/config.example.py
#
# Copy to `config.py` on the device and fill in. config.py is per-device and
# should NOT be committed (add it to .gitignore if you keep devices in a repo).

# ── Wi-Fi ─────────────────────────────────────────────────────────────────────
WIFI_SSID = "your-ssid"
WIFI_PASSWORD = "your-password"

# ── Telemetry receiver ────────────────────────────────────────────────────────
# The harqis-work sensor receiver (workflows/workers/receiver/app.py), reachable
# on the local LAN or via the Pi/host that runs it. Use the gateway's LAN IP or
# Tailscale MagicDNS name (the ESP32 reaches the gateway over the LAN; the
# gateway is on the tailnet).
RECEIVER_URL = "http://192.168.1.10:8770/telemetry"

# Optional bearer token — must match SENSOR_RECEIVER_TOKEN on the receiver.
# Leave "" to send unauthenticated (only acceptable on a trusted LAN/tailnet).
RECEIVER_TOKEN = ""

# ── Device identity / placement ───────────────────────────────────────────────
DEVICE_ID = "esp32-garage"
LOCATION = "garage"

# ── Sensor wiring ─────────────────────────────────────────────────────────────
# GPIO the DHT22 data pin is wired to.
DHT_PIN = 4

# ── Cadence ───────────────────────────────────────────────────────────────────
# Seconds between reading cycles.
INTERVAL_SECONDS = 60
