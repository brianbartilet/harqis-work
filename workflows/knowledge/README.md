# Knowledge / RAG workflow — "Knowledge Radar"

Local Retrieval-Augmented-Generation pipeline. Ingests source corpora
(Confluence, Notion, Jira, GitHub, Google Drive) into a single sqlite-vec store
and, on top of plain Q&A, surfaces **relations and inferences across sources** —
what connects to what, what you're working on now, where the knowledge gaps are.

For the design rationale and full pipeline diagram see
[`docs/thesis/RAG-WORKFLOW.md`](../../docs/thesis/RAG-WORKFLOW.md). For the
Phase-1 + Phase-3 POC built on top of it (Confluence ingest + cross-source
intelligence) see [`docs/thesis/KNOWLEDGE-RADAR-PHASE1-3.md`](../../docs/thesis/KNOWLEDGE-RADAR-PHASE1-3.md).

## Status — embedder fixed; beat schedule still OFF by choice

The **stale-model blocker is resolved**: `apps/gemini/.../embed.py` now defaults
to `models/gemini-embedding-001`, and the four copy-pasted `_embed_batch`
helpers are DRYed into [`embed.py`](embed.py) (one place to swap provider/model,
via `HARQIS_KNOWLEDGE_EMBED_PROVIDER` / `HARQIS_KNOWLEDGE_EMBED_MODEL`).

`WORKFLOW_KNOWLEDGE` in [`tasks_config.py`](tasks_config.py) still exports `{}`
(beat entries live in `_DISABLED__WORKFLOW_KNOWLEDGE`). The remaining gate is
**operational, not code**: Gemini embedding credits must be funded (a live probe
returned `429 RESOURCE_EXHAUSTED` — *"prepayment credits are depleted"*), or
point the embedder at another provider. Task functions are intact, so manual /
MCP invocation works today once embeddings are funded.

**To re-enable beat:** fund/redirect embeddings, then rename
`_DISABLED__WORKFLOW_KNOWLEDGE` → `WORKFLOW_KNOWLEDGE` and restart the scheduler.

## Layout

```
workflows/knowledge/
├── embed.py             # single embedder (provider/model env-driven) — DRYs all ingest
├── chunking.py          # text splitting + Notion blocks + Confluence storage→text
├── entities.py          # deterministic JIRA/PR/URL/service/acronym extraction
├── retriever.py         # embed query + KNN against sqlite_vec
├── watchlist.py         # watchlists.yaml loader
├── watchlists.yaml      # standing-interest topics (keywords + services + prompt)
├── prompts/
│   ├── rag_answer.md    # system prompt for the answer step
│   └── topic_map.md     # system prompt for the topic learning brief
└── tasks/
    ├── ingest_*.py      # confluence / notion / jira / github / gdrive → embed → upsert
    ├── answer.py        # question → retrieve → Anthropic → cited answer
    ├── topic_map.py     # learn a topic + its integrations/dependencies/value (Phase 3)
    ├── topic_scan.py    # run a watchlist → ranked hit cards (Phase 1/2)
    └── cross_link.py    # working-context / relations / orphan tickets / stale docs (Phase 3)
```

## Sources (corpus labels)

| source | task | notes |
| --- | --- | --- |
| `confluence` | `ingest_confluence_pages` | **incremental** by page version; CQL-scoped to spaces |
| `notion` | `ingest_notion_pages` | full workspace search |
| `jira` | `ingest_jira_issues` | issues + comments (ADF-flattened) |
| `github` | `ingest_github_repos` | PRs + issues + review comments |
| `gdrive` | `ingest_gdrive_docs` | Google Docs (text export) |
| `hfl` | (read-only) | your Homework-for-Life timeline, queried live for cross-linking |

## MCP tools

`knowledge_search`, `knowledge_ask` (cited Q&A), plus the radar surface:
`knowledge_list_sources`, `knowledge_topic_map`, `knowledge_relations`,
`knowledge_working_context`, `knowledge_orphan_tickets`, `knowledge_stale_docs`,
`knowledge_scan_watchlist`. Confluence has its own `confluence_search` /
`confluence_get_page` / `confluence_list_spaces`.

## Run it once, locally

Bootstrap env first (see the `harqis-env-context` skill) so `${...}` placeholders
resolve, then:

```bash
# 1. Ingest Confluence (incremental — only changed/new pages re-embed)
python -c "from workflows.knowledge.tasks.ingest_confluence import ingest_confluence_pages; \
           print(ingest_confluence_pages(space_keys=['ENG','OPS'], max_pages=200))"

# 2. Ask a cited question over a source
python -c "from workflows.knowledge.tasks.answer import answer_question; \
           print(answer_question('How does token refresh work?', source='confluence'))"

# 3. Learn a topic + its integrations/dependencies/value (Phase 3)
python -c "from workflows.knowledge.tasks.topic_map import topic_map; \
           print(topic_map('Payments settlement flow')['brief'])"

# 4. What am I working on, and what connects to it? (HFL + index)
python -c "from workflows.knowledge.tasks.cross_link import working_context; \
           print(working_context(since='-7d', summarize=True)['brief'])"

# 5. Knowledge gaps + staleness
python -c "from workflows.knowledge.tasks.cross_link import orphan_jira, stale_docs; \
           print(orphan_jira()['orphan_count'], stale_docs()['candidate_count'])"
```

## Cost guard

`answer_question` defaults to **Haiku 4.5** (`claude-haiku-4-5-20251001`). Do not change the Anthropic default model in `apps_config.yaml` — pass an override via `model=` instead. The beat schedule in `tasks_config.py` already pins it.

## Adding a new corpus

1. Write `workflows/knowledge/tasks/ingest_<source>.py` mirroring the Notion ingest task.
2. Tag chunks with a unique `source=` label so retrieval can scope to it.
3. Register the task on a beat schedule in `tasks_config.py`.
4. (Optional) Add a source-scoped MCP tool in `apps/sqlite_vec/mcp.py` if it needs a dedicated entry point.

## Manifesto alignment

See [`docs/MANIFESTO.md`](../../docs/MANIFESTO.md) and [`docs/thesis/MANIFESTO-REPO-UPDATES.md`](../../docs/thesis/MANIFESTO-REPO-UPDATES.md). The same metadata is persisted on each beat entry's `'manifesto'` key in `tasks_config.py`.

| Task | code_role | para_bucket | express_target | review_artifact | hfl_signal |
| --- | --- | --- | --- | --- | --- |
| `ingest_confluence_pages` | capture | area | `vectorstore:knowledge` | `es_log` | `False` |
| `ingest_notion_pages` | capture | area | `vectorstore:knowledge` | `es_log` | `True` |
| `ingest_jira_issues` | capture | area | `vectorstore:knowledge` | `es_log` | `False` |
| `ingest_github_repos` | capture | area | `vectorstore:knowledge` | `es_log` | `False` |
| `ingest_gdrive_docs` | capture | area | `vectorstore:knowledge` | `es_log` | `True` |
| `knowledge_cross_link_report` | distill+express | area | `es_log` | `es_log` | `True` |
| `knowledge_answer_morning_brief` | distill+express | area | `es_log` | `es_log` | `True` |
