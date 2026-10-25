# Agent fleet and frontend butler

Source action: `item-cf8aea45afb448eaa3db00561d6aaf34`. The owner approved the
recommended scope on 2026-10-26 after review of the complete action and five
attached screenshots.

## Approved scope

Hermes is the execution runtime. OpenAI, Google Gemini and Anthropic Claude are
model providers, not separate native terminal implementations. The first
increment includes fleet definitions, graph relationships, thumbnails, skills,
existing workflow/trigger links, action assignment, sessions, activity receipts,
n8n discovery and a frontend butler. Vector-store administration, cross-session
memory controls, spend enforcement and automatic model routing are deferred.
Sub-agent links describe relationships; they do not silently launch children.

The butler performs writes/development on explicit requests. Optional automatic
briefings are read-only, disabled by default and configured separately.

## Runtime decision

- Classification: **hybrid**, high confidence.
- Agent execution owner: the existing Hermes action bridge and worker.
- Durable execution owner: existing canonical APIs and Celery workflows. Linking
  an existing task does not create a new task or a second schedule.
- Briefing schedule owner: **Hermes bridge sweep** (the existing dispatcher), with
  a persisted timezone/hour/cadence definition. The watch worker consumes work;
  the existing `--dispatch`/sweep schedule must also be running to discover
  briefings. No new Beat entry or machine-local cron is installed.
- n8n owns its own workflows, agents, triggers and execution. HARQIS owns local
  presentation, Space membership and visibility overrides.
- Controls: revision checks, request IDs, frozen agent/skill hashes, existing
  session leases and concurrency, credential separation, existing execution
  modes and isolated development checkouts.
- Review artifacts: action/run/session history, attached outputs, fleet audit
  receipts and `agents-activity` HFL entries.

## Persistence and compatibility

`HARQIS_AGENTS_DB` defaults to `agents.sqlite3` beside `PROFILE_STORE_PATH`.
It holds versioned definitions, content-addressed PNG/GIF/Markdown assets, an
audit outbox, butler message/run links and briefing settings. Include it in
backups. The bridge database retains executable snapshots, native terminals,
leases and artifacts. Frontend instances that share a fleet must use the same
fleet and bridge storage; there is no cross-host registry replication in this
increment.

Default and Butler definitions are seeded idempotently on fleet initialization.
Legacy presets are imported once under stable IDs. Existing action overrides
and legacy preset inheritance remain valid. Selecting a fleet agent replaces
the legacy preset layer; action overrides still win. Editing or deactivating an
agent prevents new execution with that current definition but does not rewrite
an already-created run/session snapshot. Existing sessions and queued snapshots
retain their original execution authority. Deactivation is not cancellation.

App Settings links to Build → Agents; shared execution defaults move into the
fleet workspace. Its existing backend settings endpoint remains compatible.

## Interface and integrations

The fleet uses the existing React force-graph dependency and graph motion
functions, authenticated asset delivery and the shared color palette. DOM image
orbs preserve animated GIF playback. The inspector exposes linked capabilities,
Spaces, sessions and audit receipts. Reduced motion suppresses graph animation.
Space selection uses existing Space IDs and checkbox/search semantics.

Action configuration selects a registry agent. Each execution receives its
persona, instructions, selected skill contents/hashes, toolset names and linked
capabilities. Toolset availability and model authentication remain worker-owned;
free-form model IDs allow models supported by that worker without a stale
hard-coded model catalogue. Workflow links are references to registered tasks,
not arbitrary Python import paths or automatic dispatch instructions.

Active local fleet definitions appear as `agents` graph nodes and in board
attachment search. They are operational identities, not corpus extraction or
entity-merge candidates. Space filters are organizational rather than new
authorization boundaries. Per-user n8n agents remain in that user's fleet view
and are excluded from the shared owner board catalogue.

Butler chat is available across authenticated frontend pages. Each explicit
message creates an idempotent action run with page/Space context, the module
catalogue and bounded prior conversation. Answers are rendered as text; artifacts
remain attached to the action. A repeated message ID cannot change its body.
Scheduled briefings use a stable user/day key and skip missed days. Failure to
deliver HFL receipts retains the durable outbox; preview mode does not deliver
them to the production corpus.

## n8n connection contract

The connector stores a REST API key and an optional, separate MCP token in the
existing encrypted per-user connector store. It tests connectivity before save
or enable, strips credentials from responses and disables redirects/proxies.
Use HTTPS origins; HTTP is accepted only for loopback development instances.

- REST `/api/v1/workflows` supplies a paginated workflow browser.
- MCP `/mcp-server/http` performs initialization, tool discovery and
  `search_agents` (up to 100 results per query).
- `get_agent` refreshes the selected agent's named skills, tools, tasks and
  instructions. Local thumbnails, names, colors and Spaces survive refresh.
- Unsupported tools, missing MCP access or token failure produce actionable
  errors. First-class agents are not inferred from workflow AI Agent nodes.
- Remote execution configuration stays in n8n, reached through Open in n8n.

References verified during implementation:

- https://docs.n8n.io/connect/connect-to-n8n-mcp-server/mcp-client-examples.md
- https://raw.githubusercontent.com/n8n-io/n8n-docs/main/docs/connect/connect-to-n8n-mcp-server/mcp-server-tools-reference.md
- https://raw.githubusercontent.com/n8n-io/n8n/master/packages/cli/src/public-api/v1/openapi.yml

The first-class Agent API is a preview capability and must be available on the
connected instance. Contract tests use deterministic REST/MCP doubles; an
authenticated live n8n agent-discovery test requires a configured connector.

## Validation

`frontend/tests/test_agent_fleet.py` exercises migration, optimistic concurrency,
inactive agents, frozen sessions, skill snapshots, asset validation, CSRF,
Space/connector isolation, repeatable session preparation, butler idempotency,
briefing occurrence keys, MCP negotiation and desktop/mobile interaction.
Relevant existing action, connector, graph and Space suites are also run.

Validation on 2026-10-26: the focused fleet and migrated settings checks pass
(21 tests), including desktop/mobile browser interaction and screenshot review.
The broader six-module run passed 138 tests; its two settings assertions were
updated for the new location and pass in the focused run. Three remaining
browser failures reproduce unchanged on base commit `eca875da`: the native
workspace attachment-order assertion and two connector Link-button cases.
The graph bundles build successfully and `git diff --check` passes.

The local authenticated worker readiness check passes. A live read-only Butler
request reached the worker and recorded its failure correctly, but the machine's
configured `github-copilot` / `gpt-5.3-codex` combination returned HTTP 400
(model unavailable for the configured integrator). Successful live inference
remains unverified; select a model supported by the configured provider before
retrying. No global worker/provider settings were changed.

Local preview uses separate mutable frontend stores and a separate loopback
server/worker. The worker still uses the machine's configured Hermes account and
tools. Optional briefings remain off until configured. Advanced screenshot
features listed above are not presented as working controls.
