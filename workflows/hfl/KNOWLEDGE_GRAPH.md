# HFL Knowledge Graph — Three-Phase Rollout

> Turn the HFL corpus + dumps inbox into a queryable knowledge graph so the
> manifesto's "queryable by prompt" promise becomes real graph traversal
> instead of substring scanning.

## Why this exists

`workflows/hfl/` already captures a daily structured Markdown corpus from
8 ingestors (ChatGPT, browsing, location, AI threads, media vision, time
capsules, manual capture, weekly summaries). The manifesto explicitly
promises the corpus becomes **"queryable by prompt"** —
*"What was I working on the week of 2026-04-12?"*, *"Reconstruct the
timeline for the OANDA forex agent rollout."*

Today's `retrieve_hfl_corpus` answers that promise with a substring + tag
scan. Each retrieval re-reads every file. The connections between entries
(person → project → tech → place → time) are implicit; you have to
already know what to search for. **A knowledge graph closes that gap.**

`workflows/dumps/` is the second half of the same opportunity: a daily
multi-machine file inbox (screenshots, photos, logs) that today is
write-only — `analyze_daily_dumps` emits a per-machine summary to the
HUD feed and stops there. The inbox is exactly the kind of multi-modal
content Graphify ingests natively.

---

## Graphify in 30 seconds

[Graphify](https://graphify.net) is an MIT-licensed OSS tool that builds
queryable knowledge graphs from multi-modal content. Core stack:

| Layer | Tech |
|---|---|
| Code structure | Tree-sitter (31 languages) → ASTs, call graphs, docstrings |
| Prose / Markdown / PDF | LLM semantic extraction via your own API key |
| Images / diagrams | Vision-model pass |
| Graph construction | NetworkX + Leiden clustering |
| Output | `graphify-out/` with `graph.html` (interactive), `GRAPH_REPORT.md` (audit), `graph.json` (persistent) |

**Privacy**: never sends raw source/bytes; only semantic descriptions.
No telemetry. Aligns with harqis-work's self-hosted posture.

**Headline claim**: ~71.5× query-token reduction vs full-text RAG —
matters because the daily Anthropic budget is bounded.

PyPI package is `graphifyy` (double y); the CLI is `graphify`.

---

## Phase 1 — HFL corpus graph ✅ SHIPPED IN THIS PR

### What it does

`workflows/hfl/tasks/build_knowledge_graph.py` wraps the Graphify CLI as
a Celery task. Run it adhoc; it:

1. Resolves the corpus root via the documented precedence
   (`apps_config.yaml::HFL.corpus.path` → `HFL_CORPUS_PATH` env → repo
   `logs/hfl/`).
2. Pins **Haiku 4.5** via `ANTHROPIC_MODEL` / `GRAPHIFY_MODEL` env vars
   exported into the subprocess (project convention — never raise
   `BaseApiServiceAnthropic.DEFAULT_MODEL`).
3. Writes outputs under `<corpus_dir>/_graph/<YYYY-Www>/`:
   - `graph.html` — interactive viewer (open in any browser)
   - `GRAPH_REPORT.md` — one-page audit: top concepts + surprising connections
   - `graph.json` — the persistent graph; future `retrieve_hfl_via_graph` traverses this
4. Projects a build summary doc into the `harqis-hfl-graph` ES index
   (env `HFL_GRAPH_ES_INDEX` overrides). Deterministic id on
   `(corpus_dir, ISO week)` → re-runs upsert.

### Hard contract

- **graphify CLI missing** → `WARNING` log + `{"ok": False, "skipped": "cli_missing"}` — Beat never breaks.
- **Empty corpus** → no-op with `skipped="empty_corpus"`.
- **Subprocess timeout** (default 30 min) → `WARNING` + `{"ok": False, "reason": "timeout"}`.
- **Non-zero exit** → `WARNING` + stderr tail in the result for diagnosis.
- **ES projection failure** → swallowed; graph files on disk are the win.

### Beat schedule

Phase 1 ships **adhoc-only** (`crontab(day_of_week='sun', hour=3, minute=35)`
— an effectively-never slot mirroring the `capture_hfl_entry` pattern).
Invoke via `.delay()`, the MCP layer, or `/run-tests`-style smoke. Promote
to a real weekly cadence (Sunday 21:30, after `summarize_hfl_week`) once
Phase 1 is validated — see *Phase promotion* below.

### Activation

```bash
# 1. Install graphify (note the double-y package name)
pip install graphifyy

# 2. Verify CLI is on PATH
graphify --help

# 3. Smoke-run adhoc from any harqis-work shell with Sprout configured
python -c "from workflows.hfl.tasks.build_knowledge_graph import build_hfl_knowledge_graph; \
           print(build_hfl_knowledge_graph(corpus_dir_override=None))"

# 4. Inspect the result
open logs/hfl/_graph/<latest>/graph.html   # macOS
explorer logs\hfl\_graph\<latest>\graph.html  # Windows
```

### Cost guard

| Knob | Default | Effect |
|---|---|---|
| `model` | `claude-haiku-4-5-20251001` | Locks the cheapest production model. |
| `max_files` | 500 | Caps how many corpus files graphify hands to the LLM. |
| `timeout_sec` | 1800 (30 min) | Hard ceiling on the subprocess. |

A typical week's HFL corpus is 7–30 files; max_files=500 covers months of
backfill on a first run.

---

## Phase 2 — Dumps multi-modal graph (planned)

### Scope

New `workflows/dumps/tasks/build_dumps_graph.py` that:

1. Runs Graphify with vision-mode enabled over the latest day's folder
   under `<harqis_server_inbox>/`.
2. Filters aggressively (images, screenshots, PDFs only — raw logs are
   noise) before feeding files to the subprocess.
3. Merges into a rolling `dumps-graph` ES index keyed by
   `(machine, date, node_id)`.
4. Cross-links to HFL entries via the **shared file-path key** that
   `analyze_hfl_media` already uses (the dump file path → the HFL entry
   `references`).

### Outcome

Ask *"show me everything from the OANDA forex agent rollout week"* and a
single graph traversal pulls:

- The HFL stories tagged `#oanda` or `#forex`
- The dump screenshots from those days (camera roll + screenshots)
- The location timeline for that week (Nominatim stay-points)
- The ChatGPT distillation entries from that period

…all connected, all token-cheap.

### Dependencies on Phase 1

- Reuses `_build_env` and ES projection helpers (will be lifted to a
  shared `workflows/_lib/graphify_runner.py` when Phase 2 lands).
- Reuses the `tenant_safe` manifesto pattern.

### Cadence

Daily after the existing `analyze_daily_dumps` (01:00 local + 30 min →
01:30) so the graph reflects what the analyzer already cataloged.

---

## Phase 3 — Surface (planned)

Three small additions, each independent of the other:

### 3a — HUD widget `hud_knowledge_graph`

`workflows/hud/tasks/hud_knowledge_graph.py` — Rainmeter section that
reads the latest `harqis-hfl-graph` ES doc and shows:

- Week's top-N connected concepts
- Node/edge/cluster counts
- A "surprising connection" line lifted from `GRAPH_REPORT.md`

One file, fits the existing HUD pattern; see
`docs/info/SKILLS-INVENTORY.md` → `/create-new-hud` for scaffolding.

### 3b — Frontend route `/graph`

`frontend/main.py` adds a `StaticFiles` mount that serves the latest
`graph.html` from the corpus dir. One-liner; gated behind the existing
auth (single-tenant) or the Clerk middleware (multi-tenant from PR #27).

### 3c — MCP tool `hfl_graph_query`

`workflows/hfl/mcp.py` exposes `hfl_graph_query(question: str, k: int)`
that:

1. Embeds the question.
2. Walks `graph.json` from the latest build.
3. Returns the top-k connected entry summaries to the calling agent.

This is the same retrieval pattern as `workflows/knowledge/answer.py`,
but over the HFL graph instead of the Notion/Jira/GitHub/Drive vector
store. Closes the loop on the manifesto promise.

---

## Phase promotion (Phase 1 → real schedule)

Promote the Phase 1 task from adhoc-only to weekly when **all** of:

1. Three consecutive adhoc runs complete in < 5 minutes each.
2. `GRAPH_REPORT.md` for a typical week surfaces ≥ 3 connections that the
   substring `retrieve_hfl_corpus` would not have found.
3. The Anthropic cost per run (visible in `hud_api_costs`) is below
   $0.20 — the budget we already accept for `summarize_hfl_week`.
4. No `WARNING` logs from `hfl.build_knowledge_graph` over a 14-day
   window of adhoc runs.

Promotion is a one-line edit in `workflows/hfl/tasks_config.py`:
swap the Sunday 03:35 slot for `crontab(day_of_week='sun', hour=21, minute=30)`
(right after `summarize_hfl_week` at 21:00).

---

## Risks

### R1 — LLM cost on a growing corpus
Each new week's weekly run re-extracts concepts over the whole corpus
unless we wire **incremental** mode (Graphify supports `graph.json` as a
persistent base; only new files get LLM'd). Phase 1 ships full-rebuild;
incremental is a follow-up. **Mitigation**: `max_files=500` cap, Haiku
4.5 pin, hard 30-minute timeout.

### R2 — Graphify is young
Latest releases are April–May 2026 per public reporting. The CLI flag
surface and report-MD format may change. **Mitigation**: subprocess
isolation (one file to update if the CLI evolves); `_parse_stats()` is
defensive and returns `{}` on any unknown line.

### R3 — Subprocess shells out to a third-party Python tool
`graphify` runs `pip`-installed code in our environment with our API key.
**Mitigation**: pin the version in `requirements.txt` once a known-good
release is selected (Phase 1 leaves it floating; see *Pinning* in the PR).
Review `graphifyy` changelog before each version bump.

### R4 — Dumps directory is huge (multi-GB/day)
Phase 2 must filter aggressively (`*.png`, `*.jpg`, `*.pdf` only; size
cap per file) before invoking graphify. Without that, the LLM bill and
the run-time both blow out. **Mitigation**: Phase 2 scaffolding will land
with the filter in place; do not pre-build the schedule entry.

### R5 — Two graphs vs one
Keeping `hfl-graph` and `dumps-graph` separate is cleaner for tenant
isolation (PR #27) and for cost attribution. **Mitigation**: merge at
**query time** in Phase 3c (`hfl_graph_query`) rather than at build time.

### R6 — Privacy boundary at the LLM call
Graphify sends *semantic descriptions* (not raw bytes) to the LLM. That's
right for OSS code; HFL entries can contain personal moments — names,
locations, reflections. **Mitigation**: the corpus already runs through
Haiku 4.5 in every other HFL ingest task (`summarize_hfl_week`,
`ingest_chatgpt_activity`, etc.). Adding graphify is **not** an expanded
privacy surface — it's the same LLM under the same API key.

### R7 — Trigger collision in multi-tenant mode
Phase 1 marks the task `manifesto.tenant_safe=True` (PR #27 hook). When
multi-tenant mode is on, `tenant.metering.register_metering` refuses to
enqueue without a bound tenant. **Mitigation**: this is the desired
behaviour — accidental cross-tenant graph builds would leak entry text
through node labels.

### R8 — Disk growth on `_graph/`
Each weekly run writes a new `<corpus_dir>/_graph/YYYY-Www/` folder. Over
a year that's 52 folders × N MB. **Mitigation**: a `manage-queues`-style
cleanup task in a later PR (retain the most recent 8 weeks + an archive
roll-up). Phase 1 does **not** auto-prune.

---

## Files in this PR (Phase 1)

| Path | Purpose |
|---|---|
| `workflows/hfl/tasks/build_knowledge_graph.py` | The Celery task (subprocess + ES projection) |
| `workflows/hfl/tasks_config.py` | Adhoc-only beat entry with `tenant_safe: True` |
| `workflows/hfl/KNOWLEDGE_GRAPH.md` | This document |
| `requirements.txt` | Documents the `pip install graphifyy` step (optional dep) |

## Files in follow-up PRs

| Phase | Path | Purpose |
|---|---|---|
| 2 | `workflows/dumps/tasks/build_dumps_graph.py` | Dumps multimodal graph |
| 2 | `workflows/_lib/graphify_runner.py` | Shared subprocess + ES helpers |
| 3a | `workflows/hud/tasks/hud_knowledge_graph.py` | HUD widget |
| 3b | `frontend/main.py` (edit) | `/graph` route + StaticFiles mount |
| 3c | `workflows/hfl/mcp.py` (edit) | `hfl_graph_query` MCP tool |
| later | `workflows/hfl/tasks/prune_knowledge_graph.py` | R8 retention task |

---

## See also

- [Graphify product page](https://graphify.net)
- [Graphify on GitHub (safishamsi/graphify)](https://github.com/safishamsi/graphify)
- [Graphify on PyPI](https://pypi.org/project/graphifyy/)
- `docs/MANIFESTO.md` — the "queryable by prompt" promise this closes
- `docs/info/SKILLS-INVENTORY.md` — "External skill ecosystems worth tracking"
- `workflows/hfl/README.md` — the broader HFL workflow
- `workflows/dumps/README.md` — the dumps inbox Phase 2 will graph
- PR #27 (`feat/aaas-tenant-foundation`) — `tenant_safe` manifesto hook
