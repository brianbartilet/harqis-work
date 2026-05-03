# sqlite_vec

Local vector store for harqis-work RAG workflows. Single SQLite file backed by [sqlite-vec](https://github.com/asg017/sqlite-vec) — no server, no extra service.

## Why this exists

Embedding generation lives in `apps/gemini` (and the stubs in `apps/grok`, `apps/perplexity`). Generation lives in `apps/antropic` / `apps/open_ai`. This app fills the gap in the middle: somewhere to **persist embeddings and do KNN search** without running Qdrant / pgvector / Chroma.

It is the smallest viable vector store. When a corpus outgrows it (~5M chunks), swap the backing file for a real vector DB — the public API (`upsert`, `search`, `stats`, `delete_by_source`) is intentionally portable.

## Public API

```python
from apps.sqlite_vec import store

store.upsert(
    chunk_id="page-abc:0",
    text="raw chunk text",
    embedding=[0.01, ...],     # any dim; table is created on first call
    source="notion",
    ref="https://notion.so/...",
    meta={"page_id": "abc", "chunk_idx": 0},
)

hits = store.search(query_embedding=[...], k=5, source="notion")
# → [{id, source, ref, text, meta, distance}, ...]

store.stats()                  # → {total, by_source, path}
store.delete_by_source("notion")
```

## Storage

Default DB path: `<repo>/data/vector_store.db`. Override with the `HARQIS_VECTOR_DB` env var (or pass `db_path=` per call).

Vectors are L2-normalised on write so the `vec0` virtual table's L2 distance behaves like cosine — smaller = more similar.

## MCP

`register_sqlite_vec_tools(mcp)` adds three Claude Desktop tools:

| Tool | Purpose |
|---|---|
| `vector_store_stats` | counts per source — ingestion smoke check |
| `vector_store_search_text` | KNN against a pre-computed embedding |
| `vector_store_delete_source` | clear before a full re-ingest |

End-to-end question answering goes through the `knowledge_ask` workflow tool, not this app — this one is for plumbing only.

## Tests

`pytest apps/sqlite_vec/tests` — uses an isolated tmp DB per test.
