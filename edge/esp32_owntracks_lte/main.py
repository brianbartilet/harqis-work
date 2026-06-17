# edge/esp32_owntracks_lte/main.py
#
# MicroPython reference firmware: an ESP32 + SIMCom cellular modem (SIM7000 LTE-M
# / NB-IoT family) that reads a GPS fix and publishes it to an OwnTracks Recorder
# over LTE — emulating the OwnTracks app's HTTP payload.
#
#   ESP32 + SIM7000 ──LTE──▶ POST /pub?u=<user>&d=<device>  (OwnTracks JSON)
#                                       │
#                              OwnTracks Recorder
#                                       │  read back by apps/own_tracks
#                                       ▼
#        workflows/workers/tasks/broadcast_report_location :: _resolve_via_owntracks
#        → harqis-worker-locations (Kibana fleet map) + HFL location timeline
#
# This is a *reference template*, not a turnkey binary: AT-command sequences vary
# by modem. It targets the SIMCom SIM7000 (GNSS via AT+CGNSINF, data via AT+CNACT,
# HTTP via the SH* command set). For a SIM7600 swap CGNSINF→CGPSINFO and the SH*
# flow → AT+HTTP*. See README.md.

import time
import ujson
from machine import UART

import config

_modem = None


def _modem_init():
    global _modem
    _modem = UART(config.MODEM_UART, baudrate=config.MODEM_BAUD,
                  tx=config.MODEM_TX_PIN, rx=config.MODEM_RX_PIN, timeout=1000)


def at(cmd, wait_ms=1500):
    """Send an AT command and return the modem's reply as text."""
    _modem.write((cmd + "\r\n").encode())
    time.sleep_ms(wait_ms)
    buf = b""
    while _modem.any():
        buf += _modem.read()
    reply = buf.decode("ascii", "replace")
    print(">", cmd, "->", reply.strip())
    return reply


def lte_up():
    """Bring up the LTE data context (SIM7000: AT+CNACT)."""
    at("AT")
    at("ATE0")                       # echo off
    at("AT+CFUN=1", 3000)
    at('AT+CGDCONT=1,"IP","{0}"'.format(config.APN))
    at("AT+CNACT=1", 5000)           # activate PDP context / get IP
    at("AT+CNACT?")                  # prints the assigned IP


def gnss_fix():
    """Power GNSS and return (lat, lon, alt_m, speed_kmh) or None.

    Parses the SIM7000 +CGNSINF line:
      +CGNSINF: <run>,<fix>,<utc>,<lat>,<lon>,<alt>,<speed_kph>,<course>,...
    """
    at("AT+CGNSPWR=1", 2000)
    # Give the receiver a few attempts to acquire a fix.
    for _ in range(30):
        reply = at("AT+CGNSINF", 1000)
        if "+CGNSINF:" not in reply:
            time.sleep(2)
            continue
        try:
            body = reply.split("+CGNSINF:")[1].strip().splitlines()[0]
            parts = body.split(",")
            fix_status = parts[1]
            if fix_status != "1":     # 1 = valid fix
                time.sleep(2)
                continue
            lat = float(parts[3])
            lon = float(parts[4])
            alt = float(parts[5]) if parts[5] else None
            speed_kmh = float(parts[6]) if parts[6] else None
            return lat, lon, alt, speed_kmh
        except (IndexError, ValueError):
            time.sleep(2)
    return None


def build_owntracks(lat, lon, alt, speed_kmh):
    """Build the OwnTracks `_type:location` payload (matches the phone app)."""
    payload = {
        "_type": "location",
        "lat": lat,
        "lon": lon,
        "tst": int(time.time()),     # epoch seconds (ensure RTC/NTP is set)
        "tid": config.TID,
        "conn": "m",                 # mobile connection
    }
    if alt is not None:
        payload["alt"] = int(alt)
    if speed_kmh is not None:
        payload["vel"] = int(speed_kmh)
    return payload


def http_post_owntracks(payload):
    """POST the OwnTracks JSON to the Recorder /pub via the modem (SIM7000 SH*)."""
    body = ujson.dumps(payload)
    url = "{0}?u={1}&d={2}".format(
        config.RECORDER_PUB_URL, config.OWNTRACKS_USER, config.OWNTRACKS_DEVICE,
    )
    # SIM7000 "SH" HTTP(S) request flow.
    host = url.split("/")[2]
    at('AT+SHCONF="URL","{0}"'.format(url))
    at('AT+SHCONF="BODYLEN",1024')
    at('AT+SHCONF="HEADERLEN",350')
    at("AT+SHCONN", 6000)
    at("AT+SHSTATE?")
    at('AT+SHAHEAD="Content-Type","application/json"')
    if config.RECORDER_USER:
        # Basic auth header if the Recorder requires it (precompute base64 offline).
        at('AT+SHAHEAD="Authorization","Basic <base64(user:pass)>"')
    at("AT+SHBOD={0},1000".format(len(body)))
    _modem.write(body.encode())      # send the JSON body
    time.sleep_ms(500)
    at("AT+SHREQ=\"{0}\",3".format(url), 6000)   # 3 = POST
    at("AT+SHDISC")


def main():
    _modem_init()
    lte_up()
    interval = getattr(config, "INTERVAL_SECONDS", 120)
    while True:
        fix = gnss_fix()
        if fix:
            lat, lon, alt, speed_kmh = fix
            payload = build_owntracks(lat, lon, alt, speed_kmh)
            try:
                http_post_owntracks(payload)
                print("published:", payload)
            except Exception as exc:
                print("publish error:", exc)
        else:
            print("no GPS fix this cycle")
        time.sleep(interval)


if __name__ == "__main__":
    main()
