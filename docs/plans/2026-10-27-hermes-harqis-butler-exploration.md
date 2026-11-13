# Hermes / HARQIS Butler exploration

**Status:** design exploration, 2026-10-27; not an implementation or deployment
report. **Express output:** an owner-facing Butler that understands explicitly
supplied HARQIS context, performs bounded approved work, and returns verified
results linked to canonical records.

The subsequent [primary assistant implementation](2026-10-27-primary-hermes-assistant.md)
records the shipped code scope, owner gateway setup, transport limits and test
coverage. It does not turn this inspection snapshot into live deployment evidence.

This complements, rather than replaces, the [agent fleet and frontend Butler
plan](2026-10-26-agent-fleet.md). That branch already implements owner-facing
Butler messages through the existing action bridge/worker. The staged design
below identifies integration and verification work; it does not imply that the
branch has no Butler or that these additional controls are deployed.

## Evidence and scope

The runtime observations below are a read-only inspection snapshot supplied for
this exploration, not fresh deployment checks performed by this documentation
change. The inspection exercised health and unauthenticated page requests, not
an authenticated frontend action. No configuration changes, service restarts,
deployments, or production writes were performed for the exploration.

| Layer | Observation / boundary |
| --- | --- |
| CLI | Local macOS terminal backend, home-directory working directory, active `default` profile; observed model `gpt-6-astra` via the Codex provider. These are session observations, not required Butler settings. |
| Messaging | A separate launchd-supervised default Hermes gateway reported Telegram and Discord connected. A connected gateway is not proof that this CLI session belongs to that gateway. |
| Profile | The default profile root contained configuration, session state, memories, skills, and a gateway socket. Sharing a profile is not sharing a live conversation. |
| HARQIS | Loopback `:8081/health` returned HTTP 200 / healthy. Unauthenticated `/second-brain` redirected to `/login`; authenticated interaction was not tested. |
| Scoped inference | Separate `sharecorpus` on loopback `:8643` reported Hermes 0.21.7. Its sharing adapter uses scoped inference and cleans up generated sessions. This is not an owner-action endpoint. |
| Default API / browser | No listener on default `:8642` and no default-profile API-server configuration were observed. Browser-controller support was not configured in that profile. Installed API documentation does not establish an enabled endpoint. |

A historical gateway warning mentioned deprecated `MESSAGING_CWD` pointing to an
older workspace while `terminal.cwd` was `.`. Treat that as snapshot evidence of
an unresolved effective messaging directory, **not** an enduring configuration
recommendation. Verify the effective directory before allowing file operations.
A port number or a documented default alone does not identify a profile: the
Second Brain configuration reference also mentions `:8643`; that does not prove
it is the observed sharecorpus process or authorize reusing its credentials.

## Model, session, profile, runtime, workspace

- **Model/provider:** the inference service used by a turn. Changing it does not
  move files, attach a browser, or select a different operating-system process.
- **Session:** conversation history and associated execution identity. A saved
  transcript, a live turn, and an action/run record are related but distinct.
- **Profile:** configuration and state namespace. Typically `$HERMES_HOME`
  (default `~/.hermes`) contains `config.yaml`, `state.db`, `skills/`, `memories/`,
  and gateway/session state; named profiles have separate homes. Secrets stay
  there or in the configured credential store, never in this document.
- **Runtime:** the process executing tools: e.g. local CLI versus the supervised
  messaging gateway. Hermes source (often `~/.hermes/hermes-agent`) is code, not
  the profile's memory store. HARQIS's runtime checkout is likewise separate
  from its code-development checkout.
- **Workspace:** the effective filesystem directory for a task. A code checkout,
  deployed runtime checkout, and isolated Git worktree have different roles;
  profile selection does not by itself grant permission to modify any of them.
  Resolve a scoped workspace explicitly, never infer it from an old warning.

For repository conventions see [Hermes](../info/HERMES.md). Use placeholders such
as `<code-checkout>`, `<runtime-checkout>`, and `<task-worktree>` in designs rather
than embedding a personal home path. Documentation/development belongs in the
code checkout or an isolated worktree; deployed runtime files remain untouched
unless a separate deployment is authorized.

## Existing branch versus proposed integration

[`frontend/modules/agents/butler.py`](../../frontend/modules/agents/butler.py)
already accepts bounded `path`/`space` context, bounded conversation history and a
request ID, creates a canonical action, and enqueues it on the existing bridge.
It explicitly treats prior conversation as evidence rather than new authority.
The [fleet plan](2026-10-26-agent-fleet.md) records its validation and a live
provider/model failure; successful live inference was not established there.
Those historical results are not new tests of this exploration.

Do not replace that path with a second executor just to add chat. Extend its
session/run mapping and controls where appropriate. Typed record revisions,
concrete per-mutation approval, and same-tab control below are proposed contract
requirements, not claims about the current `path`/`space` payload.

```text
owner-only frontend panel
  -> authenticated HARQIS backend (authorization + context validation)
  -> existing action bridge / scoped Hermes session and allowlisted tools
  -> concrete mutation preview -> owner approval -> canonical API/MCP write
  -> exact-target read-back -> result links + redacted audit receipt
```

Gateway credentials remain server-side. Public/redeemed sharing routes must not
reach this authority plane. Keep the [share inference adapter](../../frontend/modules/hfl_shares/agent.py)
and `sharecorpus` service scoped; do not turn them into a privileged Butler.
The [Second Brain](../info/SECOND-BRAIN.md) remains advisory-only: Hermes may
propose context, while [Celery owns collection, persistence, retries and
reconciliation](../../workflows/second_brain/README.md). A feed item is not an
approval to execute an action.

## Three interaction modes

1. **Page context:** send a bounded, versioned envelope with route, typed entity /
   action / Space IDs, selected record revisions and allowed context fields.
   The backend resolves ownership and canonical records; client text, page
   content and prior answers are untrusted evidence, not executable instructions.
   Show context freshness and selected scope. Space membership organizes work;
   it is not a new authorization boundary.
2. **API/MCP actions:** prefer typed canonical APIs and allowlisted wrappers over
   clicks. Read evidence, propose an exact operation, obtain approval, execute,
   then read the target back. No arbitrary shell or import path from page data.
3. **Optional browser control:** distinguish an agent-owned browser from the
   owner's exact tab. The latter requires explicit opt-in to an authenticated
   controller/extension or narrowly scoped frontend command bridge. Verify tab,
   origin and controller identity; navigation/highlighting are separate from
   permission to submit changes. Disconnect/revocation disables further control.

## Continuity, controls and execution safety

Installed Hermes programmatic-integration documentation describes JSON-RPC
sessions, streaming and approvals, including multi-client attachment to a live
session within **one authenticated gateway**. This is not cross-process shared
session ownership. Attaching this exact CLI session to a frontend was unverified.
Shared profile memory, copied history, session resume and live attachment must
be labelled separately in the UI.

The installed API-server reference describes capabilities, runs, lifecycle
streams, approval, stop, steer and opt-in browser control. Discover the actual
endpoint's capabilities before enabling controls; do not advertise an endpoint
merely because it is documented. Transport selection (existing worker, HTTP/SSE
or JSON-RPC) remains an integration decision, not a deployment performed here.

Proposed UI states: `idle`, `queued`, `running`, `awaiting approval`, `stopping`,
`cancelled`, `interrupted`, `failed`, and `verified complete`. Distinguish a
transport response from verification of the business result.

- **Stop:** request cancellation and show pending acknowledgement. Do not imply
  rollback of a mutation already committed; reconcile the exact target first.
- **Steer:** send bounded guidance to an accepting live run at a tool boundary.
  Steering cannot expand permissions or substitute for approval.
- **Approve / deny:** bind a single-use, expiring approval to owner, action/run,
  operation, exact target, proposed payload and expected revision. A changed
  payload, target or revision invalidates it. Authorization is enforced by the
  backend/tool wrapper, not just a prompt or visible button.
- **Resume / reconnect:** recover canonical run state and pending approvals,
  clearly distinguishing transcript resume from live attachment. Never silently
  resubmit an interrupted write. Revalidate authority and inspect its outcome.

Authenticate all controls and event subscriptions; use CSRF protection for
cookie-authenticated mutations and least-privilege tool/session scopes. Default
to read-only. Serialize or reject competing writes and use optimistic revision
checks. Scope idempotency keys to owner + action + operation; persist the payload
binding and result so a retry cannot duplicate an external mutation. A message
or run creation key alone is not sufficient end-to-end mutation idempotency.

Read-back must match the approved target and expected effect. If a timeout leaves
an unknown outcome, report it as unknown and reconcile before retrying. Audit
records should connect owner, action/run/session IDs, approved operation,
revision, idempotency key and verification status; redact secrets and unnecessary
private context. Use existing receipts/outbox infrastructure and agree retention
before adding raw transcripts, screenshots or tool output.

A Butler is not continuously aware of the page or world: explicit page events,
messages and scheduled/event-triggered work supply observations. Stored history
or durable run metadata does not guarantee a running turn survives a restart.
Recovery requires explicit reconciliation; do not promise restart-proof runs.

## Phased acceptance gates

These are proposed gates for the exploration, not a claim that the branch's
existing fleet increment must be rebuilt.

| Phase | Bounded deliverable | Acceptance evidence required |
| --- | --- | --- |
| 1: read-only concierge | Owner-only panel on the existing bridge, explicit context and session/run mapping. | Unauthenticated and shared-route access denied; only scoped reads available; canonical evidence links and freshness shown; page changes/reconnect preserve the intended mapping without duplicate requests. |
| 2: one approved HFL-linked action | A single low-risk canonical action with preview, exact approval, revision checks, idempotency and read-back. | Denial/expired approval causes no write; stale revision and changed payload fail closed; duplicate/reconnect submissions produce one mutation; read-back matches; redacted action/run/HFL receipt recorded. |
| 3: opt-in same-tab navigation | Navigation/highlighting via a verified controller or frontend bridge. | Exact tab/origin verified; disconnect and revoke stop control; unrelated tabs inaccessible; navigation alone cannot authorize a write. |
| 4: proactive event-driven work | Read-only suggestions using existing scheduling ownership and persisted delivery state. | Triggers deduplicate; missed/replayed events and restarts reconcile visibly; notifications are opt-in; no duplicate scheduler or unapproved writes. |

Preserve Celery Beat's Second Brain schedule and Celery's deterministic work.
Fleet briefings already belong to the existing Hermes bridge sweep according to
the fleet plan; do not add a competing cron/Beat schedule. Proactive suggestions
must cross the same explicit approval boundary before any later mutation.

## Open decisions and verification gaps

- Choose the first low-risk HFL-linked operation and its concrete approval UI.
- Decide whether the existing worker is sufficient or needs a scoped transport
  adapter; choose the profile/tool allowlist without broadening public inference.
- Define frontend-to-action/run/session identity and concurrency policy. Prove
  exact CLI attachment only if it is needed; otherwise present a separate session.
- Select bounded page-context fields, revision sources and audit retention.
- Decide whether same-tab control is worth a controller at all; API-first remains
  the default. Verify tab identity and disconnect semantics before enabling it.
- Test authenticated frontend interaction, supported model/provider inference,
  endpoint capabilities and restart/retry recovery in a separately authorized
  environment. None was established by the runtime snapshot above.

## References and validation scope

- [Existing fleet design and validation](2026-10-26-agent-fleet.md).
- [Hermes programmatic integration](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration).
- [Hermes API server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server).
- Installed reference paths: `<hermes-source>/website/docs/developer-guide/programmatic-integration.md`
  and `<hermes-source>/website/docs/user-guide/features/api-server.md`. Installed
  and live documentation can evolve independently; verify the running version's
  contract rather than treating either as enabled deployment configuration.

This documentation change validates Markdown links, whitespace and consistency
with the cited branch sources. It does not validate the proposed runtime gates,
modify the Second Brain authority model, or certify a deployment.
