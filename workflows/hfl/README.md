# `workflows/hfl/` — Homework for Life

> The manifesto's principle 2 made concrete: a workflow surface for the daily
> story-moment habit from Matthew Dicks' *Storyworthy*. Treats Homework for
> Life as a **first-class data source** — captured, retrievable, summarizable —
> not a journaling app.

This scaffold ships **inactive**: the package exists and the tasks are
importable, but `workflows/config.py` does not yet pull `WORKFLOW_HFL` into
the beat schedule. Activation is a deliberate, separate decision. See
§Activation below.

---

## Why this workflow exists

`docs/MANIFESTO.md` calls Homework for Life out by name and specifies a
standard entry shape:

```text
## YYYY-MM-DD
Moment:
What happened:
Why it stayed with me:
Possible use:
Tags:  #work-story #debugging #automation …
```

The manifesto's promise is that the corpus becomes "queryable by prompt"
— *"What was I working on the week of 2026-04-12?"*, *"Show me debugging
stories tagged #root-cause."*, *"Reconstruct the timeline for the OANDA
forex agent rollout."* This workflow makes that promise honest.

The audit at `docs/thesis/MANIFESTO-REPO-UPDATES.md` §3.3 documents the gap
this scaffold closes.

---

## Tasks

| Task | What it does | Express target | Schedule (when active) |
| --- | --- | --- | --- |
| `capture_hfl_entry` | Appends one structured entry to today's corpus file. Empty `moment` is a no-op. | `file:hfl_corpus` | Adhoc — invoked via `.delay()`, an MCP tool, an agent, or a hotkey. The scheduled slot fires Sunday 03:33 with empty kwargs (i.e. is a no-op). |
| `retrieve_hfl_corpus` | Substring + tag scan over the corpus, optional date filter. Returns up to `k` entries, most recent first. | `es_log` (callers consume the return value) | Adhoc — same pattern as capture. |
| `summarize_hfl_week` | Weekly Haiku 4.5 rollup of the past N days; writes `_summary-YYYY-Www.md` alongside the daily files. | `file:hfl_summary+es_log` | Sundays 21:00 local. |
| `ingest_chatgpt_activity` | **Primary daily research log.** Auto-discovers the operator's ChatGPT conversations created/updated that day via the ChatGPT web app's private backend (no thread ids), distils the questions asked into ONE corpus entry. Haiku-distilled, raw fallback. No token / no prompts → no entry, no call. | `file:hfl_corpus` | Daily 23:00 local (active — no-op until `CHATGPT_WEB_ACCESS_TOKEN` is set). |
| `ingest_ai_activity` | Alternate source (OpenAI **Platform API** assistant threads, via `OPENAI_HFL_THREAD_IDS`). Superseded by `ingest_chatgpt_activity` — kept in code but its beat entry is **disabled** (commented-out) to avoid a nightly no-op. | `file:hfl_corpus` | Disabled (uncomment in `tasks_config.py` if you also want Platform-API threads). |
| `ingest_browsing_activity` | Daily web-browsing digest. Reads the Chrome + Edge `History` SQLite DBs directly (copy-to-temp to dodge the browser lock; no app/credential), distils the day's visits into ONE corpus entry with the most-visited pages as `references`. Haiku-distilled, raw fallback. No history DB / no visits → no entry, no call. No domain filtering by default (`exclude_domains` kwarg to redact). | `file:hfl_corpus+es:hfl-entries` | Daily 23:00 local (active — `os: windows`; no config needed). |

Each carries the manifesto metadata block on the beat entry — see
`workflows/hfl/tasks_config.py`.

---

## Corpus layout

```
<corpus_root>/
  2026-05-13.md              # one file per day, entries appended
  2026-05-14.md
  _summary-2026-W20.md       # weekly summary written by summarize_hfl_week
```

### Corpus path resolution (first hit wins)

1. `apps_config.yaml::HFL.corpus.path` — preferred for distributed/worker
   nodes that load config remotely.
2. Env var `HFL_CORPUS_PATH` — convenient for local dev.
3. Fallback: `<repo>/logs/hfl/`.

A future activation step adds an `HFL:` section to `apps_config.yaml` and
the matching env var to `.env/apps.env`. The scaffold does not require
either to be present — the fallback path works on day one.

---

## Entry format

Capture writes plain Markdown, one block per call, appended to the day's
file. Multiple captures on the same day stack:

```markdown
## 2026-05-13 09:14
Moment:          Almost ignored a small bug in the feed decorator.
What happened:   The ${VAR} folder appearing at repo root turned out to be
                 an unresolved env var leaking into Path().resolve().
Why it stayed:   Small details reveal big problems.
Possible use:    #lesson  #linkedin-idea
Tags:            #debugging #root-cause #python
References:
                 - https://github.com/owner/repo/commit/abc1234
                 - C:\dump\2026-05-13\screenshot.png
```

The format is the formal `HflEntry` DTO (`workflows/hfl/dto/entry.py`) —
`_render_entry` delegates to it, so every producer emits an identical,
round-trippable block. Retrieval splits files on `## ` headers, so the
format must be preserved if entries are hand-edited.

**`References:` (optional).** URLs or host file paths pointing at the
source material behind the moment. The block is rendered **only when
present** — entries without references are byte-identical to the
pre-DTO format. References are searchable via `retrieve` and, on the
weekly run, `summarize_hfl_week` resolves them (bounded HTTP/file fetch,
text-only, size/timeout caps) and injects the excerpts into the rollup
prompt so the summary is grounded in the source — see
`workflows/hfl/references.py`. `analyze_hfl_media` auto-sets this to the
source dump file path (the dumps→media→corpus provenance loop).

> Privacy/cost note: resolved file and URL content is sent to Anthropic
> in the weekly prompt. v1 bounds it (existence check, text-only,
> per-ref + total byte caps) but does **not** path-allowlist — any
> readable text file referenced will be resolvable.

---

## Activation

When ready to turn this workflow on:

1. **Wire the corpus path.** Either add an `HFL:` block to
   `apps_config.yaml`:
   ```yaml
   HFL:
     corpus:
       path: ${HFL_CORPUS_PATH}
   ```
   and set `HFL_CORPUS_PATH` in `.env/apps.env`, or rely on the
   `<repo>/logs/hfl/` fallback (fine for a single-host setup).

2. **Add to the beat schedule.** In `workflows/config.py`:
   ```python
   from workflows.hfl.tasks_config import WORKFLOW_HFL
   ...
   CONFIG_DICTIONARY = (
       WORKFLOW_PURCHASES | WORKFLOWS_HUD | WORKFLOWS_DESKTOP
       | WORKFLOW_SOCIAL | WORKFLOW_KNOWLEDGE | WORKFLOW_DUMPS
       | WORKFLOW_HFL
   )
   ```

3. **Restart Beat + an `adhoc`-subscribed worker and an `agent`-subscribed
   worker.** Capture and retrieve land on `adhoc`; the weekly summarizer
   lands on `agent`.

4. **Optional: drop a hotkey or n8n trigger** that prompts for the daily
   entry and calls `capture_hfl_entry.delay(moment=..., ...)`. The scheduled
   capture slot is a no-op safety net, not the real entry point.

5. **Optional: pipe the corpus into the existing `knowledge` RAG**
   workflow once it has critical mass — see
   `docs/thesis/MANIFESTO-REPO-UPDATES.md` §7.

### Activating `ingest_chatgpt_activity` (primary daily research log)

This task is **active** in `tasks_config.py` and is a clean no-op until
you give it a ChatGPT session token. It auto-discovers every ChatGPT
conversation you created/updated that day — no thread ids to manage.

> ⚠️ **Unofficial backend.** OpenAI's official Platform API cannot list
> threads or see ChatGPT-app chats at all. The only thing that can is the
> ChatGPT **web app's own private backend** (`chatgpt.com/backend-api`),
> which this task calls. It is undocumented and can change/break with any
> web deploy (the task degrades to a no-op, never a broken beat).
> Automating it is your own account + your own data for a personal log —
> the defensible case — but it is a grey area vs. the sanctioned API.

To make it produce entries:

1. **Grab a session token.** While logged in to chatgpt.com, open
   `https://chatgpt.com/api/auth/session` and copy the `accessToken`
   value.
2. **Set it** in `.env/apps.env`:
   ```
   CHATGPT_WEB_ACCESS_TOKEN=<accessToken>
   # Optional — only if Cloudflare blocks scripted requests:
   CHATGPT_WEB_COOKIE=cf_clearance=...; __Secure-next-auth.session-token=...
   CHATGPT_WEB_USER_AGENT=<the exact UA string from your browser>
   ```
3. **Restart Beat + an `hfl`-subscribed worker.** The
   `run-job--ingest_chatgpt_activity` entry is already active; it runs
   daily at 23:00 local, distils that day's prompts with Haiku, and
   appends one entry to the day's corpus file.

The token **expires** (days). When it does the task logs an HTTP 401 and
no-ops — re-grab it from `/api/auth/session` and re-paste. Only your own
(`role == "user"`) messages are read — the questions you asked, not
ChatGPT's answers. Claude (Haiku) is used solely as the distiller.

### Alternate: `ingest_ai_activity` (OpenAI Platform-API threads)

Disabled by default (commented-out beat entry). Reads specific Platform-API
assistant threads listed in `OPENAI_HFL_THREAD_IDS` — only useful if you
drive research through the official API rather than the ChatGPT app.
Uncomment its block in `tasks_config.py` and set the env var to enable it
alongside the ChatGPT-web task.

### `ingest_browsing_activity` (daily browsing digest)

**Active by default, no configuration.** Reads the *Default* profile
`History` SQLite DB for Chrome and Edge on the Windows worker (the beat
entry is `os: windows`), copies each DB (+ `-wal`/`-shm` sidecars) to a
temp file to dodge the browser's exclusive lock, windows by visit time,
distils with Haiku, and **dual-writes** corpus + the `harqis-hfl-entries`
ES index. The most-visited pages are stored as the entry's `references`.

- No history DB found / no visits in the window → clean no-op (no LLM).
- No domain filtering by default — pass `exclude_domains=("host", …)` in
  the beat kwargs to redact specific hosts, or trim `max_visits` /
  `browsers` to bound volume.
- Non-default profiles or a non-Windows layout: set absolute paths in
  `HFL_BROWSING_CHROME_HISTORY` / `HFL_BROWSING_EDGE_HISTORY`.
- Recency caveat: visits still buffered in the browser's `-wal` sidecar
  (not yet checkpointed) may miss the very latest pages — fine for a
  once-a-day digest.
- Live view (no write): the `browsing_activity` MCP tool in
  `workflows/hfl/mcp.py`.

---

## Elasticsearch entry index (dual-write)

The Markdown corpus is the source of truth. Ingest sources scaffolded by
`/create-new-ingest-source-hfl` **dual-write**: they append the corpus
entry *and* index the structured `HflEntry` to a queryable Elasticsearch
index via `workflows/hfl/es_store.py`.

- **Write:** `index_hfl_entry(entry, *, source, synthesized)` →
  `core.apps.es_logging.app.elasticsearch.post`. Deterministic doc id
  (`<YYYYMMDD>-<source>-<moment-hash>`) so re-runs upsert, never
  duplicate. Best-effort: any ES failure is logged and swallowed — the
  corpus entry and the beat run are unaffected.
- **Read:** `query_hfl_entries(query, since, until, tags, source, limit)`
  → `get_index_data` (Query DSL). Returns `[]` on any failure.
- **Index name:** env `HFL_ES_INDEX` (default `harqis-hfl-entries`).
  Reuses the existing `ELASTIC_LOGGING` app config — no new credentials.
- **Retrieval (MCP):** `memory_recall_es` in `workflows/hfl/mcp.py` reads
  this index by window/query/tags/source (optional Haiku synthesis;
  `found=false` + no LLM on empty). The corpus-based `memory_recall`
  is unchanged and still serves the Markdown tiers.

> Status: `capture`, `ingest_git`, `ingest_ai`, `analyze_media`, and
> `summarize` now dual-write via the shared `append_entry` helper in
> `capture.py` (`append_entry` → corpus write + `index_hfl_entry`,
> returning `(bytes, doc_id)`). `ingest_browsing` dual-writes the same
> way. **`ingest_chatgpt` is the one remaining gap** — it still uses the
> bare `_render_entry`+write path and is not yet ES-indexed; routing it
> through `append_entry` is the clean follow-up.

## Adding a new ingest source

Run `/create-new-ingest-source-hfl <source_name> [<spec_or_url>]
[--app <name>] [--schedule "<cron>"] [--window-days N] [--no-mcp]`. It
scaffolds the task (the `ingest_chatgpt` template), prompt, `__init__`
registration, `tasks_config` beat entry, tests, and a paired read-only
MCP live-view tool — dual-writing corpus + ES. It composes with
`/create-new-service-app` for a missing source API and never uses
`/create-new-workflow`.

---

## Manifesto alignment

| Task | code_role | para_bucket | express_target | review_artifact | hfl_signal |
| --- | --- | --- | --- | --- | --- |
| `capture_hfl_entry` | capture | area | `file:hfl_corpus` | `es_log+file` | `True` |
| `retrieve_hfl_corpus` | distill+express | area | `es_log` | `es_log` | `True` |
| `summarize_hfl_week` | distill+express | area | `file:hfl_summary+es_log` | `es_log+file` | `True` |
| `ingest_browsing_activity` | capture+distill+express | area | `file:hfl_corpus+es:hfl-entries` | `es_log+file` | `True` |

This block is also persisted on each beat entry's `'manifesto'` key — see
`workflows/hfl/tasks_config.py`. `scripts/agents/manifesto_audit.py` reads from
there.

---

## Related

- [`docs/MANIFESTO.md`](../../docs/MANIFESTO.md) §Homework for Life
- [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](../../docs/thesis/MANIFESTO-REPO-UPDATES.md) §3.3, §4.4
- [`workflows/knowledge/`](../knowledge/README.md) — RAG path the corpus
  joins once it has mass
- `/create-new-ingest-source-hfl` —
  [`.claude/skills/create-new-ingest-source-hfl/SKILL.md`](../../.claude/skills/create-new-ingest-source-hfl/SKILL.md)
  scaffolds new dual-writing ingest sources
