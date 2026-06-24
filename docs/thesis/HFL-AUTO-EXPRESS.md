# Auto-expressing `hfl_signal` — task output → HFL corpus

> A *why* document (per the `docs/thesis/` convention). Describes how a task's
> `manifesto.hfl_signal` flag becomes an actual Homework-for-Life entry, the
> design chosen (Option B), and how it consolidates with the existing
> `workflows/hfl/` pipeline. Phase 1 of this design ships alongside this doc.

---

## 1. Problem

Every scheduled task carries a `manifesto` metadata block (see
[`MANIFESTO-REPO-UPDATES.md`](MANIFESTO-REPO-UPDATES.md)). One field,
`hfl_signal: True`, declares *"this task's output is personal/lived signal that
belongs in the Homework-for-Life corpus."*

Today that flag is **inert**. It lives in the beat-schedule entry in
`tasks_config.py`, is **stripped before Celery** (`workflows/config.py::_celery_safe_schedule`),
and is read only by the manifesto audit and docs tooling. ~20 tasks set it
`True`, but nothing turns their successful runs into corpus entries.

**Goal:** when an `hfl_signal` task runs successfully, its output should
automatically become an HFL entry — without per-task boilerplate, without
flooding the corpus, and without fighting the existing ingest pipeline.

## 2. What already exists (and must be reused, not duplicated)

The HFL write path is a single, clean funnel:

- `HflEntry` DTO (`when, moment, what_happened, why_it_stayed, possible_use,
  tags, references`) → `es_store.index_hfl_entry(entry, source=, doc_id=)`,
  which upserts into `harqis-hfl-entries` with a deterministic id. Best-effort,
  never raises.
- The existing ingest tasks (`ingest_git`, `ingest_plaud`, `analyze_hfl_media`,
  …) are all **PULL + self-express**: each runs on its own schedule, pulls from
  a source, Haiku-distills *one entry per day (or per item)*, and calls
  `index_hfl_entry` itself.

Auto-express must plug into this funnel as **another source**, not a parallel
writer.

## 3. The three hard problems

1. **Heterogeneous output.** Task returns have no common shape — HUD tasks
   return rendered strings, ingest tasks return `{"entries_written": N}`,
   `broadcast_report_location` returns a location doc. There is no universal
   "moment" to extract.
2. **Frequency/volume mismatch.** HFL entries are *daily-granularity stories*,
   but `get_schedules` runs 6×/day, `show_daily_radar` 4×/day,
   `broadcast_report_location` ~96×/day across N workers. One entry per
   successful run would bury the corpus in operational noise.
3. **Double-write.** The `workflows/hfl/*` ingestors already self-express **and**
   carry `hfl_signal: True`. Naively expressing on every `hfl_signal` success
   would duplicate their entries.

## 4. Design — Option B: signal buffer + daily rollup

Split **capture** (cheap, per-run) from **express** (batched, daily, LLM) —
exactly the CODE lifecycle:

```
task runs OK ──▶ task_success hook ──▶ append 1 lightweight signal
                  (no LLM, ~instant)     to harqis-hfl-signals (buffer)

                                  … signals accumulate through the day …

daily 23:20 ──▶ rollup_hfl_signals ──▶ group by source, Haiku-distill each
                                        group → index_hfl_entry (existing path)
```

- **Capture (Phase 1, shipped):** a Celery `task_success` handler appends one
  cheap, no-LLM **signal record** to a dedicated buffer index `harqis-hfl-signals`.
- **Express (Phase 2, planned):** a daily `rollup_hfl_signals` HFL task reads the
  day's buffered signals, groups by source, distills each group into a small
  number of proper entries, and writes through `index_hfl_entry`.

Why this solves the three problems:

| Problem | How Option B handles it |
|---|---|
| Heterogeneous output | The buffer stores a cheap string summary now; the daily rollup is what turns grouped summaries into prose. |
| Frequency/volume | 96 raw signals/day collapse into ≤1 distilled entry per source per day. The corpus stays story-grained. |
| Double-write | Self-expressing tasks set `hfl_express: 'self'` (or omit it) and the hook skips them. |
| Cost | No LLM on the hot path; one bounded Haiku batch per source per day. |

### 4.1 Manifesto schema addition — `hfl_express`

`hfl_signal` stays the *"is this HFL-relevant?"* label. A new optional field
says *"what should the wiring DO?"*:

```python
'manifesto': {
    'code_role': 'capture',
    'hfl_signal': True,
    'hfl_express': 'buffer',   # NEW — optional. 'self' | 'buffer' | 'none'
    ...
}
```

| `hfl_express` | Meaning |
|---|---|
| `'self'` | Task writes its own HFL entry; the hook skips it. (All current `workflows/hfl/*` ingestors.) |
| `'buffer'` | Each successful run buffers a signal for the daily rollup. (The opt-in candidates.) |
| `'none'` / absent | `hfl_signal` stays a pure label; no auto-express. **Default — fully backward-compatible.** |

Nothing changes for an existing task until it is explicitly opted in. The audit
(`manifesto_audit.py`) already ignores unknown extra keys; a follow-up can add
soft-validation of `hfl_express` values (Phase 3).

### 4.2 Where the hook lives — `task_success`, not `@log_result`, not task bodies

A single Celery `task_success` receiver (`workflows/hfl/express_signals.py`):

- reads `sender.name` (dotted task path) + the return value,
- recovers the task's `manifesto` block from `CONFIG_DICTIONARY` via a
  lazily-built `task-path → manifesto` map (the block is stripped from the
  Celery schedule, so this is the only place it survives),
- if `hfl_express == 'buffer'`, writes one signal via `signal_store.index_hfl_signal`.

Rejected alternatives:

- **Inside `@log_result`** — that decorator is in `harqis-core`; baking HFL into
  it breaches the migrate-to-core boundary (AI/HFL stays in harqis-work).
- **Inside each task body** — 20+ invasive edits, easy to forget on new tasks.

The receiver is connected by importing `workflows.hfl.express_signals` at the
bottom of `workflows/config.py` — the module the sprout app imports on **both**
beat and worker startup (`core/apps/sprout/__init__.py`), so the signal connects
in both processes. The import is at the bottom (after `CONFIG_DICTIONARY`) and
`express_signals` imports `CONFIG_DICTIONARY` lazily, so there is no circular
import.

### 4.3 The signal buffer (`harqis-hfl-signals`)

Reuses the `ELASTIC_LOGGING` app config (same as `es_store` / `@log_result`) —
no new credentials. One document per buffered run:

| Field | Meaning |
|---|---|
| `task` | dotted task path (producer) |
| `source` | rollup grouping key, e.g. `signal:get_schedules` |
| `summary` | cheap no-LLM digest of the task output (≤1000 chars) |
| `status` | `success` |
| `when` / `entry_date` | event time |
| `references` | the task's `express_target` (provenance, carried into the entry) |
| `rolled_up` | `False`; Phase 2 flips this when the rollup drains it |

The doc id is `minute-bucket + task + hash(dedup_key)`, so a task **retry** or a
broadcast **re-fire** with the same output in the same minute upserts rather
than duplicating, while genuinely distinct runs are all preserved.

## 5. Consolidation with existing `workflows/hfl`

This is the core review question — *does it fight the existing pipeline?* No,
because auto-express is a **source**, not a competing writer:

- The rollup writes via the **same** `index_hfl_entry` as `ingest_plaud` et al,
  with `source="signal:<task>"`. The corpus/ES schema, deterministic dedup,
  retrieval (`query_hfl_entries`, the `memory_recall` MCP), and the weekly
  `summarize_hfl_week` + `resolve_references` all work unchanged.
- The `workflows/hfl/*` ingestors are **exempt** (they self-express): they set
  `hfl_express: 'self'` or omit it, so the hook skips them — no double-write.
- The buffer is a **staging** index, distinct from the corpus. The corpus stays
  the source of truth and story-grained; the buffer is drained daily and can be
  pruned with a short ILM/retention policy.

Net: one new capture source feeding the existing distill→index pipeline, plus
one new daily task that looks exactly like the other ingestors.

## 6. Phasing

| Phase | Scope | Status |
|---|---|---|
| **1 — capture** | `task_success` hook + `signal_store` buffer (no LLM) + opt one task in (`get_schedules`) + unit tests | **Shipped with this doc** |
| **2 — rollup** | `rollup_hfl_signals` daily task: buffer → grouped Haiku distill → `index_hfl_entry`; mark `rolled_up` | Planned |
| **3 — refinement** | per-task `to_signal` transforms for richer summaries; `manifesto_audit` validation of `hfl_express`; broadcast-task dedup; buffer retention policy | Planned |

## 7. Risks & open questions (for review)

- **Broadcast tasks** (`workers_broadcast`) fire on N workers → N signals. The
  minute-bucket dedup collapses identical output, but per-worker-distinct output
  (e.g. each worker's own location) will produce N records. Phase 1 opts in only
  a non-broadcast task; broadcast handling is a Phase 3 decision (dedup by
  content vs. one-entry-per-worker vs. exclude).
- **Privacy/trust boundary.** Buffered summaries land in the same ES cluster as
  `@log_result` (which already logs task args), so no new boundary — but the
  rollup prompt sends summaries to Anthropic. Same posture as the other ingests.
- **Which tasks to opt in.** Phase 1 ships `get_schedules` as the demonstrator.
  Candidates for Phase 2+: calendar/schedule, dumps, knowledge, social — the
  tasks whose output reflects *what happened*, not HUD chrome or fleet health.
- **Summary quality.** The Phase 1 summary is a raw stringify. If the daily
  rollup struggles to distill it, Phase 3's per-task transforms are the fix.

## 8. Related reading

- [`MANIFESTO-REPO-UPDATES.md`](MANIFESTO-REPO-UPDATES.md) — the `manifesto`
  block and the original audit.
- [`../MANIFESTO.md`](../MANIFESTO.md) §1 — CODE (Capture→Distill→Express),
  which this design operationalizes for task output.
- `workflows/hfl/es_store.py` — the `index_hfl_entry` funnel this reuses.
