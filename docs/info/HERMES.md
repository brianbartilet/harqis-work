# Hermes — Agent Runtime & Orchestrator

> The agent runtime for harqis-work. Hermes hosts Claude-powered agents, registers
> the harqis-work MCP server, schedules cron jobs (with or without an agent reasoning
> loop), and keeps agent memory, plans, and logs under `~/.hermes/`.
>
> **Hermes supersedes OpenClaw.** The OpenClaw Gateway + `harqis-openclaw-sync` model
> is deprecated. See [Migrating from OpenClaw](#migrating-from-openclaw) below and the
> legacy reference in [`OPENCLAW-SYNC.md`](OPENCLAW-SYNC.md).

---

## What Hermes is

Hermes is the always-on agent layer that sits on top of the harqis-work platform. Where
`harqis-work` provides the *integrations* (`apps/`) and the *scheduled workflows*
(`workflows/`), Hermes provides the *reasoning + orchestration* surface:

- **Agent runtime** — runs Claude agents against the harqis-work MCP tools and the
  filesystem, with an agent/API reasoning loop that can be invoked per task.
- **MCP host** — registers the harqis-work MCP server so any Hermes agent (or a cron
  job) can call OANDA, YNAB, Google, Telegram, Trello, Jira, TCG, OwnTracks, etc.
- **Cron scheduler** — runs recurring jobs in two modes: **agent mode** (full reasoning
  loop) and **`no_agent` mode** (run a script and deliver its output, no reasoning loop).
- **Memory & plans store** — persists agent lessons, narrative memory, plans, and logs
  under `~/.hermes/` (per-machine, local — no separate sync repo).

Hermes is the control layer in this picture:

```
┌────────────────────────────────────────────────────────┐
│                  CONTROL LAYER                         │
│                                                        │
│   Hermes agent runtime ◄──► LLM model (reasoning loop) │
│        │                         │                     │
│        │                  harqis-work MCP tools        │
│        │            (finance, calendar, GPS,           │
│        │             messaging, trading, cards)        │
│        ▼                                               │
│   Hermes cron ◄──► Celery workers (Beat + RabbitMQ)    │
│   (agent / no_agent)         │                         │
│                    ┌─────────┴────────┐                │
│                    │   APPS LAYER     │                │
│             OANDA  │  YNAB  │ Google  │                │
│             Jira   │ Trello │ Telegram│                │
│             TCG    │ Scry   │ OwnTrks │                │
│                    └──────────────────┘                │
└────────────────────────────────────────────────────────┘
```

---

## The `~/.hermes/` layout

Hermes state is local to each machine under the user's home directory. There is no
separate cross-machine sync repository (that was the OpenClaw model).

```
~/.hermes/
├── memory/
│   ├── agent_lessons.md          # extracted recurring lessons (written by the weekly
│   │                             # lessons extractor; read by the agent-learning hook)
│   └── ...                       # narrative / long-term memory
├── plans/
│   └── YYYY-MM-DD_HHMMSS-<slug>.md   # plans written by /max-plan and planning passes
├── scripts/                      # cron-invoked helper scripts (e.g. lessons extraction)
└── logs/                         # job logs (e.g. weekly_lessons_extraction.log)
```

A **repo-local** `.hermes/plans/` directory also exists inside `harqis-work` for plans
produced by the [`/max-plan`](../../.agents/skills/max-plan/SKILL.md) skill against this
repo. Both `.hermes/` (repo-local) and `~/.hermes/` (home) are git-ignored — they are
machine-local agent state, never committed.

| Path | Written by | Read by |
|---|---|---|
| `~/.hermes/memory/agent_lessons.md` | `scripts/agents/learning/lessons_extractor.py` (weekly) | `scripts/agents/learning/agent_learning_hook.py` (before multi-step tasks) |
| `~/.hermes/scripts/` | maintainer / installer | Hermes cron |
| `~/.hermes/logs/` | cron jobs | maintainer |
| `.hermes/plans/` (repo-local) | `/max-plan` | maintainer / agents |

---

## MCP registration

Hermes spawns the harqis-work MCP server (a stdio server) on demand and keeps it
registered. The MCP server itself is started by the platform deploy pipeline
(`python scripts/deploy.py`); Hermes points at it.

```bash
# List MCP servers registered with Hermes
hermes mcp list

# If the harqis-work MCP server is missing, (re)start it via the platform deploy:
python scripts/deploy.py --restart mcp
```

Any Hermes agent or cron job with the harqis-work MCP server registered can call every
tool the server exposes — see [`mcp/README.md`](../../mcp/README.md) for the full
catalog. The MCP server is a stdio server: clients (Hermes, Claude Desktop, etc.) spawn
it and keep stdin/stdout attached, so it is **not** run as a detached deploy daemon.

---

## Cron scheduling — agent vs `no_agent`

Hermes schedules recurring work. Two modes:

| Mode | What runs | Use for |
|---|---|---|
| **agent** | A full Claude reasoning loop with MCP tools | Tasks that need judgement (triage, research, multi-step automation) |
| **`no_agent`** | A plain script; Hermes only schedules + delivers the output | Deterministic jobs — extract a file, post a summary, run a canonical skill — where reasoning would add cost without value |

`no_agent` jobs stay **silent when there is nothing to deliver**, so an off-cycle run
doesn't spam the delivery channel. Examples already in the repo:

- `scripts/cron/send_latest_daily_radar_dump.py` — extracts the latest Daily Radar dump
  from Google Drive and delivers it to Telegram via Hermes `no_agent` cron.
- `scripts/agents/repo-quality/migrate_to_core_agent.py` — runs Claude Code locally against the
  canonical `/migrate-to-core` skill on a bi-monthly schedule, so Hermes cron schedules
  the work with **no** Hermes agent/API reasoning loop; quiet on off-cycle Saturdays.
- `scripts/agents/learning/weekly_lessons_extraction.py` — calls the lessons extractor weekly
  (`0 14 * * 0`) via Hermes cron, logging to `~/.hermes/logs/`.

---

## Agent memory & lessons

Hermes agents get better over time through a capture → distill → recall loop on top of
`~/.hermes/memory/` (this is the [MANIFESTO](../MANIFESTO.md) CODE loop applied to the
agent's own work):

1. **Capture** — reasoning entries from agent runs accumulate over the week.
2. **Distill** — `scripts/agents/learning/lessons_extractor.py` (Sundays ~22:00) scans the past
   7 days, detects recurring patterns, and appends insights to
   `~/.hermes/memory/agent_lessons.md`.
3. **Recall** — `scripts/agents/learning/agent_learning_hook.py` loads relevant lessons before a
   multi-step task and applies matching patterns to execution.

---

## Migrating from OpenClaw

OpenClaw (the Gateway runtime + the `harqis-openclaw-sync` workspace repo) is
**deprecated**. Hermes replaces it. The model mapping:

| OpenClaw (deprecated) | Hermes (current) |
|---|---|
| OpenClaw Gateway process (24/7 agent runtime) | Hermes agent runtime |
| `harqis-openclaw-sync` repo (cross-machine workspace) | `~/.hermes/` — local per-machine (no sync repo) |
| `.openclaw/workspace/{SOUL,USER,AGENTS,MEMORY}.md` | `~/.hermes/memory/` (agent_lessons + narrative memory) |
| Heartbeat polling (`HEARTBEAT.md`) | Hermes cron jobs (agent + `no_agent` modes) |
| MCP via `openclaw.json` / Claude Desktop config | `hermes mcp` (register / list) |
| Auto-pull sync every 30 min across machines | per-machine `~/.hermes/` (nothing to sync) |
| Messaging channels wired in the Gateway | Hermes cron delivery (e.g. `no_agent` → Telegram) + MCP messaging tools |

**What carries over unchanged:** the harqis-work platform itself — `apps/`,
`workflows/`, the MCP server, the Celery host/node deploy model, Tailscale networking,
and the Kanban orchestrator under `agents/`. Hermes changes only the *agent runtime and
its memory model*, not the platform underneath it.

**What to stop doing:**
- Don't clone or auto-pull `harqis-openclaw-sync` — that repo and its 30-minute sync job
  are retired.
- Don't write agent identity/memory into `.openclaw/workspace/` — use `~/.hermes/memory/`.
- Don't run `openclaw gateway` / `openclaw tui` — use the Hermes CLI.

---

## Related reading

- [`HERMES-HOST.md`](HERMES-HOST.md) — host deployment, service inventory, worker nodes, and the Hermes agent configuration on the always-on machine.
- [`AGENTS-TASKS-KANBAN.md`](AGENTS-TASKS-KANBAN.md) — the Kanban orchestrator, agent profiles, permission model, and MCP bridge.
- [`AI-TOOLS-WIRING.md`](AI-TOOLS-WIRING.md) — how reasoning-model harnesses and Hermes are wired and where each one writes.
- [`SKILLS-GUIDE.md`](SKILLS-GUIDE.md) — model-neutral agent skills and Hermes integration patterns.
- [`mcp/README.md`](../../mcp/README.md) — the MCP tool catalog Hermes agents call.
- [`OPENCLAW-SYNC.md`](OPENCLAW-SYNC.md) — **deprecated** legacy reference for the old OpenClaw sync model.
