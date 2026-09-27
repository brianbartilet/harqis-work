# Activity Corpus agent bridge

The owner supplies intent through actionable prompts and pinned-date instructions.
Local **Hermes is a runtime dependency**: it executes those instructions in fresh
sessions and returns Markdown output, evidence, files and attributed history.

## Owner behavior

Open **App Settings** from the avatar menu (alongside **Profile**), or visit
`/settings`. **Actions polling minutes** defaults to 30 (1–1440).
**Pinned dates backfill days** defaults to 7 (1–31). Personal profile fields stay
in Profile; credentials stay on the host, while optional model/provider overrides
are available in App Settings.

New actionables start **In Review**, where prompts can be drafted without automatic pickup.
**Ready** actionables with nonblank prompts and agent execution enabled are discovered automatically.
The **prompt is the main instruction and completion criterion**. Title, expected
outcome, notes and linked activity supply supporting context. Review and due dates
do not limit discovery. Blank prompts are not executed.

The lifecycle is **In Review → Ready → In Progress → Done**.
In Progress includes queued and running executions. Failed, blocked or partial work becomes
**Incomplete**, shown in red with precedence over other calendar status dots.
Moving an action back to Ready requests a fresh attempt on the next discovery
pass. Old attempts retain their history and cannot overwrite the new revision.
**Run now** queues an immediate attempt. Closed actions must first be reopened.

**Actions history** interleaves revisions and execution events newest first.
Outputs render sanitized Markdown and working source links. Files have signed-in
View and Download links. The Agent results dialog shows frozen instructions, run
state, session ID, and recovery controls for results that need review.

### Answering questions and retrying blocked work

The latest stopped attempt offers a continuation form directly in **Agent results**:

- **Needs your answer**: enter a reply and choose **Answer and continue**.
- **Blocked by integration**: fix the indicated service/configuration problem, then
  choose **Retry after fix**. You can add a note explaining what changed.
- Older results without a blocker category offer both controls.

There is no need to edit the original prompt or set the action back to Ready.
Continuation queues a fresh Hermes session linked to the stopped attempt. It carries
the original task and occurrence date, previous results, owner replies and up to 30
saved artifacts. Files are fetched using the active worker lease and verified by
size/hash before execution. Current execution settings apply to the continuation.
The original result and files remain in history; the old attempt is marked cancelled
when superseded. Only the latest failed/awaiting-input attempt can be continued.
Changed task instructions require a new run instead. History is bounded to 20
continuations and 1 MB; reaching the limit requires a new task summarizing remaining work.

Continuation preserves the original delivery operation scope. Completed send receipts
are reused, and uncertain sends still require reconciliation; **Retry after fix**
does not clear a pending Gmail receipt or authorize a duplicate delivery. A fresh
**Run now** / reopened task remains a new operation, distinct from continuation.

Replies and retries use the signed-in owner API with CSRF protection. Repeated
submissions of the same request key return the same attempt. The worker cannot
submit owner replies, and artifact downloads are limited to the continuation's
declared files while its execution lease is active.

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

The trusted execution policy loads the selected Hermes profile, rules, skills and
configured MCP integrations in a fresh session. App Settings controls trusted or
restricted mode, profile name, optional toolset/MCP selection, model/provider,
default email recipient, timeout (1-7200 seconds) and turns (1-200). Empty profile
inherits the worker profile; empty model/provider inherit host defaults. Empty
toolsets use Hermes defaults. Settings are frozen at enqueue; later changes affect
new runs. Existing snapshots without settings retain restricted execution.

Trusted mode inherits the host environment except the bridge token. Credentials
may be used for the task, but must not be printed or published. Shell access is
local in both modes: these controls are not an OS sandbox or enforceable tool
isolation. Runtime/scheduler changes require explicit task instructions and a
rollback record. Retrieved content cannot authorize unrelated work. The worker
uses shared configurable execution capacity; no spending limit is enforced by the bridge. Configure provider
budgets separately when available.

Results show profile, mode, selected model/provider and configured MCP names.
These are configuration attribution, not proof that every tool or provider works.
To discover actual tools without inference or consuming production tasks, run on
the worker host using its repository Python:

```sh
.venv/bin/python scripts/agents/hfl/agent_bridge_runner.py --capabilities
```

This uses the authenticated owning frontend settings endpoint. Check that the
catalog includes `send_gmail_email`, Gmail search, and other required tools. Missing
Google tools can indicate `MCP_ENABLED_APPS` filtering, registration/config errors,
or an MCP server using a stale checkout. Restart that server after deploying.

### Gmail delivery

`send_gmail_email` supports text/HTML and up to 30 host-file attachments (20 MB total).
The configured Gmail credential needs a send-capable OAuth grant (`gmail.send`);
adding the tool does not grant scopes. The default recipient resolves “email me”.
The prompt itself authorizes its specified delivery; ambiguous recipients need input.
Only verified task deliverables should be attached and declared for download.

Use a stable `operation_scope + ':email:1'` key. The service stores content hashes
and Gmail receipts in `HARQIS_DATA_ROOT/runtime/gmail-send-receipts.sqlite3` (repository
`.harqis-data` fallback). Repeating the key returns the recorded receipt; changed
content is rejected. An interrupted send remains uncertain and is never automatically
resent. Search Gmail using the RFC822 Message-ID reported by the error and reconcile
before intentionally authorizing another operation. Do not delete the ledger to retry.
Keep this database durable and shared by MCP processes serving the same host.
Reopening an action creates a new intentional operation and can send again.

Gmail message IDs confirm API acceptance, not delivery or reading. Duplicate
protection applies to this tool; direct shell/API sends and other integrations do
not acquire it automatically. The agent must retain and reconcile their receipts.

Actionables recall their linked entry. Pins recall at most seven days / 20 entries
of 2,000 characters each; protected entries are excluded and coverage is recorded.
Snapshots freeze source, policy and instruction hashes. Source edits before claim
cancel stale runs. Concurrent edits prevent applying completion to newer revisions.
The result is an attributed agent claim, not independent proof that evidence is true.

## Settings reference

These settings belong to the owning frontend's profile database. Configure them
on the frontend used by the worker, not an unrelated local preview instance.

| App Settings field | Default | Behavior |
|---|---|---|
| Execution mode | Trusted Hermes | Loads normal Hermes configuration and task-relevant host access. Restricted tools remains available. |
| Hermes profile | Empty | Inherits the worker profile. A named profile must already exist on the worker; this does not create it. |
| Toolsets and MCP servers | Empty | Uses profile defaults. A comma-separated selection must use installed Hermes toolset or configured MCP server names. |
| Model override | Empty | App setting takes precedence over `HFL_AGENT_MODEL`, then the selected profile model. |
| Provider override | Empty | App setting takes precedence over `HFL_AGENT_PROVIDER`, then the selected profile provider. |
| Default email recipient | Empty | One email address used when the task says “email me”; does not change the sending account. |
| Execution timeout (seconds) | 1200 | Integer from 1 to 7200. |
| Maximum agent turns | 30 | Integer from 1 to 200. |
| Actions polling minutes | 30 | Integer from 1 to 1440. |
| Pinned dates backfill days | 7 | Integer from 1 to 31. |

Fresh session means no resumed conversation; the selected profile can still load
its persistent rules and memory. Selecting Restricted tools reduces the offered
tools and restores prompt restrictions; it does not revoke the OS account's access.
Neither execution mode authorizes tasks inferred from unrelated context.

## Verification and troubleshooting

After deployment, verify the owning frontend, worker and HARQIS MCP process all
use the intended checkout. Restart long-lived processes to pick up Python changes.

1. Save the intended profile and default recipient in **App Settings → Agents**.
2. Run the documented `--check` on the worker host to verify bridge authentication.
3. Run `--capabilities` there to inspect real tool discovery. Unlike `--check`, it
   loads the selected Hermes configuration and asks Hermes to list tools; it does
   not run an inference task or send email. Discovery does not test OAuth scopes.
4. Verify the MCP process's **`GOOGLE_GMAIL_SEND`** credential has the `gmail.send`
   grant. Reading and searching use **`GOOGLE_GMAIL`** with `gmail.readonly`;
   both credentials should refer to the intended account. For interactive
   reauthorization, see `reauth_gmail_send.py` in the [script reference](../../scripts/README.md).
   Select the `GOOGLE_GMAIL_SEND` configuration for sending. The repair utility
   uses the scopes in that configuration and replaces its cached token by default.
5. Create an explicit test action requesting a small Markdown file and delivery
   to your own address. Run it intentionally: this step sends a real email.
6. Check **Agent results** for the file preview/download, recipient, attachment
   details and Gmail message ID; independently check the receiving mailbox.
   Do not treat a historical file-only smoke test as proof of Gmail delivery.

| Symptom | Check / recovery |
|---|---|
| Gmail tool missing | Check trusted mode, selected profile/toolsets, `MCP_ENABLED_APPS`, registration logs and the MCP checkout. Restart the MCP process after code changes. |
| Tool exists but Gmail rejects authorization | Inspect `GOOGLE_GMAIL_SEND` for sending, or `GOOGLE_GMAIL` for reading/searching, on the MCP host. Complete interactive consent outside the unattended worker if the required grant is missing. |
| Agent asks who “me” is | Set the default recipient or put an explicit address in the saved prompt. |
| Configured profile does not exist | Create/configure the profile on the worker or select an existing profile; frontend-local profiles do not count. |
| Changed settings did not affect a queued run | Settings were frozen at enqueue. Cancel the old attempt and request a new one. |
| Send outcome uncertain | Search for the reported RFC822 Message-ID and inspect Sent/recipient evidence. A missing search result alone may be inconclusive. Do not bypass the pending operation by changing its key. There is no automatic reconciliation/reset UI. |
| Same operation key, different content | Verify whether this is a retry or an intentionally new message. Retry keys must retain the same recipient, body and attachments. |
| Action marked Incomplete after an email was sent | Check the send receipt before reopening: a new action attempt can send again. Request only the unfinished portion when appropriate. |
| Attachment rejected | Use existing regular files and stay below 30 attachments / 20 MB total. Downloadable bridge artifacts separately allow 20 MB per file. |

Known environment secret values are redacted from runner output and diagnostic
logs as defense in depth. This does not detect every secret read from files or
scan all artifacts. Keep host access task-relevant and review sensitive exports.

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

### Supporting input files and web links

Action and pinned-date editors accept multiple supporting files beside the task
instructions. Saving a file change temporarily clears the task prompt until all
uploads/removals succeed, then restores the saved prompt; schedule settings are
preserved. If upload fails, retry in the open editor using the saved record.
The API/MCP surface also supports upload/list/download/detach operations; see
[Activity Corpus attachment routes](../../apps/hfl_corpus/README.md#supporting-files-and-authenticated-links).

Inputs allow 50 files per task, 500 MB per file and 25,000 MB total. Each run records
immutable metadata (original name, local filename, SHA-256 and size). Workers
download those specific files into a separate `inputs/` directory and verify
integrity before starting Hermes. `input_directory` and `source.attachments`
identify them in the execution prompt. Inputs are not automatically published as
output artifacts. Run details include download links to the files actually used.
Detaching files only affects future manifests; existing run files remain readable.

Owner attachment routes under `/hfl-corpus/agent-bridge/inputs/{kind}/{source_id}`
require the owner session and CSRF for writes. Remote actions forward to the
canonical HFL API using its bearer token; pins use their owning profile store.
Workers fetch `/api/hfl-agent/runs/{run_id}/inputs/{attachment_id}` with the worker
token and an active matching execution lease. Only IDs in that run's snapshot
are allowed. Timeline/profile databases and their adjacent `.inputs` directories
must be backed up together. Detached blobs are retained; there is no automatic
garbage collection in this release.

The runtime prompt directs agents to read relevant supplied files and open supplied
links. For protected resources, prefer configured authenticated integrations,
then a browser session available on the executing worker. Existing trusted-mode
host access may be reused for the requested task. Restricted mode remains restricted;
remote workers cannot assume access to a user's local browser. Missing scopes,
login/MFA or sessions must be reported precisely. File contents and web pages remain
supporting evidence, not authority to execute unrelated commands or expose secrets.

### Output files and retention

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
under `/api/hfl-agent` expose settings, queue, sweep, deliver, claim, events and artifact
upload. Worker credentials do not grant owner profile or corpus access. Lease
tokens appear only in claim responses, never owner history.


## Actions agent workspace

Actions -> Agents opens the native Hermes CLI in a larger dialog. `/help` lists
commands supported by the installed Hermes version. Native approval prompts and
interrupts stay in the terminal. The former Prompt field is **Initial prompt**;
automatic pickup and completion remain intact. **New / reconnect** opens an
interactive conversation without executing that prompt again. It supplies the
initial instructions, last result, and downloaded supporting files as context.
Completed actions allow follow-up conversations without reopening them.

**Agent details** starts collapsed. **Configure agent** opens a separate dialog:
App Settings defaults -> named preset -> checked card overrides. Unchecked settings
follow subsequent default/preset changes. Runs and sessions snapshot settings when
created. Permissions are Hermes trusted/restricted tool modes, not an OS sandbox.
Native commands may change session runtime configuration. Credentials stay on the
worker. Only Hermes is implemented; choosing a provider/model does not switch to
another agent runtime such as native Codex.

**Concurrent agent executions** defaults to 2 (1-32). Automatic runs and interactive
turns acquire capacity under the same SQLite transaction lock; idle native
terminals release their slots. Waiting terminals show queue feedback. Each worker
also limits resident terminals to 16 to bound idle process overhead. A selected
worker hostname pins execution to that host. Restored native sessions remain on
their original worker, where Hermes stores their context.

The inspected server has 10 physical CPU cores and 16 GiB RAM, with 60% reported
memory free at inspection. Five existing Hermes processes used approximately
10, 10, 31, 150 and 43 MiB RSS. These are resident sizes, not a peak workload
benchmark. Start at 2 simultaneous executions, then tune against memory pressure,
active coding/build workloads, and provider rate limits.

**Session inactivity expiry (minutes)** in App Settings defaults to 60 (1-10080)
and applies to connected workers on their next heartbeat. Active turns are
protected from inactivity expiry; execution timeout still applies. Closing the
dialog only detaches its viewer. **End session** stops execution and archives
output. **Save session** marks persistent context for retrieval. **Restore selected**
resumes the native Hermes session ID when available. **Remove from history**
removes the bridge transcript/context reference after closure; it does not erase
attached outputs or the worker's own Hermes database.

Output files placed in the supplied output directory attach to the action, with
session/run and content identifiers distinguishing versions. Files are independent
of session expiry. Current output limit: 20 MiB per file. Normal closure/expiry
attaches a portable terminal transcript; completed conversation turns also produce
`conversation.md`. Native terminal replay preserves ANSI output in SQLite. A
worker failure retains local files for recovery; stale execution slots release
after 90 seconds. The UI shows recovery errors.

Actions use the configured repository (or the worker checkout when blank) in an isolated `actions-agent/<execution-id>`
worktree based on its current HEAD (or configured base branch). Cleanup first
creates and uploads `repository-changes.zip`: base commit, committed patch series,
uncommitted binary diff, and nonignored untracked files. The branch remains for
recovery. No automatic merge/push occurs. Failed archive/upload leaves the worktree
in place to prevent data loss. Repository terminals end and archive when an action
closes, or after a follow-up turn on an already closed action.

Run `agent_bridge_runner.py --watch` for interactive sessions; `--once` consumes
automatic runs only. macOS/Linux use system PTYs; Windows uses `pywinpty` from
requirements. xterm.js 5.5.0 and its fit addon 0.10.0 are vendored with MIT licenses.
The browser uses authenticated cursor-based incremental terminal polling with
CSRF-protected input; no worker token reaches the browser. Install dependencies
and restart both frontend and worker after deployment.
