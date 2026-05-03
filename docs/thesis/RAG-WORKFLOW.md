# HARQIS-RAG-WORKFLOW

A practical, locally-runnable Retrieval-Augmented-Generation stack built on top of the existing harqis-work platform. This document explains **what** RAG is, **why** the components were chosen the way they were, **how** the pieces fit together, and **what** you can build on top once the smallest viable RAG is in place.

---

## 1. Introduction

### 1.1 What is RAG?

A standard LLM call is a single hop: prompt → model → answer. The model can only use what it was trained on (potentially years stale, definitely not your private notes) plus whatever you cram into the prompt.

**Retrieval-Augmented Generation** turns that into a two-hop pipeline:

```
question
  │
  ▼
[1] Retrieve     ── search a corpus you control (notes, code, tickets, …)
  │              ── return the top-k most relevant chunks
  ▼
[2] Generate     ── LLM answers using only those retrieved chunks
  │              ── cites the chunks so the answer is auditable
  ▼
answer + sources
```

The win:
- **Fresh.** New notes are searchable the next time the ingest job runs — no retraining.
- **Private.** Your data never leaves your control until query time, when only the relevant slice is sent to the LLM.
- **Citable.** Each fact in the answer points back to its origin (a Notion URL, a Jira ticket, a file path).
- **Cheap.** You pay for embeddings once at ingest, then only for the small slice of context the answer step needs.

### 1.2 What is in this repo today

The harqis-work platform already ships almost every component RAG needs:

| Layer | Where | Notes |
|---|---|---|
| Embedding generation | `apps/gemini` | `text-embedding-004`, asymmetric task types |
| LLM generation | `apps/antropic`, `apps/open_ai`, `apps/gemini`, `apps/grok`, `apps/perplexity` | Haiku 4.5 default for cost |
| Knowledge sources | `apps/notion`, `apps/google_drive`, `apps/airtable`, `apps/jira`, `apps/trello`, `apps/github`, `apps/reddit`, `apps/discord`, `apps/telegram`, `apps/linkedin`, `apps/filesystem`, `apps/scryfall`, `apps/alpha_vantage`, `apps/investagrams` | One per corpus |
| Orchestration | `workflows/`, Celery + RabbitMQ, queue topology in `workflows/config.py` | Beat schedules, fanout queues |
| Surfacing | `mcp/server.py` (Claude Desktop), `workflows/hud` (Rainmeter widgets) | |

What was missing: **a vector store**. This thesis fills that gap with `apps/sqlite_vec` and wires four ingestors through `workflows/knowledge` — **Notion, Jira, GitHub, and Google Drive Docs** — all writing into the same store under their own `source=` labels. Adding more (Confluence, Slack, Trello, …) is the same recipe; see §6.2.

> **Aside on Anthropic embeddings.** Anthropic does not provide a first-party embeddings API — their docs recommend Voyage AI. We use Gemini for the embed step (free tier, asymmetric task types) and Anthropic for the generate step. The split is intentional and is the same pattern Anthropic itself recommends in their RAG cookbook.

---

## 2. Stack

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Claude Desktop                                  │
│                          (or any MCP client)                                 │
└────────────────────────────────────┬─────────────────────────────────────────┘
                                     │ stdio
                                     ▼
                            ┌────────────────────┐
                            │  mcp/server.py     │  ← FastMCP server
                            │  knowledge_ask()   │
                            │  knowledge_search()│
                            │  vector_store_*()  │
                            └─────────┬──────────┘
                                      │
                ┌─────────────────────┴──────────────────────┐
                │                                            │
                ▼                                            ▼
   ┌────────────────────────┐                    ┌──────────────────────┐
   │ workflows/knowledge    │                    │ apps/sqlite_vec      │
   │  - retriever.py        │  upsert / search   │  - store.py          │
   │  - tasks/ingest_*.py   │ ─────────────────▶ │  - mcp.py            │
   │  - tasks/answer.py     │                    │  data/vector_store.db│
   │  - prompts/rag_answer  │                    └──────────────────────┘
   └─────────┬──────────────┘
             │
             ├──── apps/gemini ─────▶ Gemini text-embedding-004
             │                       (RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY)
             │
             ├──── apps/notion ─────▶ Notion REST (search + blocks)
             │
             └──── apps/antropic ───▶ Claude Haiku 4.5 (generate)
```

### 2.1 Why these choices

| Decision | Reason |
|---|---|
| **Gemini for embeddings** | Already wrapped in the repo; free tier; supports asymmetric `RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY` task types that measurably improve recall over symmetric embeddings. |
| **sqlite-vec for storage** | Single file, zero infrastructure, runs anywhere a Celery worker runs. Trivially swappable for Qdrant or pgvector when scale demands it (our `upsert/search/stats/delete_by_source` API is intentionally portable). |
| **Anthropic Haiku 4.5 for generation** | Cheapest Claude model; per project convention (memory: `feedback_anthropic_model_override`) the default in `apps_config.yaml` stays Sonnet; cost-sensitive jobs override per-call. |
| **Celery beat for ingestion** | Same scheduler the rest of the platform uses; nightly ingest is a one-line crontab change; failures land in the existing log/ES pipeline. |
| **MCP for queries** | Claude Desktop already speaks MCP; no UI to build; an `knowledge_ask` tool is enough to get a chat surface for free. |

### 2.2 What lives where (filesystem map)

```
apps/sqlite_vec/                   ← NEW: local vector store
├── store.py                       ← upsert / search / stats / delete_by_source
├── mcp.py                         ← MCP wrappers (stats, raw search, delete)
├── README.md
└── tests/test_store.py

workflows/knowledge/               ← NEW: RAG pipeline
├── chunking.py                    ← text splitter + Notion block extractor + ADF flattener
├── retriever.py                   ← embed query + KNN
├── prompts/rag_answer.md          ← system prompt for the answer step
├── tasks/
│   ├── ingest_notion.py           ← Notion → embed → upsert (beat: 02:30)
│   ├── ingest_jira.py             ← Jira issues + comments  (beat: 02:45)
│   ├── ingest_github.py           ← GitHub PRs + issues     (beat: 03:00)
│   ├── ingest_gdrive.py           ← Google Docs             (beat: 03:15)
│   └── answer.py                  ← question → retrieve → Anthropic
├── tasks_config.py                ← beat schedules (4 ingestors + answer slot)
├── mcp.py                         ← knowledge_ask + knowledge_search MCP tools
└── README.md

workflows/config.py                ← MODIFIED: registers WORKFLOW_KNOWLEDGE
mcp/server.py                      ← MODIFIED: adds two new registrars
requirements.txt                   ← MODIFIED: adds sqlite-vec
docs/thesis/RAG-WORKFLOW.md        ← THIS DOCUMENT
```

---

## 3. Process & flow

### 3.1 Ingestion flow (write path)

Four ingestors all follow the same shape — only **fetch** and **flatten** vary by source. The Notion path is the canonical example:

```
Celery beat (staggered nightly: 02:30 / 02:45 / 03:00 / 03:15)
    │
    ▼
ingest_<source>_*  (notion / jira / github / gdrive)
    │
    ├── fetch from source API                          → list of items (paginated)
    │
    ├── for each item:
    │       extract_text(item)                         → plain text
    │         └─ Notion : iterate blocks, pull rich_text
    │         └─ Jira   : flatten ADF JSON → text
    │         └─ GitHub : title + body + first 20 comments
    │         └─ Drive  : files().export(text/plain)
    │       chunking.chunk_text(text, chars=2000)      → list of chunks
    │
    ├── batch (50 at a time):
    │       apps/gemini/embed.batch_embed_contents(
    │           texts, task_type='RETRIEVAL_DOCUMENT')  → list of vectors
    │
    └── for each (chunk, vector):
            apps/sqlite_vec/store.upsert(
                id=f"{item_id}:{chunk_idx}",
                text=chunk,
                embedding=vector,
                source='<notion|jira|github|gdrive>',   ← the per-source label
                ref=item_url,
                meta={...source-specific extras...})
```

Idempotency: re-running any task is safe. Chunk ids are stable (`{item_id}:{idx}`), so re-ingesting an item replaces its existing rows. For a clean rebuild, pass `rebuild=True` — the task drops only its own source first, leaving the other corpora untouched.

### 3.2 Query flow (read path)

```
Claude Desktop (user types a question)
    │
    ▼
mcp.knowledge_ask(question, k=5, source='notion')
    │
    ▼
workflows/knowledge/tasks/answer.answer_question
    │
    ├── retriever.embed_query(question)
    │       → apps/gemini/embed.embed_content(task_type='RETRIEVAL_QUERY')
    │
    ├── apps/sqlite_vec/store.search(vec, k=5, source='notion')
    │       → top-5 chunks ordered by L2 distance on normalised vectors
    │
    ├── retriever.format_context(hits)
    │       → numbered context block: [1] ... [2] ...
    │
    └── apps/antropic/send (Haiku 4.5):
            system: rag_answer.md (cite [n], say so when context lacks it)
            user:   "Question: …\n\nContext snippets:\n\n[1] (ref: …) …"
            → answer with [n] citations + Sources: footer
```

The asymmetric task types matter: the same query embedded as `RETRIEVAL_QUERY` lands at a different point in vector space than if embedded as `RETRIEVAL_DOCUMENT` — Gemini's encoder uses the hint to optimise for the search side of the asymmetry. Mixing them silently degrades recall.

### 3.3 Idempotency, cost, and failure modes

| Concern | Mitigation |
|---|---|
| Duplicate ingest runs overlap | Beat task uses `expires=6h`; chunk ids are deterministic so overlap just rewrites same rows. |
| Embedding cost grows unbounded | Page-level dedup via stable ids; `max_pages` cap per run; nightly cadence for incremental ingest. |
| Generation cost | Haiku 4.5 default ($0.25/M input). Sonnet only on explicit override. Top-k bounded at 5. |
| Vector store gets corrupt | Single SQLite file — back it up by copying `data/vector_store.db`. Worst case: delete + re-ingest. |
| Notion API throttling | The wrapper already includes retry backoff (see `apps/notion/references/web/base_api_service.py`). |
| Stale answers | Cited URLs let the user verify. Re-ingest cadence (nightly) is the staleness ceiling. |

---

## 4. How it works — narrative walkthrough

### 4.1 The shape of a chunk

Every row in the store holds:

```python
{
  "id":        "abc-123:0",            # f"{page_id}:{chunk_idx}" — stable for upsert
  "source":    "notion",                # corpus label, used to scope queries
  "ref":       "https://notion.so/...", # citation link returned in the answer
  "text":      "raw chunk text",        # what the LLM actually reads
  "meta":      {page_id, title, ...},   # arbitrary JSON — extend per corpus
  "embedding": [0.012, ...],            # L2-normalised vector, dim = model's
  "distance":  0.18,                    # set on search; smaller = more similar
}
```

Two design rules baked in here:

1. **`id` is content-addressable.** Re-ingesting a page replaces, never duplicates. This is what lets the nightly task be idempotent and cheap.
2. **`source` is a first-class filter.** Every query can scope to one corpus (`source='notion'`) or query across all of them (`source=None`). This is how the same store will host Notion + Jira + code without cross-contamination.

### 4.2 Why we normalise on write

`vec0` (the sqlite-vec virtual table) ranks by L2 distance. After L2-normalising every stored vector, L2 distance becomes mathematically equivalent to cosine distance — `||a-b||² = 2 - 2·cos(a,b)`. We get cosine ranking for free without writing a custom distance function. The cost is one division per vector at write time.

### 4.3 Why chunk on paragraphs

`chunking.chunk_text` greedily packs paragraphs up to ~2000 chars (~500 tokens), with a 200-char overlap when it has to break a paragraph. The reasoning:

- **2000 chars** sits well under Gemini's per-input cap, leaves headroom in the answer prompt, and is small enough that retrieved snippets are focused but big enough to contain a complete thought.
- **Paragraph-first** avoids cutting mid-sentence, which destroys semantic coherence and tanks recall.
- **Overlap** preserves context for ideas that straddle a chunk boundary — the second half of a definition still appears alongside the first half in at least one chunk.

A real production system would replace this with a tokenizer-aware splitter (tiktoken or the model's own counter). For the smallest viable RAG, character-count is close enough.

### 4.4 The answer prompt is doing real work

`prompts/rag_answer.md` is short but load-bearing:

> If the snippets don't contain the answer, say so plainly. Do not invent facts.

Without that line, the model will paper over retrieval misses with confident hallucinations. With it, the model says *"the indexed knowledge base doesn't cover this"* — which is the actually-useful signal that you need to either (a) re-ingest or (b) widen `k`.

> End the answer with a "Sources:" line listing each cited tag and its `ref` value …

Forces the model to surface citations as plain URLs — readable in terminal output, clickable in the Claude Desktop UI.

### 4.5 Why two MCP tools, not one

`knowledge_search` returns raw hits with no LLM call. `knowledge_ask` runs the full pipeline. Splitting them gives:

- **Debugging** — you can inspect what the retriever pulled before paying for generation.
- **Cost control** — quick "did the ingest work?" checks don't burn Claude tokens.
- **Composition** — another agent can call `knowledge_search` and assemble its own prompt.

---

## 5. Capabilities & use cases

The smallest viable RAG built above is the foundation. Each capability below extends the same pattern (ingest → embed → store → retrieve → generate) to a different corpus or surface.

### 5.1 "Ask my Notion" — personal knowledge base ✅ shipped

**Status:** built — this is the reference implementation in `workflows/knowledge`.

**Pipeline:**
- Ingest: Celery beat pulls Notion pages → `chunking.chunk_text` → `gemini.batch_embed_contents(task_type='RETRIEVAL_DOCUMENT')` → `sqlite_vec.upsert` keyed by `(page_id, chunk_idx)`.
- Query: MCP tool `knowledge_ask(query, source='notion')` → embed as `RETRIEVAL_QUERY` → top-5 → Anthropic generates answer with citations back to Notion URLs.

**Use case:** *"What did we decide about the merge-freeze policy?"* — answered from your own notes inside Claude Desktop, with the answer linking back to the exact Notion page.

**Extending it:**
- Add `apps/google_drive` ingest as a second source for any docs that don't live in Notion.
- Add a per-page `last_edited_time` filter to the ingest task so only changed pages re-embed.

### 5.2 Trading-research RAG

**Sources:**
- `apps/alpha_vantage` — fundamentals, news, earnings
- `apps/investagrams` — PSE-specific signals
- `apps/reddit` — subreddit scrapes (`r/wallstreetbets`, `r/PHinvest`, ticker-tagged posts)
- `apps/perplexity` — fresh web results when the local corpus runs cold

**Pipeline:**
- Ingest: One Celery task per source, all writing to the same store with `source` labels (`av_news`, `investagrams`, `reddit`).
- Each chunk's `meta` carries the ticker symbol(s) extracted at ingest time.
- Hourly task runs over yesterday's filings; daily task indexes Reddit threads tagged by ticker.

**Query:** `knowledge_ask("any new $TSLA risk signals today?", source=None)` — cross-source query, retriever pulls from all three corpora, Haiku 4.5 summarises into a risk brief.

**Use case:** A `workflows/hud` widget runs the query every market open and renders the summary to Rainmeter — you see the day's risk signals on your desktop without opening any of the source apps.

### 5.3 MTG deck-builder

**Source:** `apps/scryfall` (already in the repo). Card oracle text is stable — embed once, re-embed only when Scryfall adds new sets.

**Pipeline:**
- One-shot ingest: pull every card → embed `oracle_text` → upsert with `source='scryfall'`, `meta={set, mana_cost, type, colors}`.
- Query layer applies metadata filters before KNN (e.g. `colors=['U']`, `cmc<=3`) so semantic search runs on a pre-filtered subset.

**Use case:** *"give me a budget mono-blue control shell — counterspells, card draw, no fetchlands"* → metadata-filtered KNN over `colors=['U']` returns ~80 candidate cards → Claude composes a 60-card decklist with sideboard reasoning.

**Extending it:**
- Pair with `apps/echo_mtg` and `apps/tcg_mp` to inject current prices into the answer prompt.
- Add a `format='modern'` filter to keep recommendations legal.

### 5.4 Kanban agent with project memory  🟡 ingest shipped, agent hook pending

**Background:** the kanban agent in `agents/projects` re-reads card history each run. It has no memory of similar cards solved months ago.

**Status:** Jira ingest is live (§6.3) — every closed ticket is now retrievable as `source='jira'`. What's left is the small agent-side change: a pre-action hook that calls `retrieve(card.summary, k=5, source='jira')` and prepends the result to the agent's prompt.

**Pipeline:**
- Ingest: handled by `ingest_jira_issues` (already shipped).
- Pre-action hook in the agent calls `retrieve(card.summary, k=5, source='jira')` and injects "5 most semantically similar past tickets" as a context block.

**Use case:** Agent picks up *"investigate flaky test X"* and is told *"these 3 prior tickets (PROJ-481, PROJ-512, PROJ-633) solved similar flakes by checking the Y race condition"* — without bloating every prompt with the whole project history.

**Extending it:**
- Decay weight by recency (multiply distance by a `1+age_in_days/365` factor) so recent solutions outrank ancient ones at the same similarity.
- Index resolution comments separately so the retriever finds *fixes* preferentially over *problems*.

### 5.5 Standup digest

**Sources:** `apps/discord`, `apps/telegram`, `apps/jira` (recent comment activity), `apps/github` PR review comments.

**Pipeline:**
- Hourly ingest of the last 24h, sliding window (each chunk gets `meta={timestamp, channel, author}`; older chunks stay in store as historical record).
- Standup task at 09:00: `knowledge_ask("what blocked the team yesterday?", source=None, k=15)` filtered by `meta.timestamp >= now-24h` (filter applied client-side after KNN).

**Use case:** A daily Slack-or-email digest summarising blockers, with grouped citations by channel/author. Replaces the manual "what's everyone working on" round-robin.

### 5.6 Code-aware Q&A over harqis-work itself

**Source:** the repo. Chunk Python files at the function/class boundary (use `ast` for clean cuts), include the surrounding docstring + a few lines of context.

**Pipeline:**
- Ingest: walk `apps/`, `workflows/`, `docs/` → AST-chunk each `.py` and `.md` → embed → upsert with `source='harqis_code'`, `meta={file_path, line_start, line_end, symbol}`.
- MCP tool `harqis_qa(question)` defined as a thin wrapper: `knowledge_ask(question, source='harqis_code')`.

**Use case:** *"how do I add a broadcast task?"* → retriever pulls the relevant snippet from `workflows/README.md` (the "Adding a new broadcast task" section) plus `workflows/hud/tasks/broadcast_reload.py` as a code example → Claude composes a step-by-step answer that cites both.

**Why this is high-leverage:** it makes the codebase searchable in natural language, including by people (or future you) who don't remember where `WorkflowQueue.HUD_BROADCAST` is declared.

**Considerations:**
- Re-ingest on every commit is overkill. Re-ingest weekly via beat, or trigger from a git post-commit hook for the changed files only.
- Use `voyage-code-3` (when/if `apps/voyage` is added) — domain-tuned code embeddings outperform `text-embedding-004` on code retrieval by a noticeable margin.

### 5.7 Hybrid web + local RAG

**Pattern:** the local store covers *what you know*; `apps/perplexity` covers *what's happening now*. A router decides which (or both).

**Routing rules:**
1. If the query mentions a known internal entity (config key, repo name, person on the team) → local only.
2. If the query is time-sensitive ("today", "latest", "current") → Perplexity only.
3. Otherwise → both, merge ranked, re-cite.

**Pipeline:**
```
question
  │
  ├── intent classifier (small LLM call or keyword heuristic)
  │
  ├── if local: retrieve(question)              ──┐
  │                                                ├── merge → Anthropic generate
  └── if web:   apps/perplexity.search(question)──┘
```

**Use case:** *"what's the latest on the Anthropic Haiku pricing change?"* — known external topic → web only. *"what model are we using for the kanban agent?"* — internal entity → local only. *"how does our cost-override pattern compare to industry RAG defaults?"* — both, merged.

---

## 6. Multi-source extension

The single-source ("Ask my Notion") pipeline was the v0. The store was always designed to host multiple corpora — every chunk carries a `source` label, and queries can scope to one (`source='notion'`) or cross-search them all (`source=None`). v1 extends the system with three more ingestors, each writing to the same store under its own label.

### 6.1 Why these three sources, in this order

| Order | Source | Why it earns its place | App reused |
|---|---|---|---|
| 1 | **Jira** (`source='jira'`) | Highest leverage for any ticket-driven team — tickets contain the *current* state of the work plus the negotiation that led there. The "kanban agent with project memory" capability from §5.4 becomes real once this exists: every closed ticket is suddenly retrievable by similarity. | `apps/jira` ✅ |
| 2 | **GitHub PRs + issues** (`source='github'`) | Institutional memory — the *why* of every code decision lives in the PR description and the first ~20 review comments. Six months later when nobody remembers why a function returns a tuple instead of a dict, the answer is here. | `apps/github` ✅ |
| 3 | **Google Drive Docs** (`source='gdrive'`) | The catch-all for anything outside Notion — long-form RFCs, meeting notes, vendor contracts, anything a teammate wrote in Docs and dropped a link to once. Cheap to add given the auth dance was already done. | `apps/google_drive` ✅ |

Each source label is independent. You can run all four ingestors, only Notion + Jira, or just GitHub. Queries cross sources automatically (`source=None`) or stay scoped (`source='jira'`).

### 6.2 The shared shape (recipe for any future source)

Every ingest task follows the same five-step skeleton:

```python
@SPROUT.task()
@log_result()
def ingest_<source>(**kwargs):
    items = pull_from_source_api()              # 1. fetch — the only per-source code
    for item in items:
        text = extract_text(item)               # 2. flatten to plain text (varies)
        chunks = chunk_text(text)               # 3. chunk (reuse chunking.py)
        vectors = batch_embed(chunks)           # 4. embed (reuse Gemini)
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            store.upsert(
                chunk_id=f"{item.id}:{i}",      # 5. upsert with stable id
                text=chunk,
                embedding=vec,
                source="<source>",              # ← the new label
                ref=item.url,
                meta={...},                     # source-specific extras
            )
```

Steps 3, 4, and 5 are shared across every ingestor. Only steps 1 and 2 differ — and step 2 is small for most sources (their APIs already return text-friendly fields).

### 6.3 v1 ingestors — what each one captures

#### `ingest_jira_issues` (Jira)

- **Captures:** issue summary, description, type, status, plus up to N comments per issue. Descriptions and comments are Atlassian Document Format (ADF) JSON in the Cloud REST v3 API — flattened to plain text by `chunking.flatten_adf`.
- **Chunk id:** `f"{issue_key}:{chunk_idx}"` — re-ingest is idempotent at the issue level.
- **Reference:** browse URL (`https://<domain>.atlassian.net/browse/HARQIS-42`).
- **Meta:** `issue_key`, `project`, `status`, `issue_type`, `summary`.
- **Scope:** by `project_keys` kwarg, with optional JQL extension via `jql_extra` (e.g. `'updated >= -30d'` for incremental ingest).
- **Default schedule:** nightly **02:45**.

#### `ingest_github_repos` (GitHub)

- **Captures:** PR body + first 20 issue-thread comments + first 20 review comments (line-level reviews). For plain issues: body + first 20 comments. The GitHub wrapper (`apps/github/references/web/api/repos.py`) doesn't expose the comment endpoints directly — the task uses the base service's `_get` method to hit `/repos/.../issues/N/comments` and `/repos/.../pulls/N/comments` directly.
- **Chunk id:** `f"{owner}/{repo}#PR{n}:{i}"` for PRs, `f"{owner}/{repo}#I{n}:{i}"` for issues — namespaced so PR and issue numbers can't collide.
- **Reference:** `html_url`.
- **Meta:** `owner`, `repo`, `kind` (`pr` or `issue`), `number`, `state`, `title`, plus `merged` for PRs and `labels` for issues.
- **Scope:** by `repos=['acme/web', 'acme/api']` kwarg, plus `states='open'/'closed'/'all'`.
- **Default schedule:** nightly **03:00**.

#### `ingest_gdrive_docs` (Google Drive Docs)

- **Captures:** Google Docs only (MIME type `application/vnd.google-apps.document`). Sheets and Slides are skipped in v1 — their cell-/slide-shaped content benefits from a dedicated extractor we'll add when first needed. Binary files (PDFs, images) are skipped too.
- **Extraction:** `files().export(mimeType='text/plain')` — Google does the heavy lifting; we just chunk the result.
- **Chunk id:** `f"{file_id}:{idx}"`.
- **Reference:** `https://docs.google.com/document/d/{file_id}/edit`.
- **Meta:** `file_id`, `name`, `modified_time`, `mime_type`.
- **Scope:** by `folder_id` (None = whole Drive), plus `modified_after` RFC 3339 timestamp for incremental ingest.
- **Default schedule:** nightly **03:15**.

### 6.4 Why the schedules are staggered

Gemini's free-tier embedding quota is generous but not infinite (60 RPM at the time of writing). Running four ingestors at the same minute would race for the same bucket and cause throttling:

```
02:30  ingest_notion_pages         ┐
02:45  ingest_jira_issues          ├─ each gets a clean 15-min runway
03:00  ingest_github_repos         │
03:15  ingest_gdrive_docs          ┘
```

15 minutes is comfortable for a few hundred pages/issues/docs at the free-tier rate. If a corpus grows past that, either bump its `max_*` cap, set a `modified_after` filter for incremental runs, or move to the paid tier.

### 6.5 Cross-source query patterns

The retriever takes a single optional `source` filter today:

```python
# scoped — fast, focused, lowest risk of irrelevant hits
knowledge_ask("what did we decide about merge-freeze?", source="notion")

# cross-source — finds connections you'd otherwise have to chase by hand
knowledge_ask("how did we solve the flaky-test issue?", source=None)
# → may cite [1] from Jira, [2] from a GitHub PR, [3] from a Notion runbook
```

For multi-source filters (e.g. "Notion + Jira but not GitHub"), the change is small — `apps/sqlite_vec/store.py:search()` would swap `c.source = ?` for `c.source IN (...)`. Not implemented in v1 because the two extreme cases (one source vs all) cover ~95% of query intents.

**Caveat — cross-source noise.** When one corpus is much chattier than the others (a busy Discord ingest can be 10× the size of Notion), unscoped queries can be dominated by it. Two mitigations available:

1. **Per-source quota.** Modify the retriever to ask for `k_per_source` instead of `k`, then merge. Cheap; ~10 lines.
2. **Source weighting.** Multiply distance by a per-source factor (0.9 for trusted curated sources, 1.1 for chatty ones) before sorting. Tuneable from config.

Neither ships in v1 — they're listed in the roadmap and recommended once you've watched real query patterns for a week.

### 6.6 Cost — what to watch

The user explicitly opted into observed Gemini cost for v1. Reference points to anchor the bill against:

| Operation | Tokens (rough) | Gemini text-embedding-004 free tier |
|---|---|---|
| One Notion page (~2 chunks) | ~1k | covered ad infinitum |
| One Jira issue + 30 comments (~3 chunks) | ~1.5k | covered |
| One GitHub PR + 20 comments (~5 chunks) | ~2.5k | covered |
| One Google Doc, 10 pages (~6 chunks) | ~3k | covered |
| Full nightly run, 200 of each | ~1.6M | well within free tier |

What costs **money** is the answer step (Anthropic). Haiku 4.5 at the time of writing: ~$0.80/M input, ~$4/M output. A single `knowledge_ask` with k=5 is roughly:
- ~3k input tokens (system prompt + 5 chunks + question) → $0.0024
- ~500 output tokens (cited answer)                      → $0.002
- **≈ $0.005 per question**

For observation, the simplest way to track is the existing ES logging — `@log_result()` already wraps every ingest task and the `answer` task. Look at `harqis-mcp.knowledge` and `knowledge.ingest_*` log streams. If you want a dedicated dashboard:
- **Embed ingest cost:** sum of `chunks_written × avg_chunk_tokens` across the four ingest tasks per night
- **Answer cost:** count of `answer` task calls × ~$0.005

If the bill starts to surprise you: drop `max_pages` / `max_issues` / `max_files` / `per_repo_limit` in `tasks_config.py` and the next run is throttled.

### 6.7 Setup — going from one source to four

Each source needs its config block in `apps_config.yaml` populated. Notion you've already done. The other three:

| Source | Required env vars (in `.env/apps.env`) | Where to get the credential |
|---|---|---|
| Jira | `JIRA_DOMAIN`, `JIRA_API_TOKEN` | <https://id.atlassian.com/manage-profile/security/api-tokens> |
| GitHub | `GITHUB_API_TOKEN` (or whatever your config block names it) | <https://github.com/settings/tokens> — fine-grained PAT with `repo` read scope |
| Google Drive | OAuth credentials JSON in `credentials.json` and a `storage-drive.json` token cache | Google Cloud console → OAuth client → Desktop app type. The `apps/google_drive/config.py` flow handles the rest. |

Once env vars are set, populate the kwargs in `workflows/knowledge/tasks_config.py`:

```python
'run-job--ingest_jira_issues': { ..., 'kwargs': {'project_keys': ['HARQIS', 'OPS'], ...}, ... },
'run-job--ingest_github_repos': { ..., 'kwargs': {'repos': ['brianbartilet/harqis-work'], ...}, ... },
'run-job--ingest_gdrive_docs':  { ..., 'kwargs': {'folder_id': '<root or specific folder id>', ...}, ... },
```

Then either wait until 02:45 / 03:00 / 03:15 or trigger manually:

```bash
# Manual smoke runs (synchronous, no broker required)
python -c "from workflows.knowledge.tasks.ingest_jira import ingest_jira_issues; print(ingest_jira_issues(project_keys=['HARQIS'], max_issues=20))"
python -c "from workflows.knowledge.tasks.ingest_github import ingest_github_repos; print(ingest_github_repos(repos=['brianbartilet/harqis-work'], per_repo_limit=20))"
python -c "from workflows.knowledge.tasks.ingest_gdrive import ingest_gdrive_docs; print(ingest_gdrive_docs(max_files=20))"
```

After each, sanity-check via the MCP tool `vector_store_stats` — you should see `by_source: {notion: …, jira: …, github: …, gdrive: …}`.

### 6.8 Operational gotchas

| Symptom | Likely cause | Fix |
|---|---|---|
| `ingest_jira_issues` returns 0 | `project_keys=[]` (default) and the user has access to nothing | Set `project_keys` explicitly in `tasks_config.py` |
| Jira description shows up as `{...ADF noise...}` in chunks | Old API path that doesn't go through `flatten_adf` | The current `_compose_issue_text` covers it; if you bypass it, route the field through `chunking.flatten_adf` |
| `ingest_github_repos` returns 0 | `repos=[]` (default) — explicitly required | Set `repos=['owner/repo', …]` |
| GitHub PRs ingest but issues are empty | `apps/github` `list_issues` already filters out PRs (it skips items with `pull_request` key); plain issues need to actually exist | Confirm the repo has issues and the token has issue read scope |
| `ingest_gdrive_docs` returns 0 | OAuth token cache (`storage-drive.json`) expired or never created | Re-run the auth flow from `apps/google_drive` |
| `chunks_written: 0` everywhere | Likely a Gemini rate-limit / quota error | Check the task logs for 429s; reduce `max_*` and stagger longer |

---

## 7. Roadmap — what to build next

In rough priority order:

1. **Voyage embeddings app.** Scaffold `apps/voyage` via `/new-service-app` so domain-tuned models (`voyage-code-3`, `voyage-finance-2`) become available. Run an A/B against Gemini on a fixed eval set before switching anything by default.
2. **Re-ranker step.** After top-k retrieval, re-rank with a small cross-encoder (Cohere rerank, or Gemini's `RANKING` task type) before sending to the LLM. Cheap, often a +10-20% recall@5 win.
3. **Eval harness.** A fixed list of (question, expected-source) pairs + a script that runs the full pipeline and scores recall@k. Without this, every config tweak is a guess.
4. **Per-corpus chunkers.** Code wants AST-aware chunks; Notion wants block-aware chunks; Jira wants comment-aware chunks. Centralise the contract in `workflows/knowledge/chunking.py`; specialise per corpus.
5. **Promote sqlite-vec → Qdrant** when the store crosses ~1M chunks or query latency exceeds 200ms p95. The `store` API is already shaped for it.
6. **Caching.** Cache `(question_hash, k, source) → answer` for ~1h. Most "ask my Notion" sessions ask the same question two or three times in a row.

---

## 8. Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Make sure GEMINI + ANTHROPIC are set in apps_config.yaml / apps.env, plus
#    whichever sources you want to index: NOTION, JIRA, GITHUB, GOOGLE_DRIVE.

# 3. Trigger ingests (synchronous — no broker required, so you can watch costs land)
python -c "from workflows.knowledge.tasks.ingest_notion  import ingest_notion_pages;   print(ingest_notion_pages(max_pages=20))"
python -c "from workflows.knowledge.tasks.ingest_jira    import ingest_jira_issues;    print(ingest_jira_issues(project_keys=['HARQIS'], max_issues=20))"
python -c "from workflows.knowledge.tasks.ingest_github  import ingest_github_repos;   print(ingest_github_repos(repos=['brianbartilet/harqis-work'], per_repo_limit=20))"
python -c "from workflows.knowledge.tasks.ingest_gdrive  import ingest_gdrive_docs;    print(ingest_gdrive_docs(max_files=20))"

# 4. Sanity-check the store
python -c "from apps.sqlite_vec import store; import json; print(json.dumps(store.stats(), indent=2))"

# 5. Ask a scoped question (one corpus)
python -c "from workflows.knowledge.tasks.answer import answer_question; import json; \
           print(json.dumps(answer_question('what did I write about merge freeze?', source='notion'), indent=2))"

# 6. Ask a cross-source question (all corpora)
python -c "from workflows.knowledge.tasks.answer import answer_question; import json; \
           print(json.dumps(answer_question('how did we solve the flaky-test issue?', source=None, k=8), indent=2))"

# 7. Or via Claude Desktop — the MCP server registers knowledge_ask + knowledge_search automatically
python mcp/server.py
```

Once the beat scheduler is running (`./scripts/sh/deploy.sh` or platform equivalent), the four ingestors run nightly at 02:30 / 02:45 / 03:00 / 03:15 and keep the store warm without manual intervention.
