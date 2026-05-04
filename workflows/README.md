# Workflows 

# Description
- Please see the [documentation](https://github.com/brianbartilet/harqis-core/tree/main/docs/WORKFLOWS.md) in HARQIS-core for workflow principles and guidelines.
```shell
>pip install --upgrade --force-reinstall --no-cache-dir git+https://github.com/brianbartilet/harqis-core.git#egg=harqis-core
```

## Queue topology

Queue names live in `workflows/queues.py`. The wire-level topology (which queues are direct vs fanout) is declared in `workflows/config.py` via `SPROUT.conf.task_queues`. The two are paired — every name in the enum must have a matching declaration, otherwise Celery routes to a non-existent queue.

| Queue | Type | Behaviour |
|---|---|---|
| `default` | Direct (competing-consumers) | One worker dequeues each task. The default home for any task without an explicit route. |
| `hud` | Direct | One HUD worker per task. The `workflows.hud.tasks.*` route sends every HUD task here. |
| `tcg` | Direct | One TCG worker per task. |
| `adhoc` | Direct | One worker per task; used for one-off triggers. |
| `hud_broadcast` | **Fanout** | **Every** subscribed worker runs every task. Use for cluster-wide actions: config reload, cache invalidation, "refresh all HUD machines now". |

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
