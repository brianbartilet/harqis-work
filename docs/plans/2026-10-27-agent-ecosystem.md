# Agent ecosystem control panel

## Agreed scope

Build the graph, local mock ecosystem and existing recorded outputs. Live Mac
Hermes/Telegram ingestion is a follow-up, as selected by the owner. This extends
the existing primary-assistant increment on `feat/agent-fleet-workspace`.

## Runtime decision

- Classification: **hybrid**, high confidence. Agents perform interactive/adaptive
  work; existing Celery tasks retain deterministic collection and delivery.
- Execution owner: authenticated HARQIS projections for the graph; existing
  Hermes action bridge for execution; existing connectors for provider discovery.
- Schedule owner for this increment: **manual**. Graph refresh only reads records.
  Existing Celery Beat and Hermes schedules are unchanged; no duplicate initiator.
- Celery operations added: none. `create-new-workflow` informs provenance and
  runtime boundaries; this is not a new workflow scaffold.
- Controls: owner authentication/CSRF, per-owner observations, stable source/object
  identities, bounded summaries, safe links, producer/parent binding, isolated
  mock data and disabled execution for mock agents.
- Review artifact: agent graph, output inspector, mock preview and browser tests.

## Behavior

Agent services include Hermes, Codex, Claude, ChatGPT, n8n, Grok Bot and a generic
service category. Classifications are coding, general purpose and workflows.
Display name, description, avatar and color remain independently editable. The
existing Butler seed becomes HARQIS Butler with gold coloring; customized names
and colors are preserved. The global chat pill and header use HARQIS Butler.

Manual external profiles represent identities, not working API connections.
Execution settings for discovered providers remain provider-managed. Build >
Integrations remains the account connection surface. Mock profiles cannot execute
or become the primary assistant.

The shared `HflWorkspacePicker` supplies the same checkbox selection, color dots,
apply-on-close and Escape/outside-click behavior as Corpus/Kanban. Graph objects
support text, service, type, Space, date and mock/deactivated filters. Matching
outputs retain their agent anchors. Undated configuration is excluded by date
filters; agent creation dates do not hide agents whose outputs match the dates.

Canvas nodes support pointer dragging, neighboring-node motion through the existing
`graph-drag.mjs` helpers, animations and per-owner browser-local positions. The
keyboard-accessible agent list and output buttons provide parallel navigation.
Orb radius uses the shared Activity Graph logarithmic formula based on visible
connections after filtering. Entry dots retain the Activity Graph fixed leaf size;
other objects, including agent and subagent orbs, grow with their connection count.
Recent activity counters remain metadata, not sizing inputs or provider health.

## Sources and provenance

The graph reads:

- configured skills, tools, workflows, triggers and persistent subagent links;
- action-bridge run summaries, artifact metadata and evidence links;
- actions created through exact assistant approval;
- existing local Second Brain feed records and the HUD catalogue;
- owner-scoped observations submitted to `/agents/api/observations`.

Solid relationships distinguish produced/configured/delegated/returned work.
Dashed **monitors** relationships link Second Brain feed/HUD objects to Butler
without claiming Butler authored deterministic Celery results.

An observation carries a stable `source` + `id`, agent ID, kind, label, bounded
summary, timestamp, optional canonical URL and Spaces. Repeated reports update the
same object, while changes to producer/parent/type are rejected. A `subagent`
observation represents a temporary delegation; an artifact's `delegation_id`
links it to that observation and must report to the same parent agent. Arbitrary
canonical object kinds can be added to the typed projection as adapters mature.
The ingestion endpoint does not execute tools, read local files or fetch URLs.

On the Agents page, live Butler chat receives a bounded selection of recent
recorded outputs. Mock data is excluded. This does not grant continuous awareness
or import every remote Celery/Mac/Telegram event. Existing workflow producers can
later report correlated completion observations through an authenticated adapter.

## Local testing

`POST /agents/api/demo` is restricted to `HFL_TIMELINE_LOCAL_PREVIEW=1`, requires
owner CSRF and seeds stable per-owner mock identities. Repeating it preserves edits
and does not duplicate outputs. The local fleet preview's databases remain under
ignored `results/fleet-preview`; no production corpus records are created.

Seed data: Ada (Codex senior developer), Leo (Claude junior developer), Sage
(ChatGPT researcher), Atlas (n8n operations), Nova (Grok workflows), Iris (Hermes
researcher), temporary Milo/Scout subagents, and twenty connected sample objects.
Mac schedules, Telegram messages and Celery completions in this scenario are
explicit simulations. **Show mock data** hides them; **Load mock ecosystem** makes
the scenario reproducible in an isolated preview.

Primary files: `modules/agents/ecosystem.py`, fleet service/projection/router,
`src/agent-fleet.jsx`, `src/fleet-graph.mjs`, fleet/Butler styles and templates, and
`workflows/hfl/agent_fleet_store.py` for additive observation storage.

No new dependency, secret, external message, Beat entry or live ingestion job is
introduced. Unit/API and desktop/mobile browser checks cover provenance, mock
isolation, connector classifications, graph filtering and workspace interactions.
