# Knowledge / RAG workflow

Local Retrieval-Augmented-Generation pipeline. Ingests source corpora into a single sqlite-vec store and answers questions over them with Anthropic Claude.

For the design rationale, full pipeline diagram, and the broader capability roadmap, see [`docs/thesis/HARQIS-RAG-WORKFLOW.md`](../../docs/thesis/RAG-WORKFLOW.md).

## Status — beat schedule is currently DISABLED (2026-05-14)

`WORKFLOW_KNOWLEDGE` in [`tasks_config.py`](tasks_config.py) exports an empty
dict. Celery beat has no entries for this workflow. The task functions
themselves are intact, so manual / on-demand invocation (`.delay()`, the MCP
tool, the `python -c …` snippets below) still works — and will surface the
same blockers.

**Why disabled:** ES rollups showed the three Gemini-dependent ingestors
(`ingest_notion_pages`, `ingest_jira_issues`, `ingest_gdrive_docs`) failing
5 nights in a row with `RuntimeError`. `ingest_github_repos` was logged as
"passing" only because the beat config had `repos: []`, which short-circuits
the task before it ever touches Gemini.

**Two stacked root causes — both must be resolved before re-enabling:**

1. **Stale embedding model.** `apps/gemini/references/web/api/embed.py:6`
   hard-codes `DEFAULT_EMBED_MODEL = 'models/text-embedding-004'`, which
   Google retired. The endpoint now returns `404 NOT_FOUND`. The
   `_embed_batch()` helper (copy-pasted across all four ingestors) then
   sees `{'error': …}` instead of `{'embeddings': […]}`, and the length
   mismatch raises `RuntimeError`.
   Fix: bump to `'models/gemini-embedding-001'` (current GA — `gemini-embedding-2`
   is also available).
2. **Gemini credits depleted.** Even with a valid model name, a live probe
   returns `429 RESOURCE_EXHAUSTED`: *"Your prepayment credits are depleted."*
   Top up at <https://ai.studio/projects>, or swap the embedder for a
   different provider (sentence-transformers locally, OpenAI, Cohere).
   Gemini's free tier no longer covers embeddings.

**To re-enable:** in `tasks_config.py`, rename `_DISABLED__WORKFLOW_KNOWLEDGE`
back to `WORKFLOW_KNOWLEDGE` and restart the beat scheduler. The entry
definitions are preserved verbatim — no values were lost.

**Bonus cleanup worth doing at the same time:** `_embed_batch` is copy-pasted
four times (`ingest_notion.py:67`, `ingest_jira.py:81`, `ingest_gdrive.py:41`,
`ingest_github.py:44`). DRY it into `workflows/knowledge/embed.py` so the
next model rename is one edit, not four.

## Layout

```
workflows/knowledge/
├── chunking.py          # text splitting + Notion block extraction
├── retriever.py         # embed query + KNN against sqlite_vec
├── prompts/
│   └── rag_answer.md    # system prompt for the answer step
└── tasks/
    ├── ingest_notion.py # Notion → embed → upsert (Celery beat: nightly)
    └── answer.py        # question → retrieve → Anthropic → answer (sync helper + Celery task)
```

## Run it once, locally

```bash
# 1. Make sure NOTION + GEMINI + ANTHROPIC are configured in apps_config.yaml
# 2. Trigger an ingest (synchronous, no broker needed)
python -c "from workflows.knowledge.tasks.ingest_notion import ingest_notion_pages; print(ingest_notion_pages())"

# 3. Ask a question
python -c "from workflows.knowledge.tasks.answer import answer_question; \
           print(answer_question('What did I decide about merge-freeze?', source='notion'))"
```

## Cost guard

`answer_question` defaults to **Haiku 4.5** (`claude-haiku-4-5-20251001`). Do not change the Anthropic default model in `apps_config.yaml` — pass an override via `model=` instead. The beat schedule in `tasks_config.py` already pins it.

## Adding a new corpus

1. Write `workflows/knowledge/tasks/ingest_<source>.py` mirroring the Notion ingest task.
2. Tag chunks with a unique `source=` label so retrieval can scope to it.
3. Register the task on a beat schedule in `tasks_config.py`.
4. (Optional) Add a source-scoped MCP tool in `apps/sqlite_vec/mcp.py` if it needs a dedicated entry point.
