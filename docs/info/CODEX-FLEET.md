# Codex fleet observation and Butler oversight

The Codex connector observes the Codex installation on the **HARQIS frontend
server host**, using that operating-system user's existing Codex home/sign-in.
It is not the ChatGPT mobile Remote Control pairing interface. A container or
another machine cannot discover the desktop installation simply because Codex
is installed on the browser user's computer.

## Connect

1. Inspect the host with `python scripts/setup_codex.py --remote <machine-key>`.
   Add `--install` to install Codex only if missing (macOS/Linux); existing
   installations are reused without upgrades. Omit `--remote` on the host itself.
   The installer is the [official OpenAI standalone installer](https://learn.chatgpt.com/docs/cli).
   Sign in on the frontend host as the HARQIS service user when prompted by setup.
   The adapter discovers managed daemon/standalone packages on Windows, macOS,
   and Linux, then the local executable on PATH.
   `HARQIS_CODEX_BINARY` can select a native executable; shell scripts and browser
   supplied commands are not accepted.
2. Open **Applications → Integrations → Codex → Test local host**.
3. Select **Save and enable**, then **Open in Fleet**. This imports an installation
   agent, local installed plugins, and a bounded page of saved tasks/executions.
4. Alternatively choose Codex in **Add agent** and link the saved connector.
   Repeated linking reuses the existing identity and preserves customization.
   An existing manual Codex profile can be linked explicitly in its editor.
   Uncheck linking to retain a manual presentation-only profile.

No task is started, steered, interrupted, approved, or authenticated by discovery.
The web connector never installs software: setup is an administrator CLI operation.
An invalid `HARQIS_CODEX_BINARY` fails explicitly instead of installing another copy.
The adapter launches a bounded `codex app-server --listen stdio://` reader and
closes only that reader. It does not stop the desktop app or managed daemon.
Installed schema verification used CLI 0.167.2 and managed app-server 0.169.0.
The daemon proxy timed out on the development host; no live subscription is
claimed. Version-dependent unavailable methods are reported as stale/unsupported.

## Host executable configuration

The **Host setup instructions** button in the Connect Codex dialog explains
installation, sign-in, executable configuration, and restart steps. It opens
automatically when a connection test fails.

If discovery cannot find an existing installation, add a documented override to
the gitignored `machines.local.toml`, under the frontend host's machine profile
(the profile mapped by `[hostnames]`, not the `[ssh.*]` target key):

```toml
[harqis-server.env_vars]
# Codex fleet reader: native executable owned by the HARQIS service user.
# Use the managed current symlink so the path survives Codex upgrades.
HARQIS_CODEX_BINARY = "/Users/<service-user>/.codex/packages/app-server-daemon/current/bin/codex"
```

Merge the setting into an existing section rather than repeating its header.
Replace `<service-user>` with the real macOS account. For standalone installs,
use `.codex/packages/standalone/current/bin/codex`; on Linux the home directory
is typically `/home/<service-user>`. On Windows use an absolute native executable
path such as `C:/Users/<service-user>/.codex/packages/app-server-daemon/current/bin/codex.exe`.
Do not put credentials in this setting. An explicit override takes priority over
automatic discovery, so a stale override must be corrected or removed.

If editing from another machine, run the config sync for the intended SSH target.
Then, using the host checkout's virtual environment, restart the frontend:

```bash
.venv/bin/python scripts/deploy.py --restart frontend
```

On Windows use `.venv/Scripts/python.exe`. A full verified remote deployment is
also sufficient: `python scripts/deploy.py --remote <machine-key>`.
Sign in as that same host user if needed, then **Test local host → Save and enable**.
Changing the browser computer's environment does not change the server process.

## Objects and identity

| Codex object | Fleet representation |
|---|---|
| Host/Codex home | Owner-scoped connector and execution identity |
| Installed local plugin | Application, namespaced by installation/marketplace/plugin ID |
| Thread | Task with stable installation/thread ID |
| Completed or failed turn | Execution observation beneath its task |
| Final response evidence URLs | Linked output evidence |

Plugin catalogs are restricted to local marketplaces; advertised but uninstalled
plugins are excluded. Connected plugin accounts and remote/cloud catalogs are
not inferred. Names do not establish cross-provider identity. Shared application
links and explicit reversible entity merges use the existing fleet controls.

## Collection and reporting

**Runtime: hybrid.** Celery Beat alone initiates
`workflows.hfl.tasks.fleet_observations.reconcile_fleet_observations` every five
minutes on `WorkflowQueue.HOST`. It calls the authenticated owner endpoint
`POST /api/hfl/fleet/reconcile` using existing `HFL_PERSONA_API_URL` (fallback
`HFL_CORPUS_API_URL`) and `HFL_CORPUS_API_TOKEN`. The frontend retains credentials
and performs provider discovery; the worker never receives connector secrets.

The endpoint has a durable per-owner overlap lease. Cursor progress, observations,
and deduplicated execution receipts persist across retries. Codex reads recent
active tasks each cycle alongside a bounded sweep of active/archived history;
large histories take multiple cycles. Turn histories are likewise paginated.
Five minutes is the reconciliation cadence, not an unconditional latency guarantee
for every historical execution or an offline/overloaded host.

Nod inventory/results and linked n8n agent executions reuse their existing
read/capture adapters. Other connectors are visible to Butler with execution
reporting explicitly delegated to their existing integrations. They are not
represented as universally observable execution APIs.

Completed/failed Codex executions produce one HFL receipt per owner, installation,
thread and turn. Receipts contain bounded final-response summaries and evidence
links; raw prompts, command output and plugin payloads are excluded. Common token
formats are redacted. Existing fleet audit delivery uses the HFL outbox. Task
pages are partial observations, so their absence never deletes prior tasks.
An empty complete plugin snapshot marks removed plugins no longer observed;
failed/partial snapshots retain previous identities and provenance.

Butler monitors each enabled owner-visible connector. Recorded results and
coverage warnings are available from any Butler chat page and in scheduled
briefing evidence. These relationships do not grant credentials or execution
authority. Delegation remains on explicit request. The existing Hermes briefing
sweep alone owns briefing occurrences; reconciliation never creates briefings
or changes their configured cadence.

## Validation and deployment

Tests cover repeated discovery, owner isolation, partial/empty inventory,
manual-profile reuse, merge/refresh/unmerge, pagination, receipt deduplication,
read-only protocol methods, and desktop/mobile connection controls. Real host
verification is separate from isolated test stores.

Restart/redeploy the frontend and reload the Celery worker/Beat configuration to
activate changed code and the schedule. A successful local probe does not imply
that a different deployed frontend host can access the same installation.

Protocol sources: [Remote connections](https://learn.chatgpt.com/docs/remote-connections)
and [Codex app-server](https://learn.chatgpt.com/docs/app-server), plus the installed
CLI's generated JSON schema. The installed executable remains the capability
authority; unsupported capabilities are never fabricated.
