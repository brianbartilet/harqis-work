# n8n Workflow

## Description

- Utility helpers for integrating HARQIS tasks with [n8n](https://n8n.io/), a self-hosted workflow automation platform.
- Does not define any Celery tasks — provides shell utilities and ngrok tunnel setup for exposing local services to n8n.
- n8n orchestrates HARQIS Celery tasks via HTTP webhooks using `workflows.mapping` as the task registry.

## Directory Structure

```
workflows/n8n/
├── utilities/
│   ├── assistant_widget.py     # UI widget helper for n8n assistant integration
│   ├── command_runner.py       # Shell command execution helper
│   ├── send_flower_task.py     # Trigger Celery tasks via Flower HTTP API
│   └── __init__.py
└── README.md
```

## ngrok Setup (exposing local n8n to external webhooks)

n8n runs locally at `http://localhost:5678`. To expose it to the internet (e.g. for ElevenLabs voice agent webhooks):

```sh
# Install ngrok (Windows, via Chocolatey)
choco install ngrok

# Expose n8n port (replace XXXX with your n8n port, default 5678)
ngrok http 5678

# With basic auth (optional)
ngrok http 5678 --basic-auth="username:supersecretpassword"
```

The ngrok public URL is then used in n8n as the webhook base URL.

## Utilities

### `command_runner.py`
Executes shell commands from n8n HTTP calls. Used by n8n "Execute Command" nodes to run scripts or trigger Python jobs.

### `send_flower_task.py`
Triggers Celery tasks via the [Flower](https://flower.readthedocs.io/) monitoring API (HTTP). Allows n8n to fire specific Celery tasks without a direct RabbitMQ connection.

### `assistant_widget.py`
Helper for the ElevenLabs voice agent integration — manages the n8n widget state and session context.

## `workflows.mapping`

The auto-generated `workflows.mapping` file at the repo root is mounted into n8n. It exposes all Celery tasks in a machine-readable format so n8n workflows can select and trigger them dynamically.

Keys follow: `run-job--<task_name>`

## Deploy scripts

`workflows/n8n/deploy/` ships paired `.bat` and `.sh` variants of `backup`, `restore`, and `deploy`. The desktop task `run_n8n_sequence` (in `workflows/desktop/tasks/commands.py`) auto-picks the right extension via `sys.platform` so the same beat entry runs on Windows (`cmd /c …bat`) and macOS / Linux (`bash …sh`).

The task is routed to the dedicated **`n8n` queue** (declared in `workflows/queues.py` and `workflows/config.py`), which is consumed only by `harqis-server` per `machines.toml`. This pins n8n container ops to the always-on hub and keeps them off worker nodes.

The deploy scripts target the same bind-mounted data path as `docker-compose.yml`:

```text
${HARQIS_DATA_ROOT:-./.harqis-data}/n8n:/home/node/.n8n
```

If `HARQIS_DATA_ROOT` is unset, the scripts resolve n8n state to `<repo>/.harqis-data/n8n`. If it is set, the scripts use `<HARQIS_DATA_ROOT>/n8n`. They no longer touch the old `n8n_data` Docker volume path.

## Version upgrades and rollback

Production pins n8n to `2.47.7` in the root `docker-compose.yml`. The container
bundles its Node.js dependencies; upgrading n8n does not require upgrading the
HARQIS Python requirements. `GENERIC_TIMEZONE=Asia/Singapore` configures schedules.
The independent demo stack retains its separately configured version.

Before changing the image, record the running image ID and retain it with a
rollback tag. Stop n8n before archiving the entire resolved bind-mounted data
directory, including the SQLite database and WAL files, configuration/encryption
key, binary data, and community nodes. Keep the archive private and verify it
can be extracted. The existing `backup.sh`/`backup.bat` scripts do not stop n8n;
their caller must ensure the service is stopped for a consistent upgrade backup.

Rehearse migrations against an extracted copy with networking disabled. Check
database integrity, workflow/credential counts, community-node loading, and
readiness before upgrading production. Test external integrations separately
using controlled inputs. Review schedule and credential-access changes in the
[release notes](https://docs.n8n.io/changelog).

For rollback, stop the upgraded container, preserve its data separately, restore
the complete pre-upgrade archive into an empty data directory, and recreate n8n
with the retained old image and original configuration. Do not run the old image
against a migrated database. The legacy restore scripts perform SQLite repair
and remove WAL files; use the complete archive restore for upgrade rollback so
uncheckpointed transactions are preserved. All paired backup, restore, and deploy
scripts remain available in `deploy/`.

## Notes

- n8n must be running locally (default `http://localhost:5678`) for the `run_n8n_sequence` desktop task to work.
- ngrok is only needed for inbound webhooks from external services (ElevenLabs, Slack, etc.).
- Programmatic workflow import should use Docker CLI import (`docker cp` + `docker exec n8n n8n import:workflow`); the previous REST API key path is stale.
