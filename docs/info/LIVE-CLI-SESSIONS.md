# Live CLI sessions

Approved scope: 2026-11-20. Implementation extends the action-linked native PTY.
See the original [investigation](../thesis/BROWSER-CLI-AGENT-SESSIONS.md).

## Feature spec

**Goal:** responsive browser terminals for Hermes, Codex, Claude and Jev-enabled
Hermes, retaining action context, transcripts and isolated repository workspaces.

**Trigger:** manually start/open a session from an Action's agent workspace.
The CLI selector chooses a runtime and a worker for a new session; it does not
change the Action's automatic assignment or reasoning-model configuration.

**Ownership:** the worker owns the PTY process. The frontend authenticates and
relays terminal traffic. Manual initiation is the only schedule owner. No new
Celery schedule, automatic routing, merge, push or deployment is installed.

**Inputs:** action context, runtime/host, existing host authentication, terminal
input, attachments, dimensions, and explicit end-session controls.

**Outputs:** live terminal output, durable replay, downloadable transcripts,
attached artifacts and preserved worktree changes. Opening a native terminal
does not submit the saved action prompt.

**Acceptance:** authenticate both streams, reconnect without restarting the CLI,
preserve ordered replay and input identity, enforce existing worker leases and
capacity, show unavailable runtimes with reasons, and verify local desktop/mobile
interaction plus focused protocol/worker regression tests.

## Architecture and limits

Browser xterm.js ↔ authenticated WebSocket ↔ FastAPI/SQLite ↔ authenticated
worker WebSocket ↔ PTY ↔ native CLI.

- Browser admission requires the existing owner session, matching Origin/Host,
  and a CSRF token in the first frame. Tokens are not put in WebSocket URLs.
- Worker admission requires the bridge bearer credential and terminal lease.
  Existing owner HTTP controls and uploads remain compatible.
- Output persists before acknowledgement. Stable output keys make retries
  idempotent. Browser replay has one bounded batch in flight, acknowledged after
  xterm rendering; slow sends time out and reconnect from the rendered cursor.
- Input is durably keyed before acknowledgement. A live worker retains its
  delivered cursor across reconnects and ignores older input. Browser input with
  an uncertain acknowledgement is reported for review, not silently resent.
  This is not exactly-once execution across worker crashes.
- Local store mutations wake streams immediately. A one-second server-side
  SQLite reconciliation catches writes from another ASGI process or legacy HTTP
  client. Single-process deployments get immediate local wakeups; multi-process
  deployments can incur that reconciliation delay. No shared-memory-only routing
  assumption or new Redis dependency is introduced.
- Worker reconnect retries are bounded to 60 seconds, below the existing
  90-second stale-worker threshold. During a prolonged outage PTY output can
  back up. This release does not survive worker/service restarts via tmux.
- Session discovery still checks every two seconds. Runtime advertisements
  refresh every 30 seconds and expire after 90 seconds.
- A Git worktree separates edits; it is not an OS security sandbox. Native
  providers retain their own approval prompts. The bridge credential is removed
  from child environments; terminal output retains existing credential redaction.
  Redaction covers known environment secret values, not arbitrary secrets typed
  into a terminal. Input and output are retained in the session store; complete
  provider sign-in on the host before opening a browser session.

## Runtime behavior

| Runtime | Admission and context | Continuation |
| --- | --- | --- |
| Hermes | Existing per-turn hooks and profile settings | Existing native session ID |
| Codex | `workspace-write`, `on-request`; context-file guidance, no startup prompt | Reattach the live process; no automatic discovery of its native session ID |
| Claude | Default permission prompts; context-file guidance, no startup prompt | Explicit generated session UUID and `--resume` |
| Jev · Hermes | Dedicated trusted Hermes profile with existing TypeSafe MCP tools | Hermes session continuation |

Codex/Claude reserve an execution slot for the entire live session because they
do not use Hermes's per-turn hook. Their configured timeout bounds the session;
the UI must not infer model activity from terminal escape sequences. Model and
toolset settings in the existing execution form are Hermes settings; native
Codex/Claude use their own host configuration. Image paste inserts a file
reference; interpretation remains provider-specific.

Worker discovery checks executable availability and Codex/Claude auth status
without returning credential output. Hermes discovery validates the installation;
provider access can still fail when inference begins. A selected runtime is
pinned to the reporting worker, not whichever host claims first.

## Jev prerequisites

Jev remains recommendation-only action triage through the existing
[TypeSafe integration](JEV-HERMES.md). It is not a standalone conversational CLI.
Use `HFL_AGENT_JEV_PROFILE` to select its Hermes profile (default `jev-decisions`).
The worker requires `TYPESAFE_API_KEY`, a profile configuration containing
`harqis_typesafe`, and the installed `jev-action-triage` skill. The session must
use trusted profile execution so MCP tools load. No profile or credential is
silently created by opening the terminal.

## Operations and implementation map

Install normal requirements, including explicit `websockets>=15.0`, then start
the frontend and existing bridge worker. Reverse proxies must forward WebSocket
Upgrade headers and preserve the browser's public Host. The Full screen control
expands the current terminal dialog using the browser fullscreen API.
The fullscreen target is the document element: browsers reject fullscreen
requests on `<dialog>` elements. Exiting fullscreen keeps the session open.
Secondary controls are grouped under the hamburger **Actions** menu.

The stream initializes its store once per connection, reads session state and
replay rows together through a session/sequence index, and uses asynchronous
local wakeups. Connected workers omit legacy polling sleeps; browser typing
flushes after four milliseconds without restarting the timer for each keystroke.

- `frontend/modules/hfl_corpus/terminal_stream.py`: stream auth, replay and controls.
- `workflows/hfl/action_agent_store.py`: durable I/O, leases, host capabilities.
- `workflows/hfl/terminal_events.py`: bounded local wakeups.
- `scripts/agents/hfl/terminal_transport.py`: worker stream and reconnect.
- `scripts/agents/hfl/terminal_runtimes.py`: discovery and native launch policies.
- `scripts/agents/hfl/action_terminal.py`: PTY lifecycle, capacity and artifacts.
- `frontend/static/js/action-agent-workspace.js`: existing controls, runtime picker,
  xterm acknowledgement and reconnect status. Existing timeline styling is reused.

References checked during implementation:
[Codex CLI](https://developers.openai.com/codex/cli/reference/),
[Claude CLI](https://code.claude.com/docs/en/cli-reference),
[TypeSafe quick start](https://docs.typesafe.ai/introduction/quickstart).
Installed CLI help/auth commands were also inspected; provider versions differ.

## Local verification — 2026-11-20

A real loopback WebSocket → Windows PTY echo benchmark (12 requests, durable
SQLite I/O) measured 214.6 ms median / 295.4 ms maximum before the latency fixes
and 84.4 ms median / 98.2 ms maximum afterward. This measures terminal transport,
not model inference or xterm rendering, and is not a comparison against another
product. Run `frontend/tests/test_terminal_latency.py` to reproduce it. Host load
and storage affect the result; multiple ASGI processes retain the reconciliation
delay described above.

- 38 focused tests passed across `frontend/tests/test_action_agents.py`,
  `frontend/tests/test_terminal_stream.py`, `frontend/tests/test_terminal_latency.py`, `scripts/tests/test_action_terminal.py`
  and `scripts/tests/test_terminal_runtimes.py`.
- Tests cover stream authentication, replay, keyed input, disconnect cleanup,
  runtime admission, existing session lifecycle, real Windows PTY argument
  quoting, browser reconnect, keyboard input, image paste, fullscreen entry/exit
  and responsive layout.
- Native Hermes, Codex 0.170.0 and Claude reached their interactive interfaces.
  Hermes `/help` input was acknowledged through the browser stream and its output
  was received. These were startup/transport checks, not model-inference benchmarks.
- The isolated loopback preview passed desktop/mobile visual checks with no
  JavaScript errors or horizontal overflow; `/health` returned HTTP 200.
- Jev could not be exercised live: this host lacks `TYPESAFE_API_KEY` and the
  dedicated profile. Its unavailable state is reported instead of claiming support
  is ready to execute locally.
