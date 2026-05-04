# Worker Config Distribution — Centralising `apps.env` + `apps_config.yaml` on the Host

**Related:** [VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md)  
**Date:** 2026-04-27

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [How Config Is Loaded (Current vs. Remote)](#2-how-config-is-loaded-current-vs-remote)
3. [Architecture Overview](#3-architecture-overview)
4. [Backend A — Redis Config Store](#4-backend-a--redis-config-store)
5. [Backend B — HTTP Config Server](#5-backend-b--http-config-server)
6. [Choosing a Backend](#6-choosing-a-backend)
7. [Environment Variables Reference](#7-environment-variables-reference)
8. [Host Setup](#8-host-setup)
9. [Remote Worker Setup](#9-remote-worker-setup)
10. [Security Model](#10-security-model)
11. [Script Reference](#11-script-reference)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Problem Statement

In the distributed Celery setup, each worker node currently requires local copies of:

- `.env/apps.env` — all API keys, tokens, passwords
- `apps_config.yaml` — service configuration with `${PLACEHOLDER}` references

Copying these to every worker node:
- Creates multiple copies of sensitive credentials on different machines
- Requires manual sync whenever secrets rotate or config changes
- Makes the secrets surface area proportional to the number of workers

**Goal:** Keep both files exclusively on the host machine. Worker nodes receive only the resolved config at startup, over an already-trusted network channel.

---

## 2. How Config Is Loaded (Current vs. Remote)

### Current (local) loading chain

```
.env/apps.env  ──── shell sources ────▶  OS environment vars
                                               │
apps_config.yaml ── ConfigFileYaml.load() ─────▶  ${PLACEHOLDER} replaced by os.getenv()
                                               │
                                         Python dict (resolved)
                                               │
                                         AppConfigManager._current_app_configs
                                               │
                                         CONFIG_MANAGER.get('OANDA') ──▶ task uses it
```

### Remote loading chain

```
HOST ONLY:
  .env/apps.env + apps_config.yaml
        │  resolved once at push/serve time
        ▼
  Python dict (all ${...} substituted)
        │
        ├─── Redis backend ──▶  SET harqis:config <JSON blob>
        │
        └─── HTTP backend  ──▶  GET /config → JSON response

WORKER (no local files needed):
  CONFIG_SOURCE=redis or http
        │  fetched at Python import time (apps/apps_config.py)
        ▼
  Python dict (same resolved dict)
        │
  AppConfigManager._current_app_configs
        │
  CONFIG_MANAGER.get('OANDA') ──▶ task uses it
```

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  HOST MACHINE  (Mac Mini / on-premise server)                               │
│                                                                             │
│  .env/apps.env          apps_config.yaml                                    │
│       │                       │                                             │
│       └──── resolved once ────┘                                             │
│                   │                                                         │
│          ┌────────┴────────┐                                                │
│          │                 │                                                │
│   ┌──────▼──────┐   ┌──────▼──────┐                                         │
│   │  Redis      │   │  HTTP       │   ← choose one (or both)                │
│   │  DB 1       │   │  server     │                                         │
│   │  :6379/1    │   │  :8765      │                                         │
│   └──────┬──────┘   └──────┬──────┘                                         │
│          │                 │                                                │
└──────────┼─────────────────┼────────────────────────────────────────────────┘
           │   VPN / network │
┌──────────┼─────────────────┼───────────────────────────────────────────────┐
│  REMOTE WORKERS            │                                               │
│                            │                                               │
│  ┌──────────────────┐  ┌───▼──────────────────┐                            │
│  │  Worker Node A   │  │  Worker Node B       │   ...                      │
│  │  CONFIG_SOURCE   │  │  CONFIG_SOURCE=http  │                            │
│  │    =redis        │  │  → fetch at startup  │                            │
│  │  → fetch at      │  │  → no apps.env       │                            │
│  │    startup       │  │  → no apps_config    │                            │
│  └──────────────────┘  └──────────────────────┘                            │
│                                                                            │
│  Workers only need:                                                        │
│    CONFIG_SOURCE + connection vars (Redis URL or HTTP URL + token)         │
│    CELERY_BROKER_URL (host RabbitMQ over VPN)                              │
└────────────────────────────────────────────────────────────────────────────┘
```

## 4. Backend A — Redis Config Store

The host resolves all config once and writes it as a JSON blob to a dedicated Redis key (separate DB from the Celery result backend). Workers read the key at startup.

**Pros:**
- Redis is already in the stack (Celery result backend)
- Workers already connect to Redis — no new firewall rules
- Zero extra process to keep alive
- Config is updated instantly on next worker restart after a re-push

**Cons:**
- Resolved secrets stored in Redis (at rest, unencrypted by default)
- Requires `redis>=5.0.0` installed on the host push machine
- Config snapshot is static until re-pushed (workers do not auto-reload)

**Required env vars on workers:**

| Variable | Description |
|---|---|
| `CONFIG_SOURCE` | `redis` |
| `CONFIG_REDIS_URL` | Redis URL, e.g. `redis://10.0.0.1:6379/1` (use DB ≥ 1) |
| `CONFIG_REDIS_KEY` | Optional. Key name. Default: `harqis:config` |
| `CELERY_BROKER_URL` | Host RabbitMQ URL |

**Mitigate Redis at-rest risk:** Enable Redis `requirepass` in your Docker Compose:

```yaml
redis:
  command: redis-server --requirepass ${REDIS_PASSWORD}
```

Then use `redis://:${REDIS_PASSWORD}@10.0.0.1:6379/1` as `CONFIG_REDIS_URL`.

---

## 5. Backend B — HTTP Config Server

The host loads config and starts a FastAPI server that responds to `GET /config` with the resolved dict as JSON. Workers fetch from it at startup over an authenticated HTTPS/HTTP connection.

**Pros:**
- Config is served fresh on every worker restart (no Redis state to manage)
- Easy to scope per-worker if needed (extend `/config/{worker_id}` later)
- Bearer token auth; easy to add TLS (nginx reverse proxy or Cloudflare Tunnel)
- No Redis required on workers

**Cons:**
- Requires a long-running process on the host (manage with LaunchAgent / systemd)
- Workers fail to start if the server is down
- One more service to monitor

**Required env vars on workers:**

| Variable | Description |
|---|---|
| `CONFIG_SOURCE` | `http` |
| `CONFIG_SERVER_URL` | e.g. `http://10.0.0.1:8765` |
| `CONFIG_SERVER_TOKEN` | Bearer token (must match the server's token) |
| `CELERY_BROKER_URL` | Host RabbitMQ URL |

**Available endpoints:**

| Endpoint | Auth | Response |
|---|---|---|
| `GET /config` | Bearer token | Full resolved config JSON |
| `GET /health` | None | `{"status":"ok","sections":[...]}` |

---

## 6. Choosing a Backend

| Situation | Recommendation |
|---|---|
| Redis is already accessible from workers (WireGuard VPN) | **Redis** — zero extra infra |
| Workers are ephemeral / frequently recycled | **Redis** — always-current snapshot on next restart |
| You want per-worker config scoping in the future | **HTTP** — easier to extend the server |
| You want TLS-encrypted config delivery | **HTTP** — put nginx/Cloudflare in front |
| Host machine uptime is unreliable | **Redis** — survives host restarts (data persists) |
| You want to avoid secrets at rest in Redis | **HTTP** — config lives only in server RAM |

You can run **both** simultaneously — some workers use Redis, others use HTTP. The `CONFIG_SOURCE` env var is per-process.

---

## 7. Environment Variables Reference

### Host machine

| Variable | Default | Description |
|---|---|---|
| `CONFIG_SOURCE` | `local` | Leave as `local` on the host |
| `CELERY_BROKER_URL` | `amqp://guest:guest@localhost:5672/` | Local RabbitMQ URL |
| `REMOTE_BROKER_URL` | *(unset)* | Set this to the VPN/network address when pushing config for remote workers |
| `CONFIG_REDIS_URL` | `redis://localhost:6379/1` | Redis URL for config store |
| `CONFIG_REDIS_KEY` | `harqis:config` | Redis key for the config blob |
| `CONFIG_SERVER_TOKEN` | *(none)* | Bearer token for the HTTP server |
| `CONFIG_SERVER_PORT` | `8765` | HTTP server port |

### Remote worker nodes

| Variable | Required | Description |
|---|---|---|
| `CONFIG_SOURCE` | Yes | `redis` or `http` |
| `CELERY_BROKER_URL` | Yes | Host RabbitMQ URL (VPN address) |
| `CONFIG_REDIS_URL` | Redis only | Redis URL on host |
| `CONFIG_REDIS_KEY` | No | Key name (default: `harqis:config`) |
| `CONFIG_SERVER_URL` | HTTP only | HTTP server base URL |
| `CONFIG_SERVER_TOKEN` | HTTP only | Bearer token |

---

## 8. Host Setup

### 8.1 Install redis-py (for Redis backend)

```bash
.venv/bin/pip install 'redis>=5.0.0'
```

This is already added to `requirements.txt`.

### 8.2 Parameterise the Celery broker URL

`apps_config.yaml` now uses `${CELERY_BROKER_URL}` for the broker field.
Env loading is handled automatically by `scripts/launch.py` (defaults to `localhost` for local runs).

When pushing config for remote workers, set `REMOTE_BROKER_URL` to the address
that workers will use to reach RabbitMQ (typically the host's VPN/LAN IP):

```bash
export REMOTE_BROKER_URL="amqp://guest:guest@10.0.0.1:5672/"
python scripts/launch.py push-config
```

### 8.3 Push config to Redis (Backend A)

```bash
# On the host, after any change to apps.env or apps_config.yaml:
export REMOTE_BROKER_URL="amqp://guest:guest@10.0.0.1:5672/"
python scripts/launch.py push-config

# Custom Redis URL:
python scripts/launch.py push-config --redis-url redis://10.0.0.1:6379/1 --key harqis:config
```

### 8.4 Start the HTTP config server (Backend B)

```bash
# Generate a strong token once:
export CONFIG_SERVER_TOKEN="$(openssl rand -hex 32)"
echo "Token: $CONFIG_SERVER_TOKEN"   # save this for workers

export REMOTE_BROKER_URL="amqp://guest:guest@10.0.0.1:5672/"
python scripts/launch.py serve-config --port 8765 --token "$CONFIG_SERVER_TOKEN"
```

To keep it running as a daemon, add a LaunchAgent plist (macOS) or systemd unit (Linux) similar to the existing scheduler/worker plists.

---

## 9. Remote Worker Setup

### 9.1 Create worker.env on the remote machine

```bash
# On the remote worker node:
cp .env/worker.env.example .env/worker.env
nano .env/worker.env   # fill in host IP + token
```

Minimum content for **Redis mode**:

```env
CONFIG_SOURCE=redis
CELERY_BROKER_URL=amqp://guest:guest@10.0.0.1:5672/
CONFIG_REDIS_URL=redis://10.0.0.1:6379/1
```

Minimum content for **HTTP mode**:

```env
CONFIG_SOURCE=http
CELERY_BROKER_URL=amqp://guest:guest@10.0.0.1:5672/
CONFIG_SERVER_URL=http://10.0.0.1:8765
CONFIG_SERVER_TOKEN=<token from host>
```

### 9.2 Start a worker (cross-platform)

```bash
# Default queue:
python scripts/launch.py worker

# TCG queue:
python scripts/launch.py worker --queues tcg

# HUD queue:
python scripts/launch.py worker --queues hud
```

### 9.3 Verify config loaded correctly

```bash
# Quick smoke test on the remote node (CONFIG_SOURCE merged into launch.py — set CONFIG_SOURCE in apps.env):
cd <repo-root>
source .venv/bin/activate
python -c "from apps.apps_config import CONFIG_MANAGER; print(list(CONFIG_MANAGER._current_app_configs.keys()))"
```

Expected output: list of all config section names (OANDA, HARQIS_GPT, etc.).

---

## 10. Security Model

### What stays on the host only

| Asset | Location |
|---|---|
| `.env/apps.env` | Host disk only — never copied to workers |
| `apps_config.yaml` | Host disk only — never copied to workers |
| Raw API keys / tokens | Host env only — resolved at push/serve time |

### What workers receive

| Asset | How | At rest on worker |
|---|---|---|
| Resolved config dict | Redis GET or HTTP GET | RAM only — no disk write |
| Celery broker URL | Included in resolved dict | RAM only |
| Application secrets | Included in resolved dict as resolved values | RAM only |

### Threat surface comparison

| Scenario | Legacy (local files) | Redis backend | HTTP backend |
|---|---|---|---|
| Secrets on worker disk | Yes (apps.env file) | No | No |
| Secrets in transit | No (local read) | JSON over TCP/VPN | JSON over HTTP/VPN |
| Secrets at rest in store | N/A | Redis key (plaintext) | Server RAM only |
| Exposure if worker compromised | Full apps.env | Full resolved dict | Full resolved dict |
| Exposure if store compromised | N/A | Full resolved dict | N/A (RAM only) |

### Hardening recommendations

1. **Redis backend:** Enable `requirepass` in Redis and use an authenticated URL.
2. **HTTP backend:** Set `CONFIG_SERVER_TOKEN` to a random 32+ byte hex string.
3. **Both:** Run all inter-node traffic over WireGuard VPN — no public internet exposure.
4. **Both:** Consider running Redis on DB ≥ 1 (separate from Celery result backend on DB 0).
5. **Rotate:** Re-push config to Redis / restart HTTP server whenever secrets change.

---

## 11. Script Reference

### Host scripts

| Command | Purpose |
|---|---|
| `python scripts/launch.py push-config` | Resolve config + push to Redis |
| `python scripts/launch.py serve-config` | Resolve config + start HTTP server |

### Remote worker commands

| Command | Queue |
|---|---|
| `python scripts/launch.py worker` | default |
| `python scripts/launch.py worker --queues tcg` | tcg |
| `python scripts/launch.py worker --queues hud` | hud |

(CONFIG_SOURCE is read from `.env/apps.env` — merged into launch.py.)

### Python module CLI

```bash
# Push resolved config to Redis
python -m apps.config_remote push-redis --redis-url redis://10.0.0.1:6379/1 --key harqis:config

# Start HTTP config server
python -m apps.config_remote serve-http --port 8765 --token <token> --host 0.0.0.0
```

---

## 12. Troubleshooting

### Worker fails with "Config key not found in Redis"

```
RuntimeError: Config key 'harqis:config' not found in Redis at redis://...
```

**Fix:** Run `python scripts/launch.py push-config` on the host first, then restart the worker.

---

### Worker fails with "Config server rejected the bearer token"

```
PermissionError: Config server rejected the bearer token.
```

**Fix:** Ensure `CONFIG_SERVER_TOKEN` on the worker matches the value passed to `python scripts/launch.py serve-config --token`.

---

### Apps still use localhost broker on remote workers

**Symptom:** Tasks dispatch but never arrive at the remote worker; Flower shows 0 active workers.

**Cause:** `CELERY_BROKER_URL` was not set to the host's VPN/network address before pushing config. The config blob contains `amqp://localhost/`.

**Fix:**
```bash
export REMOTE_BROKER_URL="amqp://guest:guest@10.0.0.1:5672/"
python scripts/launch.py push-config   # re-push with correct broker URL
# Then restart all remote workers
```

---

### CONFIG_SOURCE=local on a remote worker (misconfiguration)

**Symptom:** Worker starts but uses empty or wrong config (reads local `apps_config.yaml` which may not exist or is a stale copy).

**Fix:** Ensure `.env/worker.env` sets `CONFIG_SOURCE=redis` or `CONFIG_SOURCE=http`, not `local`.

---

### Verify what's in the Redis config key

```bash
# On any machine with redis-cli or redis-py:
redis-cli -u redis://10.0.0.1:6379/1 GET harqis:config | python3 -m json.tool | head -30
```
