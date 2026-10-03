# File Index

## Description

Lightweight metadata catalog behind **Organize → Files**. Records identify files,
their storage locations, metadata, and audit events. Package revisions preserve
membership/metadata and materialize private original content into independently
shared Google Drive copies on explicit publication.

Local/server, Drive, HTTP, and SFTP discovery/retrieval are supported. FTP stores
references only. No original files are moved or deleted.

## Supported Automations

- [x] webservices — owner API, Drive, HTTP, and local CLI/MCP
- [ ] browser automation
- [ ] desktop automation
- [ ] mobile automation
- [ ] iot automation

## Directory Structure

```text
file_index/
  __init__.py
  __main__.py                 # machine-aware init/check commands
  adapters.py                 # local, HTTP, Drive, SFTP boundaries
  store.py                    # SQLite schema, identity, leases, revisions/audit
  service.py                  # scan, retrieve, publish, expire, registration
  mcp.py                      # shared CLI/MCP registration
  references/web/api/catalog.py
  tests/test_catalog.py
  tests/test_adapters.py
```

## Configuration

See the [server deployment guide](../../docs/info/FILES-DEPLOYMENT.md) for all
settings, OAuth, SFTP profiles, queues, persistence, and acceptance checks.

| Setting | Default / purpose |
|---|---|
| `FILES_STORE_PATH` | `results/files/catalog.sqlite3`; use an absolute persistent server path |
| `FILES_ENABLED` | Off; opt in to Beat and generated-output signals |
| `FILES_HOST_ID` | OS hostname; stable local-source identity |
| `FILES_ALLOWED_ROOTS` | `[]`; JSON allowlist for local source roots |
| `FILES_GOOGLE_CONFIG_ID` | `GOOGLE_DRIVE`; existing OAuth app config |
| `FILES_SFTP_PROFILES_PATH` | Unset; private named SSH profiles JSON |
| `FILES_QUEUE` | `files`; only the catalog host should consume it |
| `FILES_PUBLIC_URL` | Unset; HTTPS frontend origin for guest QR |
| `FILES_MAX_BYTES` | 2 GiB per retrieval |
| `FILES_SCAN_LIMIT` | 100,000 discovered files per complete scan |

No new `apps_config.yaml` block or API secret is needed for this **local**
service. Google discovery operations reuse the existing `GOOGLE_DRIVE` section.
This deliberate local-service adaptation avoids an artificial REST base class
or dummy bearer token. Keep connection secrets outside catalog records.

## Available Services

| Service | Operations |
|---|---|
| `ApiServiceFileIndex` | `search_files`, `get_file`, `list_sources`, `get_package`, `register_output` |
| `service` | `scan`, `retrieve_file`, `publish`, `expire`, `register_output`, `register_reference` |
| `Store` | Transactional metadata, pagination, immutable revision selection, audit, leases |

Source discovery handles metadata incrementally; files are not re-downloaded on
scans. Drive locators use stable provider IDs. Local/SFTP locators are paths;
renames are not automatically guessed or merged. Alternate locations can be
registered manually. SHA-256 is computed for retrieved content.

Configured `FILES_ALLOWED_ROOTS` automatically become local **Locations** when
the Files UI or maintenance reconciles them. Matching existing sources keep
their preferences, including paused scans. New locations default to a 24-hour
scan interval. Removed configured roots retain their history but stop automatic
scanning. Scheduled scans still require `FILES_ENABLED=1`.

In the UI, **Browse folders** lets owners choose existing local files without
typing paths or waiting for a complete scan. Adding a selection records metadata
and selects the files for a package; it does not upload or publish them. Remote
storage is added in **Locations**, while manual path references are under
**Advanced**. The picker enforces the same host/root boundaries as retrieval,
excludes symbolic links and catalog files, and bounds listings and selections.

## MCP Tools

CLI and MCP use the same registrar. Run these on the catalog host.

| Tool | Parameters | Description |
|---|---|---|
| `search_file_index_files` | `query`, `category`, `offset`, `limit` | Search paginated metadata |
| `get_file_index_file` | `file_id` | File and all locations |
| `list_file_index_sources` | none | Source roots and scan state |
| `get_file_index_package` | `package_id` | Owner revisions and recent audit |
| `create_file_index_output` | `path`, `provenance` | **Write** metadata for an existing generated file under an enabled local source |

```text
python -m tools commands file_index
python -m tools schema file_index search_file_index_files
python -m apps.file_index init
python -m apps.file_index check
```

Output registration creates metadata only. It does not publish or upload content.
Publication and configuration remain explicit owner UI commands.

## Tests

`tests/test_catalog.py` exercises real temporary SQLite databases and local
files, failure handling, revision immutability, retry recovery, and expiry.
`tests/test_adapters.py` covers controlled HTTP/SFTP boundaries and Drive
pagination. Provider substitutes avoid public shares and live credential use.

Use the repository's machine-aware environment bootstrap before pytest:
`pytest.main(['apps/file_index/tests', '-q'])`. The full deployment guide provides
the bootstrap. Related tests live in `frontend/tests/test_files_module.py` and
`workflows/files/tests/test_index.py`.

## Notes

- The catalog and its worker live on one host; remote sources use SFTP/Drive/HTTP.
- HTTP URLs are explicit, public, credential-free final URLs without query strings.
  DNS is pinned to validated public addresses; redirects are rejected.
- SFTP verifies host keys and restricts paths to a configured profile root.
- Native Google documents are exported as PDF; unsupported exports block publishing.
- Source failures cannot silently produce a partial public package. Retry or create
  a new revision excluding unavailable files.
- A public deadline is persisted before permission changes. Expiry closes the guest
  page immediately and retries provider revocation through Beat maintenance.
- No OCR/AI extraction, source-byte retention, or automatic deletion is performed.
- Owner downloads use bounded temporary files, with attachment disposition even
  for HTML/SVG. User-facing activity records only what HARQIS actually observes.
  `last_opened` records opening the file inspector in HARQIS; it does not infer
  that an external desktop application or a Drive recipient opened the original.
