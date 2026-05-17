Scaffold a new Homework-for-Life ingest source under `workflows/hfl/` — a Celery task that captures information from a source, distils it with Claude Haiku into a structured `HflEntry`, and **dual-writes** it (Markdown corpus + the `harqis-hfl-entries` Elasticsearch index). Follows the proven `ingest_git` / `ingest_ai` / `ingest_chatgpt` template, composes with `/create-new-service-app`, and (by default) adds a paired read-only MCP tool.

This skill exists because every HFL ingest source has the same shape; encoding it removes the boilerplate and *enforces* the manifesto Capture → Distill → Express loop (docs/MANIFESTO.md §1–§2) for every new source.

## Arguments

`$ARGUMENTS` format (parse left to right):

```
<source_name> [<spec_or_url>] [--app <existing_app>] [--schedule "<cron>"] [--window-days N] [--no-mcp]
```

| Token | Required | Description |
|---|---|---|
| `source_name` | Yes | snake_case identifier, e.g. `readwise`, `notion`, `pocket`. Becomes `ingest_<source_name>.py` / `ingest_<source_name>_activity`. |
| `spec_or_url` | No | OpenAPI/docs URL for the source's API. Only forwarded to `/create-new-service-app` when the source has **no** `apps/` integration yet. |
| `--app <name>` | No | Reuse an existing `apps/<name>` integration instead of creating one. |
| `--schedule "<cron>"` | No | Celery beat schedule. Default: daily `crontab(hour=23, minute=0)` (same slot as the other ingest sources). |
| `--window-days N` | No | Lookback window the task captures. Default `1`. |
| `--no-mcp` | No | Skip generating the paired read-only MCP tool (default: generate it). |

---

## Step 0 — Read the template before writing anything

Habit 5 (manifesto): no generation without exploration. Read, in order:

1. `workflows/hfl/tasks/ingest_chatgpt.py` — the closest full template (self-contained client + collectors + distiller + task).
2. `workflows/hfl/tasks/ingest_git.py` — the canonical template; note `_parse_model_json` and the raw-fallback pattern.
3. `workflows/hfl/dto/entry.py` — the `HflEntry` DTO every entry is built from.
4. `workflows/hfl/es_store.py` — `index_hfl_entry(entry, *, source, synthesized)` (the dual-write call) and `query_hfl_entries`.
5. `workflows/hfl/tasks/capture.py` — `_render_entry` (delegates to `HflEntry`) and `resolve_corpus_dir`.
6. `workflows/hfl/tasks_config.py` — the beat-entry shape incl. the `manifesto` metadata block and `WorkflowQueue.HFL`.
7. `workflows/hfl/__init__.py` — explicit task-module imports (Celery registration).
8. `workflows/hfl/mcp.py` — `register_memory_tools(mcp)` and the `git_activity` live-view tool (the MCP pattern to mirror).
9. `workflows/hfl/prompts/__init__.py` + an existing `prompts/ingest_*.md` — the `load_prompt` loader and prompt shape.

Do not skip this. The generated code MUST match these conventions exactly.

---

## Step 1 — Resolve the source integration

Determine how the task reaches the source:

- `--app <name>` given → confirm `apps/<name>/` exists; use it. Stop if it doesn't.
- Source already has an `apps/<name>` integration → use it.
- No integration and `<spec_or_url>` given → invoke **`/create-new-service-app <source_name> <spec_or_url>`**, wait for it to finish, then continue.
- No integration and no spec → the source is self-contained (e.g. a private web backend like `ingest_chatgpt.py`). Build a minimal `httpx` client *inside* the task module, exactly like `_ChatGptWebClient`. Document the auth/caveats in the module docstring.

Never use `/create-new-workflow` — HFL ingest tasks are not generic category workflows (no `tasks_config.py` category dir, no `workflows/config.py` merge; they live inside the already-active `workflows/hfl`).

---

## Step 2 — Generate the prompt

Create `workflows/hfl/prompts/ingest_<source_name>.md` mirroring `prompts/ingest_chatgpt.md`:

- Role + goal paragraph, source-specific.
- "Reply with a SINGLE JSON object and nothing else" + the exact schema:
  `skip` (bool), `moment`, `what_happened`, `why_it_stayed`, `possible_use`, `tags` (2–6, no `#`).
- Grounding rules (no invention; synthesize across items; be specific).
- One concrete worked example.

---

## Step 3 — Generate the ingest task

Create `workflows/hfl/tasks/ingest_<source_name>.py`. Required structure (copy `ingest_chatgpt.py` and adapt):

- Module docstring: what it captures, the source, auth/config env vars, the "no token / no items → clean no-op" contract, and that it dual-writes.
- Imports: `SPROUT`, `log_result`, `create_logger`; `get_anthropic_config` + `BaseApiServiceAnthropic`; `load_prompt`; `from workflows.hfl.tasks.capture import _render_entry, resolve_corpus_dir`; `from workflows.hfl.tasks.ingest_git import _parse_model_json`; `from workflows.hfl.dto import HflEntry`; `from workflows.hfl.es_store import index_hfl_entry`.
- `_DEFAULT_HAIKU = "claude-haiku-4-5-20251001"` (never raise the Anthropic default model).
- `collect_<source>_activity(*, since, until, ...) -> dict` — plain function (MCP-reusable), bounded by explicit caps, windowed by date.
- `distill_<source>_activity(activity, *, synthesize=True, model=_DEFAULT_HAIKU, cfg_id="ANTHROPIC", max_tokens=900) -> dict` — Haiku via `load_prompt("ingest_<source_name>")`, `_parse_model_json`, raw-fallback dict on any failure.
- `@SPROUT.task()` / `@log_result()` `ingest_<source_name>_activity(*, cfg_id__anthropic="ANTHROPIC", model=_DEFAULT_HAIKU, window_days=<N>, ...)`:
  1. Missing credential / no source items → return `{"skipped": ..., "entries_written": 0}` (NO LLM, NO network beyond the cheap check).
  2. Collect → if empty, skip. Distil → if `skip`, skip.
  3. Build the entry **once** as an `HflEntry(when=…, moment=…, …, tags=…, references=…)`.
  4. **Dual-write:** append `entry.to_markdown()` to `<corpus>/YYYY-MM-DD.md` (via `_render_entry` for parity) **and** call `index_hfl_entry(entry, source="<source_name>", synthesized=d.get("synthesized", False))`.
  5. Return `{"entries_written": 1, "indexed": <doc_id is not None>, "synthesized": ..., "model": ..., "path": ...}`.
- Every external failure is caught and turned into a logged skip — the beat must never break (match `ingest_chatgpt.py` exactly).

Set `references` to the source artifact when one exists (URL/path) — the manifesto provenance convention (docs/MANIFESTO.md §2).

---

## Step 4 — Register the task

Append to `workflows/hfl/__init__.py` (mandatory — without it Celery logs `Received unregistered task`):

```python
import workflows.hfl.tasks.ingest_<source_name>  # noqa: F401
```

---

## Step 5 — Add the beat schedule entry

Add to `workflows/hfl/tasks_config.py` a `run-job--ingest_<source_name>_activity` entry: the resolved `--schedule` (default `crontab(hour=23, minute=0)`), `kwargs` (`cfg_id__anthropic`, `model` Haiku, `window_days`, caps), `options` `{'queue': WorkflowQueue.HFL, 'expires': 60*60*12}`, and the `manifesto` block (`code_role: 'capture+distill+express'`, `para_bucket: 'area'`, `express_target: 'file:hfl_corpus+es:hfl-entries'`, `review_artifact: 'es_log+file'`, `hfl_signal: True`). Ship it **active** only if the credential is set; otherwise ship it commented-out with a one-line activation note (mirror how `ingest_ai` / `ingest_chatgpt` were handled).

---

## Step 6 — Generate the paired MCP tool (unless `--no-mcp`)

In `workflows/hfl/mcp.py`, inside `register_memory_tools(mcp)`, add a read-only `@mcp.tool()` `<source_name>_activity(...)` mirroring `git_activity`: same `_resolve_window` vocabulary, calls the plain `collect_*` / `distill_*` collectors with **no corpus/ES write**, `found=false` + NO LLM on empty. This is the live view; `memory_recall_es` already covers retrieving *stored* entries from the ES index.

---

## Step 7 — Tests

Create `workflows/hfl/tests/test_ingest_<source_name>.py` (mirror `test_ingest_chatgpt.py`):

- Integration: the no-credential / no-items path → clean no-op, no network, no write (safe to run live).
- `@pytest.mark.skip(reason="Manual only — live …")` for the full pipeline.
- Unit: collector windowing/parse helpers; `distill_*(synthesize=False)` raw fallback (no API).
- A test asserting the task calls `index_hfl_entry` (monkeypatch it) so the dual-write contract is covered.

Do not run tests automatically unless asked; print the command.

---

## Step 8 — Verify

```bash
.venv/bin/python -m py_compile workflows/hfl/tasks/ingest_<source_name>.py workflows/hfl/tasks_config.py workflows/hfl/__init__.py
.venv/bin/python -c "import sys;sys.path.insert(0,'scripts');import launch;launch.setup_env();import workflows.hfl;from core.apps.sprout.app.celery import SPROUT;print('workflows.hfl.tasks.ingest_<source_name>.ingest_<source_name>_activity' in SPROUT.tasks)"
```

Both must succeed (registration prints `True`).

---

## Step 9 — Docs

Append a row to the `workflows/hfl/README.md` Tasks table and an Activation note (env var, schedule, dual-write, MCP tool) — mirror the existing `ingest_chatgpt` / `ingest_ai` sections.

---

## Step 10 — Activation checklist

Print, filled in: the credential/env var to set, whether the beat entry shipped active or commented-out, the `--no-mcp` decision, the `HFL_ES_INDEX` default (`harqis-hfl-entries`), the verify commands, and `pytest workflows/hfl/tests/test_ingest_<source_name>.py -v`.

---

## Hard rules — never break these

1. **Match the template.** The generated task must be structurally identical to `ingest_chatgpt.py` — same skip/no-op contract, same raw-fallback, same "never break the beat".
2. **Dual-write is mandatory.** Every generated source writes BOTH the Markdown corpus and `index_hfl_entry(...)`. The corpus is the source of truth; ES is the queryable projection. Never ES-only.
3. **Haiku only.** Distil with `claude-haiku-4-5-20251001`. Never raise `BaseApiServiceAnthropic.DEFAULT_MODEL`.
4. **No secrets written.** Credentials/tokens are printed as instructions for `.env/apps.env`, never written to a tracked file.
5. **Compose, don't reinvent.** Delegate a missing source API to `/create-new-service-app`. Never invoke `/create-new-workflow`.
6. **No-op cleanly.** Missing credential or empty window → return a skip dict, make no LLM call, write nothing (manifesto "smallest useful entry" + no dead weight).
7. **Register or it's dead.** The `workflows/hfl/__init__.py` import in Step 4 is not optional.
