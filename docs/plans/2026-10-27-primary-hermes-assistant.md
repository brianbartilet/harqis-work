# Primary Hermes frontend assistant

## Approved implementation scope

The owner approved the recommendation to evolve Butler into the primary Hermes
frontend interface. This increment adds primary fleet selection, separate persistent
frontend conversations, canonical page context, streamed answer text, stop/steer
controls and one exact approved operation: create an HFL action for later review.

Runtime classification: agent-owned interactive inference with deterministic HARQIS
authorization and persistence. Manual chat has no scheduler. Existing action bridge
workers own task execution; existing bridge sweep owns briefings; Celery retains
its existing collection/reconciliation schedules.

## Existing patterns reused

- `frontend/templates/base.html`, `static/js/butler.js`, `static/css/butler.css`:
  global panel, CSRF, focus styles, responsive sizing and cache-versioned assets.
- `frontend/src/agent-fleet.jsx`: inspector actions and optimistic version handling
  for the per-owner primary-agent preference. Existing agent IDs are preserved.
- `workflows/hfl/agent_fleet_store.py`: SQLite persistence and audit outbox.
- `frontend/modules/integrations/service.py`: canonical action creation/read-back.
- `frontend/modules/hfl_corpus/action_agents.py`: action-agent assignment; new
  actions have execution disabled and open in the existing action/task UI.

## Owner gateway setup (deployment prerequisite)

This change does not enable/restart gateways, modify a personal Hermes profile,
or deploy HARQIS. Configure these server-only environment variables:

```dotenv
HARQIS_HERMES_URL=http://127.0.0.1:8642
HARQIS_HERMES_API_KEY=<owner-gateway-key>
HARQIS_HERMES_TOOL_POLICY=no-tools-no-mcp
```

The URL is the gateway root, without `/v1`. Remote endpoints require HTTPS;
loopback HTTP is supported. Do not use the public sharing gateway or its key.

**The policy variable is an operator assertion, not a runtime sandbox.** Before
setting it, configure the gateway's API platform with no execution toolsets and
no implicit MCP servers. Current Hermes supports this configuration:

```yaml
platform_toolsets:
  api_server: [no_mcp]
```

Verify the installed version's effective toolset resolution is empty, including
plugins/context-engine tools. For a custom context engine that adds tools despite
this selection, use a tool-free owner API profile or disable that engine on this
surface. Do not weaken the policy gate. This is independent of tool settings for
Telegram/Discord/CLI; a shared profile does not mean a shared live conversation.

The adapter also checks `/v1/toolsets` before every submission and rejects any
enabled toolset. Current upstream discovery omits implicit default MCP servers,
so discovery alone cannot prove a tool-free runtime. Deployment policy is required
in addition to discovery; changes to the gateway configuration must preserve it.

Required capabilities: run submission/status and durable `runs_idempotency` with
at least one hour of retention. Streaming, stop and steer controls appear only
when advertised. Errors show no credentials or upstream exception bodies.

Select an active Hermes agent in Express > Second Brain and choose **Make primary
assistant**. Open Butler, then **New**. A conversation freezes the fleet identity,
persona and instructions. The connected gateway supplies its provider/model;
worker-specific overrides, shell skills and tool lists apply to action execution,
not tool-free chat. No assumption is made that a gateway endpoint represents a
particular local profile. Its host is displayed; profile identity must be verified
at deployment.

## Contracts and recovery

- HARQIS mints session IDs and binds conversations to owner, fleet version and a
  private endpoint/credential fingerprint. Clients cannot select arbitrary Hermes
  session IDs. Endpoint/key rotation blocks reuse; saved local answers remain
  readable. Restore the connection to reconcile outstanding work.
- One outstanding turn per conversation. Requests persist their exact payload
  before admission. Retries reuse the same durable Hermes admission key; after
  one hour an unknown admission requires operator reconciliation, never blind
  resubmission. Completed turns persist locally across frontend navigation/restart.
- Page context v1 accepts a route and optional action ID/revision. The backend
  fetches a bounded canonical action projection. Browser text, supplied URLs and
  arbitrary context fields are rejected. Space/entity retrieval is not yet added.
- SSE forwards answer deltas only; reasoning, tool payloads and raw upstream errors
  are omitted. Polling reconciles final state. Stop is acknowledged as `stopping`
  until Hermes confirms the terminal result; it never promises rollback.
- API sessions are separate from CLI/Desktop/messaging sessions. No cross-process
  attachment, proactive page surveillance or browser control is implemented.
- **Preview action** uses a completed response, editable title/outcome, and the
  original request as the task prompt. A ten-minute immutable preview requires
  explicit approval. The UI shows all persisted business fields and that execution
  is disabled. Source revisions are checked before approval. Creating a record has
  no pre-existing target revision; read-back verifies its exact newly minted ID.
- Approval is owner-scoped and persisted before the canonical write. A fixed
  request ID and payload permit safe creation reconciliation after timeout/crash.
  Denied/expired/stale previews cannot write. After submission, reconcile instead
  of denying/replaying under a new identity. Read-back mismatch is reported without
  creating another action. Audit receipts use the existing HFL outbox.
- Local conversation storage retains bounded user messages, answers, canonical
  context snapshots and admission payloads in the fleet DB, matching the existing
  persisted Butler-history behavior. No raw tool output, screenshots or private
  reasoning is captured. Gateway transcript retention is managed by Hermes;
  this implementation does not promise automatic transcript deletion or expiry.

## Compatibility and remaining stages

Legacy `/agents/api/butler` and briefing jobs continue using the existing worker;
this increment does not reinterpret their historical runs or scheduled policy.
External Grok Bot/n8n discovery remains separate from Hermes execution. The new
assistant saves work into the existing action flow rather than directly executing
external agents. Exact browser-tab control and proactive suggestions remain
optional later stages, as agreed in the recommendation.

Tests cover owner/CSRF boundaries, selection versions, tool-policy denial, context
revisions, session continuity, conflicting messages, durable admission retries,
connection rotation, streaming redaction, stop/steer, denied/expired/stale approvals,
single-use canonical creation and lost-response reconciliation. Browser checks
exercise the panel and preview flow at desktop and mobile sizes. These use a
contract fixture for Hermes; they are not evidence of live inference or deployment.

Upstream contracts checked during implementation:
- https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server
- https://github.com/NousResearch/hermes-agent/blob/main/gateway/platforms/api_server.py
- https://github.com/NousResearch/hermes-agent/blob/main/gateway/platforms/api_server_runs.py
- https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/tools_config.py
