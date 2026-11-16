---
name: design-agent-connector
description: Design and implement a provider connector, fleet agent, and related entities through interactive API or MCP exploration. Use when onboarding another agent source or extending its application, account, schedule, and child-object mappings.
---

# Design an agent connector

Explore the provider with the user, agree its entity mappings, then extend the
existing connector and fleet contracts. A connection is transport and identity;
an agent is an execution identity; a child entity is a separately identifiable
object. A visual association does not authorize execution or share credentials.

## Discover and agree

- Read the nearest adapter in `frontend/modules/integrations/`, the fleet graph
  in `frontend/modules/agents/ecosystem.py`, and the provider's actual API/MCP
  contract. Prefer an existing connected tool. Use bounded read-only calls to
  confirm response shapes and capabilities; do not infer endpoints from labels.
- Describe supported operations and unsupported/unknown capabilities separately.
  Never start a task, authenticate a new third-party account, or edit a remote
  schedule merely to explore the app.
- With the user, map each source object to an existing fleet kind, its stable ID,
  owner/installation namespace, display fields, relationship, and execution owner.
  Distinguish an application from each connected account and a schedule from its
  task executions. Reuse kinds before introducing a new one.
- Use `clarify-feature` for a new feature scope and `review-frontend-patterns`
  before proposing controls. Preserve scope already approved in the session.
- Record when discovery runs and one schedule owner. Nod, for example, owns its
  remote schedules; manual HARQIS discovery must not install a second scheduler.

## Implement the mapping

- Extend the provider adapter and encrypted connector store. Reuse credentials;
  keep tokens and source payloads out of graph metadata, logs, and browser output.
- Use `frontend/modules/agents/entities.py`: `entity` builds stable identities,
  `observe` adds relationships, and `reconcile` updates a complete source category
  without deleting prior observations. Scope external IDs by owner and provider
  installation; only use a global application key when its equivalence is proven.
- Link agents through independent relationships. Do not duplicate entities for
  every agent. Use separate account identities even when their labels match.
  Cross-provider matches require evidence or reviewed merges, never name matching.
- Preserve existing agent customizations when discovery reuses its agent identity.
- Use merge preview and explicit confirmation. The reversible overlay retains
  original identities and relationships, allowing refresh and unmerge without
  losing provenance. Do not silently merge HFL Corpus entities.
- Keep discovery failures distinct from empty successful snapshots. Preserve
  last-known entities, report stale/unsupported states, and bound response sizes.
- Reuse connector cards, versioned static assets, fleet entity controls, and
  relationship inspection. Label manual associations separately from discovered
  connections. Do not present association as a new permission grant.

## Verify and deliver

Test repeated discovery, multiple agents sharing applications, distinct accounts,
owner isolation, partial failures, removed objects, merge-refresh-unmerge, and
source changes. Use isolated stores and protocol doubles. Inspect the UI at
desktop and mobile widths, including search, selected values, and error states.

Report implemented mappings, verified capabilities, remaining limitations, and
whether the real saved connector was linked. Do not claim a live connection from
mock tests. Follow `run-tests` and the host environment bootstrap for local tests.

Reference adapter: `frontend/modules/integrations/nod_entities.py` maps Nod's
`/api/apps` connection IDs to account entities and `/api/schedules` IDs to schedule
entities. Its watch relationships come from explicit connection IDs.
