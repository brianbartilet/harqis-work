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

## Expose the agent's entry points in Fleet

- Include a usable entry point in the selected agent's inspector toolbar, not
  only a connector-management link. Discover whether the provider offers a web
  interface, an interactive CLI, or both; expose the supported options. When
  neither is available, explain the limitation rather than inventing execution.
- For a web interface, use the saved connector's validated HTTP(S) URL. Add an
  **Open <provider> in new window** icon with a tooltip and accessible label;
  isolate the opened window from its opener and retain a normal link fallback.
  Never place credentials in the URL. Keep **Manage connector** as a separate
  control. Reuse `OpenNod` in `frontend/src/nod-conversation.jsx` as the pattern.
- For a CLI, add **Open session** using the existing Fleet prepare endpoint and
  action-linked terminal dialog, as Codex/Claude do in
  `frontend/modules/agents/service.py` and `frontend/src/agent-fleet.jsx`.
  Resolve the selected agent's runtime and execution host from live worker
  capabilities; preserve owner/installation boundaries and reuse its Sessions
  action and live session. Do not silently switch providers or hosts. Check
  executable discovery and authentication in the background worker environment,
  including standard install locations absent from an interactive shell's PATH.
- Opening a CLI must not submit the saved Action prompt or enable unsupported
  automated execution. Keep the CLI in the existing dialog unless the user
  explicitly requests another presentation. Report missing worker/auth setup
  with an actionable reason; disable execution for inactive or mock agents.
- In Conversation tabs, group interface, refresh and connector controls into a
  compact toolbar with consistent button styling. Use existing Fleet icons,
  tooltips and keyboard focus behavior; keep labels on secondary actions where
  they aid recognition. Preserve available connector/settings controls.

## Verify and deliver

Test repeated discovery, multiple agents sharing applications, distinct accounts,
owner isolation, partial failures, removed objects, merge-refresh-unmerge, and
source changes. Use isolated stores and protocol doubles. Inspect the UI at
desktop and mobile widths, including search, selected values, and error states.
Verify inspector entry points as well: web links open the correct installation
with an isolated opener; CLI controls select the correct runtime/host and reuse
the live session. Cover unavailable workers, inactive/private agents, repeated
clicks, and narrow-screen toolbar layout. Build changed frontend bundles using
the repository's asset tooling and retain only intended generated changes.

Report implemented mappings, verified capabilities, remaining limitations, and
whether the real saved connector was linked. Do not claim a live connection from
mock tests. Follow `run-tests` and the host environment bootstrap for local tests.

Reference adapter: `frontend/modules/integrations/nod_entities.py` maps Nod's
`/api/apps` connection IDs to account entities and `/api/schedules` IDs to schedule
entities. Its watch relationships come from explicit connection IDs.
