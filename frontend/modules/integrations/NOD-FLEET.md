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

HARQIS now runs a separate self-hosted Nod server alongside Nod Desktop. The
Desktop profile is preserved; Desktop's private per-launch port/token are not
this connector's contract. The existing per-agent health-only setup remains
compatible; use Integrations for the shared conversation capability.

### HARQIS installation (2026-11-16)

- Pinned ARM64 bundle revision: `d3e6d5f77b3bfc64516e98af75bfa0cd85ae0b06`.
  Archive checksums and loaded image IDs, architecture and revision were verified.
- Private HTTPS origin: `https://harqis-ones-mac-mini.tail6d1d40.ts.net:8444`;
  Tailscale Serve proxies the loopback server on port 4310.
- Installation: `/Volumes/HARQIS-Nod/installation`, on a growing 100 GiB APFS
  sparsebundle at `/Volumes/harqis-data/nod-server/nod-data.sparsebundle`.
  The surrounding ExFAT disk was not reformatted.
- Database, workspace, tools and server data use external named bind volumes.
  Images and browser state remain in Docker Desktop's internal Linux storage:
  the browser control socket cannot use the Mac-shared filesystem. Browser
  state is included in backups. Monitor internal free space before upgrades.
- `work.harqis.nod` is a user LaunchAgent that mounts the storage and starts the
  stack after Docker is available. It skips an absent drive and respects the
  installation's `.maintenance` marker. Keep the external disk attached.
- The owner connector uses an encrypted server token. The existing HARQIS OpenAI
  key was connected through Nod's model API; no credentials are in this repo.
- Run `sh /Volumes/HARQIS-Nod/installation/backup-external.sh
  /Volumes/HARQIS-Nod/backups/<new-timestamp>` as one command. The wrapper prevents
  the startup guard racing the backup's temporary stop. An initial backup was
  restored successfully into a separate stopped project without starting an
  assistant. Keep another copy on a different physical disk.
- Original compose, backup and restore files are retained alongside the
  external-volume adaptations. Follow `HARQIS-OPERATIONS.md` in the installation
  for restore and upgrade procedures; the original installer expects its
  unmodified checksummed compose file.

The Fleet conversation smoke test completed successfully. Connecting Desktop to
this server is optional and does not migrate Desktop's history or accounts.

The adapter targets Nod's application HTTP contract inspected on 2026-11-16:
`GET /api/health`, `GET /api/state`, `POST /api/messages`, and
`POST /api/thread/stop`. These are not a promised versioned public API. Pin a
tested Nod revision and run adapter checks before upgrading. Polling is used
instead of an SSE proxy in this version.

Sources: [self-hosting](https://nod.n8n.io/docs/deploy/self-host/),
[desktop internals](https://nod.n8n.io/docs/deploy/desktop-app/),
[server contract](https://github.com/n8n-io/nod/blob/main/src/server/app.ts),
[message schema](https://github.com/n8n-io/nod/blob/main/src/server/audio-messages.ts).
