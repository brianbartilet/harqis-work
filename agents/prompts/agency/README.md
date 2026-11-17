# Profile sources in Agent Fleet

Open **Fleet → Add agent → Specialist profile → Profile sources**. The panel also
appears in Edit agent. Search results preserve their existing card layout,
descriptions, division filter, classification ranking and Show more control.

## Storage and migration

Git contains only Agency Agents bootstrap metadata (283 profiles at the initial
pinned revision), source license, division definitions and HARQIS helper mappings.
Upstream Markdown bodies are no longer vendored. Previous commits still contain
those files; no history rewrite is required.

On first use, metadata seeds `fleet_profile_sources` and `fleet_profile_index` in
the existing Fleet SQLite database. Source configuration and refresh results are
host-local application data, not Git changes. Browsing never downloads bodies.
Opening a profile fetches its indexed revision, verifies SHA-256 and caches bytes
in `fleet_profile_cache`. This disposable cache expires after 30 unused days and
is bounded to 64 MB. Saved agents keep independent immutable instruction snapshots.

Existing saved profiles, including legacy unqualified Agency IDs, continue working
without downloads. New IDs include the source to prevent collisions. Back up the
Fleet database to retain sources and saved agents when moving hosts. Deploying a
new Git revision does not reset source settings.

## Configure a source

**Add profile source** supports:

- **Public GitHub repository:** enter `owner/repository`, a branch/tag/commit, and
  relative include patterns, one per line (e.g. `engineering/*.md`). Refresh resolves
  the ref to a full commit and temporarily scans its archive for Markdown frontmatter
  with `name` and `description`. Bodies are discarded after indexing. An unchanged
  commit skips archive discovery. Small updates fetch only changed profile files;
  larger updates fall back to a temporary archive scan.
- **HTTPS metadata catalog:** enter a public HTTPS JSON URL using the schema below.
  Refresh does not download profile bodies. Content hashes are mandatory.
- **Local directory:** enter a directory on the HARQIS server and include patterns.
  Its parent must be allowed by `HARQIS_PROFILE_SOURCE_ROOTS` (use the OS path
  separator for multiple roots). Symlinks outside the root are excluded. Changed
  local files must be refreshed before their new content can be applied.

Source settings save separately from the agent form. Save a source, then choose
**Refresh** to discover profiles. Sources can be disabled or removed; the default
Agency source can be disabled. Failed refreshes retain the old index and show an
error. Concurrent edits and refreshes use version checks.

Public HTTPS downloads verify TLS, connect to validated public IPs, and reject
redirects, credentials in URLs and private-network destinations. Private GitHub
authentication is not yet supported. This catalog applies instruction profiles;
`SKILL.md` packages are preview-only so scripts and supporting files cannot be
silently omitted. Install complete packages through the native skill workflow.
No source content is executed during discovery or download.

### Compatible HTTPS manifest

```json
{
  "revision": "2026-11-17",
  "profiles": [{
    "id": "reviewer",
    "name": "Team Reviewer",
    "description": "Review changes against team conventions.",
    "division": "Engineering",
    "classification": "coding",
    "url": "https://example.org/profiles/v1/reviewer.md",
    "hash": "<64-character SHA-256 of the exact downloaded bytes>"
  }]
}
```

Classification may be `coding`, `general` or `workflows`. Prefer immutable URLs.
Changed bytes fail integrity validation until a refresh supplies their new hash.
Mark executable skill package entries `kind: "skill-package"`; these are preview-only.

## Apply and update profiles

Select a card, inspect instructions and documentation, then **Use this profile**.
An empty description fills automatically; replacing your description requires the
replacement checkbox. Custom guidance stays separate. Preview instructions and
save. Changes affect new sessions only.

Refresh reports added, changed and removed profiles. When an assigned profile's
hash changes, Edit agent shows **Update available → Review profile update**.
Inspect the instruction diff, choose **Apply reviewed update**, then save the agent.
Existing sessions and saved instructions never change automatically. Removed,
disabled and offline sources do not invalidate saved snapshots.

Hermes action and conversation paths compose specialist and local guidance while
preserving runtime tool restrictions. External providers retain Fleet metadata and
show **Provider setup required**. Saving does not install plugins, grant tools,
execute tasks or schedule work. Composed instructions are bounded to 56,000
characters (60,000 including conversation context).

HARQIS helpers in `helpers.json` remain separate from upstream content. Other
profiles show their source descriptions and instructions without invented helper
or skill mappings. Source attribution appears on cards and previews.

## Maintainer bootstrap

To update default metadata for fresh installations, download a source ZIP for one
explicit Agency Agents commit, then run:

```powershell
.venv/Scripts/python.exe -m tools.agency_catalog archive.zip --revision <full-commit-SHA>
```

This writes metadata and attribution only, never Markdown bodies. Existing
installations update through Profile sources. Review the diff and run
`frontend/tests/test_profile_sources.py` and `frontend/tests/test_fleet_specialists.py`.
Tests use isolated databases and mocked downloads, not live GitHub requests.
