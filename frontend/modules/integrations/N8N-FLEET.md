# n8n agent fleet

Connect an instance in **Build → Integrations → n8n**. The REST API key reads
workflows and execution metadata; the separate instance-level MCP token discovers
first-class agents and reads their draft configuration. Enable MCP access for each
agent in n8n. No Assistant sandbox is needed for this connection.

Enabling the connector synchronizes its inventory. **Sync inventory** repeats discovery
and refreshes details for the first 25 agents. The **n8n workflow library** Fleet
profile contains all accessible workflows, including ones not attached to an agent;
it is an inventory, not an executable remote agent. **View in Fleet** opens n8n
with text, date and type filters cleared and a local all-Spaces view until you
choose a Space. Existing connections can use **Sync inventory** without reconnecting.

Open **Agents Fleet** directly to see all available connected agents. Agent hubs
remain visible across activity date, Space and node-type filters, even with no
executions or linked workflows. Search and Service narrow agents for the current
visit; reopening Fleet starts with all services and no search. The Agent work drawer
opens on every reload. Agents and the corpus owner have a 16px minimum orb radius,
plus growth for visible connections.

In **Add agent**, choose **n8n**, then select an existing remote agent in the
searchable connection field. Save creates a stable, owner-scoped Fleet link;
repeating this operation returns the same profile. Leaving the field empty keeps
the previous profile-only behavior. Existing discovered agents can use the new
**n8n** inspector tab without re-creating their profiles.

## Ownership and synchronization

- Fleet profile names, descriptions, colors, Spaces and classifications are local.
- **Refresh from n8n** reads remote draft name/instructions, workflow tools,
  schedules and recent workflow executions. It does not run or publish anything.
- **Edit n8n draft** writes only name and instructions through MCP `mutate_agent`
  with `baseConfigHash`. Both the Fleet version and current remote hash are
  checked. Stale edits are rejected; refresh and review before resubmitting.
- Draft changes do not update the published version. Publish deliberately in n8n.
- Workflow definitions, tool attachments and schedule edits remain in n8n; refresh
  reflects them in Fleet. This is explicit synchronization, not automatic polling
  of remote services or full bidirectional editing of every n8n field.

The adapter was checked against the installed n8n 2.47.7 MCP tool implementation.
Missing MCP capabilities fail explicitly. An API-only connection still supports
the workflow browser and Fleet workflow library. Old manual and discovered Fleet records are kept.

## Dependency and execution coverage

Workflow tools are resolved against up to 1,000 accessible workflows. Their static
sub-workflow references are followed with cycle detection, bounded to 100 workflows.
Node types identify application dependencies and core processing/configuration
nodes. Arbitrary HTTP URLs, dynamic expressions and opaque custom code are not
resolved to applications; credential health is not inferred. Credentials, node
parameters and execution input/output payloads are never persisted in the snapshot.

Up to 20 recent executions for each of the first 25 linked workflows are read.
These are **workflow executions**, not an agent conversation transcript. A run may
have originated from a schedule or another user. The adapter does not attribute it
to the linked agent as its executor.

**Capture executions in corpus** places terminal runs in the existing durable
Fleet audit outbox and attempts HFL delivery. Deduplication uses owner, instance
origin and execution ID, so repeated captures and shared workflow links do not
duplicate entries. Entries include status, source timestamps and an execution URL.
The existing `/agents/api/audit/deliver` endpoint retries pending delivery. Capture
is manual; no new scheduler, live execution dispatch, or historical backfill is added.

## Local review

Run `python scripts/n8n_preview.py --port 8094` and open
`http://127.0.0.1:8094/preview-login`. It creates an isolated preview user and stores
mock state under `.harqis-data/n8n-fleet-preview`. Both preview flags are required
to enable the mock adapter. No worker or scheduler starts.

The seeded Atlas agent has three workflows, a sub-workflow dependency, application
nodes, schedules and six executions. Use **Simulate a change in n8n**, then refresh
to inspect inbound synchronization. Save a draft to inspect outbound synchronization.
Execution capture creates labeled preview receipts and graph entries only; it never
writes mock data to the production Activity Corpus. Real integration testing and
live provider execution are separate from this mock review.


Browser navigation can use a separate **Browser URL** in the n8n connector form,
for example `http://harqis-ones-mac-mini:5678`, while the instance API address remains
`http://127.0.0.1:5678`. Only the API origin receives credentials. Refresh inventory
after changing the browser URL to update existing links.

Workflow definitions and their dependency nodes are independent of activity dates.
Unassigned definitions remain visible across Spaces. Fleet Filters can hide inactive
and archived workflows; both are shown initially. These filters also apply to the
compact workflow list. Dependency details expand on demand.
