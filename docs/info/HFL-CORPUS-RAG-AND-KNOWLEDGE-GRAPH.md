# HFL Corpus RAG and Knowledge Graph Analysis

## Conclusion

Retrieval-augmented generation (RAG) is applicable to the HFL Markdown corpus.
Its immediate value is better semantic retrieval and cited answer synthesis, not
search performance.

The recommended direction is:

1. Add HFL Markdown ingestion to the existing Knowledge vector pipeline.
2. Combine vector retrieval with the existing Elasticsearch and metadata search.
3. Retain the knowledge graph from
   [PR #29](https://github.com/brianbartilet/harqis-work/pull/29) as an optional
   relationship-discovery layer after updating it for the current corpus layout.

PR #29 still has value for HARQIS, but it should not be merged unchanged or
treated as a substitute for RAG.

## Concepts

| Capability | Best at | Current HFL support |
|---|---|---|
| Keyword search | Exact words, tags, dates, and sources | Yes |
| Vector search | Similar meaning expressed with different words | No first-class HFL index |
| RAG | Retrieving relevant evidence and generating a cited answer | Available for other Knowledge sources |
| Knowledge graph | Traversing explicit relationships between entries and entities | Proposed by PR #29 |

For example:

- Keyword search for `authentication failure` finds entries containing those
  words.
- Vector search may also find `login stopped working because credentials
  expired`.
- RAG can retrieve several relevant entries and summarize the recurring problem
  with citations.
- A knowledge graph can reveal that the incidents involved the same machine,
  application, credential, artifact, or earlier decision.

RAG does not replace the Markdown corpus. Markdown remains the source of truth:

```text
Question
   |
   v
Extract date, tag, and source constraints
   |
   +--> Elasticsearch keyword search
   |
   +--> Vector similarity search
              |
              v
       Combine and rank results
              |
              v
       Optional graph expansion
              |
              v
       Best Markdown evidence
              |
              v
       Answer with citations
```

## Current HARQIS implementation

HFL already has useful structured and lexical retrieval:

- The corpus frontend recursively indexes Markdown and supports text, date, tag,
  and source filters.
- `workflows/hfl/es_store.py` projects entries into Elasticsearch and searches
  multiple structured fields.
- `workflows/hfl/tasks/retrieve.py` provides direct substring and tag retrieval
  from Markdown.
- `workflows/hfl/mcp.py` exposes narrative and structured recall through MCP.

HARQIS also already contains most of the infrastructure required for RAG:

- `workflows/knowledge/embed.py` generates document and query embeddings.
- `workflows/knowledge/retriever.py` performs vector retrieval.
- `workflows/knowledge/tasks/answer.py` retrieves evidence and generates cited
  answers.
- The Knowledge workflow embeds Confluence, Notion, Jira, GitHub, and Google
  Drive content.

Recent HFL entries are used as a live signal for cross-source linking, but HFL
entries are not themselves stored as first-class vectors. This is the main
missing integration.

## How RAG would help

RAG would improve questions where the user remembers the meaning rather than the
original wording:

- When have I encountered problems similar to this MCP startup failure?
- What past decisions might explain why the sharing page works this way?
- Find previous incidents caused by configuration drift.
- What recurring themes exist in my work on corpus navigation?
- What did I learn from earlier authentication problems?

Expected benefits include:

- Semantic recall when terminology changes.
- Synthesis across multiple days or documents.
- Smaller prompts because only the best evidence is sent to the answer model.
- Citations back to the source Markdown entries.
- Better retrieval across sparsely or inconsistently tagged entries.
- The ability to combine personal context with project knowledge.

RAG does not automatically:

- Guarantee correct answers.
- Discover reliable causal relationships.
- Replace exact date, tag, or source filtering.
- Compensate for missing or poorly captured source entries.
- Eliminate privacy concerns when external embedding or generation providers
  process corpus content.

On the Windows checkout inspected for this analysis, the configured corpus
contained approximately 45 Markdown files, 45 parsed entries, and 0.09 MiB of
content. At that size, direct search is sufficient for performance. RAG is
justified by semantic questions and cited synthesis, and its value will grow as
the corpus reaches hundreds or thousands of entries.

## Assessment of PR #29

[PR #29](https://github.com/brianbartilet/harqis-work/pull/29) implements an
opt-in relationship knowledge graph rather than RAG.

It adds:

- Deterministic nodes for entries, dates, ISO weeks, tags, sources, machines,
  and artifacts.
- Optional Graphify and Claude semantic extraction.
- A read-only `memory_graph_query` MCP tool.
- Immutable graph generations outside the Markdown corpus.
- Validation and filesystem hardening.
- Opt-in execution without an automatic Beat schedule.

The idea remains aligned with the HFL goal of discovering connections across
memories. However, the branch needs design updates before integration.

### Current concerns

#### Archived documents are omitted

The deterministic graph discovery and Graphify snapshot inspect only root-level
`YYYY-MM-DD.md` files. Current corpus handling archives older documents in nested
year and month directories. The graph would therefore omit archived history,
where relationship discovery is likely to be most valuable.

#### Graph queries remain keyword-seeded

`query_graph()` selects seed nodes by checking whether tokens from the question
occur in node text. It then traverses outward from up to five seeds. If the
question uses different terminology, no suitable seed may be selected.

Vector retrieval addresses this semantic gap more directly and can also provide
better seed nodes for graph traversal.

#### There is functional overlap

The existing Knowledge workflow already provides embedding retrieval and a
`relations()` capability. The proposed graph is richer and HFL-specific, but
adding another large retrieval subsystem before indexing HFL in the existing
vector store creates avoidable duplication.

#### Semantic edges need evidence

Graph artifact validation proves structural correctness, not factual correctness.
Relationships inferred by an LLM need confidence, provenance, and visible
supporting excerpts.

#### Privacy and cost require evaluation

The semantic graph build sends Markdown source text to Anthropic. An HFL RAG
implementation also requires an embedding privacy decision, but it can process
entries incrementally and could use a local embedding model if required.

#### The branch has drifted from main

The branch is substantially behind current `main`. A merge-tree comparison found
one direct content conflict in `workflows/hfl/mcp.py`. That conflict is
manageable, but the nested archive layout and newer HFL sources are more
important architectural differences.

The PR appropriately leaves real-corpus usefulness, privacy, and cost evaluation
as promotion criteria. It should therefore be considered a defended experiment,
not a production-ready feature.

## Recommended implementation

### 1. Add HFL to the existing vector pipeline

Create an HFL ingestion adapter that:

- Recursively discovers current and archived Markdown.
- Parses entries through the existing `HflEntry` DTO.
- Normally treats one HFL entry as one semantic chunk.
- Stores date, tags, source, machine, references, document path, and entry ID as
  vector metadata.
- Uses stable IDs and content hashes for incremental updates.
- Removes vector records when source entries disappear.
- Links every result to its Markdown source.

The inspected median entry size was approximately 2,200 characters, which is a
reasonable semantic chunk. Only unusually long entries should require
subdivision.

### 2. Use hybrid retrieval

Elasticsearch should remain part of the retrieval path:

- Elasticsearch handles exact terms and structured filters.
- Vector search handles semantic similarity.
- Rank fusion combines the result sets.
- An optional reranker orders the best 10 to 20 candidates.
- Approximately 5 to 8 evidence entries are supplied to the answer model.

This preserves precise queries such as `tag:github after:2026-06-01` while also
supporting conceptual questions.

### 3. Rework the graph as a second layer

After hybrid retrieval works, the graph can expand relationships around the
strongest retrieved entries:

```text
Current issue
  -> same application
  -> earlier incident
  -> related configuration change
  -> resulting decision
```

PR #29 would be easier to validate if separated into:

1. A smaller deterministic graph change.
2. A separate semantic Graphify experiment.
3. A later integration that uses vector-retrieved entries as graph seeds.

The deterministic graph is inexpensive, explainable, and private. Semantic
enrichment should be promoted only if it repeatedly discovers useful
relationships that hybrid RAG does not.

## Final recommendation

- RAG fills a real semantic-retrieval gap and reuses infrastructure already in
  HARQIS.
- It is not currently required for corpus performance.
- Hybrid HFL RAG should be implemented before adding another standalone
  retrieval system.
- PR #29 remains useful as an optional relationship-discovery layer.
- PR #29 should first be rebased and updated for recursive archived-corpus
  discovery, semantic graph seeding, and current HFL integrations.
- The preferred order is hybrid RAG, deterministic graph, and then externally
  generated semantic graph enrichment after measured validation.
