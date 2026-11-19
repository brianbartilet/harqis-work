# Action execution and Butler delegation

## Contract

Actions support Hermes and connected Nod Fleet agents. Assignment saves intent;
execution requires an explicit Initial prompt and a Ready transition, Run now,
an authenticated trigger request, or an enabled schedule. Unsupported providers
remain assignment-only. Existing disabled Actions are never automatically enabled.

Queued Actions remain Ready (or retain their existing status for a manual run).
Provider acceptance moves them to In Progress. Evidence-backed completion moves
them to Done; failure, partial results, or required input moves them to Incomplete.
Provider submission success is not completion. User edits and closed statuses win
over late results through canonical optimistic revisions.

## Runtime decision

Classification: **hybrid**, high confidence. Hermes/Nod own adaptive execution;
Butler owns delegation and review. Celery owns deterministic dispatch/reconciliation.
Celery Beat is the single Action discovery owner, running the host-queue task
`workflows.hfl.tasks.action_execution.reconcile_action_executions` every minute.
The existing Hermes dispatcher continues pins and briefings, but no longer discovers
Actions. Run history, instruction hashes, provider receipts, and parent/child IDs
are the review artifacts. Existing HFL agent bridge URL/token configure the task.

Schedules specify an interval of 1 minute to 7 days. Each due occurrence has a
stable key and can request only a Ready, enabled Action. Closed or Incomplete
Actions are not silently reopened. Missed occurrences are coalesced to one current
request rather than replaying a backlog. Disabling a schedule restores ordinary
Ready-trigger discovery; disabling agent execution disables automatic work.

## Provider receipts

`ActionExecutionStore` extends the canonical bridge database with receipts,
installation slots, reconciliation locks, and schedules. No database moves or
destructive migrations are required. Nod uses a deterministic client message ID
per attempt, and stores the thread/message/turn receipt before tracking results.
An uncertain send is never automatically resent. Recovery searches for that exact
message and turn; missing history or a reset conversation remains unresolved.
For an unaccepted submission with no turn receipt, the owner can record explicit
provider verification in Agent results and release the slot. Recovery refuses
when a matching message or active provider work is still visible, and retains
the owner's evidence in execution history.

Only one Action uses a Nod installation at a time, including connections owned
by different users. Busy shared conversations wait. Fleet's regular composer
cannot submit competing work while an Action owns the conversation; explicit
approval replies remain available. Direct use of Nod outside HARQIS can still
introduce activity, so reconciliation always correlates the exact turn.

Nod approvals/private input remain provider-owned. HARQIS reports Incomplete and
resumes when provider state confirms the interaction is resolved, provided the
owner has not changed the Action. Cancellation is local: it never calls Nod's
thread-wide stop automatically. The slot remains reserved until the tracked turn
ends. Timeouts similarly retain the slot, preventing duplicate external work.

Nod must return a final JSON outcome with `summary`, `complete`, and nonempty
`evidence`, optionally `blocked_reason` and `question`. Unstructured responses
require review. Supporting file submission is not supported by this adapter;
validation directs the user to Hermes or to remove attachments. Available links
remain in the outcome evidence. Credentials are never included in run snapshots.

## Butler handoff

Choose Butler coordination and explicitly select permitted delegation targets.
The active parent receives a signed, expiring capability scoped to that parent
and its current execution lease. It can submit or inspect children only; it does
not receive the bridge's general authentication token. Replays return the same
child. Different work under the same key is rejected. Maximum ten children;
nested delegation and delegation to Butler are disallowed.

Child results appear in the parent's Agent results view. They cannot change the
parent Action directly. Butler must return `reviewed_child_ids` covering every
child. The parent cannot report complete while a child is pending or incomplete.
Provider approvals are never granted by delegation itself.

The Hermes watch worker reserves one additional execution slot for delegated
children and prioritizes them in its queue. This lets a Butler wait for a Hermes
child even when ordinary concurrency is one. Roots retain the configured limit;
Nod runs use their separate installation slot.

## Interfaces

- Owner: `POST /hfl-corpus/agent-bridge/actions/{id}/trigger`, with `request_key`.
- Service: `POST /api/hfl-agent/actions/{id}/trigger`, authenticated with the
  existing bridge token. Same idempotency contract as Run now.
- Owner: `GET/POST /hfl-corpus/agent-bridge/actions/{id}/schedule` with `minutes`
  and `enabled`. Writes require CSRF authentication.
- Scoped parent: `GET/POST /api/hfl-agent/delegation/{run_id}`. POST accepts
  `agent_id`, `prompt`, `request_key`; GET returns correlated child receipts/results.
- MCP: `trigger_hfl_action_execution`, `delegate_hfl_action_execution`, and
  `get_hfl_action_delegation_results` in the existing HFL Corpus integration.
- Hermes has a scoped JSON-stdin helper at `apps/hfl_corpus/action_execution.py`
  for environments where those MCP tools are not configured.

## Rollout and verification

Deploy the frontend and host Celery worker/Beat together so the new task is
registered before retiring Action discovery in the old worker. Preserve the
Hermes dispatcher for pins/briefings. Do not run an old and new frontend together.
Verify one Beat instance, host queue coverage, authenticated bridge reachability,
and execution history before enabling production Actions.

Tests use isolated databases and synthetic provider state; they never send email
or submit work to the live Nod installation. Live-provider verification must use
a harmless synthetic task in an idle conversation after deployment.
