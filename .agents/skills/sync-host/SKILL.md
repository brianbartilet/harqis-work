---
name: sync-host
description: >
  Push a configured set of local files to a remote harqis-work checkout via tar and ssh
  using machines.local.toml sync settings.
user-invocable: true
allowed-tools: Bash Read Glob Grep
---

Push a configured set of local files to a remote harqis-work checkout via `tar | ssh`. One password prompt per run.

All identifying info (machine keys, hostnames, remote paths, file list) lives in `machines.local.toml` (gitignored). The scripts ship no defaults of their own.

The argument `$ARGUMENTS` is an optional machine key (matches a `[ssh.<key>]` block). If empty, the scripts use `[sync] default_machine`. Also accepts:
- `--dry-run` / `-n` — print the resolved command without running it
- `--list` / `-l` — show all `[ssh.*]` blocks defined in `machines.local.toml`
- `--preflight` / `-p` — compare pending local items with the remote safely, print
  the disposition, and stop without transferring files

Every normal sync runs the same preflight before transfer. Calling `/sync-host`
directly is authorization to transfer material changes; `--preflight` exists for
callers such as `/commit` that must inspect first and ask separately.

## Required `machines.local.toml` shape

```toml
[sync]
default_machine = "<machine-key>"             # used when no key is passed
items           = ["<path>", "<path>", ...]   # repo-relative paths to push

[ssh.<machine-key>]
user = "<remote-user>"
host = "<reachable-hostname>"
auth = "password"                  # informational; ssh prompts as needed
path = "<remote-destination>"
```

If `[sync]` is missing, the scripts error with a message pointing at this schema.

## How it resolves the SSH target

1. Read `machines.local.toml` at the repo root.
2. Determine the machine key: `$ARGUMENTS` → `[sync] default_machine` → error.
3. Look up `[ssh.<machine-key>]` for `user`, `host`, `path`.
4. Read `[sync] items` for the file list to push.
5. Build `user@host` and stream the items through `tar -cf - … | ssh user@host "mkdir -p <path> && tar -xf - -C <path>"`.

A single SSH connection ⇒ a single password prompt for all items. Files are overwritten on the remote.

## Steps

1. **Resolve the script flavor** for the current OS:
   - Windows → `powershell -NoProfile -File scripts/sync-to-host.ps1`
   - macOS / Linux → `bash scripts/sync-to-host.sh`
2. **Parse `$ARGUMENTS`**:
   - If `--list`/`-l`, run the script with that flag and print the output.
   - Extract `--preflight`/`-p`; this is handled by the safe comparison below
     and is not passed to the transport script.
   - Else extract `<machine-key>` (first non-flag token) and pass it as `-MachineKey <key>` (PS) or `MACHINE_KEY=<key>` env (bash). Omit if not provided — the script will fall back to `default_machine`.
   - Pass `--dry-run` / `-n` through.
3. **Find pending leaf files.** Read `.git/sync-host.last` as epoch-seconds
   (missing/invalid means `0`). For every configured item:
   - File: pending when its mtime is newer than the marker.
   - Directory: enumerate files recursively and retain each leaf whose mtime is
     newer than the marker. Report leaf paths, not only the parent directory.
   - Missing configured items remain a hard stop; never transfer a partial set.
4. **Run a read-only remote comparison before any transfer.** Resolve the SSH
   target and compare each pending leaf with its corresponding remote path.
   Never print file contents, raw hashes, or unredacted secrets.

   Structured formats:
   - JSON (`*.json`), TOML (`*.toml`), and dotenv-style files (`.env`, `.env.*`,
     `*.env`) are compared by flattened key path.
   - Report three categories: `added`, `changed`, and `removed`.
   - For non-sensitive fields, show values compactly:
     - added: `<key>: <local value>`
     - changed: `<key>: <remote value> -> <local value>`
     - removed: `<key>: <remote value>`
   - Redact the value whenever the key path contains (case-insensitive)
     `token`, `password`, `passwd`, `secret`, `credential`, `api_key`,
     `apikey`, `private_key`, `client_secret`, `refresh`, or `authorization`,
     or whenever the value resembles a bearer token, private key, or long
     high-entropy credential. Print only `<redacted: added>`,
     `<redacted: changed>`, or `<redacted: removed>`.
   - Internal hashes may be used solely for equality comparison; never display
     them.
   - Compact non-sensitive values to one line and truncate them to 120
     characters so config previews remain readable.

   Opaque, binary, unsupported, or malformed files:
   - Report only relative path, byte size, and modification time.
   - Mark their disposition `unknown`; never auto-skip them.

   Remote failures:
   - If SSH, remote reads, or parsing fail, explain that detailed inspection was
     unavailable, report only safe file metadata, and use disposition `unknown`.
   - A comparison failure never authorizes an automatic skip.
5. **Classify and print one machine-readable disposition line** after the human
   summary:
   - `SYNC_PREFLIGHT=clean` — no pending files or local and remote content match.
   - `SYNC_PREFLIGHT=ephemeral` — all differences are changed leaf keys named
     exactly `token` and/or `expiry`; there are no added/removed keys, file
     additions, opaque files, or comparison errors; and any refresh credential
     present in the documents exists on both sides and is unchanged.
   - `SYNC_PREFLIGHT=material` — at least one safely inspected difference is
     not ephemeral.
   - `SYNC_PREFLIGHT=unknown` — comparison was incomplete or unsafe to classify.
6. **Handle clean or ephemeral results without transfer.** Unless this is
   `--dry-run`:
   - `clean`: advance `.git/sync-host.last` to current epoch-seconds and report
     `Config sync: remote already matches; marker advanced.`
   - `ephemeral`: advance the marker and report
     `Config sync: skipped ephemeral token/expiry refresh; marker advanced.`
   Stop successfully. This applies to direct and `--preflight` invocations so
   routine access-token rotations are not offered repeatedly.
7. **Honor audit-only modes.** For `--preflight`, stop after reporting a
   `material` or `unknown` disposition. For `--dry-run`, never transfer files
   and never update the marker.
8. **Run the transport script for a normal material/unknown sync.** It may
   prompt for the SSH password (`auth = "password"` is informational). Don't
   feed a password programmatically; let the user type it.
9. **Report** what was pushed (resolved machine key, item list, remote
   `user@host:path`) and whether the script exited 0.
10. **On success, touch the sync marker.** If the script exited 0, write current
    epoch-seconds to `.git/sync-host.last`. On failure, leave it unchanged.

## Adding a new target

Append to `machines.local.toml`:

```toml
[ssh.<new-key>]
user = "<remote-user>"
host = "<reachable-hostname>"
auth = "password"
path = "<remote-destination>"
```

Then `/sync-host <new-key>`. To make it the default, also update `[sync] default_machine`.

## Failure modes

- **`machines.local.toml not found`** — file is gitignored; the user needs to create it locally with `[sync]` and `[ssh.*]` blocks.
- **`[sync] section missing`** — schema not yet populated. Show the example block above.
- **`[ssh.<key>] not found`** — suggest running with `--list` to see configured targets.
- **`Missing 'user' or 'host'`** — incomplete block; tell the user which field is missing.
- **`ssh` exits non-zero** — surface stderr; common causes: wrong password, host unreachable (try `ping` or check Tailscale), `mkdir`/permission error on remote.
- **Items missing locally** — don't push a partial set; refuse and tell the user which file is absent.
- **Structured comparison unavailable** — report safe metadata, classify as
  `SYNC_PREFLIGHT=unknown`, and do not auto-skip.
- **Only access token and expiry changed** — redact the token, show the
  non-sensitive expiry transition, classify as `SYNC_PREFLIGHT=ephemeral`, skip
  transfer, and advance the marker.
