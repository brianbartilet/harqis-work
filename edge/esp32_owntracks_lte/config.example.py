# edge/esp32_owntracks_lte/config.example.py
#
# Copy to `config.py` on the device and fill in. config.py is per-device and
# must NOT be committed (it is gitignored via edge/**/config.py).

# ── Cellular (LTE) ────────────────────────────────────────────────────────────
APN = "internet"                 # your carrier's APN
APN_USER = ""                    # usually blank
APN_PASS = ""                    # usually blank

# ── Modem UART wiring (ESP32 <-> SIMCom modem) ────────────────────────────────
MODEM_UART = 1                   # ESP32 UART id
MODEM_TX_PIN = 27                # ESP32 TX -> modem RX
MODEM_RX_PIN = 26                # ESP32 RX <- modem TX
MODEM_BAUD = 115200

# ── OwnTracks Recorder (HTTP mode) ────────────────────────────────────────────
# The Recorder's /pub endpoint. User + device are passed as query params so the
# Recorder files the fix under owntracks/<user>/<device> — which is exactly what
# apps/own_tracks reads back (see workflows/workers/tasks/broadcast_report_location
# :: _resolve_via_owntracks). Reach it over the public internet or via a tunnel.
RECORDER_PUB_URL = "https://owntracks.example.com/pub"
OWNTRACKS_USER = "brian"
OWNTRACKS_DEVICE = "car"
TID = "ca"                       # 2-char tracker id shown on the map
# Optional HTTP Basic auth for the Recorder (leave "" if none).
RECORDER_USER = ""
RECORDER_PASS = ""

# ── Cadence ───────────────────────────────────────────────────────────────────
INTERVAL_SECONDS = 120           # how often to publish a fix
