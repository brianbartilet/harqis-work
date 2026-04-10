# VPS Cluster Agent Design — Mac Mini Orchestrator + Cloud Worker Nodes

**Related:** [TRELLO-AGENT-KANBAN.md](TRELLO-AGENT-KANBAN.md)  
**Date:** 2026-04-10

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Component Design](#3-component-design)
4. [Networking and Security](#4-networking-and-security)
5. [Scaling Model](#5-scaling-model)
6. [Cost Analysis](#6-cost-analysis)
7. [Comparison: VPS vs N100 Nodes](#7-comparison-vps-vs-n100-nodes)
8. [Risks and Mitigations](#8-risks-and-mitigations)
9. [Recommended Starting Configuration](#9-recommended-starting-configuration)
10. [Hybrid Topology: VPS + N100 Windows Nodes](#10-hybrid-topology-vps--n100-windows-nodes)

---

## 1. Overview

This document designs a distributed Kanban agent cluster where:

- **Orchestrator:** Mac Mini (on-premise, always-on) — holds all secrets, polls the Kanban board, routes tasks, and runs Windows/macOS-specific workloads (Rainmeter HUD, desktop tools)
- **Worker nodes:** Cloud VPS instances — stateless Linux workers that execute agent tasks and scale on demand

This replaces the original N100 mini-PC worker nodes with cloud VPS instances, trading fixed hardware cost for elastic pay-per-use compute.

```
Human → Trello / Jira Card
            │
            ▼
    ┌───────────────────┐
    │   Mac Mini M4     │  ← On-premise orchestrator
    │   (Orchestrator)  │     Secrets vault
    │                   │     Board polling
    │   Redis (broker)  │     Profile resolution
    │   FastAPI webhook │     Task dispatch
    └────────┬──────────┘
             │  Celery tasks over encrypted WireGuard tunnel
             │
    ┌────────┴──────────────────────────────────────┐
    │              Cloud VPS Worker Pool             │
    │                                               │
    │  ┌──────────────┐  ┌──────────────┐          │
    │  │  VPS Node 1  │  │  VPS Node 2  │  ...     │
    │  │  agent:code  │  │  agent:write │          │
    │  │  2 vCPU/4GB  │  │  2 vCPU/4GB  │          │
    │  └──────────────┘  └──────────────┘          │
    │                                               │
    │  Auto-scaled: add/remove nodes on demand      │
    └───────────────────────────────────────────────┘
             │
             ▼
    External Services
    (Anthropic API, Trello, Jira, GitHub, Gmail, …)
```

---

## 2. Architecture

### 2.1 Data Flow

```
1. Human places card in Backlog (Trello / Jira)
2. Orchestrator (Mac Mini) polls every 30s or receives webhook
3. Profile matched by card label (agent:code, agent:write, …)
4. SecretStore scopes only declared env-vars for that profile
5. Scoped secrets encrypted with Fernet key (orchestrator-only)
6. Celery task dispatched to worker queue with encrypted payload
7. Worker VPS decrypts payload, sets scoped env, runs agent loop
8. Agent calls Anthropic API + MCP tools (Jira, Gmail, etc.)
9. Result posted as card comment, card moved to Done
10. Audit log written; secrets discarded from worker memory
```

### 2.2 Process Map per Node

```
VPS Worker Node
├── celery worker  (harqis-core SPROUT)
│     ├── queue: code    → agent:code tasks
│     ├── queue: write   → agent:write tasks
│     └── queue: default → any unspecialised task
├── Docker (optional)    → isolated sandbox per task
└── WireGuard            → encrypted tunnel to Mac Mini
```

### 2.3 Orchestrator Responsibilities (Mac Mini only)

| Responsibility | Tool |
|----------------|------|
| Board polling / webhook | FastAPI + APScheduler |
| Profile resolution | YAML profile registry |
| Secret vault | macOS Keychain / HashiCorp Vault |
| Task dispatch | Celery → Redis broker |
| Secret encryption for workers | Fernet (symmetric key on Mac Mini only) |
| Health monitoring | Periodic ping; dead node → card back to Backlog |
| Result aggregation | Writes comment + moves card |
| Windows/macOS desktop tasks | Runs locally (Rainmeter HUD, iCUE, etc.) |

---

## 3. Component Design

### 3.1 Mac Mini — Orchestrator

**Minimum spec:** Mac Mini M4, 16 GB RAM, 256 GB SSD  
**Role:** Always-on, on-premise hub. Never runs heavy agent compute.

Services running on the Mac Mini:

| Service | Port | Purpose |
|---------|------|---------|
| Redis | 6379 | Celery broker (local, not exposed externally) |
| FastAPI (orchestrator) | 8000 | Webhook receiver, health API |
| Flower | 5555 | Celery monitoring UI |
| WireGuard | 51820/UDP | VPN server — workers connect in |

The Fernet encryption key for scoped secrets lives **only** on the Mac Mini, stored in macOS Keychain. Workers receive an encrypted payload blob and a one-time symmetric key fragment — they cannot reconstruct the master key.

### 3.2 VPS Worker Nodes

Each worker is a stateless Linux VPS. Workers are interchangeable — any worker can handle any queue it is subscribed to.

**Bootstrap (first-time per node):**
```sh
# On worker VPS
git clone https://github.com/brianbartilet/harqis-work.git
pip install -r requirements.txt

# Join VPN
sudo wg-quick up wg0   # config distributed by orchestrator

# Register as Celery worker
celery -A workflows.config worker --loglevel=info -Q code,default
```

**Per-task lifecycle:**
```
Receive encrypted Celery task
  → Decrypt scoped secrets (Fernet, key from orchestrator)
  → Set env vars in-process only
  → Run BaseKanbanAgent loop
  → Post result via Trello/Jira MCP tool
  → Clear secrets from memory
  → Worker ready for next task
```

Workers have **no persistent secrets** — no `.env` file, no credentials stored on disk. Everything arrives encrypted in the task payload and is discarded after the agent completes.

### 3.3 Redis Broker (on Mac Mini)

Redis runs locally on the Mac Mini and is **not** exposed to the internet. Workers reach it over the WireGuard VPN tunnel.

```
Mac Mini:6379 ← accessible only via VPN (wg0 interface)
```

For higher availability, Redis can be replaced with a managed Redis service (Upstash, Redis Cloud free tier) — this removes the single-point-of-failure dependency on the Mac Mini being online.

### 3.4 Secret Distribution Model

```
Mac Mini (Fernet master key in Keychain)
  │
  ├── At task dispatch:
  │     scoped_secrets = SecretStore.scoped_for_profile(profile)
  │     payload = Fernet(master_key).encrypt(json(scoped_secrets))
  │
  └── Worker receives:
        encrypted_payload → decrypt → inject into agent env → discard
```

Workers never see: the master Fernet key, the full `.env/apps.env`, or any secret not declared in the profile's `secrets.required` list.

---

## 4. Networking and Security

### 4.1 WireGuard VPN Topology

```
Mac Mini (WireGuard server, 10.0.0.1)
  ├── VPS Node 1  (10.0.0.2)
  ├── VPS Node 2  (10.0.0.3)
  ├── VPS Node 3  (10.0.0.4)
  └── VPS Node N  (10.0.0.N)
```

All inter-node traffic (Redis, Celery, health checks) goes over the VPN. VPS nodes have no open inbound ports except the WireGuard UDP port (51820). External API calls (Anthropic, Trello, Jira) go directly from the worker over the public internet — no need to route through the Mac Mini.

### 4.2 VPS Firewall Rules

```
Inbound:  51820/UDP (WireGuard only)
Outbound: 443/TCP   (Anthropic, Trello, Jira, Gmail, etc.)
          6379/TCP  (Redis — over VPN interface only)
```

### 4.3 Mac Mini Firewall Rules

```
Inbound:  51820/UDP (WireGuard — from VPS nodes)
          6379/TCP  (Redis — VPN interface only, never public)
          8000/TCP  (FastAPI webhook — optionally behind Cloudflare Tunnel)
Outbound: 443/TCP   (Trello/Jira polling, Anthropic API)
```

### 4.4 Trello Webhook (optional, replaces polling)

Replace the 30-second poll loop with a Trello webhook for near-instant card pickup:

```
Trello → HTTPS POST → Cloudflare Tunnel → Mac Mini FastAPI :8000/webhook
```

Cloudflare Tunnel (`cloudflared`) exposes the local FastAPI endpoint publicly without opening a port or needing a static IP. Free tier is sufficient.

---

## 5. Scaling Model

### 5.1 Horizontal Scaling

Add a worker VPS when:
- Queue depth > N tasks consistently for > 10 minutes
- Worker CPU > 80% sustained
- Agent iteration latency degrades

Remove a worker VPS when:
- Queue depth = 0 and worker idle > 30 minutes

With VPS providers like Hetzner or Vultr, node spin-up takes ~60 seconds — fast enough for reactive scaling.

### 5.2 Queue-Based Specialisation

Workers subscribe to queues matching the agent types they support. This lets you scale specific capabilities independently:

```
Heavy code tasks (bash, pytest) →  code queue  →  larger VPS (4 vCPU / 8 GB)
Light write tasks               →  write queue →  small VPS  (2 vCPU / 2 GB)
General tasks                   →  default     →  any worker
```

Agent profile YAML declares the queue:
```yaml
hardware:
  queue: code        # routes to code-queue workers
  node_affinity: any # or pin to a specific node label
```

### 5.3 Burst Strategy

For infrequent heavy bursts (e.g. processing 50 cards at once):

1. Detect queue depth spike (Flower API / Redis `LLEN`)
2. Spin up N additional VPS nodes via provider API (Hetzner Cloud API, Vultr API)
3. Bootstrap via cloud-init (install dependencies, join VPN, start worker)
4. Tear down after queue drains

This can be automated as a Celery task on the orchestrator itself.

### 5.4 Scaling Limits

| Constraint | Limit | Notes |
|------------|-------|-------|
| Anthropic API rate limit | ~60 req/min (Tier 1) | Shared across all workers |
| Redis connections | ~1,000 (local Redis) | Non-issue at small scale |
| Mac Mini network | ~1 Gbps | Supports 50+ workers easily |
| Trello API rate limit | 300 req/10s per token | Shared; use Jira for higher volume |

The primary scaling constraint is the **Anthropic API rate limit**, not compute. At Tier 1, ~5–10 concurrent agent runs is the practical ceiling before hitting rate limits. Upgrade to higher tier to scale agent parallelism.

---

## 6. Cost Analysis

All prices approximate as of April 2026. Currency: USD/month.

### 6.1 Orchestrator (Fixed Cost)

| Item | Cost |
|------|------|
| Mac Mini M4 16 GB (one-time) | ~$800 |
| Home electricity (~15W idle) | ~$1.50/month |
| Internet (existing) | $0 incremental |
| Cloudflare Tunnel | Free |
| **Monthly fixed** | **~$1.50** |

Amortised over 3 years: ~$22/month equivalent.

### 6.2 VPS Worker Nodes (Variable Cost)

Pricing from major providers for a 2 vCPU / 4 GB RAM / 40 GB SSD Linux VPS:

| Provider | $/month per node | Notes |
|----------|-----------------|-------|
| **Hetzner Cloud (CX22)** | **$4.50** | Best value; EU/US/Asia regions |
| Vultr (Regular Cloud) | $12 | US/EU/Asia; 2 vCPU / 4 GB |
| DigitalOcean (Basic) | $18 | 2 vCPU / 4 GB |
| Linode/Akamai | $12 | 2 GB RAM at this price |
| AWS Lightsail | $10 | 2 GB; limited regions |
| AWS EC2 t3.medium | $30 | On-demand; 2 vCPU / 4 GB |

**Recommended: Hetzner** — best price-to-performance, ARM64 available, data centres in EU, US, Singapore.

### 6.3 Total Monthly Cost by Scale

| Workers | Provider | Worker Cost | + Orchestrator | Total/month |
|---------|----------|-------------|----------------|-------------|
| 1 | Hetzner | $4.50 | $1.50 | **$6** |
| 3 | Hetzner | $13.50 | $1.50 | **$15** |
| 5 | Hetzner | $22.50 | $1.50 | **$24** |
| 10 | Hetzner | $45 | $1.50 | **$47** |
| 1 | DigitalOcean | $18 | $1.50 | **$20** |
| 3 | DigitalOcean | $54 | $1.50 | **$56** |

### 6.4 Anthropic API Cost

| Usage | Tokens/month | Cost (Sonnet 4.6) |
|-------|-------------|-------------------|
| Light (5–10 cards/day) | ~5M | ~$15 |
| Medium (20–30 cards/day) | ~20M | ~$60 |
| Heavy (50+ cards/day) | ~50M | ~$150 |

At $3/M input + $15/M output (Sonnet 4.6 pricing).

### 6.5 Total Cost of Ownership — Starter Config

> 1 Mac Mini + 2 Hetzner VPS + light API usage

| Item | Monthly |
|------|---------|
| Orchestrator (Mac Mini electricity) | $1.50 |
| 2× Hetzner CX22 | $9.00 |
| Anthropic API (light) | ~$15 |
| **Total** | **~$26/month** |

---

## 7. Comparison: VPS vs N100 Nodes

| Dimension | VPS (Cloud) | N100 (On-premise) |
|-----------|-------------|-------------------|
| **Upfront cost** | $0 | ~$150–$200 per node |
| **Monthly cost** | $4.50–$18/node | ~$3–5 electricity/node |
| **Break-even** | — | ~2–3 months vs Hetzner |
| **Scaling** | Spin up in 60s | Order, ship, setup (days) |
| **Scale-down** | Terminate instantly, stop paying | Hardware sits idle |
| **Reliability** | Provider SLA (99.9%+) | Depends on home network/power |
| **Network latency to broker** | ~5–20ms (VPN) | <1ms (LAN) |
| **Maintenance** | Provider handles hardware | You handle hardware |
| **Data sovereignty** | Data leaves premises | Data stays local |
| **Max parallelism** | Unlimited (burst) | Fixed by hardware owned |
| **Burst handling** | Auto-scale via API | Must pre-provision |
| **Power cut resilience** | Unaffected | All nodes go down with home |
| **Windows support** | Linux only | Can run Windows (for HUD) |
| **Best for** | Elastic workloads, no upfront budget | Predictable steady load, cost-sensitive long-term |

**Verdict:** For a personal/small-team Kanban agent system with variable workload, VPS is the better fit. The low steady-state cost ($6–$15/month for 1–3 workers) and zero upfront spend outweigh the slightly higher per-hour cost vs N100 at constant load. N100s win only if you're running agents 24/7 with a predictable, high-volume workload — the break-even at that point is roughly 3 months.

---

## 8. Risks and Mitigations

### 8.1 Single Point of Failure — Mac Mini

**Risk:** If the Mac Mini goes offline (power cut, hardware failure), the orchestrator stops and no cards are processed. Redis broker is also down.

**Mitigations:**

| Option | Cost | Complexity |
|--------|------|------------|
| UPS (uninterruptible power supply) | ~$80 one-time | Low |
| Move Redis to Upstash (managed, free tier) | $0 | Low |
| Secondary orchestrator (another Mac Mini or VPS) | +$4.50/month | Medium |
| Full HA with leader election (Consul/etcd) | Engineering effort | High |

**Recommended:** UPS + managed Redis (Upstash free tier). This covers the 99% case at minimal cost.

### 8.2 Secret Exposure on Worker Nodes

**Risk:** A compromised VPS worker could attempt to extract secrets from memory or intercept Anthropic API calls.

**Mitigations:**
- Scoped secrets per profile — workers only receive the subset declared in `secrets.required`
- Fernet encryption in transit — plaintext secrets never hit the network
- Secrets not written to disk on workers — injected in-process only
- Worker VPS has no access to Mac Mini Keychain or master Fernet key
- Rotate Fernet key periodically; old payloads become invalid

### 8.3 Anthropic API Rate Limits

**Risk:** Multiple concurrent agents sharing one API key hit rate limits, causing jobs to fail or retry.

**Mitigations:**
- Track concurrent agent count in the orchestrator; cap dispatches to stay under limit
- Implement exponential backoff in `BaseKanbanAgent` (SDK handles retries automatically)
- Upgrade Anthropic tier as volume grows
- Use different API keys per agent type (code agents vs write agents)

### 8.4 VPS Provider Outage

**Risk:** Hetzner (or any provider) has an outage; all workers go down.

**Mitigations:**
- Cards stay in "In Progress" state — orchestrator detects stale cards after a timeout and returns them to Backlog
- Spread workers across two providers (e.g. Hetzner + Vultr) for redundancy
- The orchestrator (Mac Mini) is unaffected; it will re-dispatch when workers come back

### 8.5 Network Latency (VPN tunnel)

**Risk:** Redis traffic over WireGuard VPN adds ~5–20ms latency per Celery message compared to LAN.

**Impact:** Negligible. Agent tasks take seconds to minutes; broker round-trip latency has no meaningful effect.

**Mitigation if needed:** Move Redis to a VPS in the same region as workers (e.g. Hetzner Falkenstein). Eliminates the home-internet hop entirely.

### 8.6 Cost Runaway

**Risk:** A buggy agent gets stuck in an infinite loop, consuming API tokens and keeping a VPS running indefinitely.

**Mitigations:**
- `max_iterations = 50` hard cap already in `BaseKanbanAgent`
- `lifecycle.timeout_minutes` in agent profiles (default: 30 min)
- Celery task `time_limit` and `soft_time_limit` for hard process kill
- Anthropic spend limit set in console ($X/month hard cap)
- Flower monitoring for stuck tasks; alerting via Discord/Telegram

---

## 9. Recommended Starting Configuration

### Phase 1 — Single worker, zero upfront (start here)

```
Mac Mini (existing)
  └── 1× Hetzner CX22 ($4.50/month)
        └── queue: default (all agent types)

Total: ~$21/month (incl. API usage)
```

Validate the full end-to-end flow: card → orchestrator → VPS worker → Claude → result posted. Identify which agent types need more compute before specialising.

### Phase 2 — Specialised queues (after validating Phase 1)

```
Mac Mini
  ├── 1× Hetzner CX32 (4 vCPU / 8 GB, $8.50) — queue: code
  └── 1× Hetzner CX22 (2 vCPU / 4 GB, $4.50) — queue: write, default

Total: ~$30/month (incl. API usage)
```

Code agents get more CPU for `bash`/`pytest` workloads. Write agents run lean.

### Phase 3 — Auto-scaling (when Phase 2 saturates)

Add Hetzner Cloud API integration to the orchestrator. Trigger a new worker node when queue depth exceeds a threshold; terminate after idle. At this point the system is fully elastic.

### Node Bootstrap Script (cloud-init for Hetzner)

```yaml
#cloud-config
packages:
  - git
  - python3-pip
  - wireguard

runcmd:
  - git clone https://github.com/brianbartilet/harqis-work.git /opt/harqis
  - pip3 install -r /opt/harqis/requirements.txt
  - echo "[WireGuard config provided by orchestrator]" > /etc/wireguard/wg0.conf
  - systemctl enable --now wg-quick@wg0
  - cd /opt/harqis && celery -A workflows.config worker
      --loglevel=info -Q code,write,default
      --detach --logfile=/var/log/harqis-worker.log
```

Orchestrator generates the WireGuard config and pushes it over SSH to the new node immediately after VPS creation.

---

## Summary

| | Value |
|--|--|
| **Orchestrator** | Mac Mini M4 (existing hardware) |
| **Workers** | Hetzner CX22 @ $4.50/node/month |
| **Networking** | WireGuard VPN (zero-trust, encrypted) |
| **Secrets** | Mac Mini Keychain + Fernet-encrypted payloads |
| **Scaling** | Horizontal — add/remove VPS nodes on demand |
| **Starter cost** | ~$21/month (1 worker + API) |
| **3-worker cost** | ~$30/month |
| **Break-even vs N100** | ~2–3 months |
| **Primary risk** | Mac Mini SPOF → mitigate with UPS + managed Redis |
| **API constraint** | Anthropic rate limit caps ~5–10 concurrent agents at Tier 1 |

---

## 10. Hybrid Topology: VPS + N100 Windows Nodes

A hybrid cluster mixes cloud VPS Linux workers with on-premise N100 (or similar) Windows mini-PCs. This is not a compromise — it is the natural fit for this codebase, because some agent workloads require Windows APIs and software that simply cannot run on Linux VPS nodes.

### 10.1 The Core Insight

The existing Celery queue model already supports heterogeneous workers. Each worker subscribes to one or more named queues; the orchestrator routes tasks to the right queue based on the agent profile. Windows-specific tasks go to a `windows` queue (served only by N100 nodes); headless agent tasks go to `code` / `write` / `default` queues (served by VPS nodes). Neither node type needs to know about the other.

### 10.2 Hybrid Architecture Diagram

```
Human → Trello / Jira Card
            │
            ▼
    ┌───────────────────┐
    │   Mac Mini M4     │  ← On-premise orchestrator
    │   (Orchestrator)  │     Secrets vault, board polling
    │   Redis (broker)  │     Profile resolution, task dispatch
    └────────┬──────────┘
             │  WireGuard VPN (all nodes)
             │
    ┌────────┴──────────────────────────────────────────────┐
    │                  Mixed Worker Pool                    │
    │                                                       │
    │  ── Linux VPS Nodes (Hetzner) ──────────────────────  │
    │  ┌──────────────┐  ┌──────────────┐                  │
    │  │  VPS Node 1  │  │  VPS Node 2  │  ...             │
    │  │  queue:code  │  │  queue:write │                  │
    │  │  2vCPU/4GB   │  │  2vCPU/4GB   │                  │
    │  └──────────────┘  └──────────────┘                  │
    │                                                       │
    │  ── Windows N100 Nodes (On-premise) ─────────────────  │
    │  ┌──────────────────────┐  ┌──────────────────────┐  │
    │  │  N100 Node A         │  │  N100 Node B         │  │
    │  │  queue:windows,hud   │  │  queue:windows,tcg   │  │
    │  │  Rainmeter, iCUE     │  │  desktop automation  │  │
    │  │  Win32 API, winsound │  │  MTG pipeline        │  │
    │  └──────────────────────┘  └──────────────────────┘  │
    └───────────────────────────────────────────────────────┘
```

### 10.3 Queue Routing by Node Type

| Queue | Served by | Workload |
|-------|-----------|----------|
| `code` | VPS Linux | Agent coding tasks — bash, pytest, git, file ops |
| `write` | VPS Linux | Agent writing tasks — docs, summaries, PRs |
| `default` | VPS Linux + N100 | Catch-all agent tasks |
| `windows` | N100 Windows only | Any task requiring Win32, Rainmeter, iCUE |
| `hud` | N100 Windows only | Rainmeter HUD updates, winsound alerts |
| `tcg` | N100 or VPS | MTG card pipeline (cross-platform, flexible) |

Agent profiles declare which queue they target:

```yaml
# agent_hud.yaml
hardware:
  queue: hud        # routes only to Windows N100 nodes
  node_affinity: windows

secrets:
  required:
    - YNAB_API_KEY
    - OANDA_API_KEY
    - GOOGLE_CALENDAR_CREDENTIALS
```

```yaml
# agent_code.yaml
hardware:
  queue: code       # routes only to VPS Linux nodes
  node_affinity: linux
```

### 10.4 How N100 Nodes Join the Cluster

N100 nodes join the same WireGuard VPN as VPS nodes. From the orchestrator's perspective, they are just another Celery worker — the only difference is the queues they subscribe to.

**N100 worker startup (Windows):**

```bat
REM set_env_workflows.bat
call scripts\windows\set_env_workflows.bat

REM Start as a Celery worker on windows+hud queues
python -m celery -A core.apps.sprout.app.celery:SPROUT worker ^
    --loglevel=info ^
    -Q windows,hud,default ^
    --concurrency=2
```

Or using the existing `run_workflow_worker_hud.bat` (already in `scripts/windows/`), extended with WireGuard connectivity to the Mac Mini broker.

**WireGuard on Windows:** Install the WireGuard Windows client; the orchestrator distributes a `.conf` file via SSH/SFTP, same as for VPS nodes.

### 10.5 Secret Distribution

Identical to VPS nodes. The orchestrator's `SecretStore` scopes and Fernet-encrypts secrets per profile; N100 nodes receive the encrypted payload in the Celery task, decrypt in-process, discard after the agent completes. N100 nodes hold **no credentials on disk** in this model.

If preferred for operational simplicity, N100 nodes can use a local `.env` file instead (they are on-premise and physically secured). This trades the zero-credential-on-disk security property for simpler setup. Both approaches work; the profile-scoped injection is the same either way.

### 10.6 Cost Comparison

#### Scenario A — Pure VPS (all-Linux)

```
Mac Mini (existing) + 2× Hetzner CX22
= $1.50 + $9.00 = ~$10.50/month infrastructure
```

No Windows-specific workloads possible.

#### Scenario B — Hybrid (VPS + N100)

```
Mac Mini (existing) + 1× Hetzner CX22 + 1× N100 Windows
= $1.50 + $4.50 + ~$3 electricity = ~$9/month infrastructure
```

- N100 (~$160–$200 one-time) amortises in 2–3 months vs an equivalent VPS
- After break-even: N100 is cheaper than a VPS for steady Windows workloads
- VPS nodes handle elastic headless compute; N100 handles fixed Windows workloads

#### Scenario C — Hybrid with spare capacity burst

```
Mac Mini + 1× N100 Windows (permanent) + VPS nodes on-demand
= ~$5/month baseline + VPS burst cost as needed
```

Best of both: low steady-state cost, elastic headless scale when needed.

### 10.7 Operational Considerations

| Aspect | VPS nodes | N100 Windows nodes |
|--------|-----------|-------------------|
| Setup time | ~5 min (cloud-init) | ~30 min (manual or Ansible) |
| OS updates | Provider handles; node is stateless | Manual; reboots disrupt running tasks |
| Failure recovery | Terminate + recreate in 60s | Power cycle; check locally |
| Geographic distribution | Any cloud region | Fixed location (home/office) |
| Power resilience | Unaffected by home power cut | Goes down with local power |
| Windows-specific tasks | Not possible | Native support |
| Network latency to broker | 5–20ms (VPN) | <1ms (LAN) if broker also local |

**Recommendation for N100 nodes:**
- Run them on a UPS (same as Mac Mini recommendation)
- Register with a fixed WireGuard IP in the VPN (e.g., 10.0.0.10, 10.0.0.11) so the orchestrator can monitor them distinctly
- Subscribe to `windows,hud` queues only — do not put them on the `code` queue where VPS nodes compete; keep roles clean

### 10.8 When to Choose Hybrid

| Situation | Recommendation |
|-----------|----------------|
| You only run headless agent tasks (code review, writing, Jira/Trello ops) | Pure VPS — simpler, no hardware to maintain |
| You actively use Rainmeter HUD, iCUE profiles, or desktop automation | Hybrid — N100 handles Windows; VPS handles headless |
| You have N100s already sitting idle | Add them to the cluster as Windows workers; marginal cost is just electricity |
| You want zero on-premise hardware beyond the Mac Mini | Pure VPS — accept that Windows-specific workflows run on the orchestrator itself |
| You want maximum resilience to home power cuts | Pure VPS or hybrid with broker moved to managed Redis |

### 10.9 Recommended Hybrid Starting Point

```
Mac Mini M4  (orchestrator, WireGuard server, Redis broker)
  ├── 1× Hetzner CX22     ($4.50/month) — queue: code, write, default
  └── 1× N100 Windows     (~$3/month electricity) — queue: windows, hud, tcg
```

**Total infrastructure: ~$9/month + one-time N100 hardware**

This covers all queue types. Add a second VPS when code/write queue depth grows; add a second N100 if HUD/desktop workload scales.

The queues are already wired in the codebase (`run_workflow_worker_hud.bat` targets HUD workers, `run_workflow_worker_tcg.sh` targets TCG). Adding a `windows` queue label is the only new plumbing required.
