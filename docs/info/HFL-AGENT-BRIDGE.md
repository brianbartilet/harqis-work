# Activity Corpus agent bridge

Open **Agent work** on an actionable or **Agent** beside a pinned period.
**Run now** queues its prompt for local Hermes. **Save schedule** explicitly
opts that source into automatic runs. Saving ordinary instructions never starts
execution. Category guidance supplies shared defaults; each pin's instructions
describe the specific task. Categories do not automatically opt their pins in.

## Execution policy and architecture

The initial `research-draft-v1` policy supports research and draft text, exposing
only Hermes `web_search` and `web_extract`. It does not execute code, write arbitrary
files, send messages, or change external systems. Unsupported work returns a
blocker. Hermes safe mode disables custom rules, plugins, and MCP servers; only
the configured model/provider selection and inference/web credentials are retained.
Prompt text cannot grant tools or approval. Future operation policies should use
typed canonical HARQIS operations and recorded authorization.

**Runtime: hybrid.** Hermes owns adaptive reasoning and the daily schedule. The
owning frontend's bridge store owns requests, claims, approvals, events, and receipt
retry state. Canonical actionable APIs own actionable revisions. Existing HFL
persistence/outbox and Celery delivery own durable corpus delivery. No new Celery
task or duplicate Beat schedule is introduced.

Run one bridge owner per profile, on the frontend serving the owner's pins.
Pins remain in its profile database. Remote actionables are read and updated
through the canonical timeline API, so they are not duplicated locally. Point
the worker at that frontend, not the standalone corpus API. For remote operation,
deploy the actionable GET and agent-attribution changes on the corpus API too.

This implements the [manifesto](../MANIFESTO.md)'s intent → Express output → new
memory loop. Request snapshots, plans, results, and reviews provide PAER evidence.
It follows the [runtime guide](AUTOMATION-RUNTIME-GUIDE.md) and
[Memory Signal architecture](../thesis/HFL-MEMORY-SIGNAL-CALENDAR-AND-AGENT-ACTION.md)
without adding mutable task state to immutable HFL entries.

## Context, scheduling, and completion

- Each request freezes source instructions/version/hash, category guidance,
  runtime policy, and bounded corpus context. Changed instructions before claim
  cancel a stale request. History retains the instructions actually used.
- Actionables recall their linked entry. Pins recall up to seven recent days
  within their period and 20 entries, each limited to 2,000 characters. Protected
  entries are excluded; coverage reports identify truncation or unavailable recall.
- **Daily while open** runs an opted-in actionable once per Singapore day.
  **Daily during this period** runs a pin only inside its dates. **Once after
  this period** runs once after the end, including on a later catch-up sweep.
- Review on and Complete by remain intent dates, not execution schedules.
- Claims move actionables to In Progress with agent attribution. A successful
  result requires a plan, output, evidence, and an explicit completion decision.
  The owner reviews by default; automatic acceptance is a per-source opt-in.
  A successful partial result does not mark the actionable Done.
- Concurrent human edits prevent agent completion from overwriting the action.
  The result stays reviewable. Evidence is an attributed agent claim; validating
  that references exist in the payload is not independent verification of truth.
- Edit the instructions, cancel the attempt, and run again to answer a blocker.
  Cancellation rejects later reports and is detected on the next heartbeat;
  it does not reset the actionable or erase previous work.

Actionable History interleaves revisions and agent milestones. Agent work shows
results, evidence, snapshots, and accept/cancel controls. Pin results also appear
in category Agent history using frozen guidance, even after edits or archiving.
Important results become deduplicated `hfl-agent-execution` entries. Actionable
completion also uses its existing completion outbox, with agent attribution.
Preview mode retains receipts locally without submitting corpus entries.

## Configuration and operation

Store settings in gitignored `.env/apps.env` or machine environment:

| Setting | Purpose |
|---|---|
| `HFL_AGENT_BRIDGE_TOKEN` | Required dedicated shared worker token on the owning frontend and runner; separate from the corpus owner token. |
| `HFL_AGENT_BRIDGE_URL` | Owning frontend origin; defaults to `http://127.0.0.1:8000`. Remote origins require HTTPS. |
| `HFL_AGENT_BRIDGE_STORE_PATH` | Optional SQLite path; defaults beside the owner's profile database. |
| `HFL_AGENT_HERMES_ROOT` | Optional Hermes source installation containing `cli.py` and `venv`; otherwise discovered from the Hermes executable. |
| `HFL_AGENT_MODEL`, `HFL_AGENT_PROVIDER` | Optional overrides; otherwise use installed Hermes model/provider selection. Existing provider authentication is required. |

Use the repository virtual environment from the repository root:

```powershell
.venv/Scripts/python.exe scripts/agents/hfl/agent_bridge_runner.py --check
.venv/Scripts/python.exe scripts/agents/hfl/agent_bridge_runner.py --once
.venv/Scripts/python.exe scripts/agents/hfl/agent_bridge_runner.py --watch
```

`--check` checks installation paths and bridge authentication, not inference
credentials. `--once` consumes up to ten requests. `--watch` polls every 15 seconds
and only consumes requested work; run it under the host's process supervisor for
continuous on-demand service. On macOS/Linux use `.venv/bin/python`.

The tracked [schedule definition](../../scripts/agents/hfl/agent_bridge_schedule.json)
defaults to 08:00 Asia/Singapore, Hermes `no_agent`, local delivery. Its wrapper
calls the runner's `--daily` mode to sweep opted-in sources and consume work.

```powershell
.venv/Scripts/python.exe scripts/agents/hfl/setup_agent_bridge.py
.venv/Scripts/python.exe scripts/agents/hfl/setup_agent_bridge.py --apply
```

The first command previews. `--apply` writes the wrapper under Hermes scripts
and reconciles only the named job. Duplicate named schedules are rejected.
Hermes timezone must match Singapore (a matching system-local timezone is
accepted). Its gateway/cron ticker must already be running; setup does not
start it. No Telegram/email delivery is configured. Deploy the frontend changes
before starting the worker or activating the daily job.

## Durability and API

One live request is allowed per source. Request/event keys suppress duplicates.
Claims are transactional; five-minute leases renew every 30 seconds. Expired
requests fail visibly and are not automatically re-executed. Hermes is bounded
to 12 tool turns and 20 minutes. States are queued, running, awaiting_input,
review, accepting, succeeded, failed, and cancelled. Accepting is recoverable
while an approved result is being applied; the UI offers Retry acceptance.

Results are spooled before reporting under
`HARQIS_DATA_ROOT/runtime/agent-bridge-results` (or local `.harqis-data`).
Undelivered envelopes retry on subsequent passes. A lease that expired before
first result delivery requires inspection of the local artifact. Corpus delivery
failures remain pending and retry through the existing durable HFL outbox.

Owner session + CSRF endpoints under `/hfl-corpus/agent-bridge`:
`GET /sources/{kind}/{id}`, `POST .../configure`, `POST .../run`, and
`POST /runs/{id}/accept` or `/cancel`. Kind is actionable or pin.

Worker-token endpoints under `/api/hfl-agent`: `GET /queue`, `POST /sweep`,
`POST /deliver`, `POST /runs/{id}/claim`, and `POST /runs/{id}/events`.
Events contain lease_token, event_key, kind, and payload. Kinds are heartbeat,
plan, progress, awaiting_input, succeeded, and failed. Successful payloads require
summary, evidence (list of references), and complete (boolean). Workers cannot
edit subscriptions, approve reviewed results, or use owner corpus APIs. Lease
tokens appear only in claim responses, not owner history.

Regression tests cover lifecycle, completion review, competing claims, duplicate
reports, cancellation/expiry, stale edits, daily opt-in/deduplication, pin snapshots
after archive, output validation, and token/CSRF boundaries.
