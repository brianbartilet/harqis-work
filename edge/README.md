# `edge/` — Device-side code for harqis-work edge automation

This tree holds code that runs **on devices**, not on the harqis-work host:
Raspberry Pi bootstrap scripts, ESP32 firmware, and sensor/GPS readers. It is
deliberately kept out of `scripts/` (which is for host/runtime tooling — see
`scripts/README.md`) because nothing here executes as part of the platform's
own deploy or Celery runtime. The platform-side counterparts (Celery tasks,
DTOs, HUD widgets, resolvers) live under `workflows/` and `apps/` as usual.

## Layout

| Directory | Device | What it does | Design doc |
|---|---|---|---|
| `rpi_node/` | Raspberry Pi (ARM Linux) | First-time bootstrap to join the Tailscale tailnet and run as a Celery worker node | [docs/info/EDGE-TAILSCALE-NODE.md](../docs/info/EDGE-TAILSCALE-NODE.md) |
| `esp32_sensor/` | ESP32 (MicroPython) | Reads a sensor and POSTs JSON to the telemetry receiver — *ships with the sensor-telemetry PR* | [docs/info/EDGE-SENSOR-TELEMETRY.md](../docs/info/EDGE-SENSOR-TELEMETRY.md) |
| `esp32_owntracks_lte/` | ESP32 + LTE modem (MicroPython) | Reads GPS and POSTs an OwnTracks payload over cellular — *ships with the LTE-fleet PR* | [docs/info/EDGE-LTE-FLEET-LOCATION.md](../docs/info/EDGE-LTE-FLEET-LOCATION.md) |

> The `esp32_*` directories are added by their respective feature PRs; this index
> lists them up front so the edge roadmap reads as one tree.

## Conventions

- **Devices hold no secrets on disk where avoidable.** Pi nodes fetch resolved
  config at startup over the tailnet (see WORKER-CONFIG-DISTRIBUTION.md). ESP32
  leaves keep only the endpoint URL + a per-device token in their config.
- **Leaves talk to a gateway, not the tailnet.** ESP32 cannot run Tailscale;
  it reaches a Pi/host on the tailnet over the local LAN (or the Pi provides the
  uplink). The Pi can act as a Tailscale subnet router to expose the leaf's
  local subnet to the mesh.
- **Each subdirectory has its own README** with wiring, flashing, and config steps.
