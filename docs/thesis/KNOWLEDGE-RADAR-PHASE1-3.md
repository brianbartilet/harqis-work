# Knowledge Radar — Phase 1 + Phase 3 POC

> RAG answers questions when you ask. **Knowledge Radar tells you what you
> should know before you ask** — and how the pieces connect.

This is the implemented POC of two phases from the knowledge-workflow roadmap,
built for the use case of working inside a large organization (e.g. a bank) with
many services owned by different teams, where the hard part is not *finding a
doc* but *understanding integrations, dependencies, ownership, and business
value across teams* — and connecting all of that to what you're working on right
now.

It extends the existing single-store RAG pipeline
([`RAG-WORKFLOW.md`](RAG-WORKFLOW.md)); it does not replace it.

## Phase 1 — useful MVP (Confluence + a stable embedder)

| Goal | What was built |
| --- | --- |
| Confluence ingest for selected spaces | `apps/confluence` (Cloud + Server/DC) + `tasks/ingest_confluence.py` |
| Incremental sync | skip-by-`version.number`; only changed/new pages re-embed (`store.get_meta_by_source`) |
| Stable embedding provider | `embed.py` — provider/model env-driven; Gemini default bumped to `gemini-embedding-001`; the 4 copy-pasted `_embed_batch` helpers DRYed into one |
| Citation-first answers | unchanged `knowledge_ask` / `answer.py` |
| Watchlist YAML | `watchlists.yaml` + `watchlist.py` + `tasks/topic_scan.py` (hit cards with *why-relevant*) |

Confluence page bodies arrive as storage-format XHTML;
`chunking.strip_confluence_storage()` flattens them (stdlib only, no new dep).
Each chunk carries `space`, `version`, `labels`, `breadcrumb`, and the page URL
so retrieval stays auditable.

## Phase 3 — cross-source second brain

The interesting layer. All of it is **grounded** (every finding carries source
refs) and combines two link signals: **deterministic entities** (Jira keys,
service names, PR refs — `entities.py`) for the hard links, and **embeddings**
for the fuzzy ones.

| Capability | Function | Question it answers |
| --- | --- | --- |
| Working context | `cross_link.working_context()` | "From my recent HFL/git activity, what am I working on and which docs/tickets/PRs connect to it?" |
| Relations graph | `cross_link.relations()` | "How does this topic connect across teams?" — nodes per source, edges on shared entities |
| Orphan tickets | `cross_link.orphan_jira()` | "Which Jira issues have no matching doc?" (knowledge gaps) |
| Stale docs | `cross_link.stale_docs()` | "Which docs match already-shipped (merged/closed) code?" — review for drift |
| Topic map | `tasks/topic_map.py` | "Teach me this topic: definition, integrations, dependencies, business value, related items, what to learn next" |

`topic_map` is the learner-facing surface the request asked for — it turns
retrieval into a structured, cited onboarding brief whose sections are exactly
*integrations & dependencies* and *business case & value*.

## How the link signals combine

```
            ┌─────────────── deterministic (entities.py) ───────────────┐
text  ──▶   JIRA keys · PR refs · service names · acronyms · URLs        │  hard links
            └────────────────────────────────────────────────────────────┘
            ┌─────────────── semantic (embed + sqlite_vec KNN) ──────────┐
query ──▶   cosine similarity over RETRIEVAL_QUERY/DOCUMENT vectors       │  fuzzy links
            └────────────────────────────────────────────────────────────┘
```

`relations()` draws an edge between two retrieved chunks from **different
sources** when they share a namespaced entity (`jira:PAY-1421`, `svc:Payments`).
That is the cross-team "these are about the same thing" signal that pure vector
similarity misses for IDs/acronyms.

## Surfaces

- **MCP**: `knowledge_topic_map`, `knowledge_relations`,
  `knowledge_working_context`, `knowledge_orphan_tickets`,
  `knowledge_stale_docs`, `knowledge_scan_watchlist`, `knowledge_list_sources`
  (+ `confluence_*`).
- **Beat** (shipped disabled): `ingest_confluence_pages` nightly;
  `knowledge_cross_link_report` weekday mornings (working-context + orphans +
  stale, ES-logged).

## What's deliberately NOT in this POC

- Telegram/email digest delivery (Phase 2 Express) — `topic_scan` returns the
  cards; wiring them to a channel is a follow-up.
- Permission/ACL propagation into the store — chunks are space-scoped via
  `source`/`meta` but not ACL-filtered. Flagged for the productionization phase.
- A persisted knowledge graph (Phase 4) — `relations()` computes the graph on
  demand rather than materializing it.

## Operational gate

Embeddings must be funded (or `HARQIS_KNOWLEDGE_EMBED_PROVIDER` pointed
elsewhere) and `CONFLUENCE_*` set in the gitignored `.env/apps.env`. The code
path is complete and unit-tested offline; live ingest needs those two inputs.
