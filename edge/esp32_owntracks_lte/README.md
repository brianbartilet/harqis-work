# `edge/esp32_owntracks_lte/` — ESP32 + LTE → OwnTracks Recorder

MicroPython reference firmware for an ESP32 with a SIMCom cellular modem that
reads a GPS fix and publishes it to an **OwnTracks Recorder** over LTE, emulating
the OwnTracks phone app's HTTP payload. Once in the Recorder, the fix flows into
harqis-work through the existing `apps/own_tracks` integration.

**Full design + use cases:** [docs/info/EDGE-LTE-FLEET-LOCATION.md](../../docs/info/EDGE-LTE-FLEET-LOCATION.md)

## Pipeline

```
ESP32 + SIM7000 ──LTE──▶ POST /pub?u=<user>&d=<device>   (OwnTracks _type:location)
                                  │
                          OwnTracks Recorder
                                  │  read by apps/own_tracks (get_last)
                                  ▼
   broadcast_report_location :: _resolve_via_owntracks
   → harqis-worker-locations (Kibana fleet map) + HFL location timeline
```

The device publishes the **same JSON shape** the OwnTracks app does, so no
server-side change is needed — the Recorder and `apps/own_tracks` treat it like
any other tracker.

## Hardware (reference)

- ESP32 dev board (MicroPython).
- SIMCom **SIM7000** LTE-M/NB-IoT modem with GNSS (or a SIM7600 — see *Adapting*).
- Active SIM with a data plan; GPS antenna.
- UART wiring per `config.example.py` (`MODEM_TX_PIN` / `MODEM_RX_PIN`).

## Why this needs Tailscale-style thinking

A cellular device sits behind carrier-grade NAT — it has no reachable public IP.
That's fine here because the device **dials out** to the Recorder; it never needs
inbound reachability. If you also want to *manage* the device (SSH, OTA), put it
behind a Pi gateway on the tailnet — see
[EDGE-TAILSCALE-NODE.md §7](../../docs/info/EDGE-TAILSCALE-NODE.md#7-connectivity-wi-fi-vs-lte5g).

## Flash it

1. Flash MicroPython to the ESP32.
2. Copy `config.example.py` → `config.py`, fill in APN + Recorder URL + user/device.
3. Upload both files (`mpremote` / Thonny / ampy) and reset.

## Adapting to other modems

This is a **template**, not a turnkey binary — AT sequences vary by modem:

| Concern | SIM7000 (this file) | SIM7600 |
|---|---|---|
| GNSS read | `AT+CGNSPWR=1` / `AT+CGNSINF` | `AT+CGPS=1` / `AT+CGPSINFO` |
| Data context | `AT+CNACT=1` | `AT+NETOPEN` / `AT+CGSOCKCONT` |
| HTTP POST | `AT+SH*` set | `AT+HTTPINIT` / `AT+HTTPDATA` / `AT+HTTPACTION=1` |

Swap `gnss_fix()` and `http_post_owntracks()` accordingly; the OwnTracks payload
(`build_owntracks`) and main loop stay the same.

## Notes

- `tst` is epoch seconds — set the RTC (NTP over LTE, or the modem clock
  `AT+CCLK?`) so the timeline timestamps are correct.
- If the Recorder uses HTTP Basic auth, precompute `base64(user:pass)` and drop it
  into the `Authorization` header line (kept as a placeholder in `main.py`).
- Verify the fix lands: `apps/own_tracks` `get_last(user, device)` should return it,
  and `broadcast_report_location` will then surface it on the Kibana fleet map.
