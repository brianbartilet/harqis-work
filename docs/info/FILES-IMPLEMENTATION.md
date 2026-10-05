# Files index and packages: implementation decision

Approved September 30, 2026 after clarification of action
`followup-b9091c455c954dacbe1e3a7ae4421760`. User approved implementation on a new
feature branch and requested a server deployment guide.

## Scope and architecture

- Organize → Files: source administration, metadata catalog, category/tag editing,
  canonical entity selection, filtered relationship graph, retrieval, packages,
  public guest pages, QR links, revision history, and audit.
- SQLite metadata catalog in `apps/file_index/store.py`. File identity is distinct
  from location identity; locations have source-specific availability. Metadata
  contains no original file bytes. Original content is read only for requested
  retrieval/publication, with bounded disk staging and SHA-256 recording.
- Source discovery: local/server folders, Drive folders (all pages), explicit
  public HTTP URLs, and SSH/SFTP directories using configured profiles and known
  hosts. FTP retains references only. Complete scans reconcile missing locations;
  failures retain records with explicit source/access status.
- Initial scans naturally include older generated files under selected roots.
  Recurrence discovers new and updated metadata. Generated-output signal hooks
  and a service/CLI entry point register explicit producer paths.
- Categories reuse the HFL taxonomy. Entity IDs are manually linked using the
  existing entity search. OCR, AI extraction, and AI categorization are deferred.
- Revisions freeze membership/metadata. Publishing materializes source bytes into
  independent Drive copies. Edits to a selection create another revision.
- Anyone-with-link read access; default expiry seven days, alternatives fifteen,
  thirty, or none. Guest and Drive QR destinations are separate. Guest history
  is restricted to the selected published revision; owner history remains private.
- Expiry revokes the public folder grant and retains private copies and metadata.

## Folder-first user experience

The primary path is **Browse folders → select existing files → create a draft
package → publish**. Owners do not need to register paths or recreate configured
local roots as sources.

- `FILES_ALLOWED_ROOTS` remains the access boundary and now also supplies the
  initial local locations. Opening Locations (or the Catalog, which loads its
  locations) and scheduled maintenance reconcile these roots transactionally.
  Matching existing sources are reused; names, labels, scan intervals, and
  paused state are preserved. Removed configured roots are retained for history
  but excluded from automatic scans and browsing. Restoring a root restores its
  availability without unpausing it.
- **Catalog** opens with Browse folders. Its first-use state lists configured
  local folders with Browse and Scan actions. Filtered zero-result states offer
  Clear filters instead of setup instructions.
- The authenticated folder picker shows only metadata within allowed local
  source roots. It supports folder navigation and pages of 100 entries, bounds
  a folder listing at 10,000 entries, and accepts up to 200 selected files per
  request. It excludes symbolic links and the catalog database/WAL/SHM. All
  selected paths must validate before any metadata is registered. Adding files
  also selects their catalog records for package creation; it neither uploads
  nor publishes content.
- **Locations** replaces the Sources label. It displays configured folders,
  scan status, pause/resume controls, and a collapsed remote/subfolder form.
  Remote fields change with storage type; Drive accepts folder links or IDs.
  FTP remains reference-only. Remote files enter the Catalog through scans;
  the interactive picker supports local server folders only.
- Manual references live under **Locations → Advanced**, with explicit labels
  and guidance that a reference does not upload or verify a file. Catalog file
  details still support alternate locations.
- Scanning remains opt-in through `FILES_ENABLED` for scheduled work. Manual
  browsing and Scan now remain available; a paused location must be resumed
  before a scan. The page refreshes while following a manually queued scan
  (up to two minutes) or while a source reports that it is scanning.
- The empty package form directs the owner back to the Catalog and disables
  draft creation until files are selected. Publication and guest access retain
  their existing explicit controls and expiry behavior.

## Automation Runtime Decision

**Classification:** celery

**Confidence:** high

**Reasoning:** Discovery, transfer, permission changes, and expiry are bounded
deterministic operations requiring queueing, host affinity, and durable retries.

**Execution owner:** frontend/API for owner edits and bounded on-demand downloads;
Celery for discovery, publication, and expiry. Downloads execute in FastAPI's
threadpool and stream to temporary disk rather than keeping bytes in memory.

**Schedule owner:** Celery Beat, once per minute when `FILES_ENABLED=1`.

**Celery operations:** `scan_source`, `publish_package`, `maintain_files`.

**Agent responsibilities:** none in runtime execution.

**Required controls:** source allowlists, SSH profile root restrictions and host
key verification, HTTP DNS/address pinning with no redirects or private targets,
same-origin authenticated owner commands, immutable revision selection, durable
preallocated Drive IDs, explicit publication intent and actor audit, SQLite
leases, bounded transfers, task IDs, and retries. No sharing occurs on a scan.

**Review artifact:** source status and run IDs; package revision state, publication
intent/results, and expiry audit; this decision and the deployment runbook.

**Open questions:** user-provided base locations and server credentials are
deployment inputs, not implementation blockers. Live provider acceptance must
be performed on those configured sources.

## Implementation choices within the approved scope

This is a local catalog service, not a new external REST integration. It uses a
small local facade under `references/web/api/` for CLI/MCP consistency without
inventing a remote base URL, bearer token, `apps_config.yaml` block, or REST
inheritance. Existing Google Drive credentials/configuration are reused. This
is a deliberate adaptation of the service-app scaffold to a local service.

The durable catalog audit replaces `@log_result` for these tasks: it is the
owner-visible Review artifact and does not depend on Elasticsearch availability.
The new Beat schedule is opt-in through `FILES_ENABLED` rather than requiring
source-code uncommenting. Original source files are never renamed or deleted.

File identity remains stable for a given source and locator. Drive IDs survive
renames. Local/SFTP renames are represented as old missing/new locations until
the owner registers an alternate reference; automatic cross-source deduplication
and rename guessing are intentionally avoided. Checksums describe retrieved
bytes, not unverified equality between locations.

## Skill provenance

SHA-256 at implementation start:

| Skill | SHA-256 |
|---|---|
| clarify-feature | `b19436a151922fcd92609bf07bf613e7aa1d12396c333836908948c684225e7f` |
| choose-automation-runtime | `388e5c5221c4b43a53bb6a41033534b6a49e2ef17da6b44f69f3da8b64a690af` |
| create-new-workflow | `5a827a11cfbbafc707736f5a018bbd721f982b8cc9a6fd857b14b5b8461302d6` |

## Validation limits

Measured validation: **77 passed, 2 deselected** across the file-index service,
Files workflow, Files frontend/browser, and existing frontend module suites.
The two deselections are the independently reproduced baseline failures below.
The browser test ran in installed Edge with desktop/mobile screenshots. Endpoint
coverage, JavaScript syntax, CLI/MCP discovery, and Git whitespace checks passed.
Local regression tests exercise provider boundaries through controlled transports; they do not prove
server OAuth, SFTP credentials, external QR routing, or production worker health.
The deployment guide includes those acceptance steps.

Two existing frontend module checks were independently reproduced using the
unchanged base navigation: a manifesto assertion for an obsolete generic-link
CSS class, and a YouTube registry assertion against stale local generated
`frontend/registry.json`. They are outside the Files feature; no unrelated
workflow settings were changed to suppress them.
