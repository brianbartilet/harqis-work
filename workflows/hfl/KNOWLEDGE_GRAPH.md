# HFL Knowledge Graph — Opt-in Relationship Discovery

> Express output: a read-only `memory_graph_query` MCP result that explains how
> memories, dates, tags, sources, machines, references, and bounded semantic
> concepts are connected.

## Why this exists

HARQIS HFL is already queryable through structured Elasticsearch projection,
`memory_recall_es`, narrative `memory_recall`, time windows, media inventory,
weekly summaries, Knowledge embeddings, and current-work cross-linking.

This graph does not replace those paths. Its distinct job is relationship
discovery:

- expand one recalled event into related projects, people, places, machines,
  artifacts, lessons, and later outcomes;
- reconstruct project and incident paths over time;
- find repeated operational patterns that use different wording;
- identify isolated entries, missing provenance, and recurring themes;
- provide evidence-bearing paths rather than another text-search result.

The Markdown corpus remains the source of truth. Graph files are disposable,
rebuildable projections.

## Architecture

### 1. Deterministic HFL graph

`workflows/hfl/knowledge_graph.py` parses the formal `HflEntry` DTO and creates
stable local nodes and edges without an LLM:

```text
Entry -> occurred_on -> Date
Entry -> part_of -> ISO week
Entry -> tagged -> Tag
Entry -> sourced_from -> Source
Entry -> captured_on -> Machine
Entry -> references -> Artifact
```

This layer is cheap, testable, privacy-preserving, and preserves explicit facts
instead of asking a model to infer them.

### 2. Optional semantic enrichment

`workflows/hfl/tasks/build_knowledge_graph.py` can run reviewed Graphify
`0.9.22` over a bounded staging copy of the newest daily corpus files. Graphify
is forced to:

```text
graphify extract <staging> --out <semantic-dir> \
  --backend claude --model claude-haiku-4-5-20251001 \
  --max-concurrency 1
```

The task then merges Graphify's semantic graph with the deterministic graph.
Semantic relationships may include concerns, involves, demonstrates,
follows-from, contradicts, or similar model-extracted concepts. They remain
an enrichment layer, not authoritative facts.

### 3. Read-only Express surface

`memory_graph_query(question, depth=2, limit=30)` is registered with the HFL MCP
surface. It:

1. loads the latest verified merged graph;
2. seeds nodes from lexical relevance to the question;
3. traverses explicit and semantic relationships in both directions;
4. returns nodes, edges, and human-readable relationship explanations.

It performs no model call and writes nothing. Use `memory_recall_es` for direct
text/date lookup; use `memory_graph_query` when the relationship path is the
value.

## Activation and scheduling

This feature has no Celery Beat entry. The task refuses to run unless all of the
following are true:

- `HARQIS_HFL_GRAPH_ENABLE=1` is explicitly set;
- the reviewed Graphify CLI is installed;
- an Anthropic key is available;
- at least one canonical `YYYY-MM-DD.md` corpus file exists;
- the output root is outside the corpus.

Install the pinned optional dependency separately:

```bash
pip install -r requirements-graphify.txt
graphify --version  # graphify 0.9.22
```

Set output and enablement on an evaluation worker:

```bash
HARQIS_HFL_GRAPH_ENABLE=1
HFL_GRAPH_OUTPUT_ROOT=/Volumes/harqis-data/hfl-graphs
```

Then invoke the Celery task explicitly or call
`build_hfl_knowledge_graph_impl()` in a configured HARQIS shell. Do not add it
to `WORKFLOW_HFL` until the promotion criteria below pass.

## Artifact layout

Output is outside the scanned corpus, so later runs cannot ingest previous
graphs:

```text
<HFL_GRAPH_OUTPUT_ROOT>/2026-W30/<generation-id>/
  deterministic.json
  graph.json                         # merged MCP/query graph
  SUCCESS.json                       # schema, build time, SHA-256
  semantic/
    graphify-out/
      graph.json                     # Graphify semantic graph
      graph.html
      GRAPH_REPORT.md
```

Each successful run uses an immutable generation directory named
`YYYYMMDDTHHMMSSffffffZ-<32 lowercase hex>`. Graphify runs only in a private
temporary workspace. Publication creates every destination component through
no-follow directory descriptors and exclusive file creation; `SUCCESS.json` is
written last after schema and artifact validation. `latest_graph()` ignores
partial, malformed, symlinked, invalid-week, invalid-generation-name, and
checksum-mismatched generations. A failed or concurrent rebuild therefore
cannot replace the previous queryable graph.

Subprocess exit code zero is not enough. The task requires all three Graphify
artifacts before it publishes the success manifest.

## Privacy and provider boundary

Graphify sends Markdown source text to the configured model for semantic
extraction. Wrapping source as untrusted content does not mean the content is
absent from the request.

For HFL this may expose names, locations, reflections, project details, local
paths, and references. This is broader than a bounded recall prompt because it
processes a corpus slice. Enable it only when that exposure is acceptable.

Controls in this revision:

- explicit opt-in environment gate;
- no schedule by default;
- newest-file limit enforced by a staging copy because Graphify 0.9.22 has no
  `--max-files` flag;
- explicit `--backend claude` and `--model` arguments;
- minimal allowlisted subprocess environment, excluding Gemini/OpenAI and other
  competing provider credentials;
- output outside the source tree;
- corpus discovery and copying use one stable, no-follow directory descriptor;
- each date-named source is opened basename-relative with `O_NOFOLLOW` and `fstat`;
- output publication uses no-follow directory descriptors and exclusive file creation;
- builds never delete or overwrite a prior generation;
- duplicate legacy entries without `Entry ID` receive stable ordinal/content-hash IDs;
- conflicting duplicate explicit `Entry ID` values reject the corpus;
- semantic ID collisions cannot overwrite deterministic entry fields;
- model stderr omitted from persisted task results;
- strict node/link schema and checksum validation before publication;
- semantic source provenance linked to the source date, never all entries in a daily file;
- semantic graph treated as non-authoritative enrichment;
- ES receives build metadata and counts, not corpus text or graph contents.

## Operational contracts

| Condition | Result |
| --- | --- |
| Enable flag absent | `skipped=disabled` before CLI/config access |
| Model differs from reviewed Haiku pin | `reason=unsupported_model` before CLI/config access |
| Graphify missing | `skipped=cli_missing` |
| No daily corpus files | `skipped=empty_corpus` |
| Symlinked corpus/output path | rejected before model or filesystem mutation |
| Output inside corpus | `reason=output_inside_corpus` |
| Anthropic key absent | semantic build refused; nothing published |
| Timeout | `reason=timeout`; previous verified generation remains latest |
| Nonzero exit | `reason=non_zero_exit`; stderr is not persisted |
| Exit zero, missing artifact | `reason=missing_artifacts` |
| Invalid graph JSON | `reason=invalid_graph_artifact` |
| ES metadata failure | verified files remain successful; `es_indexed=false` |

## Evaluation plan

Evaluate on a sanitized fixture before the real corpus. The included tests prove
three cross-entry relationship paths around a shared OAuth recovery pattern.
Real-corpus promotion requires review, not automated acceptance.

Compare each candidate question against:

1. `memory_recall_es`;
2. narrative `memory_recall`;
3. `workflows/knowledge` retrieval;
4. `memory_graph_query`.

The graph must reveal at least three correct, non-obvious relationships and
explain the edges that produced each result. Useful categories:

- same root cause across differently worded incidents;
- idea -> implementation -> bug -> fix -> retrospective -> automation;
- repeated people/place/project clusters;
- missing references or isolated entries;
- highly connected events omitted from weekly summaries.

Reject relationships that are vague, unsupported, privacy-sensitive beyond the
approved boundary, or merely duplicates of ES keyword results.

## Promotion criteria

A weekly schedule may be proposed only after all are true:

1. three consecutive opt-in runs complete within the agreed runtime/cost budget;
2. sanitized evaluation has no false relationship presented as fact;
3. real-corpus review finds at least three useful relationships unavailable from
   current recall paths;
4. privacy exposure is explicitly accepted for the configured corpus slice;
5. artifact growth and retention are measured;
6. MCP results remain useful without depending on the HTML viewer;
7. the proposed Beat entry is separately reviewed with manifesto metadata.

Until then, this remains an on-demand evaluation capability.

## Tests

`workflows/hfl/tests/test_knowledge_graph.py` covers:

- deterministic DTO projection;
- sanitized multi-memory relationship traversal and date-level semantic provenance;
- strict low-limit, stable traversal ordering;
- disabled, missing-CLI, and empty-corpus behavior;
- corpus/output symlink rejection and no-follow staging;
- current CLI argv and explicit backend/model pinning;
- allowlisted environment behavior;
- timeout and nonzero exit without stderr persistence;
- failed rebuild preservation through immutable generations;
- missing artifacts after exit zero;
- strict graph schema, success-manifest, and checksum validation;
- actual nested `graphify-out` path resolution;
- ES failure isolation;
- exact dependency pin;
- latest verified graph MCP query behavior.

## Future work

Do not automatically graph the full dumps archive. Safer follow-ups are:

- deterministic orphan/provenance analysis;
- explicit temporal predecessor edges;
- bounded photo/place/people album candidates;
- cross-domain identity rules for HFL, code, GitHub, Jira/Confluence, media,
  locations, and recordings;
- measured retention after artifact size is known.
