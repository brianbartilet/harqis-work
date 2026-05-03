# Knowledge / RAG workflow

Local Retrieval-Augmented-Generation pipeline. Ingests source corpora into a single sqlite-vec store and answers questions over them with Anthropic Claude.

For the design rationale, full pipeline diagram, and the broader capability roadmap, see [`docs/thesis/HARQIS-RAG-WORKFLOW.md`](../../docs/thesis/RAG-WORKFLOW.md).

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
