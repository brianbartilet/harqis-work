---
name: create-data-only-from-hud
description: >
  Generate a data-only fallback twin of an existing HUD render task so feed dumps and
  Elasticsearch log records keep flowing when the Windows HUD worker is offline.
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

Generate a **data-only fallback twin** of an existing HUD render task so its `@feed` dump + `@log_result` Elasticsearch record keep flowing on the always-on host even when the Windows `hud` worker is offline. Per invocation it: refactors the source task's data computation into a win32-free `collect_<slug>()`, rewrites the original `show_<slug>` to call it, generates a gated twin in `workflows/hud/tasks/hud_data_only.py` routed to the `host` queue, mirrors the schedule (with a staleness gate so it only runs when Windows didn't), and updates wiring + docs + tests.

Read the related skills for conventions if needed: `/create-new-hud` (HUD task structure, schedule entries, `__init__.py` win32 guard, docs rows) and `/create-new-workflow` (Celery task/queue patterns).

## Background — why this exists

HUD render tasks are routed `workflows.hud.tasks.* → hud` queue (`workflows/config.py`), and only Windows machines consume `hud` (`machines.toml`). When Windows is offline nobody runs the task, so the data is lost — **not** because the sinks are Windows-bound (`@log_result` writes to Elasticsearch, a network service; `@feed` resolves per-OS and the host has the same Google-Drive LOGS mount via `DESKTOP_PATH_FEED_DARWIN`), but because the **task body never executes**.

The fix: a *data-only twin* that runs the same data computation on the always-on host (`harqis-server` consumes the `host` queue), skipping the Rainmeter render. It is **fallback-only** — it gates on a heartbeat so it produces nothing on the cycles Windows is healthy.

The shared runtime already exists (committed, do not regenerate):
- `workflows/hud/fallback.py` — `windows_handled_recently()` + the `fallback_gate(...)` decorator. The gate reads the `@log_result` heartbeat doc (one per task in `harqis-elastic-logging`, keyed by `name="<module>.<qualname>"`, field `date`) and short-circuits the twin when the original ran within `max_staleness_secs`. Fails OPEN.
- `workflows/hud/collectors/` — win32-free package holding the extracted `collect_<slug>()` functions.

## Arguments

`$ARGUMENTS` format:

```
<task_fn> [--staleness <secs>] [--dry-run]
```

| Token | Required | Description |
|---|---|---|
| `task_fn` | Yes | The HUD task to mirror — bare function name (`show_tcg_orders`, `show_daily_radar`) or dotted path (`workflows.hud.tasks.hud_tcg.show_tcg_orders`). |
| `--staleness <secs>` | No | Override the computed `max_staleness_secs`. Default: largest gap between consecutive scheduled fires + 600s grace (Step 5). |
| `--dry-run` | No | Print the resolved plan (source file, slug, computed staleness, files to touch) and stop. Write nothing. |

---

## Step 0 — Resolve the task and gate eligibility

1. Resolve `task_fn` to its source file `workflows/hud/tasks/hud_<slug>.py` and its `WORKFLOWS_HUD` entry in `workflows/hud/tasks_config.py`. The `<slug>` is the source module suffix (`hud_tcg` → reuse the function name for the twin: `show_tcg_orders` → `show_tcg_orders_data_only`).
2. Read the source function body and **refuse** if it reads Windows-local state — a data-only twin on the host would produce nothing useful. Refuse if ANY of these hold:
   - It imports/uses `win32gui`, `win32api`, `winsound`, `ctypes.windll`, or `GetForegroundWindow`.
   - It reads desktop-capture paths (`ACTIONS_LOG_PATH`, `ACTIONS_SCREENSHOT_PATH`, `C:\dump`, the `DESKTOP` capture config) or local Rainmeter profile dirs.
   - It takes screenshots or reads the local filesystem for its data.

   **Known ineligible** (stay Windows-only): `show_mouse_bindings`, `build_summary_mouse_bindings`, `get_desktop_logs`, `take_screenshots_for_gpt_capture`, `show_hud_profiles`. If the user names one, explain why and stop.

   **Known eligible** (pure API/data): `show_forex_account`, `show_tcg_orders`, `show_tcg_sell_cart`, `show_jira_board`, `show_calendar_information`, `show_ynab_budgets_info`, `show_pc_daily_sales`, `show_api_costs`, `show_daily_radar`, `get_failed_jobs`, `get_schedules`.
3. If `--dry-run`, print the plan and stop here.

---

## Step 1 — Verify shared infra is present

Confirm `workflows/hud/fallback.py` and `workflows/hud/collectors/__init__.py` exist (they are committed). If somehow missing, restore them before continuing — do NOT inline the gate logic into the twin.

---

## Step 2 — Extract `collect_<slug>()` into `workflows/hud/collectors/<slug>.py`

Create a **win32-free** module that holds the source task's pure data path. The collector returns the **exact dict the HUD task returns** (`{"text": <dump>, "summary": ..., "metrics": ..., ...}`).

Split rule: keep everything that fetches data + composes the dump text + builds `summary`/`metrics`/`links`; drop everything that mutates the `ini` Rainmeter config object.

```python
"""Win32-free data collector for show_<slug> (see /create-data-only-from-hud)."""
from typing import ...

from core.utilities.logging.custom_logger import logger as log
from apps.<app>.references.web.api.<resource> import ApiService...
from apps.<app>.config import APP_NAME as APP_NAME_<APP>
from apps.apps_config import CONFIG_MANAGER
from workflows.hud.helpers.text import truncate          # render-agnostic helpers are fine
# DO NOT import apps.rainmeter.* or anything win32-only.


def collect_<slug>(<data_kwargs from the source signature, minus `ini` and render-only args>,
                   **kwargs) -> dict:
    """Fetch + distill the <slug> data. Returns the same payload show_<slug> returns."""
    # ...the fetch + dump-composition + summary/metrics block lifted verbatim
    #    from show_<slug>, with all `ini[...]` lines removed...
    return {"text": dump, "summary": ..., "metrics": ...}
```

**Verify the collector's import graph is win32-free** — it must import cleanly on macOS/Linux. If a needed helper currently lives inside a `hud_*.py` (win32-guarded) module, move it to `workflows/hud/helpers/` first.

---

## Step 3 — Rewrite `show_<slug>` to call the collector

In `workflows/hud/tasks/hud_<slug>.py`, replace the inlined data/dump block with a call to the collector, keep the Rainmeter render, and return the collector's dict unchanged. The decorator stack (`@SPROUT.task` / `@log_result` / `@init_meter` / `@feed`) stays exactly as-is — this is a pure extraction, no behaviour change on Windows.

```python
from workflows.hud.collectors.<slug> import collect_<slug>

@SPROUT.task()
@log_result()
@init_meter(RAINMETER_CONFIG, hud_item_name='<TITLE>', ...)
@feed()
def show_<slug>(ini=ConfigHelperRainmeter(), <kwargs>, **kwargs):
    result = collect_<slug>(<forward the data kwargs>, **kwargs)
    dump = result["text"]
    # ...the ini[...] layout/dimension lines, now reading `dump` / result["metrics"]...
    return result
```

Run the source task's existing tests after this edit to prove no regression (Step 8 covers the commands).

---

## Step 4 — Generate the twin in `workflows/hud/tasks/hud_data_only.py`

Create the module if absent (win32-free — collectors + feed + log_result + fallback_gate only; **never** import `apps.rainmeter`). Append one twin per invocation:

```python
"""
Data-only fallback twins of the HUD render tasks. Each twin runs on the
always-on host (`host` queue) and produces the @feed dump + @log_result ES
record ONLY when the Windows worker hasn't run the original recently
(fallback_gate). No Rainmeter render. Generated by /create-data-only-from-hud.

Imported UNCONDITIONALLY from workflows/hud/__init__.py (outside the win32
guard) — keep it win32-free.
"""
import logging

from core.apps.sprout.app.celery import SPROUT
from core.apps.es_logging.app.elasticsearch import log_result

from apps.desktop.helpers.feed import feed
from workflows.hud.fallback import fallback_gate
from workflows.hud.collectors.<slug> import collect_<slug>

logger = logging.getLogger("harqis-hud.data_only")

# Largest gap between consecutive fires of show_<slug> + grace (see Step 5).
_STALENESS__<SLUG> = <computed_secs>


@SPROUT.task(name="workflows.hud.tasks.hud_data_only.<fn>_data_only")
@fallback_gate("workflows.hud.tasks.hud_<slug>.<fn>", _STALENESS__<SLUG>)
@log_result()
@feed(filename_prefix="hud-data-only")
def <fn>_data_only(**kwargs):
    """Data-only fallback twin of <fn> — runs on the host when Windows didn't."""
    return collect_<slug>(**kwargs)
```

Decorator order is load-bearing: `@fallback_gate` is OUTSIDE `@log_result`/`@feed` so a skip short-circuits before either sink fires (no empty feed block, no spurious twin ES doc). `@feed` uses the distinct `hud-data-only` prefix so host dumps never interleave with the Windows `hud-logs-*` file.

---

## Step 5 — Mirror the schedule onto the `host` queue

Compute `max_staleness_secs` from the source task's `schedule`:
- `max_staleness_secs = (largest gap between consecutive scheduled fires) + grace`, grace = `600` (10 min) by default; bump to `~0.5×cadence` for sub-15-min cadences.
- Cadence reference: `crontab(minute=0)`→3600 · `crontab(minute='*/15')`→900 · `crontab(minute='*/30')`→1800 · `crontab(hour='*/2', minute=0)`→7200 · uneven sets (e.g. `hour='8,12,16,20'`) → use the **largest** gap (the 20:00→08:00 overnight gap = 43200) so the twin never false-fires during a legitimately quiet window · weekly → 604800.
- `--staleness <secs>` overrides this.

Append the twin entry **inside the existing `WORKFLOWS_HUD` dict** in `workflows/hud/tasks_config.py`, grouped at the bottom under a data-only comment header. Copy the source entry's `schedule` and data `kwargs` (drop render-only kwargs like `max_hud_lines`), route to `host`:

```python
# ...inside WORKFLOWS_HUD, after the last render entry:

    # ── Data-only fallback twins (host queue) — see /create-data-only-from-hud ──
    'run-job--<fn>_data_only': {
        'task': 'workflows.hud.tasks.hud_data_only.<fn>_data_only',
        'schedule': <same schedule object as the source entry>,
        'kwargs': { <same data kwargs as the source entry, minus render-only ones> },
        "options": {
            "queue": WorkflowQueue.HOST,
            "expires": <same expires as the source entry>,
        },
        'manifesto': {
            'code_role': 'capture',            # data-only: capture, never express
            'para_bucket': 'area',
            'express_target': 'feed:hud-data-only',
            'review_artifact': 'es_log+feed',
            'hfl_signal': False,
        },
    },
```

> **Keep it in `WORKFLOWS_HUD` — do NOT create a separate dict.** `frontend/generate_registry.py` catalogues only the **first** `run-job--*` dict per `tasks_config.py`; a second dict (`WORKFLOWS_HUD_DATA_ONLY`) would never reach the dashboard. Because the twin lives in `WORKFLOWS_HUD` (already imported + unioned into `CONFIG_DICTIONARY`), **no `config.py` union or import edit is needed.**

The **only** `workflows/config.py` edit (idempotent — once, ever): add a route ABOVE the `workflows.hud.tasks.*` catch-all so twins reach `host` no matter how they're called (the catch-all would otherwise send them to `hud`):
```python
SPROUT.conf.task_routes = {
    "workflows.workers.tasks.broadcast_*": {"queue": WorkflowQueue.WORKERS_BROADCAST.value},
    "workflows.hud.tasks.broadcast_*":     {"queue": WorkflowQueue.HUD_BROADCAST.value},
    "workflows.hud.tasks.hud_data_only.*": {"queue": WorkflowQueue.HOST.value},   # NEW — before the catch-all
    "workflows.hud.tasks.*":               {"queue": WorkflowQueue.HUD.value},
}
```

---

## Step 6 — Wire `workflows/hud/__init__.py`

Import the twin module **outside** the `if sys.platform == "win32":` guard so the host (and any worker) registers the twins. Add once:

```python
# Data-only fallback twins run on the always-on host (non-Windows included),
# so import unconditionally. Module is win32-free (collectors + feed + gate).
import workflows.hud.tasks.hud_data_only   # noqa: E402,F401
```

The collector modules are pulled in transitively by `hud_data_only` (host) and by the win32-guarded `hud_<slug>` (Windows) — no separate import line needed.

---

## Step 7 — Update docs

- `workflows/hud/README.md`: add a row to the Scheduled Tasks table for `<fn>_data_only` (note: "host fallback — runs only when Windows hasn't"), and a Task Files row for `tasks/hud_data_only.py` + `collectors/<slug>.py` (first time only).
- Root `README.md`: in the Desktop HUD section, add a one-line note that data-only fallback twins exist for the mirrored panels (first time only — don't repeat per task). Do NOT add a panel-inventory row (the twin renders no panel).

---

## Step 8 — Tests

1. **Collector unit test** — `workflows/hud/tests/test_collect_<slug>.py`: assert `collect_<slug>(...)` returns a dict with a non-empty `text` (live API; mirror the source task's existing integration test kwargs). Use the `test__<name>` convention, no classes.
2. **Twin gate test** — already covered generically by `workflows/hud/tests/test_fallback.py`; add a twin-specific case only if the twin has bespoke logic beyond `return collect_<slug>(**kwargs)`.
3. Run:
   ```bash
   .venv/bin/python -m pytest workflows/hud/tests/test_fallback.py workflows/hud/tests/test_collect_<slug>.py -v
   # regression on the source task's own tests:
   .venv/bin/python -m pytest workflows/hud/tests/test_hud_<slug>.py -v
   ```

---

## Step 9 — Verify wiring

```bash
# Twin registered with Celery:
.venv/bin/python -c "
from core.apps.sprout.app.celery import SPROUT
import workflows.hud
print('workflows.hud.tasks.hud_data_only.<fn>_data_only' in SPROUT.tasks)
"   # → True

# Collector is genuinely win32-free (must import without apps.rainmeter):
.venv/bin/python -c "import workflows.hud.collectors.<slug>; print('collector import OK')"

# Beat entry present and routed to host:
.venv/bin/python -c "
from workflows.config import SPROUT
e = SPROUT.conf.beat_schedule['run-job--<fn>_data_only']
print(e['options']['queue'])   # → host
"
```

On the host this is the real test: stop the Windows worker, wait one cadence, and confirm a `hud-data-only-YYYYMMDD.txt` block + a fresh `workflows.hud.tasks.hud_data_only.<fn>_data_only` doc appear in Elasticsearch; bring Windows back and confirm the twin goes quiet (gate skips).

---

## Step 10 — Activation checklist

Print, filled in:

```
Data-only twin created for <fn>:

  Code:
  [ ] workflows/hud/collectors/<slug>.py — collect_<slug>() (win32-free)
  [ ] workflows/hud/tasks/hud_<slug>.py — show_<slug> now calls the collector (no behaviour change)
  [ ] workflows/hud/tasks/hud_data_only.py — <fn>_data_only twin (gate + feed + log_result)
  [ ] workflows/hud/__init__.py imports hud_data_only OUTSIDE the win32 guard

  Schedule + routing (first task adds the config.py route; later tasks only touch tasks_config.py):
  [ ] 'run-job--<fn>_data_only' entry added INSIDE WORKFLOWS_HUD (queue=host, staleness=<secs>)
  [ ] config.py routes hud_data_only.* → host (above the catch-all) — route only, NO union/import edit
  [ ] Regenerate the frontend registry: /generate-registry
  [ ] Restart Celery Beat (harqis-server) AND the host worker

  Verify:
  [ ] Twin registered (Step 9) · collector imports win32-free · beat entry routed to host
  [ ] Tests pass (Step 8)

  Docs:
  [ ] workflows/hud/README.md rows · root README HUD note (first time)
```

---

## What NOT to do

- **Don't import `apps.rainmeter` (or anything win32) from `hud_data_only.py` or the collectors.** They're imported on the macOS host; a win32 import crashes the worker at startup. The whole point is to leave `@init_meter` behind.
- **Don't LLM-regenerate a standalone copy of the data logic.** Extract it to one `collect_<slug>()` that BOTH the Windows render task and the host twin call — otherwise the two drift the next time the source task changes.
- **Don't put `@fallback_gate` inside `@log_result`/`@feed`.** It must be the outermost (just under `@SPROUT.task`) so a skip writes nothing.
- **Don't route the twin to `hud`.** It must be `host`. The `workflows.hud.tasks.*` catch-all would capture it — that's why Step 5 adds the more-specific `hud_data_only.*` route before it.
- **Don't put twins in a separate `WORKFLOWS_HUD_DATA_ONLY` dict.** `frontend/generate_registry.py` reads only the *first* `run-job--*` dict per `tasks_config.py`, so a second dict is invisible to the dashboard. Keep the entries inside `WORKFLOWS_HUD` (no `config.py` union edit needed — only the route).
- **Don't mirror desktop-capture tasks** (Step 0 deny-list) — they read Windows-local state and produce nothing on the host.
- **Don't set the staleness shorter than one full cadence.** Below cadence the gate false-positives every cycle and the twin runs even while Windows is healthy (duplicate logs).
