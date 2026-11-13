# Agent gateway connections

The Agents fleet can connect each Hermes profile to its own Hermes Runs API.
Connections belong to the signed-in owner; the same fleet profile does not expose
another owner's gateway credentials or conversations. Nod supports connection
setup and authenticated health checks; its conversations and tasks remain in Nod.

## Configure from Add agent or Edit

1. Select **Hermes** as the agent service.
2. Under **Connection**, choose **Connected Hermes gateway**.
3. Enter the gateway origin and API key. The HARQIS server must be able to reach
   that address. Use HTTPS, or HTTP on `localhost`, `127.0.0.1`, or `::1`.
   Paths, query strings, fragments, and credentials embedded in URLs are rejected.
4. Choose **Chat only** or **Chat and task execution**.
5. Select **Test connection**, then **Save agent**. Saving verifies the connection
   again. Testing only probes capabilities; it never submits a task.

Chat-only gateways must have no enabled API-platform toolsets and must configure
`platform_toolsets.api_server: [no_mcp]`. Confirm that deployment configuration in
the editor. HARQIS also checks `/v1/toolsets`; an empty per-request tools list is
not treated as a security boundary.

Task-execution mode uses the gateway's configured tools and permissions. Sending
with **Run task** authorizes that submitted task. The gateway owns tool execution
and any additional approvals. A waiting approval is shown in the conversation;
review it in the gateway. HARQIS does not fabricate an approval API.

The adapter uses the configured gateway's agent and creates separate remote
sessions; it does not discover or select remote agent/profile identifiers. Use a
separate gateway endpoint for a separately configured remote runtime.

## Interact in the fleet

Select the agent and open **Conversation**. Check connection health, start a new
conversation, select earlier conversations, and expand the panel when needed.
Responses stream when supported; status polling remains available. **Stop** and
**Steer** appear only when the gateway advertises them. Connection failures retain
history. An ambiguous submission is retried with the same request ID to avoid a
duplicate run; it is not automatically submitted as a new task.

Gateway messages include the configured persona/instructions and the message you
send. They do not automatically include the wider Second Brain activity corpus,
local skill bodies, or action-bridge execution overrides. Local **Open session**
continues to use the existing action bridge. The global Butler chat retains its
separate read-only policy and conversation list.

## Credentials and connection changes

Connection secrets are encrypted using the existing connector key derivation
(`HARQIS_CONNECTORS_KEY`, falling back to `APP_SECRET_KEY`) and stored in
`fleet_connections` in the agent database. They are never included in agent
profiles, graph responses, audit events, or read responses. Leave the API key
blank while editing to retain the saved key for the same address. A different
address requires entering a key again.

Saving a changed connection binds future conversations to a new configuration
version. Existing conversations remain readable but cannot send or control runs
through that replacement connection. Reconcile old runs on their original
gateway. Switching to **Existing action bridge** removes the saved gateway key
and disables new gateway work; it does not stop already running remote tasks.

The UI reports a profile-save/connection-save partial failure explicitly. Retry
updates the already created profile rather than creating a duplicate. Reopen the
editor if another tab changed the connection version.

## Required gateway contract

The first adapter reuses `frontend/modules/agents/hermes_gateway.py`:

- `GET /v1/capabilities` must advertise run submission and status plus durable
  idempotent admission with at least one hour of retention.
- `POST /v1/runs` accepts a session ID, instructions and input. HARQIS supplies
  an idempotency key and an owner-created session key.
- `GET /v1/runs/{id}` supplies status and output.
- Events, stop and steer endpoints are used only when advertised.

No scheduler is added. Request submission is owned by the fleet conversation;
execution remains owned by the selected gateway. A new provider adapter must
establish its authentication, session ownership, replay and capability contracts
before enabling execution.

## Nod on a Mac host (connection scaffold)

Install Nod separately using its [Mac host guide](https://nod.n8n.io/docs/deploy/mac-mini/)
and [self-host instructions](https://nod.n8n.io/docs/deploy/self-host/). Complete
onboarding in Nod and connect a model there. HARQIS does not install or start Nod.

In **Add agent → Agent service → Nod**, choose **Self-hosted Nod server** and
supply its origin plus `NOD_AUTH_TOKEN`. Test, then save. The inspector provides
**Check connection**, **Configure Nod**, and **Open Nod**. Opening Nod uses its
own login; HARQIS never places the stored token in a browser URL.

The address must be reachable from the HARQIS backend. For a loopback deployment,
run `ssh -N -L 4310:127.0.0.1:4310 <user>@<mac-host>` on the machine running HARQIS,
then use `http://localhost:4310`. Keep the tunnel alive. If HARQIS and Nod are on
the Mac, use the local published port directly. A browser on another machine
needs its own tunnel to open that same loopback URL, or use a shared HTTPS origin
configured as Nod's `NOD_PUBLIC_URL`. Never point a remote client at its own
localhost expecting it to reach the Mac automatically.

The scaffold calls only authenticated `GET /api/health`, expecting `{"ok":true}`.
It uses bearer authentication, bounded timeouts, TLS verification, and no
redirects. This is based on Nod's [access implementation](https://github.com/n8n-io/nod/blob/main/src/server/access.ts)
and [server routes](https://github.com/n8n-io/nod/blob/main/src/server/app.ts),
reviewed on 2026-11-12. These internal endpoints may change; health success does
not establish compatibility with future chat APIs.

Only health is enabled. Sending messages, starting or stopping tasks, importing
results, streaming events, and scheduling are deliberately unavailable through
HARQIS. The backend rejects Nod conversation creation even if called directly.
Before enabling those operations, implement the Nod thread/session ownership,
idempotent submission, event filtering, approval and cancellation contracts.
Multiple profiles pointing to one Nod server represent the same remote owner
assistant; they do not create independent Nod agents. Choose **Profile only** to
remove the stored token without stopping the remote server.


## Scheduled briefings

Open the shared HARQIS Butler panel and select **Briefings** to read scheduled
worker results. **Conversations** continues to show gateway sessions. Use the
calendar button in the panel header to configure the briefing schedule.

The existing Hermes sweep remains the schedule owner. Each occurrence is recorded
once per user and local schedule date in `fleet_briefing_deliveries`, in the fleet
database. The feed joins that occurrence to its legacy worker run and displays
pending, running, completed or failed status. Pending and running results refresh
automatically while the tab is open. A completed briefing means the worker has
returned its answer; displaying it does not accept the underlying action.

Existing scheduled results are recovered only when both the exact scheduler prompt
and the deterministic user/date request ID match. Ordinary legacy messages are not
included. The new table is created automatically; include the fleet and bridge
databases in existing backups.

When `HFL_TIMELINE_LOCAL_PREVIEW=1`, the tab offers **Load sample briefings**.
These owner-scoped, explicitly marked mock cards cover all four states, never
submit worker jobs, and do not change the schedule. They are hidden outside local
preview, and the sample-creation endpoint rejects non-preview requests.
