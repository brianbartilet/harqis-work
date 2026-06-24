---
name: manage-queues
description: >
  Manage Celery task to queue assignments across workflows and surface live machine
  coverage from machines.toml.
user-invocable: true
allowed-tools: Bash Read Glob Grep Edit Write
---

Manage Celery task → queue assignments across `workflows/*/tasks_config.py` and surface the live machine coverage from `machines.toml`. Use this skill when adding a new beat-scheduled task, moving an existing task to a different queue, or deciding which queue is safe to use given the current worker topology.

The argument `$ARGUMENTS` is a free-form action. Recognised forms:

| Form | Effect |
|---|---|
| *(empty)* or `list` | Print **both** views: queue → tasks (with consuming machines) and machine → queues → tasks. |
| `by-queue` | Print only the queue → tasks view. |
| `by-machine` | Print only the machine → queues → tasks view (what would actually run on each box). |
| `by-os` | Print only the OS → tasks view (which tasks need Windows / macOS / are cross-platform). |
| `machines` | Print just the machine → queue table from `machines.toml` (no tasks). |
| `move <task-pattern> <queue>` | Reassign matching task(s) to a different queue. |
| `add <queue>` | Scaffold a new beat-schedule entry on the named queue. Asks the user for module path, schedule, kwargs. |
| `audit` | Like `list`, plus flag any queue that has tasks but no consuming worker, and OS-mismatch routing. |

`<queue>` is one of the values in `workflows/queues.py::WorkflowQueue` (`default`, `host`, `hud`, `tcg`, `adhoc`, `peon`, `agent`, `worker`, plus the `*_broadcast` fanout queues). `<task-pattern>` matches against the dotted module path (substring or exact).

## Source of truth

| Concept | File |
|---|---|
| Beat schedules + queue assignments | `workflows/*/tasks_config.py` |
| Queue enum | `workflows/queues.py` |
| Queue declarations + `task_routes` + `task_default_queue` | `workflows/config.py` |
| Machine → queues subscription | `machines.toml` (root) and `machines.local.toml` overrides |

`tasks_config.py` files use the dict form:

```python
'run-job--<short-name>': {
    'task': 'workflows.<area>.tasks.<module>.<func>',
    'schedule': crontab(...),
    'kwargs': {...},
    'options': {
        'queue': WorkflowQueue.<QUEUE>,
        'expires': <seconds>,
    },
},
```

`options.queue` is the routing decision. If absent, the task falls into `task_default_queue` (currently `default`). Per-call `apply_async(queue=…)` always wins; `task_routes` patterns in `workflows/config.py` apply only when `options.queue` isn't set.

## Steps

### Step 0 — Always do first

Read these files in parallel: `workflows/queues.py`, `workflows/config.py`, `machines.toml`, all `workflows/*/tasks_config.py`. Build:

1. **task_to_queue**: `{dotted-task-path: queue-name}` from every `'task': 'options.queue'` pair.
2. **machine_to_queues**: `{machine-name: [queues]}` from `machines.toml` `[<machine>]` blocks.
3. **queue_to_machines**: inverse of (2).
4. **task_to_os**: `{dotted-task-path: [os-labels]}` — see Step 0a.

Always re-read these — never trust prior conversation context for the current state.

### Step 0a — Resolve each task's OS requirement

For every task in `task_to_queue`:

1. **Explicit annotation** (preferred). If the beat entry's `options` dict has an `"os"` key, use it verbatim. Format: `"os": ["windows"]`, `"os": ["macos"]`, `"os": ["windows", "linux"]`, or `"os": ["any"]`.

2. **Heuristic fallback** (when no explicit `os`). Open the source module of the task (resolved from the dotted path: `workflows.<area>.tasks.<module>.<func>` → `workflows/<area>/tasks/<module>.py`). Inspect the **function body** of `<func>` (not the whole module — multiple tasks share files):
   - Windows signals: imports `win32*` / `pywin32` / `winreg` / `ctypes.windll`, references `APPDATA`/`LOCALAPPDATA`, calls `cmd /c`, executes `.bat` files, contains `Rainmeter` paths, has hard-coded `C:\` / `C:/` paths.
   - macOS signals: imports `AppKit` / `Foundation` / `objc`, calls `osascript` / `defaults write` / `launchctl`, references `/Applications/` or `/Users/<x>/Library/`.
   - Linux signals: calls `systemctl` / `apt-get`, references `/etc/systemd/`, `/var/log/`.
   - If multiple OS signals present → list all.
   - If no signals → `["any"]`.

3. **Confidence**: explicit annotations are authoritative; heuristic results should be marked `(heuristic)` in any output, with a one-line note pointing at the strongest signal so the user can verify.

The `os` field is **informational only** for now — Celery doesn't enforce it. The skill uses it to flag mismatches (a Windows-only task routed to a queue whose only consumer is a Mac box). Don't add `os` annotations on the user's behalf without asking — it's a routing decision they should make consciously.

### Step 1 — Dispatch on `$ARGUMENTS`

Branch on the first token:

- `list` / empty → Step 2 (both views)
- `by-queue` → Step 2a only
- `by-machine` → Step 2b only
- `by-os` → Step 2c only
- `machines` → Step 3
- `move` → Step 4
- `add` → Step 5
- `audit` → Step 6

If unrecognised: print the supported forms and stop.

### Step 2 — `list` (default — print both views)

Print **2a** then **2b**, separated by a horizontal rule.

#### Step 2a — by-queue

One section per queue (sorted: direct queues first, then broadcast):

```
### <queue> (N tasks) — workers: <comma-list of machine names, or "(none)">
- <dotted-task-path>  — <human schedule, e.g. "every 10 min", "Mon 08:00", "nightly 02:30">
```

Source the schedule by reading the beat entry's `crontab(...)` / `timedelta(...)` and converting to a brief English form. If you can't parse it cleanly, print the raw call.

#### Step 2b — by-machine (what would actually run on each box)

For every machine in `machines.toml` (excluding `[hostnames]` and `[default]`), print:

```
### <machine-name> — role=<role>
Subscribed queues: <comma-list>
Tasks that would run here (M total):
  ── <queue-1> ──
    - <dotted-task-path>  — <human schedule>
  ── <queue-2> ──
    - <dotted-task-path>  — <human schedule>
```

Include `(host runs Beat — dispatcher for the cluster)` annotation on whichever machine has `role = "host"`. If a queue is subscribed but has zero tasks, omit that queue's sub-section. If a machine ends up with zero tasks total, print `(no tasks would run here)` and flag it as suspicious.

If `machines.local.toml` `[hostnames]` maps the current box's hostname to a machine name, mark that machine line with `← THIS MACHINE`.

End with the machine coverage table (Step 3 output, condensed).

#### Step 2c — by-os

Group every task by its resolved OS labels (from Step 0a). Sections in this order: `windows`, `macos`, `linux`, `any`, plus an `unknown` bucket for anything that couldn't be resolved. For each:

```
### <os> (N tasks)
- <dotted-task-path>  — queue=<queue>, schedule=<human>  [annotated | heuristic: <strongest signal>]
```

Annotate each row whether the OS came from explicit `"os": [...]` in beat options or from the heuristic (and which signal triggered the heuristic). Tasks with multi-OS labels (e.g. `["windows", "linux"]`) appear under each applicable section.

After all sections, add a **routing-vs-OS check**: for each task, look up its queue's consumer machines and compare the machine's `os_label` (inferred from machine name — `windows-*` → windows, `harqis-mac-*` / `harqis-server` if comment says Mac → macos, `vps-*` → linux unless overridden). Flag any pair where the task's OS doesn't intersect any consumer's OS as `OS-MISMATCH`. Don't infer machine OS silently — print the inference rules used so the user can correct them via `machines.toml` comments.

### Step 3 — `machines`

Print a table:

```
| Machine | Subscribes to |
|---|---|
| <name> | <comma-list of queues> |
```

Include `[default]` block as `default (fallback)`. Note `machines.local.toml` `[hostnames]` mappings if relevant (e.g. "this Windows box is `windows-work-all`").

### Step 4 — `move <task-pattern> <queue>`

1. Find every entry in `task_to_queue` whose dotted path contains `<task-pattern>`. If zero matches, print "no matches" and stop. If more than 5 matches, list them and ask the user to confirm before continuing.
2. Validate `<queue>` is a real `WorkflowQueue` value. If not, suggest the closest match.
3. **Coverage check:** if `queue_to_machines[<queue>]` is empty, warn the user that no machine currently subscribes to `<queue>` and ask whether to proceed anyway, add `<queue>` to a machine in `machines.toml`, or pick a different queue. Don't silently strand tasks.
4. For each matching entry, locate it in its `tasks_config.py` file by the dotted task path. Edit the `'queue': WorkflowQueue.<OLD>` line to `WorkflowQueue.<NEW>`. Preserve all other formatting (commas, indentation, trailing `}`).
5. After all edits, run `git diff --stat workflows/` and print it. Tell the user to **restart Beat** for the new routing to take effect (`/deploy-harqis host --down` then back up).
6. **Refresh related docs** (see Step 7).

### Step 5 — `add <queue>`

1. Validate `<queue>` exists; do the coverage check from Step 4.3.
2. Ask the user for:
   - Task dotted path (must exist as an importable module — verify with `Glob workflows/<area>/tasks/<module>.py`).
   - Beat schedule in plain English (e.g. "every 10 min", "Mon 08:00", "nightly 02:30") — convert to `crontab(...)` or `timedelta(...)`.
   - Friendly job name for the dict key (default: `run-job--<func-name>`).
   - kwargs (optional).
   - `expires` seconds (default: `60 * 60`).
3. Determine the target `tasks_config.py` from the dotted path (`workflows.<area>.tasks.…` → `workflows/<area>/tasks_config.py`). If the file doesn't exist, ask before creating one.
4. Insert the new entry at the end of the existing dict (before the closing `}`), matching the surrounding indentation and trailing-comma style.
5. Print the diff, restart-Beat reminder, and a one-line "ready to commit" hint.
6. **Refresh related docs** (see Step 7).

### Step 6 — `audit`

Run Step 2's listing, then add a "Coverage gaps" section:

- Each queue that has tasks but `queue_to_machines[queue]` is empty → flag as **STRANDED** (no worker will ever pick these up).
- Each queue with only one consuming machine → flag as **single point of failure** (if that machine is offline, those tasks don't run).
- Each `[default]` fallback worker — if `default` queue has tasks, note that the fallback also serves them.
- **OS-MISMATCH** rows from Step 2c — tasks whose OS requirement doesn't intersect any consumer machine's OS (e.g. a Windows-only task on a queue served only by a Mac box).

End with a recommendation if any STRANDED, SPOF, or OS-MISMATCH issues exist (e.g. "add `peon` to `harqis-server.queues` as a backup consumer", "annotate `run_n8n_sequence` with `\"os\": [\"windows\"]` and remove `host` from `harqis-server` so it can't pick it up").

### Step 7 — Refresh related docs (mandatory after `move` and `add`)

Tasks and queues are documented in several places. Whenever Step 4 (`move`) or Step 5 (`add`) modifies a `tasks_config.py` entry, sweep these files in the same turn — don't leave doc drift behind.

**Files to check, in order:**

1. **`workflows/<area>/README.md`** — the per-workflow README for the affected area (e.g. `workflows/hud/README.md` if you moved a hud task). Update the Scheduled Tasks table row for the renamed/moved/added task — Queue column, OS column, and any per-task notes that reference the old queue.
2. **`workflows/README.md`** — only if the queue itself is new (added a value to `WorkflowQueue` enum) or a queue's *purpose* changed materially. Don't touch it for routine task moves.
3. **`README.md` (root)** — update the **Workflow Inventory** table's task count for the affected workflow. If a queue was added/removed at the enum level, also update the **Celery Task Queues** table.
4. **`docs/info/OS-COMPATIBILITY.md`** — if you added/removed an `os: [...]` annotation, update the "Beat-options `os` annotation" section's "Annotated tasks today" sentence to keep the count and examples honest.

**How to apply:**

- Prefer invoking `/update-docs` for non-trivial sweeps (3+ docs touched, or any cross-reference fan-out). Pass it a tight description of what changed: e.g. `"moved take_screenshots_for_gpt_capture from peon to hud queue"`.
- For a single localised edit (e.g. one row in one workflow README), edit directly with the Edit tool. Don't spawn `/update-docs` for a one-row change.
- **Never** add new sections, reformat tables, or rewrite prose during this step. Only update the cells that drifted.
- After editing, re-run `git diff --stat` (workflows/ + docs/) so the user sees the full set of touched files before committing.

If the docs are already up to date, say so explicitly ("docs already match — no edits needed") rather than silently skipping the step.

## Hard rules

- **Never edit `workflows/queues.py`** to add new queues without explicit user confirmation. Adding a queue means adding to `WorkflowQueue` enum, `workflows/config.py::task_queues`, and one or more `machines.toml` worker lists. Three-file change → ask first.
- **Never edit `workflows/config.py::task_routes`** unless the user explicitly asks. Pattern routing affects every task matching the glob.
- **Never edit `machines.toml` queue lists** without asking. Adding a queue to a machine changes that machine's worker subscription on next deploy.
- **Always show the diff** after editing. Use `git diff --stat workflows/` (or `git diff` for small changes).
- **Always remind to restart Beat.** Routing changes take effect only on the next Beat dispatch.
- **Always refresh related docs** (Step 7) after any `move` or `add`. A queue/task change isn't done until the per-workflow README, the root README's Workflow Inventory + Celery Task Queues tables, and `docs/info/OS-COMPATIBILITY.md` (if `os` annotations changed) reflect the new state. Skipping this leaves silent drift that a future `/manage-queues list` won't catch.

## Failure modes

- **Task pattern matches 0 tasks** — say so and exit. Don't guess.
- **Queue doesn't exist in `WorkflowQueue`** — list valid values, suggest the closest, exit.
- **Multi-file move** (e.g. several tasks across `workflows/desktop/` and `workflows/hud/`) — confirm the full set before editing.
- **Coverage gap (queue has no consumer)** — block on confirmation; don't silently strand work.
- **`tasks_config.py` parse fails** (entry not found by dotted path) — print the file path + suggest the user open it, exit. Don't blind-edit.
