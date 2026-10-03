# Deploy Files and Share Packages

Feature branch: `feature/files-index-packages`.
Related action: `followup-b9091c455c954dacbe1e3a7ae4421760`.

This guide deploys **Organize → Files** on the existing HARQIS server. Code must
first be committed and pushed (or merged into your deployment branch). Creating
the local feature branch alone does not make these changes available to the server.
This implementation does not automatically deploy, create Drive shares, or scan
your private storage during development.

## 1. Deployment topology

- Run the frontend and the worker consuming `files` on the **same server**, with
  the same absolute `FILES_STORE_PATH`, OS user/access rights, and configuration.
- The SQLite catalog is local to that server. Do not place it on NFS/SMB or point
  workers on other machines at independent copies of the database.
- Keep **one Celery Beat** process. It dispatches maintenance every minute;
  maintenance schedules source scans at each source's interval (default 24 hours).
- Give the catalog worker at least two execution slots, so long transfers do not
  starve expiry checks. Prefer a dedicated `files` worker for sustained workloads.
- Local folder sources belong to `FILES_HOST_ID`. Use SFTP for files on other
  machines. FTP records are reference-only.
- `/files` and `/files/api/*` require the existing owner login. Public
  `/file-share/<token>` pages need to reach this frontend over HTTPS. They do not
  run on the standalone HFL API host.

## 2. Install the reviewed code

On the server, from the existing repository checkout:

```bash
git status --short
git fetch origin
```

If deploying this feature branch for the first time:

```bash
git switch --track origin/feature/files-index-packages
```

If the local branch already exists:

```bash
git switch feature/files-index-packages
git pull --ff-only origin feature/files-index-packages
```

Alternatively, deploy the normal server branch after merging the reviewed
feature. Preserve local changes; do not use a hard reset to force deployment.

Install into the repository virtual environment:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r frontend/requirements.txt
```

New direct dependency: `paramiko>=3.5,<5`. QR uses the existing `segno`; Drive
uses the existing Google SDK. If the frontend uses a separate environment,
install the repository requirements there too: owner downloads use the same
adapters as the worker. Windows uses `.venv/Scripts/python.exe` instead.

## 3. Configure the server

Add these values to the server's private `.env/apps.env`, or equivalent
`[harqis-server.env_vars]` in `machines.local.toml`. Replace the example paths
and domain; do not copy these examples as real storage locations.

```dotenv
FILES_ENABLED=1
FILES_HOST_ID=harqis-server
FILES_STORE_PATH=/srv/harqis-data/files/catalog.sqlite3
FILES_ALLOWED_ROOTS='["/srv/documents","/srv/media","/srv/harqis-work/results"]'
FILES_QUEUE=files
FILES_PUBLIC_URL=https://harqis.example.com
FILES_GOOGLE_CONFIG_ID=GOOGLE_DRIVE
FILES_SFTP_PROFILES_PATH=/srv/harqis-secrets/files-sftp.json
FILES_MAX_BYTES=2147483648
FILES_SCAN_LIMIT=100000
```

`FILES_ENABLED` enables Beat maintenance and automatic generated-output
registration. It does not hide the UI or disable manual commands. Leave it off
until configuration is ready, but **do not disable maintenance while expiring
public packages remain** unless their Drive grants have been revoked separately.

`FILES_ALLOWED_ROOTS` is a JSON array. A configured local source must resolve
inside one of these roots; symlinks are not followed during discovery. Give the
service account read access to originals and read/write access to the catalog
directory and its OS temporary directory. Use narrow roots. Never include the
catalog directory in backups by reading its live WAL files independently.

Other defaults: 100,000 files per complete scan, 2 GiB per retrieved file,
500 files per package revision, 50 catalog rows per page, and 150 files per
filtered graph. A scan exceeding its limit fails without declaring unseen files
missing; split large trees into smaller source roots or adjust the bound.

The frontend and worker must load identical settings. Existing machine-specific
overrides take precedence over `.env/apps.env`. Keep `FILES_ENABLED=0` on
unrelated hosts to avoid creating separate generated-output catalogs there.

### Google Drive

The existing `GOOGLE_DRIVE` section of `apps_config.yaml` already declares:

```yaml
app_data:
  scopes:
    - https://www.googleapis.com/auth/drive
  credentials: credentials.json
  storage: storage-drive.json
```

Keep the existing surrounding config. Provide those OAuth files through the
repository's configured secrets directory (`ENV_APP_SECRETS`); do not commit
them. Authorize the account before starting unattended workers. The calendar-only
`GOOGLE_APPS` config is not sufficient. Normal server execution does not open
interactive OAuth windows.

The account must have access to source folders and permission to create files
and anyone-with-link permissions. Google Workspace administrator policy can
block public sharing; the package will show a failed publication in that case.

Package folders are created in **My Drive root** to avoid inheriting public
access from a shared parent. Each revision has separate copied files. Native
Google Workspace documents are exported to PDF; unsupported exports fail the
revision rather than silently omitting a file. Leave publication folder
permissions under HARQIS management for expiry to work as specified.

### SSH / SFTP

Create the private JSON file pointed to by `FILES_SFTP_PROFILES_PATH`:

```json
{
  "archive-server": {
    "hostname": "archive.example.internal",
    "port": 22,
    "username": "harqis-reader",
    "root": "/srv/archive",
    "key_filename": "/srv/harqis-secrets/archive_ed25519",
    "known_hosts": "/srv/harqis-secrets/known_hosts"
  }
}
```

Use the profile name `archive-server` in the source form; its root must be at or
below `/srv/archive`. Verify the server fingerprint through your trusted channel
and install its known-host entry before connecting. Unknown host keys are
rejected. No remote shell commands are executed. Password authentication can
instead reference an environment variable using `"password_env": "ARCHIVE_PASSWORD"`;
never put credentials in source URLs, the UI, or the catalog.

### HTTP

Register explicit HTTP(S) file URLs. Recursive web crawling is not performed.
URLs must have no embedded credentials, query strings, or fragments. Addresses
are validated and pinned for connection; private/internal IPs and redirects are
rejected. The server must support HEAD for discovery. Use a direct final URL or
a local/SFTP source for private resources.

## 4. Initialize storage and configure queues

```bash
.venv/bin/python -m apps.file_index init
.venv/bin/python -m apps.file_index check
```

Both commands load the machine-aware repository environment. Initialization
creates the metadata database with schema version 1; it is idempotent and does
not touch original files. Check that the printed database path and host ID match
the intended server, integrity is `ok`, and `beat_enabled` is true. A newer
unknown schema is rejected rather than downgraded. Back up any existing catalog
before deploying later schema changes.

Append `files` to the server's existing queue list in `machines.local.toml`.
For the current stock `harqis-server` queues, this is:

```toml
[harqis-server]
queues = ["default", "tcg", "host", "adhoc", "hfl", "default_broadcast", "hfl_broadcast", "n8n", "files"]
```

If your private configuration has other queues, **preserve them**. Do not add
`files` to unrelated workers. The queue is already declared in the repository;
the code handles any existing HARQIS instance prefix.

## 5. Restart and verify registration

Use the repository's existing deployment supervisor:

```bash
.venv/bin/python scripts/deploy.py --machine harqis-server --restart worker
.venv/bin/python scripts/deploy.py --machine harqis-server --restart frontend
.venv/bin/python scripts/deploy.py --machine harqis-server --restart scheduler
.venv/bin/python scripts/deploy.py --machine harqis-server --status
.venv/bin/python scripts/launch.py worker-check --queues files
```

Restart the scheduler only on the canonical Beat host. If using your own systemd
units or containers, restart the corresponding worker, frontend, and Beat
services instead; preserve mounts and the settings above. Verify that the
worker advertises these registered tasks in Flower/worker inspection:

```text
workflows.files.tasks.index.scan_source
workflows.files.tasks.index.publish_package
workflows.files.tasks.index.maintain_files
```

Confirm `run-job--maintain-files` exists exactly once in Beat. The workflow is
guarded by `FILES_ENABLED`, so merely installing the branch does not activate it.
Regenerate the optional dashboard registry with the same bootstrapped environment:

```bash
.venv/bin/python - <<'PY'
import os, runpy
from scripts.deploy import load_env_into_os, load_machine_config, machine_env_vars
load_env_into_os()
os.environ.setdefault("APP_CONFIG_FILE", "apps_config.yaml")
os.environ.setdefault("WORKFLOW_CONFIG", "workflows.config")
os.environ.update(machine_env_vars(load_machine_config(None)))
runpy.run_path("frontend/generate_registry.py", run_name="__main__")
PY
```

CLI/MCP discovery is optional:

```bash
.venv/bin/python -m tools commands file_index
.venv/bin/python -m tools schema file_index search_file_index_files
```

Reconnect MCP clients to refresh cached tool lists. These tools access the local
catalog: run them on the catalog host, not against an unrelated laptop database.

## 6. End-to-end acceptance on the server

1. Sign in and open **Organize → Files → Sources**. Add a small approved local
   folder. Set its host to `harqis-server` (or your configured `FILES_HOST_ID`).
2. Choose **Scan now**. Refresh until the source is ready. Add a second source,
   such as an SFTP folder or Drive folder ID. Verify discovery and one download
   from each. Confirm retries/errors appear on unavailable sources.
3. Change a file, scan again, and verify its existing record updates. Remove a
   test original and rescan to verify `missing`; restore it and rescan to recover.
   A connection failure must not mark the entire source missing.
4. Assign existing HFL categories and tags, link an entity through search, and
   inspect the graph. The category picker uses the configured remote HFL API
   when present; otherwise it uses the existing local category store.
5. Select disposable sample files and create a package. Confirm the default is
   seven days. Publish only that sample package. The publish button explicitly
   grants anyone-with-link read access to copied files.
6. Open the guest page in a signed-out browser, test its Drive link, and scan both
   QR variants. Verify HTTPS, public routing, and that paths/internal metadata
   are absent. The guest page must not require the owner's HARQIS login.
7. Change an original and create/publish another revision. The earlier copied
   content and metadata must remain unchanged. Inspect revision and audit history.
8. Verify maintenance runs every minute. For a real expiry acceptance, let the
   seven-day sample expire: the guest page must immediately return 404 at its
   deadline and public Drive access must be removed by maintenance. Automated
   local tests exercise elapsed deadlines without waiting seven days. Do not
   shorten a production deadline by editing the database.

Expiry is recorded just before the public permission grant, so permission
response loss cannot create an untracked perpetual share. The guest page checks
the deadline on every request. Drive revocation may lag by the maintenance
interval/queue delay and longer during a provider outage; failed revocations
remain visible in the package audit and retry next minute. Previously downloaded
copies cannot be recalled. Metadata and published copies remain owner-visible
after expiry; no automatic retention deletion is performed.

Generated outputs under enabled local sources are registered when a successful
Celery result contains declared path fields (`path`, `file_path`, `output_path`,
`output_file`, `artifact_path`, `markdown_path`, or `pdf_path`), including nested
objects. Producers can call `register_output(path, provenance)` directly or use
`create_file_index_output` through CLI/MCP. Outputs not declaring paths, or
generated on other hosts, are found by configured scans; the feature does not
rewrite every existing producer or synchronize remote catalog databases.

## 7. Troubleshooting, backup, and rollback

| Symptom | Check |
|---|---|
| Scan stays queued | Correct worker consumes `files`; frontend/worker broker and instance prefix match; tasks are registered |
| Empty catalog after restart | Absolute `FILES_STORE_PATH` is identical in frontend and worker; persistent directory exists |
| Local source rejected | Host ID and JSON allowlist; service account read permissions |
| SFTP `SSHException` / permission error | Trusted host key, profile root, key permissions, remote account |
| Drive OAuth/403 failure | `GOOGLE_DRIVE` scope/token, account storage quota, source permissions, public sharing policy |
| Guest QR unavailable | `FILES_PUBLIC_URL` is an HTTPS frontend origin |
| Share is expired but Drive still opens anonymously | Worker/Beat health and `expiry_failed` package audit; do not stop maintenance |
| A task crashed while holding a lease | Lease expires after 65 minutes (3 minutes for maintenance); then retry. Never bypass a live operation's lease |
| New file absent | Source enabled, path under configured root, completed scan, scan limit; output producer may not return a declared path |

Use SQLite's backup API or stop the frontend and catalog worker before copying
the database. Include the catalog and the private configuration/OAuth/SSH files
in your established protected backup policy; published bytes live in Drive.
Never commit these files. Keep the catalog, Drive revision IDs, and their audit
history together when restoring; restoring an old database can lose knowledge
of newer public grants.

For rollback, first revoke the feature's active public Drive folder permissions
or keep the current expiry worker running until every expiring grant has been
removed. Then stop Files scheduling/worker consumption, restore the previous
application release, and restart the frontend/worker/Beat normally. Keep the
catalog database and Drive copies for recovery. Do not delete originals or
drop metadata tables as part of rollback.

## Implementation validation

Automated tests use isolated temporary databases/files, a controlled Drive
provider, HTTP transport fixtures, and SFTP transport fixtures. The browser test
uses real JavaScript and forms against the in-process API. No live Drive/SFTP
credentials or production publication are exercised by those tests.

Run with the repository's machine-aware environment bootstrap (as above) and
`pytest.main` for `apps/file_index/tests`, `workflows/files/tests`, and
`frontend/tests/test_files_module.py`, overriding the repository's default
workflow ignore with `-o addopts=`. Browser tests require Playwright Chromium
(`python -m playwright install chromium`) or `FILES_TEST_BROWSER_CHANNEL=msedge`
on a machine with Edge. See [runtime decision](FILES-IMPLEMENTATION.md).

Provider references: [Drive sharing](https://developers.google.com/workspace/drive/api/guides/manage-sharing)
and [Paramiko SSH client](https://docs.paramiko.org/en/stable/api/client.html).
