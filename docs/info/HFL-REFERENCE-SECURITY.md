# HFL Reference Download Security Audit

Date: 2026-07-26

Scope: HFL document rendering, local and remote reference downloads, new-entry
persistence, and the historical reference migration.

## Implemented controls

| Risk | Severity | Disposition |
|---|---:|---|
| Any referenced repository file, including gitignored secrets, was implicitly downloadable because the repository root was trusted. | High | Fixed. Default trust is limited to the corpus, repository `logs/`, and configured upload root. Other roots must be explicit. |
| Path traversal or a symlink could escape an allowed root. | High | Controlled by canonical resolution plus containment checks both when creating and consuming a token. |
| Plain HTTP references could expose browsing destinations or encourage insecure navigation. | Medium | Fixed for rendering and all new `HflEntry` persistence; the migration removes historical copies from Markdown and Elasticsearch. |
| File names containing spaces, brackets, or Markdown syntax produced broken or misleading links. | Medium | Fixed by generating escaped anchor markup from classified references rather than parsing raw paths as Markdown. |
| Blocked paths and failure reasons disclosed host file names and directory policy. | Medium | Fixed. Missing, invalid, non-file, HTTP, and out-of-root references are omitted from HTML and remote reference metadata. |
| Credential-bearing HTTPS URLs could expose embedded usernames or passwords. | Medium | Fixed. URLs containing user information are rejected. |
| Tampered, expired, or replayed download tokens could bypass path checks. | Medium | Controlled by authenticated routes, timed signatures, file revalidation, and repeated allowed-root containment checks. |
| Migration failure could leave Markdown and Elasticsearch inconsistent. | Medium | Reduced through preflight scans, private backups, atomic Markdown writes, bulk ES updates, and best-effort rollback. |

## Residual risks and operating guidance

- **Configured roots are a trust boundary (medium).** An authenticated user who
  can create an HFL entry can request any regular file within an allowed root.
  Never configure `/`, a home directory, `.ssh`, `.env`, or another broad
  credential-bearing directory. Prefer narrow roots such as the notes tree or
  dumps upload directory.
- **Canonical paths are intentionally visible (low/medium).** Entry and summary
  labels expose server directory structure to authenticated users. This is a
  product requirement; download URLs themselves do not contain a raw path.
- **Remote API transport may lack application-layer TLS (medium).** If
  `HFL_CORPUS_API_URL` uses HTTP, the bearer token and downloaded content rely
  on the private network layer (for example, Tailscale) for encryption. HTTPS
  remains preferable.
- **Large remote downloads can consume frontend memory (medium).** The current
  remote proxy reads the canonical response before returning it. Keep approved
  roots free of unexpectedly large files or add streaming before allowing
  unbounded archives.
- **Filesystem time-of-check/time-of-use remains (low).** A local actor with
  write access to an allowed root could replace a file between validation and
  opening. Filesystem permissions remain the primary defense against such a
  local attacker.
- **Backups contain original references (medium).** Migration backups are
  gitignored and created with restrictive permissions, but must still be
  retained and deleted according to the host's data-handling policy.
