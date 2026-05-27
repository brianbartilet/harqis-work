# `edge/rpi_node/` — Raspberry Pi as a Tailscale Celery node

Bootstrap a Raspberry Pi (or any ARM Linux SBC) into the harqis-work cluster as a
secret-less Celery worker that reaches the host over Tailscale.

**Full design + use cases:** [docs/info/EDGE-TAILSCALE-NODE.md](../../docs/info/EDGE-TAILSCALE-NODE.md)

## What it does

`bootstrap.sh` performs a one-time, idempotent setup on a fresh Raspberry Pi OS
(64-bit) install:

1. Installs base packages + Tailscale, then `tailscale up` to join the tailnet.
2. Clones the repo and builds a Python venv with `requirements.txt`.
3. Writes a **secret-less** `.env/worker.env` that points the Celery broker and
   config store at the host's Tailscale MagicDNS name (config is fetched at
   startup per [WORKER-CONFIG-DISTRIBUTION.md](../../docs/info/WORKER-CONFIG-DISTRIBUTION.md)).
4. Starts a Celery worker on the configured queues.

## Run it

```bash
sudo HARQIS_HOST_MAGICDNS=host.<tailnet>.ts.net \
     HARQIS_QUEUES=default,worker,default_broadcast,hfl_broadcast \
     bash edge/rpi_node/bootstrap.sh
```

| Env var | Default | Purpose |
|---|---|---|
| `HARQIS_HOST_MAGICDNS` | *(required)* | Host's Tailscale MagicDNS name (or its `100.x` IP) for broker/config/ES |
| `HARQIS_QUEUES` | `default,worker,default_broadcast,hfl_broadcast` | Celery queues this node consumes |
| `HARQIS_CONFIG_SOURCE` | `redis` | `redis` or `http` config backend (see WORKER-CONFIG-DISTRIBUTION.md) |
| `HARQIS_CONFIG_SERVER_TOKEN` | — | Bearer token, required when `HARQIS_CONFIG_SOURCE=http` |
| `HARQIS_CONCURRENCY` | `2` | Worker concurrency (exported as `WORKFLOW_CONCURRENCY`) |
| `HARQIS_REPO_DIR` | `/opt/harqis-work` | Clone target |

## Make it permanent

The script launches the worker in the foreground so the bootstrap is
self-contained. For an always-on node, wrap the final launch line in a systemd
unit (`/etc/systemd/system/harqis-worker.service`) with `Restart=always`, mirroring
the LaunchAgent/systemd pattern referenced in WORKER-CONFIG-DISTRIBUTION.md §9.4.

## Map the Pi to its `machines.toml` block

`deploy.py` auto-detects the machine by hostname. Add the mapping to the gitignored
`machines.local.toml`:

```toml
[hostnames]
"raspberrypi"       = "rpi-node"
"raspberrypi.local" = "rpi-node"
```

The committed `[rpi-node]` block in `machines.toml` defines its role/queues.

## Cellular (LTE/5G)

If the Pi runs on a USB cellular modem instead of Wi-Fi, nothing here changes:
Tailscale routes over `wwan0` and DERP relays handle the carrier's CGNAT. See
EDGE-TAILSCALE-NODE.md §7.
