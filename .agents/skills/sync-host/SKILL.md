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
   - Else extract `<machine-key>` (first non-flag token) and pass it as `-MachineKey <key>` (PS) or `MACHINE_KEY=<key>` env (bash). Omit if not provided — the script will fall back to `default_machine`.
   - Pass `--dry-run` / `-n` through.
3. **Run the script.** It prompts for the SSH password (`auth = "password"` in the toml is informational — `ssh` itself does the prompting). Don't try to feed the password in; let the user type it.
4. **Report** what was pushed (resolved machine key, item list, remote `user@host:path`) and whether the script exited 0.
5. **On success, touch the sync marker.** If the script exited 0 (and this was not a `--dry-run`/`--list`), write the current epoch-seconds to `.git/sync-host.last`. The `/commit` skill reads this marker (Step 9) to decide whether `[sync] items` changed since the last sync — keeping it current here means a standalone `/sync-host` clears the "pending config" flag so the next `/commit` doesn't re-offer an already-pushed change.

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
