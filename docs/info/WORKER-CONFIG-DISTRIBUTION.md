# Worker Config Distribution — Centralising `apps.env` + `apps_config.yaml` on the Host

**Related:** [VPS-CLUSTER-AGENT-DESIGN.md](VPS-CLUSTER-AGENT-DESIGN.md) · [EDGE-TAILSCALE-NODE.md](EDGE-TAILSCALE-NODE.md) (over the tailnet, the broker/config/ES addresses below become MagicDNS names — see its §4)  
**Date:** 2026-04-27

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [How Config Is Loaded (Current vs. Remote)](#2-how-config-is-loaded-current-vs-remote)
3. [The Three-File Config Split — `apps.env` vs `machines.toml` vs `machines.local.toml`](#3-the-three-file-config-split--appsenv-vs-machinestoml-vs-machineslocaltoml)
4. [Architecture Overview](#4-architecture-overview)
5. [Backend A — Redis Config Store](#5-backend-a--redis-config-store)
6. [Backend B — HTTP Config Server](#6-backend-b--http-config-server)
7. [Choosing a Backend](#7-choosing-a-backend)
8. [Environment Variables Reference](#8-environment-variables-reference)
9. [Host Setup](#9-host-setup)
10. [Remote Worker Setup](#10-remote-worker-setup)
11. [Security Model](#11-security-model)
12. [Script Reference](#12-script-reference)
13. [Troubleshooting](#13-troubleshooting)

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

## 3. The Three-File Config Split — `apps.env` vs `machines.toml` vs `machines.local.toml`

Before the remote-distribution machinery in §4+ becomes relevant, every machine
already runs against a **three-file local config split**. Understanding which
file a variable belongs in is the foundation for everything that follows —
remote distribution only transports the *resolved* values; the source split
stays the same.

### 3.1 What each file is for

| File | Committed? | Read by | Granularity | Right for |
|---|---|---|---|---|
| `.env/apps.env` | **No** (gitignored) | `pytest.ini`, `scripts/launch.py`, every daemon process via `os.getenv()` | Process-wide; **single value** that applies to every machine that reads this file | Secrets (API keys, passwords, tokens) + values genuinely shared cluster-wide |
| `machines.toml` | **Yes** | `scripts/deploy.py` only — read once at boot, then passed to daemons as CLI flags | Per-machine `[<machine-name>]` blocks; fields can differ per host | Public per-machine knobs (queues, role, concurrency, disabled services, kanban tuning) |
| `machines.local.toml` | **No** (gitignored, sits next to `machines.toml`) | `scripts/deploy.py` — merged on top of `machines.toml` at load time | Same as `machines.toml`; values here win | Per-machine paths, hostnames, ports, and anything that leaks deployment topology |

`deploy.py` merges the two TOML files via `_merge_machines()`: keys in the
local file override keys in the committed file; nested tables (like
`[hostnames]` or `[<machine>]`) merge inner keys rather than replacing the
whole block.

### 3.2 Decision tree — which file does this variable belong in?

```
Is it a secret? (API key, OAuth token, password, bearer)
    └── Yes  →  .env/apps.env       (no exception)
    └── No   →  ↓

Does it identify a specific host or filesystem path?
  (e.g. "harqis-ones-mac-mini", "C:\Users\…", "G:\My Drive\…")
    └── Yes  →  machines.local.toml (gitignored, topology-leaking)
    └── No   →  ↓

Does it vary per machine but is safe to publish?
  (queue list, concurrency, poll interval, dry-run flag, role)
    └── Yes  →  machines.toml       (committed, diffable, per-[machine] block)
    └── No   →  ↓

Is it a cluster-wide constant?
  (APP_CONFIG_FILE, WORKFLOW_CONFIG, KANBAN_TELEMETRY_INDEX, …)
    └── Yes  →  .env/apps.env       (or a shared block in machines.toml)
```

### 3.3 The reference pattern — `kanban_num_agents`

The cleanest example of an env-var → TOML migration that already shipped:

1. **Before:** `KANBAN_NUM_AGENTS=4` lived in `apps.env`. The same line meant
   the same number for every machine that sourced this file; tuning one box
   meant hand-editing the file on that box.
2. **After:** Each `[machine]` block in `machines.toml` can carry its own
   `kanban_num_agents = N`. `deploy.py:411` reads it and passes
   `--num-agents N` to `launch.py`. `launch.py:229` still consults the env
   var as a fallback for hand-launched workers, so the env var isn't broken —
   it's just no longer the source of truth.
3. **Diff story:** Bumping concurrency on one box is now a normal commit
   (`chore(repo): set kanban_num_agents=4 on harqis-server`) rather than a
   "hand-edit-this-on-each-box" event.

The same pattern fits any per-machine numeric/boolean/list knob:
`kanban_profile`, `kanban_poll_interval`, `kanban_dry_run`,
`workflow_autoreload`, `rabbit_port`, etc. Implementation cost per variable
is: add a field to the relevant `[machine]` block + read it in
`build_service_cmd()` (or wherever the daemon is spawned) + drop a CLI flag
or env-var into the child process.

### 3.4 Current categorisation of `apps.env`

Walking the existing `.env/apps.env` top-to-bottom, here is where each
section *should* live. "Move" means a future migration; the file is correct
as it stands today, but these are the migration targets if you want to
shrink the secrets surface area.

| Section in `apps.env` | Action | Notes |
|---|---|---|
| **Platform / Harness** (`APP_CONFIG_FILE`, `WORKFLOW_CONFIG`) | Keep in env | Effectively constants; could become code defaults |
| `WORKFLOW_AUTORELOAD` | **Move to `machines.toml`** | Dev-only flag; per-machine boolean |
| **Local Python env** (`PYTHON_EXE`, `ENV_ROOT`) | **Move to `machines.local.toml`** | Pure filesystem topology; `deploy.py` already auto-detects the venv python |
| **Infrastructure** — `DOCKER_HOST_PORT_RABBIT_MQ` | **Move to `machines.toml`** | Port differs between boxes (15000 vs 15672) |
| `CELERY_BROKER`, `ELASTIC_HOST`, `KIBANA_HOST` | **Move to `machines.local.toml`** | Hostnames like `harqis-ones-mac-mini` leak topology |
| `ELASTIC_*_PASSWORD`, `KIBANA_*_PASSWORD`, `FLOWER_PASSWORD`, `NGROK_AUTHTOKEN` | Keep in env | Secrets |
| **AI providers**, **Finance**, **TCG**, **Communication tokens**, **Productivity tokens**, **Social**, **Workflow tokens** | Keep in env | API keys / OAuth / bearer tokens |
| `TCG_SAVE`, `SCRY_DOWNLOADS_PATH` | **Move to `machines.local.toml`** | Per-machine paths |
| **Desktop / HUD (Windows-only)** — all `RAINMETER_*`, `ACTIONS_*`, `DESKTOP_PATH_*`, `OWN_TRACKS_HOST`/`PORT` | **Move to `machines.local.toml`** | Strongest migration candidate — none are secrets, all only apply to the Windows box; group under `[<windows-machine>.rainmeter]`, `[<windows-machine>.actions]`, `[<windows-machine>.desktop_paths]` |
| `OWN_TRACKS_USERNAME`/`PASSWORD` | Keep in env | Secrets (when set) |
| `TELEGRAM_DEFAULT_CHAT_ID`, `DISCORD_DEFAULT_GUILD_ID`/`CHANNEL_ID` | **Move to `machines.toml`** | Non-secret routing IDs; either shared default or per-machine |
| **Kanban orchestrator** — `KANBAN_NUM_AGENTS`, `KANBAN_PROFILE_FILTER` | Already migrated | `kanban_num_agents` / `kanban_profile` in `machines.toml`; env var remains as hand-launch fallback |
| `KANBAN_POLL_INTERVAL`, `KANBAN_DRY_RUN` | **Move to `machines.toml`** | Same pattern as `kanban_num_agents` |
| `KANBAN_PROFILES_DIR`, `KANBAN_AUDIT_LOG` | **Move to `machines.local.toml`** | Per-machine paths (if used) |
| `KANBAN_TELEMETRY_INDEX` | Keep in env or shared `[kanban]` block | Cluster-wide constant |
| `KANBAN_OS_LABELS` | Keep in env | Auto-detected at runtime |
| `TRELLO_WORKSPACE_ID` / `TRELLO_BOARD_IDS` / `KANBAN_BOARD_ID` | Keep in env | Credentials-adjacent — co-located with `TRELLO_API_KEY` |
| `TRELLO_BOARD_NAME_FILTER`/`EXCLUDE`, `TRELLO_REDISCOVER_SECONDS` | **Move to shared `[kanban]` block in `machines.toml`** | Public tuning knobs |

### 3.5 Wins from the migration

- **Smaller secrets surface area** — Windows-only paths and Kanban tunables
  leave `apps.env` entirely, so the file becomes "secrets + shared cluster
  defaults" rather than "secrets + per-machine kitchen sink."
- **Per-machine config is addressable** — no more "ship the same `apps.env`
  to every box and hand-edit one section." TOML blocks are merge-friendly
  and reviewable in PRs.
- **Ops history is diffable** — bumping `kanban_num_agents` or rotating a
  queue assignment becomes a normal commit on `main`, not a tribal-knowledge
  edit on one machine.
- **Remote distribution (§4+) gets simpler** — fewer values to resolve and
  push, because per-machine values are already addressed by the local TOML
  merge instead of needing to be parameterised in the resolved config blob.

### 3.6 Cost / friction

`apps_config.yaml`'s `${PLACEHOLDER}` resolver today only reads from
`os.getenv()`. Two pragmatic migration paths:

1. **`deploy.py`-driven (cheap, in use):** read `machines.toml`, generate the
   relevant env vars / CLI flags at launch time, and let `launch.py` keep its
   current `os.environ.get()` calls. This is how `kanban_num_agents` works
   today — the daemon never knows it came from TOML.
2. **Resolver-aware (later, if needed):** teach `AppConfigManager` (or a thin
   wrapper around it) to also read from `machines.toml` for non-env-backed
   values. Required only if a value needs to appear inside
   `apps_config.yaml`'s placeholders rather than as a flag on the daemon
   process.

Stick with path 1 for new migrations. It's strictly additive (the env-var
fallback keeps working) and requires no changes to the config loader.

---

## 4. Architecture Overview

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

## 5. Backend A — Redis Config Store

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

## 6. Backend B — HTTP Config Server

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

## 7. Choosing a Backend

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

## 8. Environment Variables Reference

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

## 9. Host Setup

### 9.1 Install redis-py (for Redis backend)

```bash
.venv/bin/pip install 'redis>=5.0.0'
```

This is already added to `requirements.txt`.

### 9.2 Parameterise the Celery broker URL

`apps_config.yaml` now uses `${CELERY_BROKER_URL}` for the broker field.
Env loading is handled automatically by `scripts/launch.py` (defaults to `localhost` for local runs).

When pushing config for remote workers, set `REMOTE_BROKER_URL` to the address
that workers will use to reach RabbitMQ (typically the host's VPN/LAN IP):

```bash
export REMOTE_BROKER_URL="amqp://guest:guest@10.0.0.1:5672/"
python scripts/launch.py push-config
```

### 9.3 Push config to Redis (Backend A)

```bash
# On the host, after any change to apps.env or apps_config.yaml:
export REMOTE_BROKER_URL="amqp://guest:guest@10.0.0.1:5672/"
python scripts/launch.py push-config

# Custom Redis URL:
python scripts/launch.py push-config --redis-url redis://10.0.0.1:6379/1 --key harqis:config
```

### 9.4 Start the HTTP config server (Backend B)

```bash
# Generate a strong token once:
export CONFIG_SERVER_TOKEN="$(openssl rand -hex 32)"
echo "Token: $CONFIG_SERVER_TOKEN"   # save this for workers

export REMOTE_BROKER_URL="amqp://guest:guest@10.0.0.1:5672/"
python scripts/launch.py serve-config --port 8765 --token "$CONFIG_SERVER_TOKEN"
```

To keep it running as a daemon, add a LaunchAgent plist (macOS) or systemd unit (Linux) similar to the existing scheduler/worker plists.

---

## 10. Remote Worker Setup

### 10.1 Create worker.env on the remote machine

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

### 10.2 Start a worker (cross-platform)

```bash
# Default queue:
python scripts/launch.py worker

# TCG queue:
python scripts/launch.py worker --queues tcg

# HUD queue:
python scripts/launch.py worker --queues hud
```

### 10.3 Verify config loaded correctly

```bash
# Quick smoke test on the remote node (CONFIG_SOURCE merged into launch.py — set CONFIG_SOURCE in apps.env):
cd <repo-root>
source .venv/bin/activate
python -c "from apps.apps_config import CONFIG_MANAGER; print(list(CONFIG_MANAGER._current_app_configs.keys()))"
```

Expected output: list of all config section names (OANDA, HARQIS_GPT, etc.).

---

## 11. Security Model

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

## 12. Script Reference

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

## 13. Troubleshooting

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
