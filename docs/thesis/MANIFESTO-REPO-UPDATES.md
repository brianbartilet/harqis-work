# Aligning `workflows/` with the MANIFESTO — sweep and proposed updates

> Companion to [`docs/MANIFESTO.md`](../MANIFESTO.md). This document records the audit of `workflows/` against the four operating principles, the gaps found, and the concrete changes this PR ships to close them.

---

## TL;DR

| Gap | Severity | Change in this PR |
| --- | --- | --- |
| Each task's CODE phase, PARA bucket, Express target, Review artifact, HFL flag are implicit (inferred from name or code body) | Blocks Habit 2 ("end in mind") and dead-weight detection | Add an optional `'manifesto'` block to every beat entry across all six active workflows |
| `analyze_daily_dumps` captures inbox state and stops — no Express path, only an Elasticsearch debug log | Hard manifesto violation: "captures that never get expressed are dead weight" | Replace the `# AGENT WIRE-UP HERE` stub with a real Express path (HUD-feed summary tile + structured ES log) |
| Homework-for-Life is named in the manifesto as a first-class data source, but no workflow captures, retrieves, or summarizes entries | Principle 2 is undelivered | Scaffold a new `workflows/hfl/` (inactive — importable but not in beat schedule yet) with capture / retrieve / summarize tasks |
| No automated way to enforce manifesto alignment or surface drift | Principle 7 ("sharpen the saw") requires a check, not a vibe | Add `scripts/agents/manifesto_audit.py` — walks all `tasks_config.py`, validates the metadata, exits non-zero on violations |
| `workflows/.template/` scaffold lacks the new metadata and produces dead-weight tasks by default (no Express target, no log_result) | New workflows would drift from the manifesto on day one | Update `workflows/.template/tasks_config.py` and the demo task so `/create-new-workflow` output is manifesto-aligned |
| Workflow READMEs are substantive on *what* each task does but silent on *which manifesto phase* it occupies | Habit 5 cost — a reader has to read code to learn the phase | Add a "Manifesto alignment" section to every workflow README, plus an updated root `workflows/README.md` |

**What this PR is not:** a rewrite of any task body. Every change is additive metadata, new scaffold code, or doc. Existing schedules, queues, and decorator stacks are untouched. Risk is bounded to the single behavioral change in `analyze_daily_dumps` (which currently does nothing actionable, so the floor is "no worse than now").

---

## 1. Why this sweep was triggered

`docs/MANIFESTO.md` landed earlier in the same merge train as this PR. It declared four operating principles (CODE + PARA, Homework for Life, the 7 Habits, the PAER loop) and asserted them as governing for both humans and LLMs working in the repo. With the principles fresh in writing, the question became: **how much of the existing `workflows/` tree already complies, and where does it drift?**

The manifesto's own Habit 5 ("seek first to understand") demanded an audit before any code change. The audit ran first; this PR is its Express output.

---

## 2. Audit method

A read-only sweep of every directory under `workflows/`:

1. Inventoried each subdirectory's `tasks_config.py`, `tasks/*.py`, and `README.md`.
2. For every `@SPROUT.task`-decorated function, extracted: decorator stack, schedule, queue, kwargs, and the destination of the task's output (HUD feed, Rainmeter widget, ES log, external API, file on disk, return value).
3. Classified each task into one of CODE's four phases — **Capture**, **Organize**, **Distill**, **Express** — by name + body inference.
4. Filed each *workflow* (not task) into a PARA bucket: most are Areas (ongoing responsibilities like the HUD, knowledge corpus, marketplace pipeline); a few are Projects (active rollouts with deadlines); none are Resources or Archive.
5. Flagged any task whose only output was an Elasticsearch debug log with no downstream consumer.
6. Cross-referenced personal-signal sources (calendar, location, finance, comms, screen capture) against the manifesto's HFL framing.

Full inventory tables are summarized below; the per-task detail is now persisted as the `'manifesto'` block on each beat entry, so the audit is no longer a one-shot artifact — it is checked-in metadata anyone can grep.

---

## 3. What the audit found

### 3.1 Coverage by workflow

| Workflow | Tasks | CODE phases present | PARA bucket | HFL-relevant? | Status |
| --- | --- | --- | --- | --- | --- |
| `desktop` | 7 | Capture, Organize, Distill+Express | Area | Yes (activity logs, screenshots, summaries) | Active |
| `dumps` | 3 | Capture (×2), Distill placeholder | Area | Yes (daily file snapshots from devices) | Active — analyzer task is dead weight (fixed in this PR) |
| `hud` | 17 | Capture (×11), Organize (×2), Distill (×4), one Distill+Express (`show_daily_radar`) | Area | Indirect — `show_daily_radar` synthesizes calendar/email/location | Active |
| `knowledge` | 5 | Capture (×4 ingestors), Distill+Express (`answer`) | Area | Upstream-only (ingests Notion, which is where HFL entries land) | Active |
| `purchases` | 5 | Capture (`download_scryfall_bulk_data`), Organize (`generate_tcg_mappings`), Distill (`generate_audit_for_tcg_orders`), Express (×2) | Area | No | Active |
| `social` | 1 | Distill+Express | Area | Yes (work stories, themes) | Active |
| `finance` | 1 (designed) | Capture+Organize+Express (`add_ynab_transactions_from_pdf`) | Area | No | **Inactive** — `tasks_config.py` empty, README describes intent. Not activated in this PR (out of scope). |
| `mobile` | 0 Celery tasks | Capture-on-device | Area | Yes (Android foreground/OCR) | Standalone — runs as a Termux loop, syncs via `dumps` |
| `n8n` | 0 | (utilities only) | Resource | No | Helpers, not a beat workflow |
| `.template` | 1 demo | (no phase — placeholder) | Resource | No | Scaffold (updated in this PR) |

### 3.2 The one hard violation

`workflows/dumps/tasks/analyze.py::analyze_daily_dumps` is scheduled daily at 01:00. It walks the day's inbox tree, computes counts and totals, and writes them to the Elasticsearch log. Then it stops. The code carries an explicit marker:

```python
# AGENT WIRE-UP HERE
# TODO: hand off to a kanban agent profile
```

The manifesto's load-bearing rule: **"Anything captured must have a defined Express path within one hop. Captures that never get expressed are dead weight."** This task captures and never expresses. The Elasticsearch log is a Review artifact, not an Express target — it goes nowhere a human or downstream task can act on.

This PR replaces the stub with a real Express path: the analyzer writes a structured one-line-per-machine summary to the HUD feed (`@feed()`), so the operator sees "today's dumps landed for N machines (M files, K bytes)" on the same surface they already scan. A future Trello hand-off can layer on top without re-opening this gap.

### 3.3 The principle-level gap: HFL is named but unbuilt

The manifesto treats Homework for Life as a "first-class data source, not a journaling app" and specifies a standard entry shape:

```text
## YYYY-MM-DD
Moment:
What happened:
Why it stayed with me:
Possible use:
Tags:  #work-story #debugging #automation …
```

But no workflow exists to:

- Capture entries on a defined cadence (or in response to a signal).
- Retrieve entries by tag, theme, or date range.
- Roll up the week into a digestible summary.

Workflows that *touch* personal signal (`desktop` screen captures, `dumps` device snapshots, `hud_calendar`, `hud_radar`, `social_linkedin_monthly`) do so for their own Express targets, not for HFL. Notion is where the operator's daily entries land today — but the existing `ingest_notion_pages` treats Notion as a generic knowledge base, not as an HFL corpus with its own retrieval idiom.

This PR scaffolds `workflows/hfl/` to make HFL a real workflow surface. It is **left inactive** (not imported into `workflows/config.py`'s beat schedule) so it ships as a contract, not a behavior change. Wiring it on is a follow-up flip of two lines once the operator has loaded the first set of entries and tuned the prompts.

### 3.4 The schema gap: implicit metadata

Every active beat entry today looks like:

```python
'run-job--show_forex_account': {
    'task':     'workflows.hud.tasks.hud_forex.show_forex_account',
    'schedule': crontab(day_of_week='mon-fri', minute='*/15'),
    'kwargs':   {...},
    'options':  {'queue': WorkflowQueue.HUD, 'os': ['windows'], 'expires': 60 * 5},
},
```

There is no field that says *what manifesto phase this task occupies* or *what its Express target is*. To answer either, a reader must open `hud_forex.py` and trace the decorator stack. That violates Habit 2 ("begin with the end in mind — Express path before Capture path"). It also makes principled tooling impossible — a script cannot find dead-weight tasks if every task hides its target inside code.

The fix is to elevate the audit from one-shot to declarative. Each beat entry grows an optional `'manifesto'` block:

```python
'manifesto': {
    'code_role':       'capture',           # capture | organize | distill | express
    'para_bucket':     'area',              # project | area | resource | archive
    'express_target':  'rainmeter:FOREX_ACCOUNT',
    'review_artifact': 'es_log+hud_widget',
    'hfl_signal':      False,
},
```

Celery beat ignores keys it doesn't know about (only `task`, `schedule`, `args`, `kwargs`, `options`, `relative` are consumed), so this is a pure documentation channel that survives `python workflows/config.py` import time. The audit script in §4.3 reads it back to surface drift.

### 3.5 Other findings the PR does **not** act on

These were noted in the audit but deliberately deferred:

- **Decorator stacking order varies** (`@SPROUT.task() → @log_result() → @feed()` in some files, `@log_result() → @feed() → @SPROUT.task()` in others). Composes correctly either way; standardizing it would touch every task body for no functional benefit. Logged for a future cleanup PR.
- **`workflows/finance/` is designed but inactive** — `tasks_config.py` is empty, the README explains how to activate. Activating it from this PR would conflate "manifesto alignment" with "ship the finance feature," and the manifesto's own Habit 3 says first-things-first. Out of scope here.
- **Implicit task chains** (e.g. `take_screenshots_for_gpt_capture` → on-disk PNGs → `get_desktop_logs` reads them) are loosely coupled via side effects. The manifesto doesn't demand a chain DAG; the audit notes them and the per-task `express_target` makes the chain greppable. Building a real DAG visualizer is a separate piece of work.

---

## 4. What this PR ships

Eight discrete changes, ordered by review difficulty (easiest first).

### 4.1 `docs/thesis/MANIFESTO-REPO-UPDATES.md`

This file. Acts as the PR's design doc; lives under `docs/thesis/` per the repo convention that thesis docs are *why* documents, not how-tos.

### 4.2 The `'manifesto'` metadata block on every beat entry

Every entry in every active workflow's `tasks_config.py` gains a `'manifesto'` key:

| Field | Values |
| --- | --- |
| `code_role` | `'capture'`, `'organize'`, `'distill'`, `'express'` (or a `'+'`-joined hybrid for the rare task that does two phases, e.g. `'distill+express'` for `show_daily_radar`) |
| `para_bucket` | `'project'`, `'area'`, `'resource'`, `'archive'` — almost every workflow is an Area; new initiatives become Projects until they stabilize |
| `express_target` | Free-form short string. Conventions: `'hud_feed'`, `'rainmeter:<METER_NAME>'`, `'es_log'`, `'api:<service>'`, `'file:<purpose>'`, `'vectorstore:<name>'`, `'message:<channel>'`, `'none'` (only for archive-status tasks) |
| `review_artifact` | What a human or downstream task can read to verify the run happened. Usually `'es_log'`, often `'es_log+hud_widget'` or `'es_log+file'` |
| `hfl_signal` | `True` when the task's output contributes (or should contribute) to the Homework-for-Life corpus. Used by the audit and by the future HFL ingestor. |

Touched files (all additive — no behavioral change):

- `workflows/desktop/tasks_config.py` — 7 entries
- `workflows/dumps/tasks_config.py` — 3 entries
- `workflows/hud/tasks_config.py` — 17 entries
- `workflows/knowledge/tasks_config.py` — 5 entries
- `workflows/purchases/tasks_config.py` — 5 entries
- `workflows/social/tasks_config.py` — 1 entry

### 4.3 `scripts/agents/manifesto_audit.py`

A small CLI that walks every `workflows/*/tasks_config.py`, loads the dicts, and validates:

1. Every task has a `'manifesto'` block (or is in an explicit allow-list).
2. Every `code_role: 'capture'` task has an `express_target` other than `'none'`.
3. Every task has a non-empty `review_artifact`.
4. Reports — but does not fail on — `hfl_signal: True` tasks that are not yet wired into the HFL ingestor.

Exits non-zero on hard violations so CI / pre-commit can enforce. Soft warnings print but don't fail the run.

### 4.4 `workflows/hfl/` scaffold (inactive)

New directory with the canonical workflow layout:

```
workflows/hfl/
├── __init__.py
├── README.md
├── tasks_config.py          # Beat entries — present but not yet imported in workflows/config.py
└── tasks/
    ├── __init__.py
    ├── capture.py           # capture_hfl_entry(moment, happened, insight, tags)
    ├── retrieve.py          # retrieve_hfl_corpus(query, k=8, since=None)
    └── summarize.py         # summarize_hfl_week()
```

The capture task writes a structured Markdown entry to a configurable corpus path (default: `<DESKTOP_PATH_FEED>/hfl/YYYY-MM-DD.md`). Retrieval is initially grep + frontmatter parse — RAG via the existing knowledge workflow is a follow-up once the corpus has critical mass. Summarize uses Haiku 4.5 per the project's cost-sensitive-tasks convention.

The scaffold is **not imported** in `workflows/config.py` — flipping it on is a two-line change once the operator is ready. Shipping inactive is deliberate: the manifesto's contract is that HFL is a first-class workflow surface, and the contract is now visible in the tree; turning it on becomes a separate, deliberate decision.

### 4.5 Fix `analyze_daily_dumps`

`workflows/dumps/tasks/analyze.py` currently:

```python
@SPROUT.task(name="...")
@log_result()
def analyze_daily_dumps(...):
    # walk inbox, count files & bytes
    # AGENT WIRE-UP HERE
    return {"machines": [...], "files_count": N, "bytes_total": B}
```

After this PR it gains a real Express path: the same return payload is rendered as a per-machine summary line and pushed to the HUD feed via `@feed()`. The operator now sees on the HUD: "Daily dumps · 2026-05-13 · 6 machines · 4,182 files · 12.3 GB · top by bytes: harqis-server (8.1 GB)". The Trello hand-off marker stays in the code as a follow-up comment, but the dead-weight gap is closed.

### 4.6 Workflow READMEs

Each `workflows/<name>/README.md` gains a **Manifesto alignment** section: a small table mapping each task to its `code_role`, `para_bucket`, `express_target`, `review_artifact`, `hfl_signal`. The root `workflows/README.md` gets a short section explaining the `'manifesto'` block and linking the thesis doc.

### 4.7 Template update

`workflows/.template/tasks_config.py` and `workflows/.template/tasks/do_random.py` are updated so any workflow generated from the template inherits the manifesto metadata pattern by default — `code_role`, `para_bucket`, `express_target`, `review_artifact`, `hfl_signal` all filled in as commented placeholders the operator (or `/create-new-workflow`) replaces.

### 4.8 Branch + PR

Single branch `feat/manifesto-alignment-sweep`, committed in logical chunks, opened as a PR against `main` so the change set is reviewable section by section.

---

## 5. PAER trace for this PR

Per the manifesto's PAER loop, externalizing each phase:

- **Plan.** Decision: thesis + full implementation across all six active workflows, additive metadata only. Out of scope: rewriting task bodies, activating finance, standardizing decorator order, building DAG tooling.
- **Analyze.** Read every `tasks_config.py`, every `tasks/*.py` entry point, every workflow README. Output: §3 of this doc.
- **Execute.** §4 of this doc — the actual diff.
- **Review.** This PR description itself; the `scripts/agents/manifesto_audit.py` exit code; the operator's read of the per-workflow alignment tables. If any of the three surface drift, the fix is to update either the metadata or the manifesto, whichever is wrong.

---

## 6. Risks and what they look like if they go wrong

| Risk | Probability | Mitigation |
| --- | --- | --- |
| Celery beat rejects the new `'manifesto'` key | Very low — Celery beat reads named keys only and ignores extras | Smoke-import `workflows.config` before commit; rollback is a one-line removal per file if it ever fires |
| `analyze_daily_dumps` Express path errors when the inbox is empty | Low — the existing return path already handles empty inboxes; `@feed()` no-ops on unresolved config (see the earlier feed.py fix) | The new code paths the same dict through a small renderer with explicit `if not machines` short-circuit; tests in `workflows/dumps/tests/` |
| HFL scaffold accidentally gets enabled and writes to a misconfigured corpus path | Low — workflow is not in `workflows/config.py` import list, so beat never sees it; the capture task validates its corpus path before writing | Activation is a separate, named PR |
| Metadata drifts from reality over time | Medium — same risk as any inline doc | `scripts/agents/manifesto_audit.py` is the safety net; consider wiring it into pre-commit later |

---

## 7. Out-of-scope follow-ups

Tracked here so they aren't lost:

1. **Activate `workflows/finance/`** — populate `tasks_config.py`, import in `workflows/config.py`. Documented activation steps already exist in `workflows/finance/README.md`.
2. **Activate `workflows/hfl/`** — import in `workflows/config.py`, choose a corpus path, tune the summarize prompt, optionally wire HFL ingest into the `knowledge` workflow's RAG.
3. **Standardize decorator stacking order** — `@SPROUT.task() → @log_result() → [@feed() | @init_meter()]` across every task. Mechanical, no functional change.
4. **Pre-commit hook for `manifesto_audit.py`** — fail fast on dead-weight introductions.
5. **DAG visualizer** — surface implicit task chains (file-on-disk producers/consumers) so the operator can see the data flow without re-reading code.
6. **Trello hand-off for `analyze_daily_dumps`** — the comment marker stays; build it when the operator has a Trello board provisioned for it.

---

## 8. Acceptance criteria

This PR is ready to merge when:

- [ ] `python -c "import workflows.config"` runs clean (smoke-import, proves Celery is happy with the new metadata key).
- [ ] `python scripts/agents/manifesto_audit.py` exits 0.
- [ ] Every active `tasks_config.py` carries a `'manifesto'` block on every entry.
- [ ] `workflows/hfl/` exists with the four scaffold files, is **not** imported in `workflows/config.py`.
- [ ] `workflows/dumps/tasks/analyze.py` no longer carries `AGENT WIRE-UP HERE` as a TODO blocker; the comment may remain as a future-hand-off marker but the Express path is real.
- [ ] Each `workflows/<name>/README.md` has a Manifesto alignment section.
- [ ] Root `workflows/README.md` references this thesis.

---

## 9. Related reading

- [`docs/MANIFESTO.md`](../MANIFESTO.md) — the source of truth for the four principles.
- [`docs/info/SKILLS-INVENTORY.md`](../info/SKILLS-INVENTORY.md) — slash commands that operationalize the manifesto into builds (notably `/create-new-workflow`, which now inherits the manifesto metadata pattern via the updated template).
- [`workflows/README.md`](../../workflows/README.md) — queue topology and broadcast rules; gains a short manifesto-alignment section.
- [`docs/thesis/RAG-WORKFLOW.md`](RAG-WORKFLOW.md) — design rationale for `workflows/knowledge/`; relevant to the HFL retrieval follow-up.
