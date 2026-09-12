# Activity Corpus agent bridge

The owner supplies intent through actionable prompts and pinned-date instructions.
Local **Hermes is a runtime dependency**: it executes those instructions in fresh
sessions and returns Markdown output, evidence, files and attributed history.

## Owner behavior

Open **App Settings** from the avatar menu (alongside **Profile**), or visit
`/settings`. **Actions polling minutes** defaults to 30 (1–1440).
**Pinned dates backfill days** defaults to 7 (1–31). Personal profile fields stay
in Profile; credentials and Hermes provider settings stay on the host.

All **Open** actionables with nonblank prompts are discovered automatically.
The **prompt is the main instruction and completion criterion**. Title, expected
outcome, notes and linked activity supply supporting context. Review and due dates
do not limit discovery. Blank prompts stay Open.

The lifecycle is **Open → Active → In Progress → Done**. Active means queued;
In Progress means claimed by a worker. Failed, blocked or partial work becomes
**Incomplete**, shown in red with precedence over other calendar status dots.
Moving an action back to Open requests a fresh attempt on the next discovery
pass. Old attempts retain their history and cannot overwrite the new revision.
**Run now** queues an immediate attempt. Closed actions must first be reopened.

**Actions history** interleaves revisions and execution events newest first.
Outputs render sanitized Markdown and working source links. Files have signed-in
View and Download links. The Agent work dialog shows frozen instructions, run
state, session ID, and recovery controls for results that need review.

Pins have an optional hour selector, default **00:00 Asia/Singapore**, and a daily
schedule checkbox. New pins with instructions are enabled by default. Existing
pins preserve prior opt-in, including legacy daily/after-period subscriptions.
Blank instructions and archived categories do not execute. Daily runs cover both
start and end dates. Each occurrence combines category guidance, pin instructions,
pin context and bounded activity recall up to that occurrence's date.

Missed occurrences from the previous seven days are caught up automatically, one
live attempt per pin at a time. Stable occurrence keys prevent duplicate runs.
Older gaps create a deduplicated HFL review entry per pin period. Failed attempts
are accounted for in history rather than automatically repeated. Pin outputs are
consolidated in the category's **Agent history**, including after archiving.
Future calendar dates disable Ideas and open Actions by default.

## Architecture and authorization

This follows the [manifesto](../MANIFESTO.md)'s intent → Express output → new memory
loop and [runtime guide](AUTOMATION-RUNTIME-GUIDE.md). Runtime ownership is hybrid:

- **Hermes** owns the minute dispatcher and adaptive execution. The dispatcher
  checks pin hours every minute and respects the separate actions polling interval.
- **The owning frontend** owns durable SQLite requests, leases, source snapshots,
  subscriptions, settings, events, authenticated artifacts and delivery state.
- **Canonical timeline APIs** own actionable status and optimistic revisions.
- **Existing HFL persistence/outbox and Celery delivery** own corpus writeback.
  There is no additional Beat schedule or duplicated mutable HFL task state.

Run one bridge owner beside the frontend serving the owner's pins. Remote
actionables are read/updated through the canonical timeline API; the worker points
to the owning frontend, not the standalone corpus API. Deploy both frontend and
canonical timeline changes together.

The `prompt-execution-v2` policy exposes web, terminal, file and code execution.
Hermes safe mode suppresses unrelated rules, plugins and MCP integrations. Each
attempt runs without resume in its own workspace, with 30 tool turns and a
20-minute timeout. This is an owner-authorized local execution worker, not an OS
sandbox. External consequential actions still require authorization in the task;
retrieved pages and corpus entries cannot grant that authority. Provider/web
credentials are retained; bridge and application credentials are excluded from
the child environment. Host files remain subject to the OS account's permissions.

Actionables recall their linked entry. Pins recall at most seven days / 20 entries
of 2,000 characters each; protected entries are excluded and coverage is recorded.
Snapshots freeze source, policy and instruction hashes. Source edits before claim
cancel stale runs. Concurrent edits prevent applying completion to newer revisions.
The result is an attributed agent claim, not independent proof that evidence is true.

## Deployment and operation

Store secrets in gitignored `.env/apps.env` or the host's secret environment:

| Setting | Purpose |
|---|---|
| `HFL_AGENT_BRIDGE_TOKEN` | Dedicated shared worker token, separate from the corpus token. Required on frontend and worker. |
| `HFL_AGENT_BRIDGE_URL` | Owning frontend origin. Defaults to loopback using `PORT` (8080 fallback). Remote origins require HTTPS. Set explicitly if frontend/.env changes the port. |
| `HFL_AGENT_BRIDGE_STORE_PATH` | Optional SQLite path, otherwise `hfl-agent-bridge.sqlite3` beside the profile database. |
| `HFL_AGENT_HERMES_ROOT` | Hermes source installation with cli.py and venv. Discovered from the executable or ~/.hermes/hermes-agent. |
| `HFL_AGENT_MODEL`, `HFL_AGENT_PROVIDER` | Optional overrides; otherwise installed Hermes model/provider. Provider authentication must work. |

`machines.toml` enables `hfl_agent = true` for `harqis-server`. The deploy launcher
manages service **hfl-agent** (`work.harqis.hfl-agent`), skipped with
`--no-hfl-agent`. Startup checks the token, reconciles the Hermes cron, and starts
`--watch`. Hermes gateway must already supervise the cron ticker. The installer
requires Singapore timezone (matching system timezone is accepted).

The tracked [schedule](../../scripts/agents/hfl/agent_bridge_schedule.json) uses
`* * * * *`, `no_agent`, local delivery and `--dispatch`. Setup migrates the prior
`hfl-agent-bridge-daily` job in place to `hfl-agent-bridge-dispatch`; duplicate named
jobs are rejected rather than creating another schedule. No chat delivery occurs.

Use the repo venv (Windows: `.venv/Scripts/python.exe`; macOS/Linux below):

```sh
.venv/bin/python scripts/agents/hfl/agent_bridge_runner.py --check
.venv/bin/python scripts/agents/hfl/agent_bridge_runner.py --smoke
.venv/bin/python scripts/agents/hfl/setup_agent_bridge.py          # preview
.venv/bin/python scripts/agents/hfl/setup_agent_bridge.py --apply
.venv/bin/python scripts/launch.py hfl-agent
```

`--check` verifies paths and authenticated bridge access. `--smoke` executes two
synthetic file tasks and checks distinct Hermes sessions without consuming the
production queue. `--once` consumes up to ten queued requests; `--watch` consumes
continuously; `--dispatch` discovers due work. Legacy `--daily` dispatches and
consumes once, but is no longer scheduled.

On 2026-09-12, the configured harqis-server Mac host passed two isolated Hermes
file tasks with distinct sessions using its configured openai-codex provider.
Its gateway was supervised by launchd. A scoped bridge credential and explicit
loopback frontend origin were prepared in the host's apps.env. Application code
and the minute schedule still require deployment before production use.

## Durability and files

Only one live attempt per source is allowed. Request/event keys are idempotent.
Transactional claims have five-minute leases renewed every 30 seconds. Expired
runs become Incomplete; they are not silently rerun. Result envelopes are spooled
before delivery under `HARQIS_DATA_ROOT/runtime/agent-bridge-results`. Reconciliation
recovers queued status updates, completion application and failed-run status.
HFL receipts use existing durable delivery with deduplication.

Artifacts must be declared simple filenames in the attempt's workspace: at most
30 files, 20 MB each. The runner rejects traversal, external symlinks and missing
files. Upload requires the scoped worker token and active execution lease. Files
are stored immutably by content hash under `agent-artifacts` beside the bridge DB.
Downloads require the owner session. Safe image/PDF/text formats support viewing;
Markdown previews are sanitized and active HTML is never served inline. The
artifact directory and bridge/profile databases must be backed up together.

Owner session/CSRF APIs live under `/hfl-corpus/agent-bridge`; worker-token APIs
under `/api/hfl-agent` expose queue, sweep, deliver, claim, events and artifact
upload. Worker credentials do not grant owner profile or corpus access. Lease
tokens appear only in claim responses, never owner history.
