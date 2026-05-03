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

What was missing: **a vector store**. This thesis fills that gap with `apps/sqlite_vec` and wires a first end-to-end pipeline through `workflows/knowledge`.

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
├── chunking.py                    ← text splitter + Notion block extractor
├── retriever.py                   ← embed query + KNN
├── prompts/rag_answer.md          ← system prompt for the answer step
├── tasks/
│   ├── ingest_notion.py           ← Notion → embed → upsert (beat: nightly)
│   └── answer.py                  ← question → retrieve → Anthropic
├── tasks_config.py                ← beat schedules
├── mcp.py                         ← knowledge_ask + knowledge_search MCP tools
└── README.md

workflows/config.py                ← MODIFIED: registers WORKFLOW_KNOWLEDGE
mcp/server.py                      ← MODIFIED: adds two new registrars
requirements.txt                   ← MODIFIED: adds sqlite-vec
docs/thesis/HARQIS-RAG-WORKFLOW.md ← THIS DOCUMENT
```

---

## 3. Process & flow

### 3.1 Ingestion flow (write path)

```
Celery beat (02:30 nightly)
    │
    ▼
ingest_notion_pages
    │
    ├── apps/notion/search.search(filter='page')        → list of pages (paginated)
    │
    ├── for each page:
    │       apps/notion/blocks.get_block_children()     → flatten to plain text
    │       chunking.chunk_text(text, chars=2000)       → list of chunks
    │
    ├── batch (50 at a time):
    │       apps/gemini/embed.batch_embed_contents(
    │           texts, task_type='RETRIEVAL_DOCUMENT')   → list of vectors
    │
    └── for each (chunk, vector):
            apps/sqlite_vec/store.upsert(
                id=f"{page_id}:{chunk_idx}",
                text=chunk,
                embedding=vector,
                source='notion',
                ref=page_url,
                meta={page_id, title, chunk_idx})
```

Idempotency: re-running the task is safe. Chunk ids are stable (`page_id:idx`), so re-ingesting a page replaces its existing rows. For a clean rebuild, pass `rebuild=True` — the task drops the `notion` source first.

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

### 5.4 Kanban agent with project memory

**Background:** the kanban agent in `agents/kanban` re-reads card history each run. It has no memory of similar cards solved months ago.

**Pipeline:**
- Ingest task indexes every closed Jira/Trello card: title + description + final comment, source='kanban_history'.
- Pre-action hook in the agent calls `retrieve(card.summary, k=5, source='kanban_history')` and injects "5 most semantically similar past cards" as a context block.

**Use case:** Agent picks up *"investigate flaky test X"* and is told *"these 3 prior cards (PROJ-481, PROJ-512, PROJ-633) solved similar flakes by checking the Y race condition"* — without bloating every prompt with the whole project history.

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

## 6. Roadmap — what to build next

In rough priority order:

1. **Voyage embeddings app.** Scaffold `apps/voyage` via `/new-service-app` so domain-tuned models (`voyage-code-3`, `voyage-finance-2`) become available. Run an A/B against Gemini on a fixed eval set before switching anything by default.
2. **Re-ranker step.** After top-k retrieval, re-rank with a small cross-encoder (Cohere rerank, or Gemini's `RANKING` task type) before sending to the LLM. Cheap, often a +10-20% recall@5 win.
3. **Eval harness.** A fixed list of (question, expected-source) pairs + a script that runs the full pipeline and scores recall@k. Without this, every config tweak is a guess.
4. **Per-corpus chunkers.** Code wants AST-aware chunks; Notion wants block-aware chunks; Jira wants comment-aware chunks. Centralise the contract in `workflows/knowledge/chunking.py`; specialise per corpus.
5. **Promote sqlite-vec → Qdrant** when the store crosses ~1M chunks or query latency exceeds 200ms p95. The `store` API is already shaped for it.
6. **Caching.** Cache `(question_hash, k, source) → answer` for ~1h. Most "ask my Notion" sessions ask the same question two or three times in a row.

---

## 7. Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Make sure NOTION + GEMINI + ANTHROPIC are set in apps_config.yaml / apps.env

# 3. Trigger first ingest (synchronous, no broker required)
python -c "from workflows.knowledge.tasks.ingest_notion import ingest_notion_pages; print(ingest_notion_pages(max_pages=20))"

# 4. Ask a question
python -c "from workflows.knowledge.tasks.answer import answer_question; \
           import json; print(json.dumps(answer_question('what did I write about merge freeze?', source='notion'), indent=2))"

# 5. Or via Claude Desktop — the MCP server registers knowledge_ask + knowledge_search automatically
python mcp/server.py
```

Once the beat scheduler is running (`./scripts/sh/deploy.sh` or platform equivalent), the nightly Notion ingest at 02:30 keeps the store warm without manual intervention.
