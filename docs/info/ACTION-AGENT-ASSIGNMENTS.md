# Action agent assignments

Actions remain useful for manual work. New Actions default to manual, with no
automated execution. Existing Actions retain their previous worker configuration
until an owner changes the assignment.

In **Agent settings**, choose No agent, Butler coordination, Fleet agent, or
Default worker. Configure specialization and profile sources in **Fleet**, then
assign the agent to an Action. Action forms contain no specialist selector.
Additional guidance and execution settings are collapsed; instruction previews
open in their own dialog. Manual Actions hide these execution controls.

New runs inherit the assigned Fleet agent's current specialization, including
when an older Action has a saved specialist override. Saving configuration
normalizes those legacy fields to inheritance. Run settings capture resolved
instructions, profile and agent hash; existing runs keep their saved context.
Opening an interactive session does not execute the saved task prompt.

Both Action editors save assignment changes with their normal save lifecycle.
Automation is disabled while an assignment is being saved and enabled only after
the configuration succeeds for an executable assignment. A failed configuration
save leaves the Action without automatic pickup; retry saving to finish. These
operations span the canonical Action service and the local execution store and
are intentionally not represented as a single database transaction.

## Butler coordination

The butler runs as the assigned Hermes Fleet agent using the existing durable
Action queue. Coordination guidance requests planning, meaningful progress,
blocker reporting, artifact links, and review of the expected outcome. Existing
run events and outputs remain attached to the Action.

This does not introduce a new cross-provider scheduler or automatically manufacture
child Actions. Delegation requires tools actually available to the butler and an
execution receipt. A profile grants neither tools nor permission.

Codex and NOD can be recorded as assignments, but their current connectors do not
execute Actions through this worker queue. The editor explains this limitation;
run/session creation rejects it rather than silently substituting Hermes. Their
existing provider interfaces remain available separately.

## Session flow

The left panel shows the Action, assignment, specialist, files, runs and outputs.
**Run action** executes saved instructions; **Run with butler** identifies a
coordinated run. **Start session** opens an interactive Hermes workspace. Manual
and unsupported assignments explain why new execution is unavailable. Prior
transcripts remain readable. Advanced worker settings and presets are retained.

## Automation runtime decision

- Classification: hybrid; confidence: high.
- Judgment owner: the assigned agent, or the butler for coordinated Actions.
- Execution owner: existing Action bridge queue and authenticated workers.
- Schedule owner: the existing Ready-action polling mechanism; no new schedule.
- New Celery operations: none.
- Controls: existing run idempotency and worker leases, immutable profile content,
  bounded instructions, owner authentication/CSRF, and connector execution checks.
- Review artifact: Action run events, output, attachment links and completion note.
- Remaining extension: provider-specific Action dispatch and correlated child work.
