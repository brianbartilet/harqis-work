# Workflows 

# Description
- Please see the [documentation](https://github.com/brianbartilet/harqis-core/tree/main/docs/WORKFLOWS.md) in HARQIS-core for workflow principles and guidelines.
```shell
>pip install --upgrade --force-reinstall --no-cache-dir git+https://github.com/brianbartilet/harqis-core.git#egg=harqis-core
```

## Manifesto alignment

Every task in this tree carries a `'manifesto'` metadata block on its beat entry. Fields:

| Field | Meaning |
| --- | --- |
| `code_role` | `capture` / `organize` / `distill` / `express` (or `'+'`-joined hybrids) — the CODE phase from [`docs/MANIFESTO.md`](../docs/MANIFESTO.md). |
| `para_bucket` | `project` / `area` / `resource` / `archive` — PARA bucket. Most live workflows are `area`s. |
| `express_target` | Short string describing where the output lands: `hud_feed`, `rainmeter:<METER>`, `es_log`, `api:<service>`, `file:<purpose>`, `vectorstore:<name>`, `message:<channel>`. |
| `review_artifact` | What a human or downstream task reads to verify the run happened. Usually `es_log` plus the express surface. |
| `hfl_signal` | `True` when the task produces personal-signal data eligible for the Homework-for-Life corpus (see [`workflows/hfl/`](hfl/README.md)). |

`scripts/manifesto_audit.py` validates the metadata across all active workflows. Per-workflow alignment tables live in each `workflows/<name>/README.md` under "Manifesto alignment". Design rationale: [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](../docs/thesis/MANIFESTO-REPO-UPDATES.md).

### `manifesto` is stripped before Celery sees it

`'manifesto'` is **our** metadata — it is **not** a Celery beat-schedule key and must never reach Celery. Celery's `ScheduleEntry.__init__` accepts only a fixed set of per-entry keys; anything else is a hard error. Hand a raw entry dict (with `manifesto`) to `SPROUT.conf.beat_schedule` and beat dies on **every** startup, before it can log or write a pidfile:

```
TypeError: ScheduleEntry.__init__() got an unexpected keyword argument 'manifesto'
```

`workflows/config.py` prevents this. `CONFIG_DICTIONARY` keeps the **full** entries (so `manifesto_audit.py`, the registry, and docs tooling can read `manifesto`), but only a sanitized projection is assigned to Celery:

```python
_CELERY_ENTRY_KEYS = frozenset(
    {"task", "schedule", "args", "kwargs", "options", "relative"}
)
# per entry: keep only keys in _CELERY_ENTRY_KEYS, drop manifesto + any
# other custom metadata, then -> SPROUT.conf.beat_schedule
```

Implications when editing `workflows/*/tasks_config.py`:

- **Keep `manifesto` at the top level of the entry** (sibling of `task` / `schedule` / `options`). It is read by tooling and stripped at the Celery boundary — do **not** bury it inside `options` (Celery *would* forward `options` contents and may choke).
- Any **new** non-Celery metadata key you add to an entry is automatically dropped from the Celery schedule too — it survives in `CONFIG_DICTIONARY` for tooling, no Celery change needed.
- If you add a key that Celery *should* honour (rare), add it to `_CELERY_ENTRY_KEYS` in `workflows/config.py` — it is a strict whitelist.
- Symptom of a regression here (whitelist bypassed / entry assigned raw): scheduler "closes from the deploy" — beat exits instantly, `--status` shows `scheduler stopped`, no `scheduler.pid`, `scheduler.log` dead-ends at the startup banner.

## Queue topology

Queue names live in `workflows/queues.py`. The wire-level topology (which queues are direct vs fanout) is declared in `workflows/config.py` via `SPROUT.conf.task_queues`. The two are paired — every name in the enum must have a matching declaration, otherwise Celery routes to a non-existent queue.

| Queue | Type | Behaviour |
|---|---|---|
| `default` | Direct (competing-consumers) | One worker dequeues each task. The default home for any task without an explicit route (`task_default_queue`). |
| `host` | Direct | Tasks pinned to a host-class machine (Docker, broker access). |
| `hud` | Direct | One HUD worker per task. The `workflows.hud.tasks.*` route sends every HUD task here unless overridden. |
| `tcg` | Direct | TCG marketplace pipeline (Scryfall bulk, listings, pricing). |
| `peon` | Direct | Work-context HUD/desktop tasks (Jira boards, calendar focus, captures). |
| `adhoc` | Direct | One-off / manual triggers (no schedule, or rare cron). |
| `agent` | Direct | AI ingest / RAG / agent dispatch (e.g. `workflows.knowledge.tasks.*`). |
| `worker` | Direct | Generic background worker pool — VPS nodes default here. |
| `n8n` | Direct | n8n container ops (backup / restore / deploy) — pinned to `harqis-server` only. |
| `default_broadcast` | **Fanout** | Cluster-wide jobs every subscribed node must run locally (e.g. local cache invalidation, config reload). |
| `hud_broadcast` | **Fanout** | HUD-level fanout — `workflows.hud.tasks.broadcast_*` (auto-routed); reload skin config / refresh-all-HUDs cluster-wide. |
| `workers_broadcast` | **Fanout** | Reserved — declared in enum, no route yet. |
| `agents_broadcast` | **Fanout** | Reserved — declared in enum, no route yet. |

### Optional `os` annotation in beat options

Beat entries may include an `"os"` key listing the platforms where the task can run, e.g. `"os": ["windows"]`, `"os": ["macos", "linux"]`, or omit it for cross-platform. **Informational only** — Celery does not enforce it. The `/manage-queues` skill reads these labels to surface routing/OS mismatches (e.g. a `windows`-only task on a queue whose only consumer is a Mac box). See `.claude/skills/manage-queues/SKILL.md` for the heuristic fallback when no annotation is present.

### Direct vs fanout — decision rule

- **Direct queue** when the task has work-side-effects you want to happen exactly once cluster-wide (write to a database, post to Slack, charge a card). This is 99% of tasks.
- **Fanout / broadcast** when the task triggers a *local* action on every worker that satisfies the same role (each HUD machine reloads its own Rainmeter config, each VPS clears its own cache).

### Adding a new broadcast task

1. Pick a domain that already has a broadcast queue (currently only `hud`). To add a new domain (e.g. `tcg_broadcast`), update `workflows/queues.py`, `workflows/config.py` (`task_queues` + `task_routes`), and the broadcast-pair map in `scripts/deploy.py` first.
2. Create the task with the prefix `broadcast_` so the naming-convention route picks it up:
   ```python
   # workflows/hud/tasks/broadcast_<thing>.py
   from core.apps.sprout.app.celery import SPROUT

   @SPROUT.task(name="workflows.hud.tasks.broadcast_<thing>")
   def broadcast_<thing>(**kwargs) -> dict:
       # idempotent body — runs once per subscribed worker
       ...
   ```
3. Workers subscribe by including `hud_broadcast` in their `-Q` queue list. Easiest: `python scripts/deploy.py --role node -q hud,hud_broadcast`.
4. Trigger:
   ```python
   from workflows.hud.tasks.broadcast_<thing> import broadcast_<thing>
   broadcast_<thing>.delay()
   # → every worker subscribed to hud_broadcast runs it once.
   ```

### Idempotency rule (must read before writing a broadcast task)

A broadcast task runs simultaneously on every subscribed worker. The body **must** be safe under concurrent execution:

- ✅ Local, isolated effects only — re-read a config file, clear an in-process cache, write to a `<hostname>`-namespaced location, log to the worker's own log file, push to a `<hostname>`-keyed Elasticsearch document.
- ❌ Anything that should "happen exactly once cluster-wide" — DB rows, external API calls, Trello posts. Use a direct queue for those.

If a broadcast task accidentally writes to shared state, you'll get N races, N duplicate API calls, and a fun afternoon debugging.

### Missed-broadcast caveat

When a worker disconnects, its anonymous fanout-bound queue is auto-deleted. A broadcast published while a worker is offline is **not** delivered when the worker reconnects — RabbitMQ has nowhere to keep it. For state that must converge eventually, pair each broadcast with a "rebuild from scratch" worker-startup task that restores the same end state. The broadcast becomes a fast-path; the startup task is the safety net.

### Demo

`workflows/hud/tasks/broadcast_reload.py` ships a working `broadcast_reload_config` task that just logs the receiving worker's hostname + timestamp and returns a JSON payload. Use it as a copy-paste template for new broadcasts.
