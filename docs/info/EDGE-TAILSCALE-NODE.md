# Edge Nodes on Tailscale — Raspberry Pi as a First-Class Celery Worker

**Related:** [VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md) · [WORKER-CONFIG-DISTRIBUTION.md](WORKER-CONFIG-DISTRIBUTION.md)
**Date:** 2026-05-26

---

## Table of Contents

1. [Overview](#1-overview)
2. [Why Tailscale instead of hand-rolled WireGuard](#2-why-tailscale-instead-of-hand-rolled-wireguard)
3. [Architecture](#3-architecture)
4. [Broker & Elasticsearch reachability over the tailnet](#4-broker--elasticsearch-reachability-over-the-tailnet)
5. [`machines.toml` — the `[rpi-node]` block](#5-machinestoml--the-rpi-node-block)
6. [Bootstrapping a Pi node](#6-bootstrapping-a-pi-node)
7. [Connectivity: Wi-Fi vs LTE/5G](#7-connectivity-wi-fi-vs-lte5g)
8. [Security model](#8-security-model)
9. [Use cases solved](#9-use-cases-solved)
10. [Relationship to the existing cluster docs](#10-relationship-to-the-existing-cluster-docs)

---

## 1. Overview

A Raspberry Pi (Pi 4 / Pi 5 / Zero 2 W) runs a full Linux userland, so it can run
the same `celery` worker the VPS and N100 nodes already run in
[VPS-CLUSTER-AGENT-DESIGN.md §10](VPS-CLUSTER-AGENT-DESIGN.md#10-hybrid-topology-vps--n100-windows-nodes).
It is **not** a special device type — from the orchestrator's perspective it is just
another Celery worker subscribing to named queues.

The one thing the Pi changes is the **transport**. The cluster design distributes a
hand-written WireGuard `wg0.conf` to each node over SSH and pins static `10.0.0.x`
addresses. This document replaces that plumbing with **Tailscale**: the Pi runs
`tailscale up` once, joins the tailnet, and is reachable by a stable MagicDNS name —
no key exchange, no static IP map, no inbound port to open.

This PR ships:

- A commented `[rpi-node]` block in `machines.toml` (role `node`, ARM-friendly queues).
- A reference bootstrap script at [`edge/rpi_node/bootstrap.sh`](../../edge/rpi_node/bootstrap.sh).
- This document.

It changes **no runtime code** and touches **no live schedule** — adding a Pi is purely
additive config plus a one-time device bootstrap.

---

## 2. Why Tailscale instead of hand-rolled WireGuard

The cluster design's WireGuard model (§4 of VPS-CLUSTER-AGENT-DESIGN.md) works, but it
carries operational cost that does not survive contact with edge devices on home Wi-Fi
or cellular:

| Concern | Hand-rolled WireGuard | Tailscale |
|---|---|---|
| Per-node setup | Generate keypair, edit `wg0.conf`, distribute over SSH | `tailscale up` (browser/OAuth auth once) |
| Addressing | Static `10.0.0.x` map maintained by hand | MagicDNS name `pi-node.<tailnet>.ts.net`, auto-assigned `100.x` |
| NAT / CGNAT traversal | Needs a public endpoint or port-forward on at least one side | DERP relays punch through CGNAT automatically |
| Cellular (4G/5G) nodes | Carrier-grade NAT breaks inbound; usually unusable | Works — the node dials out, relay handles return path |
| Key rotation | Manual, per-peer | Centralised in the Tailscale admin console |
| Access control | iptables / firewall rules per node | Tailnet ACLs (tags, grants) in one policy file |

Tailscale **is** WireGuard under the hood (same userspace/kernel WireGuard data plane),
so the encryption properties the design relies on are unchanged. What it removes is the
config-distribution and addressing toil — which is exactly the part that does not scale
to "a Pi in the garage on Wi-Fi" or "a Pi in a vehicle on LTE."

`machines.toml` already anticipated this: its `[dumps]` and `pull_targets` comments
name **Tailscale MagicDNS** as the SSH transport for non-Celery devices. This PR extends
the same naming convention to Celery worker nodes.

---

## 3. Architecture

```
                       Tailnet (100.x / *.<tailnet>.ts.net)
   ┌───────────────────────────────────────────────────────────────────┐
   │                                                                     │
   │   ┌─────────────────────────┐                                       │
   │   │  Host (harqis-server)   │  role = host                          │
   │   │  host.<tailnet>.ts.net  │                                       │
   │   │                         │                                       │
   │   │   Redis / RabbitMQ      │◀───── Celery broker over tailnet ──┐   │
   │   │   Elasticsearch :9200   │◀───── ES writes over tailnet ───┐  │   │
   │   │   Beat scheduler        │                                 │  │   │
   │   └─────────────────────────┘                                 │  │   │
   │                                                               │  │   │
   │   ┌─────────────────────────┐   ┌─────────────────────────┐   │  │   │
   │   │  rpi-node-1 (Wi-Fi)     │   │  rpi-node-2 (LTE/5G)    │   │  │   │
   │   │  pi1.<tailnet>.ts.net   │   │  pi2.<tailnet>.ts.net   │   │  │   │
   │   │  role = node            │   │  role = node            │   │  │   │
   │   │  celery worker -Q ...   │───┘   celery worker -Q ...  │───┘  │   │
   │   │  (holds NO secrets)     │       (holds NO secrets) ──────────┘   │
   │   └─────────────────────────┘   └─────────────────────────┘         │
   │                                                                     │
   └───────────────────────────────────────────────────────────────────┘
```

Each Pi:

- Dials **out** to the tailnet (no inbound port needed, works behind CGNAT).
- Reaches the host's broker and Elasticsearch by **MagicDNS name**, not IP.
- Holds **no secrets on disk** — it fetches resolved config at startup via the
  Redis/HTTP backend in
  [WORKER-CONFIG-DISTRIBUTION.md](WORKER-CONFIG-DISTRIBUTION.md), now addressed over the
  tailnet instead of `10.0.0.x`.

---

## 4. Broker & Elasticsearch reachability over the tailnet

The only addressing change from the WireGuard design is swapping static VPN IPs for
MagicDNS names. Everything else in
[WORKER-CONFIG-DISTRIBUTION.md §10](WORKER-CONFIG-DISTRIBUTION.md#10-remote-worker-setup)
is unchanged.

| What | WireGuard design | Tailscale equivalent |
|---|---|---|
| Celery broker | `amqp://guest:guest@10.0.0.1:5672/` | `amqp://guest:guest@host.<tailnet>.ts.net:5672/` |
| Redis config store | `redis://10.0.0.1:6379/1` | `redis://host.<tailnet>.ts.net:6379/1` |
| HTTP config server | `http://10.0.0.1:8765` | `http://host.<tailnet>.ts.net:8765` |
| Elasticsearch | `http://10.0.0.1:9200` | `http://host.<tailnet>.ts.net:9200` |

The Pi's `.env/worker.env` (Redis mode), per
[WORKER-CONFIG-DISTRIBUTION.md §10.1](WORKER-CONFIG-DISTRIBUTION.md#101-create-workerenv-on-the-remote-machine):

```env
CONFIG_SOURCE=redis
CELERY_BROKER_URL=amqp://guest:guest@host.<tailnet>.ts.net:5672/
CONFIG_REDIS_URL=redis://host.<tailnet>.ts.net:6379/1
```

> **MagicDNS must be enabled** in the Tailscale admin console for `*.ts.net` names to
> resolve. If you prefer not to enable it, substitute the node's `100.x` Tailscale IP —
> it is stable for the lifetime of the node's enrolment.

Real hostnames and broker URLs are topology-leaking, so they belong in the gitignored
`machines.local.toml` and `.env/worker.env`, never in this committed doc — consistent
with the three-file split in
[WORKER-CONFIG-DISTRIBUTION.md §3](WORKER-CONFIG-DISTRIBUTION.md#3-the-three-file-config-split--appsenv-vs-machinestoml-vs-machineslocaltoml).

---

## 5. `machines.toml` — the `[rpi-node]` block

This PR adds a commented example block. A real Pi maps its bare hostname to a machine
name in the gitignored `machines.local.toml` (see the `[hostnames]` note in
`machines.toml`):

```toml
# ── Raspberry Pi edge node — pure worker over Tailscale ──────────────────────
[rpi-node]
role = "node"
# ARM-friendly headless queues. Keep the Pi off heavy `code` queues (bash/pytest
# builds) where VPS nodes are a better fit; let it take light agent + broadcast
# work and any edge-device bridging it hosts.
queues = ["default", "worker", "default_broadcast", "hfl_broadcast"]
kanban_profile = "agent:write"
```

`deploy.py` auto-detects the machine by `socket.gethostname()`, so the Pi's hostname maps
to `rpi-node` in `machines.local.toml`:

```toml
[hostnames]
"raspberrypi"        = "rpi-node"
"raspberrypi.local"  = "rpi-node"
```

---

## 6. Bootstrapping a Pi node

The reference script [`edge/rpi_node/bootstrap.sh`](../../edge/rpi_node/bootstrap.sh)
performs a first-time setup on a fresh Raspberry Pi OS (64-bit) install:

1. Install Tailscale and join the tailnet (`tailscale up`).
2. Install Python + git, clone the repo.
3. Write a minimal `.env/worker.env` pointing the broker/config at the host's MagicDNS
   name (so the Pi holds no secrets — see §4).
4. Start a Celery worker on the configured queues.

It mirrors the cloud-init bootstrap in
[VPS-CLUSTER-AGENT-DESIGN.md §9](VPS-CLUSTER-AGENT-DESIGN.md#9-recommended-starting-configuration),
with `tailscale up` replacing `wg-quick up wg0` and the conf-distribution step.

Run it once on the Pi:

```bash
curl -fsSL https://tailscale.com/install.sh | sh   # or: edge/rpi_node/bootstrap.sh handles this
sudo bash edge/rpi_node/bootstrap.sh
```

---

## 7. Connectivity: Wi-Fi vs LTE/5G

Tailscale runs over whatever default route the Pi has — `wlan0` (Wi-Fi) or `wwan0`
(a USB LTE modem / HAT). The mesh identity is independent of the underlying link:

- **Wi-Fi:** Pi on the home/office LAN. Direct peer-to-peer to the host when both are on
  the same network; otherwise via DERP.
- **LTE / 5G:** Pi with a USB cellular modem (e.g. SIM7600, Quectel EC25) or a HAT.
  Carriers use CGNAT, so the Pi has no reachable public IP — **this is exactly the case
  hand-rolled WireGuard cannot handle without a public relay.** Tailscale's DERP relays
  carry the return path, so the cellular Pi stays a first-class, SSH-reachable cluster
  node.

A Pi on LTE pairs naturally with the GPS/location and remote-telemetry edge workflows
(see the LTE fleet and sensor-telemetry PRs in the `edge/` tree).

---

## 8. Security model

- **No inbound ports.** The Pi only dials out to the tailnet; nothing needs to be
  port-forwarded, even on cellular.
- **No secrets on disk.** Config is fetched at startup over the tailnet via the
  Redis/HTTP backend (WORKER-CONFIG-DISTRIBUTION.md); the Pi keeps only the broker/config
  endpoint in `.env/worker.env`.
- **Tailnet ACLs.** Restrict which nodes the Pi can reach using Tailscale tags/grants —
  e.g. tag edge nodes `tag:edge` and grant them access only to the host's broker, Redis,
  and ES ports. This replaces the per-node iptables rules in
  [VPS-CLUSTER-AGENT-DESIGN.md §4.2](VPS-CLUSTER-AGENT-DESIGN.md#42-vps-firewall-rules).
- **Lost/stolen device.** Revoke the node in the Tailscale admin console; it immediately
  loses tailnet access without touching any other machine.

---

## 9. Use cases solved

| # | Use case | How this enables it |
|---|---|---|
| UC-1 | **Add a cheap on-prem worker without cloud cost** | A $35–$80 Pi joins the cluster as a `node`, taking light agent/broadcast work off the host. Marginal cost is electricity (~$3/mo), beating a VPS for steady on-prem load (cf. VPS-CLUSTER §7). |
| UC-2 | **Run a worker behind CGNAT / on cellular** | A Pi on LTE/5G has no public IP; Tailscale + DERP makes it a reachable cluster node anyway — impossible with the hand-rolled WireGuard model. |
| UC-3 | **Drop the WireGuard conf-distribution toil** | `tailscale up` replaces generating + SSH-distributing `wg0.conf` and maintaining the static `10.0.0.x` map. Onboarding a node goes from minutes of manual key/IP work to one command. |
| UC-4 | **Reach edge devices for management from anywhere** | Every tailnet node (including Pis at remote sites) is SSH-reachable by MagicDNS name regardless of network, so the `dumps` pull-targets and `sync-host` flows work to a Pi in the field. |
| UC-5 | **Host an ESP32 bridge / sensor gateway on-prem** | A Pi on the tailnet is the natural gateway for the sensor-telemetry and OwnTracks-over-LTE edge workflows — it relays leaf devices (which cannot run Tailscale) into the cluster. |
| UC-6 | **Revoke a compromised node instantly** | One click in the admin console removes tailnet access, vs hand-editing firewall/peer config across machines. |

---

## 10. Relationship to the existing cluster docs

This document **does not replace** the WireGuard design — it offers Tailscale as the
recommended transport for edge nodes while leaving the WireGuard design intact for
operators who prefer self-hosted VPN.

- [VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md) — the full orchestrator +
  worker-pool design (WireGuard §4, hybrid VPS/N100 §10). A Pi node slots into §10 as
  another worker type; Tailscale replaces the §4 networking.
- [WORKER-CONFIG-DISTRIBUTION.md](WORKER-CONFIG-DISTRIBUTION.md) — how a secret-less
  worker fetches resolved config at startup. Unchanged; only the broker/config/ES
  addresses become MagicDNS names (§4 above).
