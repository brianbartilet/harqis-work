# Nod in Agent Fleet

Nod is a separate connector from n8n. Connect a self-hosted Nod server in
Integrations using its origin and `NOD_AUTH_TOKEN`, test, save, and enable it.
Choose **Open in Fleet**, or **Add agent → Nod → Link my Nod connector**.
Linking is idempotent per owner and server, and retains an existing Fleet profile.

The Conversation tab uses the server's existing, shared conversation. It sends
messages, polls recent messages/work every five seconds while visible, shows
approval context, accepts explicit approval/decline decisions, and can stop work
after confirmation. Fleet persona and instructions do not replace Nod's prompt.
Private verification, rich interactive content, uploads, and shortened approval
previews are handed off to Nod. Stopping applies to the shared conversation,
including work started outside Fleet. Schedules and connected apps remain in Nod.

Requests carry the current thread ID and a connector binding. A reset, changed
token, disabled connector, deactivated profile, or wrong owner blocks sending.
Mutation retries are user initiated and reuse the request UUID; a durable hash
rejects reuse with changed content. Nod performs final idempotency and approval
validation. No automatic retry or approval occurs. Credentials stay encrypted in
the existing connector store. Do not share the token: Nod is a single-owner app.

**Capture completed activity** records bounded recent terminal turns (not full
history) in the existing deduplicated activity outbox. Receipts include IDs,
status, source, timestamps, and a Nod link, but no conversation text or provider
configuration. Graph nodes link the captured work to its activity receipt.
Capture is explicit; no background corpus ingestion is scheduled.

## Preview

Run `.venv/Scripts/python.exe scripts/n8n_preview.py --port 8094` (use the platform's
venv Python on macOS/Linux) and open `http://127.0.0.1:8094/preview-nod`.
This shares the existing isolated n8n preview launcher. Send a message containing
“approval” to try the approval UI. Mock messages, decisions, stop, and receipts
remain local. Live connector credential writes are blocked in this preview.
Both `HARQIS_NOD_MOCK=1` and `HFL_TIMELINE_LOCAL_PREVIEW=1` are required for the double.

## Live deployment prerequisite

This change does not install a new Nod server, migrate Nod Desktop data, or
publish HARQIS changes. The inspected host currently runs Nod Desktop 0.7.6.
Desktop's private per-launch port/token are not this connector's contract.
The existing per-agent health-only Nod setup remains compatible; use Integrations
to link an assistant with the new conversation capability.

Use a dedicated self-hosted installation with persistent volumes and a stable
origin reachable by HARQIS. The recommended disk baseline in Nod's documentation
is 50 GB; the inspected host had 16 GiB free. Resolve capacity before installing.
Desktop can subsequently connect to the server; that does not migrate its local
assistant's history or accounts. Preserve the existing desktop profile separately.
Back up the server database, workspace and encryption keys before updates.

The adapter targets Nod's application HTTP contract inspected on 2026-11-16:
`GET /api/health`, `GET /api/state`, `POST /api/messages`, and
`POST /api/thread/stop`. These are not a promised versioned public API. Pin a
tested Nod revision and run adapter checks before upgrading. Polling is used
instead of an SSE proxy in this version.

Sources: [self-hosting](https://nod.n8n.io/docs/deploy/self-host/),
[desktop internals](https://nod.n8n.io/docs/deploy/desktop-app/),
[server contract](https://github.com/n8n-io/nod/blob/main/src/server/app.ts),
[message schema](https://github.com/n8n-io/nod/blob/main/src/server/audio-messages.ts).
